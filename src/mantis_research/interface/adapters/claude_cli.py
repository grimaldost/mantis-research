"""Claude Code CLI adapter — drives ``claude -p`` headless invocations.

The adapter exposes one async method (``run``) that the Stage uses for each
attempt. The Stage builds the prompt and the per-attempt options; the
adapter handles cmdline assembly, subprocess spawn, transcript streaming,
and exit-code reporting.

Backward-compat: the cmd shape is identical to the legacy ``run_batch.py``
runner so existing transcripts remain comparable in format.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from mantis_research.core.paths import seat_lock_path
from mantis_research.interface.adapters._subprocess import (
    DEFAULT_CHILD_IDLE_TIMEOUT_S,
    run_streaming,
)
from mantis_research.interface.seat import async_seat_lock
from mantis_research.interface.transcripts import TranscriptWriter

if TYPE_CHECKING:
    from pathlib import Path

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ClaudeCliOptions:
    """Per-call options for the Claude CLI adapter.

    The Stage constructs one of these per attempt. ``session_id`` is required
    for a fresh single-turn session; ``resume_session_id`` (multi-turn)
    causes ``--resume <id>`` instead of ``--session-id <id>``.
    """

    model: str
    effort: str = 'max'
    add_dirs: tuple[Path, ...] = ()
    allowed_tools: tuple[str, ...] = ('WebSearch', 'WebFetch', 'Write', 'Read')
    append_system_prompt: str | None = None
    session_id: str | None = None
    resume_session_id: str | None = None
    name: str | None = None  # --name human-readable
    output_format: str = 'text'
    extra_args: tuple[str, ...] = field(default_factory=tuple)
    # Watchdog on silence: kill a child that has produced no output for this
    # long. None disables it. See _subprocess.DEFAULT_CHILD_IDLE_TIMEOUT_S.
    idle_timeout_s: float | None = DEFAULT_CHILD_IDLE_TIMEOUT_S
    # When set, this call holds the single local Claude seat for its duration,
    # so concurrent runs queue visibly instead of interleaving invisibly. The
    # value is the queue-legible owner name, e.g. 'batch-name/synthesis'.
    seat_owner: str | None = None


@dataclass(frozen=True, slots=True)
class ClaudeCliResult:
    """Return shape from ``ClaudeCliAdapter.run``."""

    success: bool
    exit_code: int
    duration_s: float
    raw_output: str = ''  # full stdout+stderr for rate-limit detection
    error: str | None = None
    session_id: str | None = None  # echo the id used (for state.session_id tracking)
    timed_out: bool = False  # the watchdog killed a silent child


class ClaudeCliAdapter:
    """Adapter that drives the ``claude`` CLI for headless research.

    Construct once per orchestrator run; use ``await adapter.run(...)`` for
    each topic attempt. ``preflight()`` can be called once at orchestrator
    startup to verify the CLI is reachable and authenticated.
    """

    name: str = 'claude_cli'

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary or shutil.which('claude') or 'claude'

    @property
    def binary(self) -> str:
        return self._binary

    # ── lifecycle ─────────────────────────────────────────────────

    def preflight(self) -> None:
        """Verify ``claude --version`` and ``claude auth status`` succeed.

        Raises ``RuntimeError`` if the CLI is not installed, not on PATH, or
        not authenticated.
        """
        if not self._binary or not shutil.which(self._binary):
            msg = (
                f'claude CLI not found at {self._binary!r}. '
                'Install per https://code.claude.com/docs/en/setup.'
            )
            raise RuntimeError(msg)
        try:
            subprocess.run(  # noqa: S603 — fixed args, no shell
                [self._binary, '--version'],
                capture_output=True,
                check=True,
                timeout=15,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            msg = f'claude --version failed: {e.stderr or e.stdout}'
            raise RuntimeError(msg) from e
        try:
            subprocess.run(  # noqa: S603
                [self._binary, 'auth', 'status'],
                capture_output=True,
                check=True,
                timeout=15,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            msg = (
                'claude auth status failed — run `claude auth login` (no --console). '
                f'Output: {e.stdout or e.stderr}'
            )
            raise RuntimeError(msg) from e

    # ── per-attempt call ──────────────────────────────────────────

    async def run(
        self,
        prompt: str,
        options: ClaudeCliOptions,
        transcript_path: Path,
        *,
        dry_run: bool = False,
    ) -> ClaudeCliResult:
        """Run one ``claude -p`` invocation. Captures transcript + raw output.

        Two liveness guarantees (MANT-B08): the child is killed if it produces
        nothing for ``options.idle_timeout_s``, and — when ``options.seat_owner``
        is set — the call holds the machine's single local Claude seat for its
        duration, so a concurrent run queues visibly instead of interleaving.
        """
        session_id = options.session_id or str(uuid.uuid4())
        cmd = self._build_cmd(prompt, options, session_id)

        if dry_run:
            async with TranscriptWriter(transcript_path, list(cmd)) as tx:
                tx.write_dry_run_marker()
            return ClaudeCliResult(
                success=True,
                exit_code=0,
                duration_s=0.0,
                session_id=session_id,
            )

        start = time.monotonic()
        async with AsyncExitStack() as stack:
            if options.seat_owner:
                await stack.enter_async_context(
                    async_seat_lock(seat_lock_path(), options.seat_owner)
                )
            tx = await stack.enter_async_context(TranscriptWriter(transcript_path, list(cmd)))
            stream = await run_streaming(cmd, tx, idle_timeout_s=options.idle_timeout_s)
        duration = time.monotonic() - start

        if stream.timed_out:
            return ClaudeCliResult(
                success=False,
                exit_code=stream.exit_code,
                duration_s=duration,
                raw_output=stream.output,
                error=(
                    f'claude produced no output for {options.idle_timeout_s:.0f}s '
                    f'— killed by the watchdog'
                ),
                session_id=session_id,
                timed_out=True,
            )
        if stream.exit_code != 0:
            return ClaudeCliResult(
                success=False,
                exit_code=stream.exit_code,
                duration_s=duration,
                raw_output=stream.output,
                error=f'claude exited {stream.exit_code}',
                session_id=session_id,
            )
        return ClaudeCliResult(
            success=True,
            exit_code=0,
            duration_s=duration,
            raw_output=stream.output,
            session_id=session_id,
        )

    # ── cmd assembly ──────────────────────────────────────────────

    def _build_cmd(
        self,
        prompt: str,
        options: ClaudeCliOptions,
        session_id: str,
    ) -> list[str]:
        cmd: list[str] = [self._binary, '-p']

        if options.resume_session_id:
            cmd += ['--resume', options.resume_session_id]
        else:
            cmd += ['--session-id', session_id]

        if options.name:
            cmd += ['--name', options.name]

        cmd += ['--model', options.model]
        if options.effort:
            # Synthesis runner uses --effort even on resume; keep symmetry.
            cmd += ['--effort', options.effort]
        cmd += ['--output-format', options.output_format]

        for d in options.add_dirs:
            cmd += ['--add-dir', str(d)]

        if options.allowed_tools:
            # NOTE: --allowedTools is variadic in claude CLI; pass as comma-separated
            # single value, terminated by `--` before the prompt, to stop the parser
            # from consuming the prompt as another tool name.
            cmd += ['--allowedTools', ','.join(options.allowed_tools)]

        if options.append_system_prompt:
            cmd += ['--append-system-prompt', options.append_system_prompt]

        cmd += list(options.extra_args)
        cmd += ['--', prompt]
        return cmd

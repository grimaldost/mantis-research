"""Gemini CLI adapter — drives ``gemini -p`` headless invocations (OAuth path).

The OAuth path has documented quirks captured here so they live in one
place instead of being copy-pasted across runners; this adapter is the
reference for the cmd-line args and empirically-validated workarounds.

Quirks the adapter handles internally:

- ``cwd=Path.home()`` to avoid workspace-router triggering on project files.
- ``GEMINI_CLI_TRUST_WORKSPACE=true`` env var (``--skip-trust`` alone is
  insufficient for tool-using prompts on the OAuth path).
- ``--approval-mode yolo`` to skip permission prompts.
- ``--output-format text`` even though the OAuth path's gemini-cli has a
  restricted tool set (no ``write_file``); the runner captures stdout and
  writes the brief from Python.
- Gemini noise lines stripped from saved briefs (``GEMINI_NOISE_PATTERNS``).

The Stage that uses this adapter is responsible for writing the captured
output to the brief file (the adapter does NOT do file I/O for outputs).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from mantis_research.interface.adapters._subprocess import run_streaming
from mantis_research.interface.transcripts import TranscriptWriter

log = structlog.get_logger(__name__)


# Lines emitted by gemini-cli noise that we strip from saved briefs.
GEMINI_NOISE_PATTERNS: tuple[str, ...] = (
    'Warning: 256-color support',
    'YOLO mode is enabled',
    'Ripgrep is not available',
    'Project hooks disabled',
    'Skipping project agents due',
    '(node:',
    'Warning: True color',
    '[LocalAgentExecutor]',
    'Falling back to GrepTool',
)


@dataclass(frozen=True, slots=True)
class GeminiCliOptions:
    """Per-call options for the Gemini CLI adapter."""

    model: str = 'gemini-3-pro-preview'
    approval_mode: str = 'yolo'
    skip_trust: bool = True
    output_format: str = 'text'
    extra_args: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class GeminiCliResult:
    """Return shape from ``GeminiCliAdapter.run``."""

    success: bool
    exit_code: int
    duration_s: float
    raw_output: str = ''
    cleaned_output: str = ''  # raw_output minus the noise patterns
    error: str | None = None


class GeminiCliAdapter:
    """Adapter that drives the ``gemini`` CLI on the OAuth code-assist path.

    Construct once per orchestrator run; use ``await adapter.run(...)`` for
    each subsession. The adapter captures stdout and returns it for the
    Stage to write to disk (gemini-cli on OAuth has no ``write_file``).
    """

    name: str = 'gemini_cli'

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary or shutil.which('gemini') or 'gemini'

    @property
    def binary(self) -> str:
        return self._binary

    # ── lifecycle ─────────────────────────────────────────────────

    def preflight(self) -> None:
        """Verify ``gemini --version`` succeeds.

        Auth status is verified lazily on first call (no separate auth
        subcommand on the OAuth path).
        """
        if not self._binary or not shutil.which(self._binary):
            msg = f'gemini CLI not found at {self._binary!r}'
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
            msg = f'gemini --version failed: {e.stderr or e.stdout}'
            raise RuntimeError(msg) from e

    # ── per-attempt call ──────────────────────────────────────────

    async def run(
        self,
        prompt: str,
        options: GeminiCliOptions,
        transcript_path: Path,
        *,
        dry_run: bool = False,
    ) -> GeminiCliResult:
        """Run one ``gemini -p`` invocation. Captures transcript + raw output."""
        cmd = self._build_cmd(prompt, options)

        if dry_run:
            async with TranscriptWriter(transcript_path, list(cmd)) as tx:
                tx.write_dry_run_marker()
            return GeminiCliResult(success=True, exit_code=0, duration_s=0.0)

        # OAuth quirks: cwd=Home, GEMINI_CLI_TRUST_WORKSPACE=true.
        # We can't pass cwd to run_streaming directly, so we set it via the
        # asyncio.create_subprocess_exec call inside a wrapper.
        env = {**os.environ, 'GEMINI_CLI_TRUST_WORKSPACE': 'true'}
        start = time.monotonic()
        async with TranscriptWriter(transcript_path, list(cmd)) as tx:
            exit_code, raw = await self._run_streaming_with_env(cmd, tx, env, cwd=Path.home())
        duration = time.monotonic() - start

        cleaned = self._strip_noise(raw)

        if exit_code != 0:
            return GeminiCliResult(
                success=False,
                exit_code=exit_code,
                duration_s=duration,
                raw_output=raw,
                cleaned_output=cleaned,
                error=f'gemini exited {exit_code}',
            )
        return GeminiCliResult(
            success=True,
            exit_code=0,
            duration_s=duration,
            raw_output=raw,
            cleaned_output=cleaned,
        )

    # ── helpers ────────────────────────────────────────────────────

    def _build_cmd(self, prompt: str, options: GeminiCliOptions) -> list[str]:
        cmd: list[str] = [self._binary, '-p', prompt]
        cmd += ['--model', options.model]
        cmd += ['--approval-mode', options.approval_mode]
        if options.skip_trust:
            cmd += ['--skip-trust']
        cmd += ['--output-format', options.output_format]
        cmd += list(options.extra_args)
        return cmd

    @staticmethod
    def _strip_noise(raw: str) -> str:
        """Remove gemini-cli noise lines so the saved brief is clean prose."""
        kept = [
            line
            for line in raw.splitlines(keepends=True)
            if not any(pat in line for pat in GEMINI_NOISE_PATTERNS)
        ]
        return ''.join(kept)

    async def _run_streaming_with_env(
        self,
        cmd: list[str],
        transcript: TranscriptWriter,
        env: dict[str, str],
        cwd: Path,
    ) -> tuple[int, str]:
        """run_streaming variant that supports env+cwd (OAuth-path quirks)."""
        # Inline the streaming loop because the shared helper takes neither.
        # Kept short — duplication acceptable for the cwd/env quirk.
        import asyncio

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=cwd,
        )
        if process.stdout is None:
            msg = 'subprocess stdout pipe missing'
            raise RuntimeError(msg)

        captured: list[str] = []
        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode('utf-8', errors='replace')
            transcript.append_line(line)
            captured.append(line)

        await process.wait()
        exit_code = process.returncode or 0
        transcript.finalize(exit_code=exit_code)
        # Hint to keep run_streaming used (lint quietness).
        _ = run_streaming
        return exit_code, ''.join(captured)

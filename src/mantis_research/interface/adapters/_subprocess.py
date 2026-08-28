"""Shared streaming-subprocess runner used by all CLI-based adapters.

Pattern: spawn a subprocess (stdout+stderr merged), read line-by-line into
the transcript writer, collect everything into a string for rate-limit
detection at the end.

The function is internal — adapters should depend on it but external code
should not.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from mantis_research.core.progress import RunEvent, emit

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mantis_research.core.cli_stream import OutputCadence
    from mantis_research.core.progress import ProgressCallback
    from mantis_research.interface.transcripts import TranscriptWriter

log = structlog.get_logger(__name__)

#: How long a spawned child may produce nothing before the watchdog kills it.
#: Ten minutes: long enough for a max-effort Claude turn to think between lines,
#: short enough that a silent child is a failed attempt rather than a stalled
#: run. Three synthesis children once produced zero bytes for 75+ minutes and
#: had to be killed by hand, and the falsification children that spawned against
#: their never-written artifact hung the same way.
DEFAULT_CHILD_IDLE_TIMEOUT_S = 600.0

#: Seconds between the progress events a talking child generates. A streaming
#: child emits many lines a second; forwarding each one would flood the MCP
#: channel to say one thing — that the stage is still alive.
ANNOUNCE_EVERY_S = 20.0


@dataclass(frozen=True, slots=True)
class StreamResult:
    """Outcome of one streamed subprocess run."""

    exit_code: int
    output: str  # merged stdout+stderr, for rate-limit classification
    timed_out: bool = False  # the watchdog killed a child that produced nothing


async def run_streaming(
    cmd: Sequence[str],
    transcript: TranscriptWriter,
    *,
    cadence: OutputCadence,
    idle_timeout_s: float | None = DEFAULT_CHILD_IDLE_TIMEOUT_S,
    on_event: ProgressCallback | None = None,
    label: str = 'child',
) -> StreamResult:
    """Run ``cmd``, stream stdout+stderr to transcript, return the outcome.

    The transcript already has its headers written (caller used
    ``async with TranscriptWriter(...)``). This function appends every line
    as it arrives, and finalizes the transcript with the exit code.

    ``idle_timeout_s`` is a watchdog on **silence**, not on total runtime: the
    clock resets on every line, so a long-but-talking child runs as long as it
    likes while one that has said nothing for that long is killed and reported
    as a failed attempt. ``None`` disables it. Without this a child producing
    zero output left its topic ``in_flight`` with ``last_error: null``
    indefinitely — a run that never ends and never says why.

    ``cadence`` is required, and is the fact that claim depends on: a child
    that only speaks when it finishes has no silence to measure, so pairing it
    with a watchdog produces a cap on total runtime instead. That pairing is
    refused here rather than trusted to the caller, because it is exactly what
    happened — the format said `text`, the timeout said 600 s, and between them
    they killed 28% of the local-seat stages this tool had been completing.

    Every line also becomes a ``thinking`` event, rate-limited to one per
    :data:`ANNOUNCE_EVERY_S`. A stage that reports nothing between its start and
    its end is indistinguishable from a hang for however long it runs, which is
    the whole reason the caller gives up.
    """
    cadence.validate_watchdog(idle_timeout_s)
    process = await asyncio.create_subprocess_exec(
        *cmd,
        # Closed, not inherited: the CLI otherwise waits three seconds for
        # input on every turn and prints a non-JSON warning into the envelope.
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    if process.stdout is None:
        msg = 'subprocess stdout pipe missing — should never happen with PIPE config'
        raise RuntimeError(msg)

    captured: list[str] = []
    timed_out = False
    last_announced = 0.0
    started = time.monotonic()
    while True:
        try:
            line_bytes = await asyncio.wait_for(process.stdout.readline(), timeout=idle_timeout_s)
        except TimeoutError:
            timed_out = True
            log.warning(
                'child produced no output within the idle timeout — killing',
                pid=process.pid,
                idle_timeout_s=idle_timeout_s,
            )
            await _terminate(process)
            break
        if not line_bytes:
            break
        line = line_bytes.decode('utf-8', errors='replace')
        transcript.append_line(line)
        captured.append(line)
        now = time.monotonic()
        if on_event is not None and now - last_announced >= ANNOUNCE_EVERY_S:
            last_announced = now
            emit(
                on_event,
                RunEvent(
                    kind='thinking',
                    message=f'{label} is working ({now - started:.0f}s, {len(captured)} lines)',
                    data={'label': label, 'elapsed_s': round(now - started, 1)},
                ),
            )

    await process.wait()
    exit_code = process.returncode or 0
    transcript.finalize(exit_code=exit_code)
    return StreamResult(exit_code=exit_code, output=''.join(captured), timed_out=timed_out)


async def _terminate(process: asyncio.subprocess.Process) -> None:
    """Ask the child to stop, then insist. Never raises."""
    with contextlib.suppress(ProcessLookupError, OSError):
        process.terminate()
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=10)
        return
    with contextlib.suppress(ProcessLookupError, OSError):
        process.kill()

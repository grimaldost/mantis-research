"""Shared streaming-subprocess runner used by all CLI-based adapters.

Pattern: spawn a subprocess (stdout+stderr merged), read line-by-line into
the transcript writer, collect everything into a string for rate-limit
detection at the end.

The function is internal — adapters should depend on it but external code
should not.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mantis_research.interface.transcripts import TranscriptWriter


async def run_streaming(
    cmd: Sequence[str],
    transcript: TranscriptWriter,
) -> tuple[int, str]:
    """Run ``cmd``, stream stdout+stderr to transcript, return (exit_code, raw_output).

    The transcript already has its headers written (caller used
    ``async with TranscriptWriter(...)``). This function appends every line
    as it arrives, and finalizes the transcript with the exit code.

    Returns the merged output as a single string for downstream rate-limit
    detection by the orchestrator (``classify_failure``).
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    if process.stdout is None:
        msg = 'subprocess stdout pipe missing — should never happen with PIPE config'
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
    return exit_code, ''.join(captured)

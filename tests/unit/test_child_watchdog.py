"""The no-output watchdog on spawned children (backlog MANT-B08).

The only timeouts in the codebase were `timeout=15` on two short version probes;
the main CLI spawn had no timeout, kill or wait-for at all. A child producing
zero output therefore left its topic `in_flight` with `last_error: null`
indefinitely — three synthesis children ran mute for 75+ minutes and were killed
by hand.

The clock is on silence, not on runtime: a child that keeps talking runs as long
as it likes.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

from mantis_research.interface.adapters._subprocess import run_streaming
from mantis_research.interface.transcripts import TranscriptWriter

if TYPE_CHECKING:
    from pathlib import Path

_MUTE_CHILD = 'import time; time.sleep(30)'
_TALKING_CHILD = (
    'import sys, time\n'
    'for i in range(6):\n'
    "    print(f'line {i}', flush=True)\n"
    '    time.sleep(0.05)\n'
)


async def _run(script: str, tmp_path: Path, idle_timeout_s: float | None):
    cmd = [sys.executable, '-c', script]
    async with TranscriptWriter(tmp_path / 'tx.log', list(cmd)) as tx:
        return await run_streaming(cmd, tx, idle_timeout_s=idle_timeout_s)


class TestWatchdog:
    async def test_a_mute_child_is_killed_and_reported(self, tmp_path: Path) -> None:
        result = await _run(_MUTE_CHILD, tmp_path, 0.3)
        assert result.timed_out is True
        assert result.exit_code != 0

    async def test_the_child_is_killed_rather_than_waited_out(self, tmp_path: Path) -> None:
        # Reporting a timeout while leaving the process running would be worse
        # than the original bug: a leaked child still holding the seat. The mute
        # child would run for 30 s; returning in a fraction of that proves it
        # was killed and reaped, not outlived.
        start = time.monotonic()
        result = await _run(_MUTE_CHILD, tmp_path, 0.3)
        assert result.timed_out is True
        assert time.monotonic() - start < 15.0

    async def test_a_talking_child_runs_past_the_idle_window(self, tmp_path: Path) -> None:
        # Total runtime (~0.3 s) exceeds the idle timeout (0.2 s), but no single
        # gap does — the clock resets on every line.
        result = await _run(_TALKING_CHILD, tmp_path, 0.2)
        assert result.timed_out is False
        assert result.exit_code == 0
        assert 'line 5' in result.output

    async def test_disabled_watchdog_lets_a_child_finish(self, tmp_path: Path) -> None:
        result = await _run(_TALKING_CHILD, tmp_path, None)
        assert result.timed_out is False
        assert result.exit_code == 0

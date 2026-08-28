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

import pytest

from mantis_research.core.cli_stream import OutputCadence
from mantis_research.core.retry import FailureKind, classify_failure
from mantis_research.interface.adapters._subprocess import run_streaming
from mantis_research.interface.adapters.claude_cli import ClaudeCliAdapter, ClaudeCliOptions
from mantis_research.interface.transcripts import TranscriptWriter

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.progress import RunEvent

_MUTE_CHILD = 'import time; time.sleep(30)'
_TALKING_CHILD = (
    'import sys, time\n'
    'for i in range(6):\n'
    "    print(f'line {i}', flush=True)\n"
    '    time.sleep(0.05)\n'
)


async def _run(script: str, tmp_path: Path, idle_timeout_s: float | None, **kw):
    cmd = [sys.executable, '-c', script]
    async with TranscriptWriter(tmp_path / 'tx.log', list(cmd)) as tx:
        return await run_streaming(
            cmd,
            tx,
            cadence=OutputCadence.STREAMING,
            idle_timeout_s=idle_timeout_s,
            **kw,
        )


@pytest.fixture(autouse=True)
def _spawn_allowed(allow_child_spawn: None) -> None:
    """This whole module is about the spawn, so it opts out of that ring."""
    return


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


class TestTheTripPathThroughTheAdapter:
    """What the *stage* sees when the watchdog fires.

    0.2.0 tested the watchdog at ``run_streaming`` and stopped there, so the
    translation into a ``ClaudeCliResult`` — the thing every stage actually reads
    — had no test at all. That translation is where a trip either becomes a
    retryable failed attempt with a reason, or becomes a silent success.

    Only the argv is substituted — a stalling Python child stands in for a
    ``claude`` binary that goes mute. Everything else is real: the spawn, the
    watchdog, the kill, the transcript finalize and the adapter's translation of
    the result. Substituting the argv rather than the binary is what keeps the
    adapter's own ``-p``-first cmdline out of the test's way.
    """

    @staticmethod
    async def _trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        async def mute_instead(cmd, transcript, **kwargs):
            return await run_streaming([sys.executable, '-c', _MUTE_CHILD], transcript, **kwargs)

        monkeypatch.setattr(
            'mantis_research.interface.adapters.claude_cli.run_streaming', mute_instead
        )
        adapter = ClaudeCliAdapter(binary='/fake/claude')
        options = ClaudeCliOptions(model='irrelevant', session_id='s', idle_timeout_s=0.3)
        return await adapter.run('prompt', options, tmp_path / 'tx.log')

    async def test_a_tripped_watchdog_is_a_failed_attempt_not_a_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = await self._trip(tmp_path, monkeypatch)
        assert result.success is False
        assert result.timed_out is True

    async def test_the_reason_names_the_watchdog_and_the_window(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A stage surfaces this string as the topic's `last_error`. "no output
        # for 0s — killed by the watchdog" is the difference between a diagnosis
        # and the `last_error: null` that made the original bug unreadable.
        result = await self._trip(tmp_path, monkeypatch)
        assert result.error is not None
        assert 'watchdog' in result.error
        assert 'no output' in result.error

    async def test_the_trip_is_retryable_rather_than_a_rate_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The orchestrator buckets an attempt by its raw output. A mute child
        # produced none, so the classification must fall to GENERIC — a 5-minute
        # backoff and a retry, not the 30-minute rate-limit wait.
        result = await self._trip(tmp_path, monkeypatch)
        assert classify_failure(result.raw_output) is FailureKind.GENERIC

    async def test_the_session_id_survives_the_trip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The stage writes this back to state; losing it on the trip path would
        # strand the killed session as unresumable.
        result = await self._trip(tmp_path, monkeypatch)
        assert result.session_id == 's'


class TestTheCadenceContract:
    """`run_streaming` refuses a watchdog it cannot honour (MANT-B58).

    The caller declares whether the child speaks while it works. That is the
    fact the watchdog depends on and the fact nobody was tracking — so the
    runner now requires it rather than assuming it.
    """

    async def test_a_watchdog_over_a_mute_cadence_is_refused(self, tmp_path: Path) -> None:
        cmd = [sys.executable, '-c', _TALKING_CHILD]
        async with TranscriptWriter(tmp_path / 'tx.log', list(cmd)) as tx:
            with pytest.raises(ValueError, match='silence'):
                await run_streaming(cmd, tx, cadence=OutputCadence.TERMINAL, idle_timeout_s=5.0)

    async def test_a_mute_cadence_without_a_watchdog_still_runs(self, tmp_path: Path) -> None:
        cmd = [sys.executable, '-c', _TALKING_CHILD]
        async with TranscriptWriter(tmp_path / 'tx.log', list(cmd)) as tx:
            result = await run_streaming(
                cmd, tx, cadence=OutputCadence.TERMINAL, idle_timeout_s=None
            )
        assert result.exit_code == 0


class TestTheChildIsAudibleWhileItWorks:
    """The events that make a long run legible (MANT-B58/B64).

    Progress bridging shipped in 0.2.0 and reached the MCP path, but no event
    was emitted between a stage starting and finishing — so the longest part of
    the run was still silence, and the caller still gave up.
    """

    async def test_a_line_from_the_child_becomes_an_event(self, tmp_path: Path) -> None:
        seen: list[RunEvent] = []
        result = await _run(_TALKING_CHILD, tmp_path, 5.0, on_event=seen.append, label='synthesis')
        assert result.exit_code == 0
        assert seen, 'a talking child produced no events'
        assert all(e.kind == 'thinking' for e in seen)

    async def test_the_event_names_the_stage_that_is_working(self, tmp_path: Path) -> None:
        seen: list[RunEvent] = []
        await _run(_TALKING_CHILD, tmp_path, 5.0, on_event=seen.append, label='synthesis')
        assert 'synthesis' in seen[0].message

    async def test_a_broken_listener_does_not_fail_the_run(self, tmp_path: Path) -> None:
        def explode(_event: RunEvent) -> None:
            raise RuntimeError('the audience left')

        result = await _run(_TALKING_CHILD, tmp_path, 5.0, on_event=explode)
        assert result.exit_code == 0


class TestTheChildGetsNoStdin:
    async def test_the_child_sees_end_of_input_immediately(self, tmp_path: Path) -> None:
        # Without this the CLI waits 3 s for stdin on every single turn and
        # prints a warning that is not JSON into the middle of the envelope.
        script = 'import sys; print(repr(sys.stdin.read()), flush=True)'
        result = await _run(script, tmp_path, 5.0)
        assert result.exit_code == 0
        assert "''" in result.output

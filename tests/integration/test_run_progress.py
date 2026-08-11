"""Progress over the tool's own transport (backlog MANT-B01).

The `research` handler never accepted a request context and never reported
progress: the whole multi-stage run hid behind one `asyncio.to_thread` await, so
the client saw silence from call to return. Six MCP invocations aborted at the
1800 s idle window while the same questions succeeded 3/3 over the CLI, and both
full runs on 2026-08-11 aborted the same way and lost the synthesis stage — while
a `dry_run` probe returned in seconds. The pipeline was reachable; the failure
was silence under long work.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from mantis_research.interface.mcp.server import research
from mantis_research.interface.orchestrator import Orchestrator
from mantis_research.interface.research_service import run_research

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.progress import RunEvent


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


class TestStageBoundaries:
    def test_every_stage_boundary_is_announced(self, rooted: Path) -> None:
        events: list[RunEvent] = []
        run_research(
            'q',
            assurance='fast',
            substrates=['openai', 'deepseek'],
            batch_name='b',
            dry_run=True,
            log_level='CRITICAL',
            on_event=events.append,
        )
        kinds = [e.kind for e in events]
        assert kinds[0] == 'run_named'
        assert kinds[-1] == 'run_done'
        assert kinds.count('stage_start') == 2  # fast = openrouter + synthesis
        assert kinds.count('stage_done') == 2

    def test_each_substrate_reports_start_and_finish(self, rooted: Path) -> None:
        # The research stage is the longest silence in a run; a caller has to be
        # able to tell "three substrates in flight" from "hung".
        events: list[RunEvent] = []
        run_research(
            'q',
            assurance='fast',
            substrates=['openai', 'deepseek'],
            batch_name='b',
            dry_run=True,
            log_level='CRITICAL',
            on_event=events.append,
        )
        started = [e.data['substrate'] for e in events if e.kind == 'substrate_start']
        finished = [e.data['substrate'] for e in events if e.kind == 'substrate_done']
        assert started == ['openai', 'deepseek']
        assert finished == ['openai', 'deepseek']

    def test_progress_carries_a_scale(self, rooted: Path) -> None:
        events: list[RunEvent] = []
        run_research(
            'q',
            assurance='fast',
            batch_name='b',
            dry_run=True,
            log_level='CRITICAL',
            on_event=events.append,
        )
        stage_done = [e for e in events if e.kind == 'stage_done']
        assert [(e.step, e.total) for e in stage_done] == [(1, 2), (2, 2)]

    def test_a_broken_listener_does_not_fail_the_run(self, rooted: Path) -> None:
        def explode(_: RunEvent) -> None:
            raise RuntimeError('the audience left')

        manifest = run_research(
            'q',
            assurance='fast',
            batch_name='b',
            dry_run=True,
            log_level='CRITICAL',
            on_event=explode,
        )
        assert manifest['ok'] is True


class TestBackoffHeartbeat:
    """A backoff is the longest silence in a run, so it has to keep speaking.

    Without a heartbeat here, the cap on the backoff (MANT-B02) is load-bearing
    rather than belt-and-braces: it would be the only thing keeping a wait inside
    the caller's idle window.
    """

    async def test_waiting_events_go_out_during_a_backoff(self) -> None:
        events: list[RunEvent] = []
        await Orchestrator._stop_aware_sleep(
            0.05,
            asyncio.Event(),
            on_event=events.append,
            data={'stage': 'openrouter'},
            chunk=0.01,
        )
        waiting = [e for e in events if e.kind == 'waiting']
        assert len(waiting) >= 3
        assert waiting[0].data['stage'] == 'openrouter'
        # Each heartbeat says how much of the wait is left, so the caller can
        # tell a backoff from a stall.
        assert waiting[0].data['remaining_s'] > waiting[-1].data['remaining_s']

    async def test_stop_signal_ends_the_wait_and_the_heartbeat(self) -> None:
        events: list[RunEvent] = []
        stop = asyncio.Event()
        stop.set()
        await Orchestrator._stop_aware_sleep(60.0, stop, on_event=events.append, chunk=0.01)
        assert events == []


class _FakeContext:
    """Stands in for the FastMCP request context."""

    def __init__(self) -> None:
        self.progress: list[tuple[float, float | None, str | None]] = []
        self.logged: list[str] = []

    async def report_progress(
        self, progress: float, total: float | None = None, message: str | None = None
    ) -> None:
        self.progress.append((progress, total, message))

    async def info(self, message: str, **_: Any) -> None:
        self.logged.append(message)


class TestMcpChannel:
    async def test_run_events_reach_the_mcp_context(self, rooted: Path) -> None:
        ctx = _FakeContext()
        result = await research('q', assurance='fast', substrates=['openai'], dry_run=True, ctx=ctx)
        assert result['ok'] is True
        # The bridge hands events back to this loop from the worker thread; let
        # the scheduled deliveries drain.
        await asyncio.sleep(0.05)
        assert any('dispatching' in m for m in ctx.logged)
        assert any('openrouter' in m for m in ctx.logged)
        assert ctx.progress, 'no progress notification reached the client'

    async def test_tool_still_runs_with_no_context(self, rooted: Path) -> None:
        # A client that injects no context must not break the tool.
        result = await research('q', assurance='fast', substrates=['openai'], dry_run=True)
        assert result['ok'] is True

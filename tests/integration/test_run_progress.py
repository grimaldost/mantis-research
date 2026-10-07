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
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mantis_research.core.progress import RunEvent, emit
from mantis_research.interface import research_service
from mantis_research.interface.mcp.server import research
from mantis_research.interface.orchestrator import Orchestrator
from mantis_research.interface.research_service import run_research

if TYPE_CHECKING:
    from mantis_research.core.progress import ProgressCallback


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


def _record(rooted: Path, batch: str) -> dict[str, Any]:
    return json.loads((rooted / 'outputs_root' / batch / 'run.json').read_text(encoding='utf-8'))


class TestTheRecordFollowsTheRun:
    """`run.json` is rewritten at each transition, not only at the start and end (T1e)."""

    def test_each_transition_is_on_disk_before_the_caller_hears_of_it(self, rooted: Path) -> None:
        seen: list[tuple[RunEvent, dict[str, Any]]] = []

        def listen(event: RunEvent) -> None:
            seen.append((event, _record(rooted, 'b')))

        run_research(
            'q',
            assurance='fast',
            substrates=['openai', 'deepseek'],
            batch_name='b',
            dry_run=True,
            log_level='CRITICAL',
            on_event=listen,
        )

        first_brief = next(
            rec for e, rec in seen if e.kind == 'substrate_done' and e.data['substrate'] == 'openai'
        )
        assert first_brief['current_stage'] == 'openrouter'
        assert first_brief['stages']['openrouter']['state'] == 'running'
        assert first_brief['stages']['openrouter']['substrates_done'] == ['openai']

        synthesis_start = next(
            rec for e, rec in seen if e.kind == 'stage_start' and e.data['stage'] == 'synthesis'
        )
        assert synthesis_start['status'] == 'dispatching'
        assert synthesis_start['current_stage'] == 'synthesis'
        research_stage = synthesis_start['stages']['openrouter']
        assert research_stage['state'] == 'done'
        assert research_stage['exit_code'] == 0
        assert research_stage['substrates_done'] == ['openai', 'deepseek']
        assert research_stage['finished_at']
        synthesis_stage = synthesis_start['stages']['synthesis']
        assert synthesis_stage['state'] == 'running'
        assert synthesis_stage['started_at']
        assert synthesis_stage['exit_code'] is None
        assert 'finished_at' not in synthesis_stage

        assert seen[-1][0].kind == 'run_done'
        assert seen[-1][1]['status'] == 'validated'

    def test_the_seat_wait_is_written_once_however_often_it_is_reported(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The seat reports its wait every 5 s; one write marks the start of the
        # wait, and the child's first sign of life marks its end.
        def fake(
            stage: str, cfg: Any, *, on_event: ProgressCallback | None = None, **_: Any
        ) -> int:
            if stage == 'synthesis':
                for _ in range(3):
                    emit(on_event, RunEvent(kind='waiting', message='waiting for the seat'))
                emit(on_event, RunEvent(kind='thinking', message='synthesis is working'))
            return 0

        written: list[str] = []
        real_write = research_service._write_run_record

        def counting(dirs: Any, record: dict[str, Any]) -> Path:
            synthesis = (record.get('stages') or {}).get('synthesis') or {}
            if record.get('status') == 'dispatching' and 'state' in synthesis:
                written.append(synthesis['state'])
            return real_write(dirs, record)

        monkeypatch.setattr('mantis_research.interface.cli.dispatch.dispatch_stage_config', fake)
        monkeypatch.setattr(research_service, '_write_run_record', counting)
        run_research('q', assurance='fast', batch_name='seat', log_level='CRITICAL')

        assert written == ['running', 'waiting', 'running', 'done']

    def test_a_blocked_progress_write_neither_fails_the_run_nor_drops_an_event(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # On Windows `replace` fails while a poller has run.json open. A progress
        # write is a courtesy: losing one must cost neither the run nor the
        # caller's event.
        polled = {'held': False}

        def fake(
            stage: str, cfg: Any, *, on_event: ProgressCallback | None = None, **_: Any
        ) -> int:
            if stage == 'synthesis':
                polled['held'] = True
                emit(on_event, RunEvent(kind='waiting', message='waiting for the seat'))
                emit(on_event, RunEvent(kind='thinking', message='synthesis is working'))
                polled['held'] = False
            return 0

        real_replace = Path.replace

        def held_open(self: Path, target: Any) -> Any:
            if polled['held'] and Path(target).name == 'run.json':
                raise PermissionError(13, 'in use')
            return real_replace(self, target)

        monkeypatch.setattr('mantis_research.interface.cli.dispatch.dispatch_stage_config', fake)
        monkeypatch.setattr(Path, 'replace', held_open)
        monkeypatch.setattr(research_service, '_RECORD_RETRY_PAUSE_S', 0.0)
        kinds: list[str] = []

        def listen(event: RunEvent) -> None:
            kinds.append(event.kind)

        manifest = run_research(
            'q', assurance='fast', batch_name='held', log_level='CRITICAL', on_event=listen
        )

        assert manifest['stages'] == {'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 0}}
        assert 'waiting' in kinds
        assert 'thinking' in kinds
        assert _record(rooted, 'held')['status'] == 'complete'
        assert not list((rooted / 'outputs_root' / 'held').glob('*.tmp'))

    def test_an_event_after_the_run_ended_cannot_reopen_its_record(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A late event from a stage's own machinery must not rewrite a terminal
        # record back to `dispatching`.
        kept: dict[str, ProgressCallback] = {}

        def fake(
            stage: str, cfg: Any, *, on_event: ProgressCallback | None = None, **_: Any
        ) -> int:
            if on_event is not None:
                kept['sink'] = on_event
            return 0

        monkeypatch.setattr('mantis_research.interface.cli.dispatch.dispatch_stage_config', fake)
        run_research('q', assurance='fast', batch_name='late', log_level='CRITICAL')
        kept['sink'](RunEvent(kind='waiting', message='a straggler'))

        assert _record(rooted, 'late')['status'] == 'complete'


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
    """Stands in for the MCPServer request context."""

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

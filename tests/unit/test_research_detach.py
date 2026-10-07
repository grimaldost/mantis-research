"""Starting a run and collecting it are separate acts (MANT-B61).

The `research` tool was one blocking call, and a real run legitimately takes
longer than an MCP client will hold one open. Across every recorded transcript,
18 of 18 non-dry-run calls hit the client's ceiling and none returned; the five
that did return in two seconds were dry runs. Progress notifications helped —
measured on 2026-08-23 they bought each caller 216-460 s — but they cannot
extend a call past a ceiling on its total duration.

`detach=True` is additive: the blocking default is unchanged, so no existing
caller is affected. A detached run is bound to the server's lifetime, which is
the session doing the polling; a run lost with the session is re-entered with
``resume``, which is what invariant I5 already provides.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mantis_research.core.paths import RunDirs
from mantis_research.core.progress import RunEvent, emit
from mantis_research.core.settings import settings
from mantis_research.interface.mcp.server import build_server, research, research_status
from mantis_research.interface.research_service import resume_research, run_research

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    yield tmp_path
    # A detached run outlives the call that started it, and it resolves its
    # paths on every write. Left running, it writes its record into whichever
    # test's directory is patched in next, so it is finished here, while this
    # test's paths still apply.
    for thread in threading.enumerate():
        if thread.name == 'mantis-research-run':
            thread.join(timeout=30)


class TestTheToolSurface:
    async def test_the_server_exposes_a_status_tool(self) -> None:
        names = {t.name for t in await build_server().list_tools()}
        assert names == {'research', 'research_status'}

    async def test_detach_is_off_by_default(self) -> None:
        tool = next(t for t in await build_server().list_tools() if t.name == 'research')
        assert tool.input_schema['properties']['detach']['default'] is False

    async def test_the_status_tool_documents_its_argument(self) -> None:
        tool = next(t for t in await build_server().list_tools() if t.name == 'research_status')
        assert tool.input_schema['properties']['outputs_dir']['description']


class TestADetachedCallReturnsAHandle:
    @pytest.fixture(autouse=True)
    def _instant_stages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # These tests read the handle, not the run, so the stages need not do
        # anything; the fixture teardown then has nothing to wait for.
        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', lambda *a, **k: 0
        )

    async def test_it_returns_before_the_run_finishes(self, rooted: Path) -> None:
        result = await research('a detached question', assurance='research', detach=True)
        assert result['state'] == 'running'
        assert result['outputs_dir']
        assert result['batch_name']

    async def test_the_handle_names_a_run_that_exists_on_disk(self, rooted: Path) -> None:
        result = await research('a detached question', assurance='research', detach=True)
        record = json.loads(
            (rooted / 'outputs_root' / result['batch_name'] / 'run.json').read_text(
                encoding='utf-8'
            )
        )
        assert record['question'] == 'a detached question'

    async def test_the_handle_carries_no_epistemic_payload(self, rooted: Path) -> None:
        # There is nothing to report yet; saying otherwise is the shape that
        # let a briefs-only run read as an answer.
        result = await research('q', assurance='research', detach=True)
        assert 'claims' not in result
        assert result.get('sidecar_available') is not True


class TestStatusReadsWhatIsOnDisk:
    async def test_an_unknown_directory_is_reported_not_raised(self, rooted: Path) -> None:
        status = await research_status(str(rooted / 'outputs_root' / 'no-such-run'))
        assert status['state'] == 'unknown'

    async def test_a_finished_run_reports_its_outcome(self, rooted: Path) -> None:
        blocking = await research('q', assurance='research', dry_run=True)
        status = await research_status(blocking['outputs'].get('run_dir') or _dir(rooted))
        assert status['state'] in {'finished', 'running'}

    async def test_a_failed_run_is_reported_rather_than_raised(self, rooted: Path) -> None:
        # `_agent_result` raises when a live run owed a sidecar and has none.
        # Polling must not: a caller asking "how did it go" needs the answer,
        # not an exception it has to interpret.
        run_dir = rooted / 'outputs_root' / 'failed-run'
        run_dir.mkdir(parents=True)
        (run_dir / 'run.json').write_text(
            json.dumps(
                {
                    'question': 'q',
                    'batch_name': 'failed-run',
                    'status': 'complete',
                    'ok': False,
                    'dry_run': False,
                    'produces_sidecar': True,
                    'assurance': 'fast',
                    'stages': {'synthesis': {'exit_code': 1}},
                    'outputs': {'sidecar': str(run_dir / 'nothing.json')},
                }
            ),
            encoding='utf-8',
        )
        status = await research_status(str(run_dir))
        assert status['state'] == 'finished'
        assert status['ok'] is False

    async def test_the_sidecar_outcome_is_reported_beside_ok(self, rooted: Path) -> None:
        # ADR-0011 — polling is the surface an agent uses to decide whether to
        # collect a detached run, so the run's second outcome has to reach it.
        # `ok: true` with a failed sidecar is exactly the case a poller must be
        # able to see.
        run_dir = rooted / 'outputs_root' / 'sidecar-failed-run'
        run_dir.mkdir(parents=True)
        (run_dir / 'run.json').write_text(
            json.dumps(
                {
                    'question': 'q',
                    'batch_name': 'sidecar-failed-run',
                    'status': 'complete',
                    'ok': True,
                    'dry_run': False,
                    'produces_sidecar': True,
                    'assurance': 'fast',
                    'stages': {'synthesis': {'exit_code': 0}},
                    'sidecar': {'status': 'failed', 'error': 'schema drift on every re-ask'},
                    'outputs': {'sidecar': str(run_dir / 'nothing.json')},
                }
            ),
            encoding='utf-8',
        )
        status = await research_status(str(run_dir))
        assert status['ok'] is True
        assert status['sidecar']['status'] == 'failed'
        assert 'schema drift' in status['sidecar']['error']

    async def test_a_record_predating_the_sidecar_block_reads_as_not_run(
        self, rooted: Path
    ) -> None:
        # Run records written before the field exist on disk and are polled.
        run_dir = rooted / 'outputs_root' / 'older-run'
        run_dir.mkdir(parents=True)
        (run_dir / 'run.json').write_text(
            json.dumps({'batch_name': 'older-run', 'status': 'complete', 'ok': True}),
            encoding='utf-8',
        )
        status = await research_status(str(run_dir))
        assert status['sidecar'] == {'status': 'not_run', 'error': None}

    async def test_the_status_names_the_data_root(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Runs no longer live beside the plugin's code, so a caller holding a
        # run name, or none, needs to be told where the runs are (T4e). It is
        # reported for an unknown directory too: that is when it is most useful.
        monkeypatch.setattr(settings, 'MANTIS_HOME', str(rooted / 'mantis-home'))
        unknown = await research_status(str(rooted / 'outputs_root' / 'no-such-run'))
        assert unknown['data_root'] == str(rooted / 'mantis-home')

        run_dir = rooted / 'outputs_root' / 'known-run'
        run_dir.mkdir(parents=True)
        (run_dir / 'run.json').write_text(
            json.dumps({'batch_name': 'known-run', 'status': 'complete', 'ok': True}),
            encoding='utf-8',
        )
        known = await research_status(str(run_dir))
        assert known['data_root'] == str(rooted / 'mantis-home')


def _dir(rooted: Path) -> str:
    return str(next((rooted / 'outputs_root').iterdir()))


class TestTheBlockingDefaultIsUnchanged:
    async def test_a_plain_call_still_returns_the_result(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def fake(question: str, **kw: Any) -> dict[str, Any]:
            seen['blocked'] = True
            return {
                'ok': True,
                'dry_run': True,
                'question': question,
                'assurance': 'fast',
                'produces_sidecar': False,
                'cost': {},
                'stages': {},
                'outputs': {'sidecar': str(rooted / 'none.json')},
            }

        monkeypatch.setattr('mantis_research.interface.mcp.server.run_research', fake)
        result = await research('q', dry_run=True)
        assert seen.get('blocked') is True
        assert result['question'] == 'q'


class _StageBoomError(RuntimeError):
    """The failure the fake synthesis stage dies with."""


@pytest.fixture
def dying_synthesis(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fast-tier run whose research stage succeeds and whose synthesis dies.

    The openrouter stage writes one brief under the run's output directory and
    returns 0; the synthesis stage raises, as a stage does when its adapter
    throws rather than returning a non-zero exit code.
    """
    monkeypatch.setattr(
        'mantis_research.interface.research_service.require_local_claude_seat',
        lambda **_: None,
    )

    def fake(stage: str, cfg: Any, **_: Any) -> int:
        if stage == 'openrouter':
            brief_dir = RunDirs('batch', cfg.batch_name).output('openrouter') / 'topic'
            brief_dir.mkdir(parents=True, exist_ok=True)
            (brief_dir / 'openai.md').write_text('a brief', encoding='utf-8')
            return 0
        msg = 'the synthesis adapter blew up'
        raise _StageBoomError(msg)

    monkeypatch.setattr('mantis_research.interface.cli.dispatch.dispatch_stage_config', fake)


class TestAnExceptionLeavesATerminalRecord:
    """A stage that raises used to leave `run.json` at `dispatching` for good.

    The status tool then read it as `running` for as long as the server's pid
    lived: a dead worker thread inside a live server, forever (T1d).
    """

    def test_the_run_re_raises_and_the_record_says_failed(
        self, rooted: Path, dying_synthesis: None
    ) -> None:
        with pytest.raises(_StageBoomError):
            run_research('q', assurance='fast', batch_name='dies-run')
        record = json.loads(
            (rooted / 'outputs_root' / 'dies-run' / 'run.json').read_text(encoding='utf-8')
        )
        assert record['status'] == 'failed'
        assert record['ok'] is False
        assert record['finished_at']
        assert 'the synthesis adapter blew up' in record['error']
        assert record['stages'] == {'openrouter': {'exit_code': 0}}
        assert record['question'] == 'q'
        assert record['batch_name'] == 'dies-run'

    def test_a_clean_run_keeps_its_complete_record(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            'mantis_research.interface.research_service.require_local_claude_seat',
            lambda **_: None,
        )
        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', lambda *a, **k: 0
        )
        run_research('q', assurance='research', batch_name='clean-run')
        record = json.loads(
            (rooted / 'outputs_root' / 'clean-run' / 'run.json').read_text(encoding='utf-8')
        )
        assert record['status'] == 'complete'
        assert 'error' not in record

    def test_a_blocked_replace_is_retried(
        self, rooted: Path, dying_synthesis: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # On Windows a concurrent reader (the status tool) can hold the record
        # open, and `replace` then raises PermissionError. The terminal write is
        # the one that must not be lost to that.
        real = Path.replace
        seen = {'run_record_replaces': 0}

        def flaky(self: Path, target: Any) -> Any:
            if self.parent.name == 'terminal-retry':
                seen['run_record_replaces'] += 1
                # The first replace is the `dispatching` write; the next two
                # are the terminal write being refused.
                if seen['run_record_replaces'] in (2, 3):
                    raise PermissionError(13, 'in use')
            return real(self, target)

        monkeypatch.setattr(Path, 'replace', flaky)
        monkeypatch.setattr('mantis_research.interface.research_service._RECORD_RETRY_PAUSE_S', 0.0)
        with pytest.raises(_StageBoomError):
            run_research('q', assurance='fast', batch_name='terminal-retry')
        record = json.loads(
            (rooted / 'outputs_root' / 'terminal-retry' / 'run.json').read_text(encoding='utf-8')
        )
        assert record['status'] == 'failed'


class TestADetachedRunThatDiesIsNotRunningForever:
    async def test_the_status_reaches_finished_with_the_error(
        self, rooted: Path, dying_synthesis: None
    ) -> None:
        handle = await research('q', assurance='fast', detach=True)
        status: dict[str, Any] = {}
        for _ in range(100):
            status = await research_status(handle['outputs_dir'])
            if status['state'] != 'running':
                break
            await asyncio.sleep(0.05)
        assert status['state'] == 'finished'
        assert status['ok'] is False
        assert 'the synthesis adapter blew up' in status['error']
        assert status['stages'] == {'openrouter': {'exit_code': 0}}

    async def test_a_polled_failure_can_be_resumed(
        self, rooted: Path, dying_synthesis: None
    ) -> None:
        # `resume_research` treats any record that is not `dispatching` as
        # re-enterable; a `failed` one must therefore be.
        handle = await research('q', assurance='fast', detach=True)
        for _ in range(100):
            if (await research_status(handle['outputs_dir']))['state'] != 'running':
                break
            await asyncio.sleep(0.05)
        with pytest.raises(_StageBoomError):
            resume_research(Path(handle['outputs_dir']))


@dataclass
class _SeatGate:
    """Lets a test hold the fake synthesis stage in its seat wait, then free it."""

    waiting: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def queued_synthesis(monkeypatch: pytest.MonkeyPatch) -> Iterator[_SeatGate]:
    """A fast-tier run whose research is done and whose synthesis waits for the seat.

    The shape of the 2026-09-27 batch: the briefs were on disk, the synthesis
    queued behind other runs, and `research_status` answered `stages={}` the
    whole time. The research stage writes one brief, reports it and returns 0;
    the synthesis stage reports the seat wait and blocks until the test frees it.
    """
    monkeypatch.setattr(
        'mantis_research.interface.research_service.require_local_claude_seat',
        lambda **_: None,
    )
    gate = _SeatGate()

    def fake(stage: str, cfg: Any, *, on_event: Any = None, **_: Any) -> int:
        if stage == 'openrouter':
            brief_dir = RunDirs('batch', cfg.batch_name).output('openrouter') / '01-q'
            brief_dir.mkdir(parents=True, exist_ok=True)
            (brief_dir / 'openai.md').write_text('a brief', encoding='utf-8')
            emit(
                on_event,
                RunEvent(
                    kind='substrate_done',
                    message='openai done',
                    data={'stage': 'openrouter', 'substrate': 'openai', 'status': 'done'},
                ),
            )
            return 0
        emit(
            on_event,
            RunEvent(
                kind='waiting',
                message='waiting for the local Claude seat, held by another run',
                data={'seat_owner': 'another-run', 'seat_pid': 1},
            ),
        )
        gate.waiting.set()
        gate.release.wait(timeout=30)
        return 0

    monkeypatch.setattr('mantis_research.interface.cli.dispatch.dispatch_stage_config', fake)
    yield gate
    gate.release.set()


async def _until_not_running(outputs_dir: str) -> dict[str, Any]:
    status: dict[str, Any] = {}
    for _ in range(200):
        status = await research_status(outputs_dir)
        if status['state'] != 'running':
            break
        await asyncio.sleep(0.05)
    return status


class TestALiveRunReportsItsStages:
    """The record was written at the start and the end, and nowhere between (T1e).

    A detached run that had finished its research and was queued for the seat
    reported `stages={}` for its whole life, and 10 of 11 collectors polling it
    gave up and called it failed.
    """

    async def test_a_mid_run_poll_shows_research_done_and_synthesis_queued(
        self, rooted: Path, queued_synthesis: _SeatGate
    ) -> None:
        handle = await research('q', assurance='fast', detach=True)
        assert await asyncio.to_thread(queued_synthesis.waiting.wait, 10)

        status = await research_status(handle['outputs_dir'])
        assert status['state'] == 'running'
        assert status['current_stage'] == 'synthesis'
        research_stage = status['stages']['openrouter']
        assert research_stage['state'] == 'done'
        assert research_stage['exit_code'] == 0
        assert research_stage['substrates_done'] == ['openai']
        assert research_stage['started_at'] <= research_stage['finished_at']
        synthesis_stage = status['stages']['synthesis']
        assert synthesis_stage['state'] in {'waiting', 'running'}
        assert synthesis_stage['exit_code'] is None
        assert synthesis_stage['started_at']

        queued_synthesis.release.set()
        status = await _until_not_running(handle['outputs_dir'])
        assert status['state'] == 'finished'
        assert status['stages'] == {'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 0}}
        record = json.loads(
            (rooted / 'outputs_root' / handle['batch_name'] / 'run.json').read_text(
                encoding='utf-8'
            )
        )
        assert record['status'] == 'complete'


class TestStatusFallsBackToWhatIsOnDisk:
    """A record that lags, or was written by a version that only wrote it twice,
    must not hide artifacts that are already on disk (T1e)."""

    async def test_a_running_record_reports_the_artifacts_beside_it(self, rooted: Path) -> None:
        run_dir = rooted / 'outputs_root' / 'lagging-run'
        brief = run_dir / 'openrouter' / '01-q' / 'openai.md'
        brief.parent.mkdir(parents=True)
        brief.write_text('a brief', encoding='utf-8')
        synthesis_dir = run_dir / 'synthesis'
        synthesis_dir.mkdir()
        (synthesis_dir / '01-q.md').write_text('a synthesis', encoding='utf-8')
        (synthesis_dir / '01-q.sidecar.json').write_text('{}', encoding='utf-8')
        # The model's draft is not the published sidecar.
        (synthesis_dir / '01-q.sidecar.draft.json').write_text('{}', encoding='utf-8')
        (run_dir / 'run.json').write_text(
            json.dumps(
                {
                    'question': 'q',
                    'batch_name': 'lagging-run',
                    'status': 'dispatching',
                    'owner_pid': os.getpid(),
                    'stages': {},
                }
            ),
            encoding='utf-8',
        )

        status = await research_status(str(run_dir))

        assert status['state'] == 'running'
        assert status['artifacts'] == {
            'briefs': [str(brief)],
            'synthesis': [str(synthesis_dir / '01-q.md')],
            'sidecar': [str(synthesis_dir / '01-q.sidecar.json')],
        }

    async def test_a_read_that_meets_a_replace_is_retried(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The record is now rewritten while the run is polled, and on Windows a
        # read that lands while `replace` swaps the file in is refused. That is
        # a moment, not an unknown run.
        run_dir = rooted / 'outputs_root' / 'busy-run'
        run_dir.mkdir(parents=True)
        (run_dir / 'run.json').write_text(
            json.dumps({'batch_name': 'busy-run', 'status': 'complete', 'ok': True}),
            encoding='utf-8',
        )
        real = Path.read_text
        refusals = {'left': 2}

        def mid_replace(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name == 'run.json' and refusals['left']:
                refusals['left'] -= 1
                raise PermissionError(13, 'access denied')
            return real(self, *args, **kwargs)

        monkeypatch.setattr(Path, 'read_text', mid_replace)
        monkeypatch.setattr('mantis_research.interface.mcp.server._RECORD_READ_PAUSE_S', 0.0)

        status = await research_status(str(run_dir))

        assert status['state'] == 'finished'
        assert refusals['left'] == 0

    async def test_a_running_record_with_nothing_on_disk_reports_empty_lists(
        self, rooted: Path
    ) -> None:
        run_dir = rooted / 'outputs_root' / 'fresh-run'
        run_dir.mkdir(parents=True)
        (run_dir / 'run.json').write_text(
            json.dumps(
                {'batch_name': 'fresh-run', 'status': 'dispatching', 'owner_pid': os.getpid()}
            ),
            encoding='utf-8',
        )
        status = await research_status(str(run_dir))
        assert status['artifacts'] == {'briefs': [], 'synthesis': [], 'sidecar': []}

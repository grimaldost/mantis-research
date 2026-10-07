"""Starting a run and collecting it are separate acts (MANT-B61).

The `research` tool was one blocking call, and a real run legitimately takes
longer than an MCP client will hold one open. Across every recorded transcript,
18 of 18 non-dry-run calls hit the client's ceiling and none returned; the five
that did return in two seconds were dry runs. Progress notifications helped —
measured on 2026-08-23 they bought each caller 216-460 s — but they cannot
extend a call past a ceiling on its total duration.

`detach` arrived as an opt-in (0.4.0). Left unset it is now chosen by tier
(T20a): a run whose tier uses the local Claude seat detaches, because its seat
turns alone outlast a client's ceiling, while a research-tier run and a dry run
still block. Collecting is the other half: a ``resume`` of a finished run
returns the result in that call whatever ``detach`` says, so poll-then-collect
always ends in an answer rather than another handle. A detached run is bound to
the server's lifetime, which is the session doing the polling; a run lost with
the session is re-entered with ``resume``, which is what invariant I5 already
provides.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mantis_research.core.paths import RunDirs, topic_stem
from mantis_research.core.progress import RunEvent, emit
from mantis_research.core.settings import settings
from mantis_research.interface.mcp.server import build_server, research, research_status
from mantis_research.interface.research_service import (
    LocalSeatUnavailableError,
    resume_research,
    run_research,
    seat_turn_durations,
)

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

    async def test_detach_is_chosen_by_tier_unless_the_caller_says(self) -> None:
        # T20a: unset means the automatic rule; an explicit true or false still
        # validates, so a caller that passed a boolean before is unaffected.
        tool = next(t for t in await build_server().list_tools() if t.name == 'research')
        detach = tool.input_schema['properties']['detach']
        assert detach['default'] is None
        assert {branch.get('type') for branch in detach['anyOf']} == {'boolean', 'null'}
        description = detach['description']
        assert 'uses the local Claude seat' in description
        assert 'Pass false to block' in description
        assert 'A resume of a finished run' in description
        assert 'Off by default' not in description

    async def test_the_status_tool_documents_its_argument(self) -> None:
        tool = next(t for t in await build_server().list_tools() if t.name == 'research_status')
        assert tool.input_schema['properties']['outputs_dir']['description']

    async def test_the_status_argument_is_optional(self) -> None:
        # No argument lists the runs, so the schema must not demand one (T21).
        tool = next(t for t in await build_server().list_tools() if t.name == 'research_status')
        assert 'outputs_dir' not in tool.input_schema.get('required', [])
        assert tool.input_schema['properties']['outputs_dir']['default'] == ''


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


def _exit_codes(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {stage: entry['exit_code'] for stage, entry in stages.items()}


class TestWhatStillBlocks:
    """A dry run, a research-tier run and `detach=False` return the result (T20a)."""

    async def test_a_dry_run_still_returns_the_result(
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

    async def test_a_research_tier_call_returns_the_result(
        self, rooted: Path, delivering_stages: None
    ) -> None:
        # No local-seat stage, so nothing in it outlasts a client's ceiling.
        result = await research('q', assurance='research')
        assert 'state' not in result
        assert result['ok'] is True
        assert result['assurance'] == 'research'

    async def test_detach_false_blocks_a_seat_tier_call_and_returns_the_answer(
        self, rooted: Path, delivering_stages: None
    ) -> None:
        result = await research('q', detach=False)
        assert 'state' not in result
        assert result['assurance'] == 'fast'
        assert [c['id'] for c in result['claims']] == ['c1']


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
        assert _exit_codes(record['stages']) == {'openrouter': 0}
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
        assert _exit_codes(status['stages']) == {'openrouter': 0}

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
        assert _exit_codes(status['stages']) == {'openrouter': 0, 'synthesis': 0}
        # A finished entry keeps when its stage ran, and drops the live `state`.
        for entry in status['stages'].values():
            assert entry['started_at'] <= entry['finished_at']
            assert 'state' not in entry
        record = json.loads(
            (rooted / 'outputs_root' / handle['batch_name'] / 'run.json').read_text(
                encoding='utf-8'
            )
        )
        assert record['status'] == 'complete'


_SIDECAR = {
    'sidecar_version': 2,
    'claims': [{'id': 'c1', 'text': 'a claim', 'support': 'direct'}],
    'divergences': [],
    'verification_queue': [],
    'agreements_worth_verifying': [],
    'coverage_notes': [],
}


@pytest.fixture
def delivering_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every stage succeeds at once, and the synthesis stage publishes a sidecar."""
    monkeypatch.setattr(
        'mantis_research.interface.research_service.require_local_claude_seat',
        lambda **_: None,
    )

    def fake(stage: str, cfg: Any, **_: Any) -> int:
        if stage == 'synthesis':
            out = RunDirs('batch', cfg.batch_name).output('synthesis')
            out.mkdir(parents=True, exist_ok=True)
            stem = topic_stem('1', cfg.topics[0].slug)
            (out / f'{stem}.sidecar.json').write_text(json.dumps(_SIDECAR), encoding='utf-8')
        return 0

    monkeypatch.setattr('mantis_research.interface.cli.dispatch.dispatch_stage_config', fake)


def _abandon(outputs_dir: str) -> None:
    """Leave a run's record at `dispatching`, owned by a process that is gone."""
    record_path = Path(outputs_dir) / 'run.json'
    record = json.loads(record_path.read_text(encoding='utf-8'))
    record.update(status='dispatching', owner_pid=_exited_pid())
    record_path.write_text(json.dumps(record), encoding='utf-8')


class TestASeatTierCallDetachesByDefault:
    """A plain call whose tier uses the local seat returns a handle (T20a).

    The seat turns alone take longer than a client holds one call open, so the
    blocking default was the one that failed: blocking is now the opt-in.
    """

    async def test_a_plain_fast_call_returns_a_handle_while_the_run_continues(
        self, rooted: Path, queued_synthesis: _SeatGate
    ) -> None:
        handle = await research('q')

        assert handle['state'] == 'running'
        assert handle['assurance'] == 'fast'
        assert handle['outputs_dir']
        assert 'claims' not in handle
        assert await asyncio.to_thread(queued_synthesis.waiting.wait, 10)
        assert (await research_status(handle['outputs_dir']))['state'] == 'running'

        queued_synthesis.release.set()
        assert (await _until_not_running(handle['outputs_dir']))['state'] == 'finished'

    @pytest.mark.parametrize('assurance', ['standard', 'high'])
    async def test_the_deeper_seat_tiers_detach_too(
        self, rooted: Path, queued_synthesis: _SeatGate, assurance: str
    ) -> None:
        handle = await research('q', assurance=assurance)
        assert handle['state'] == 'running'
        assert handle['assurance'] == assurance
        queued_synthesis.release.set()

    @pytest.mark.parametrize('detach', [None, True])
    async def test_an_unusable_seat_is_raised_rather_than_hidden_behind_a_handle(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch, detach: bool | None
    ) -> None:
        # The seat check runs before the run names itself. A detached call that
        # only waited for the name answered "did not name itself" instead of
        # the refusal that says what to fix.
        def refuse(**_: Any) -> None:
            msg = 'this run needs the local claude CLI seat, and that seat is not usable'
            raise LocalSeatUnavailableError(msg)

        monkeypatch.setattr(
            'mantis_research.interface.research_service.require_local_claude_seat', refuse
        )
        with pytest.raises(LocalSeatUnavailableError, match='seat is not usable'):
            await research('q', detach=detach)


class TestAResumeOfAFinishedRunCollects:
    """Collecting a finished run returns its result, not another handle (T20a).

    A resume went through the same `if detach:` as a new run, with the call's
    own default tier, so an automatic detach would have answered the collect
    call with a second handle.
    """

    @pytest.mark.parametrize('detach', [None, True])
    async def test_it_returns_the_full_result_whatever_detach_says(
        self, rooted: Path, delivering_stages: None, detach: bool | None
    ) -> None:
        first = run_research('q', assurance='fast', batch_name='finished-run')

        result = await research('', resume=first['outputs_dir'], detach=detach)

        assert 'state' not in result
        assert result['outputs_dir'] == first['outputs_dir']
        assert [c['id'] for c in result['claims']] == ['c1']

    async def test_an_abandoned_research_tier_run_blocks_on_its_own_tier(
        self, rooted: Path, delivering_stages: None
    ) -> None:
        # The call's assurance defaults to fast and is ignored on a resume; the
        # record's own tier decides.
        first = run_research('q', assurance='research', batch_name='abandoned-research')
        _abandon(first['outputs_dir'])

        result = await research('', resume=first['outputs_dir'])

        assert 'state' not in result
        assert result['ok'] is True

    async def test_an_abandoned_fast_run_detaches_on_its_own_tier(
        self, rooted: Path, delivering_stages: None
    ) -> None:
        first = run_research('q', assurance='fast', batch_name='abandoned-fast')
        _abandon(first['outputs_dir'])

        handle = await research('', resume=first['outputs_dir'], assurance='research')

        assert handle['state'] == 'running'
        assert handle['batch_name'] == 'abandoned-fast'


def _settle(outputs_dir: str, **fields: Any) -> None:
    """Rewrite fields of a run's record, as an earlier attempt that ended badly would."""
    record_path = Path(outputs_dir) / 'run.json'
    record = json.loads(record_path.read_text(encoding='utf-8'))
    record.update(fields)
    record_path.write_text(json.dumps(record), encoding='utf-8')


class TestAResumeOfARunWithStagesLeftIsNotACollect:
    """Only a run with nothing left to run is collected (T20a).

    A `failed` record, or a `complete` one with a stage that exited non-zero,
    re-runs its remaining stages on resume, and those block for as long as a new
    run's. Answering them as a collect ignored an explicit `detach=true` and the
    tier default, which is the long blocking call T20a set out to remove.
    """

    _UNFINISHED = pytest.mark.parametrize(
        'fields',
        [{'status': 'failed', 'ok': False}, {'status': 'complete', 'ok': False}],
        ids=['failed', 'a-stage-exited-non-zero'],
    )

    @_UNFINISHED
    @pytest.mark.parametrize('detach', [None, True])
    async def test_it_returns_a_handle_unless_told_to_block(
        self, rooted: Path, delivering_stages: None, fields: dict[str, Any], detach: bool | None
    ) -> None:
        first = run_research('q', assurance='fast', batch_name='unfinished-run')
        _settle(first['outputs_dir'], **fields)

        handle = await research('', resume=first['outputs_dir'], detach=detach)

        assert handle['state'] == 'running'
        assert handle['batch_name'] == 'unfinished-run'

    @_UNFINISHED
    async def test_detach_false_still_blocks_and_returns_the_result(
        self, rooted: Path, delivering_stages: None, fields: dict[str, Any]
    ) -> None:
        first = run_research('q', assurance='fast', batch_name='unfinished-run')
        _settle(first['outputs_dir'], **fields)

        result = await research('', resume=first['outputs_dir'], detach=False)

        assert 'state' not in result
        assert [c['id'] for c in result['claims']] == ['c1']

    @_UNFINISHED
    async def test_an_unfinished_research_tier_run_still_blocks_on_its_own_tier(
        self, rooted: Path, delivering_stages: None, fields: dict[str, Any]
    ) -> None:
        first = run_research('q', assurance='research', batch_name='unfinished-research')
        _settle(first['outputs_dir'], **fields)

        result = await research('', resume=first['outputs_dir'])

        assert 'state' not in result


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


def _iso(at: datetime) -> str:
    return at.isoformat()


def _finished_run(root: Path, name: str, *, seat_turn_s: float, ago_s: float = 3600.0) -> None:
    """A complete run record whose synthesis held the seat for ``seat_turn_s``."""
    took = datetime.now(UTC) - timedelta(seconds=ago_s)
    run_dir = root / 'outputs_root' / name
    run_dir.mkdir(parents=True)
    (run_dir / 'run.json').write_text(
        json.dumps(
            {
                'question': 'q',
                'batch_name': name,
                'status': 'complete',
                'ok': True,
                'stages': {
                    'openrouter': {'exit_code': 0},
                    'synthesis': {
                        'exit_code': 0,
                        'started_at': _iso(took - timedelta(seconds=30)),
                        'seat_acquired_at': _iso(took),
                        'finished_at': _iso(took + timedelta(seconds=seat_turn_s)),
                    },
                },
            }
        ),
        encoding='utf-8',
    )


def _hold_the_seat(root: Path, *, owner: str, for_s: float) -> Path:
    """Stamp the seat lock as held by this live test process for ``for_s`` so far."""
    lock = root / 'state_root' / 'claude-seat.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    since = datetime.now(UTC) - timedelta(seconds=for_s)
    lock.write_text(
        json.dumps({'pid': os.getpid(), 'owner': owner, 'at': _iso(since)}), encoding='utf-8'
    )
    return lock


def _queue_behind(lock: Path, owner: str) -> None:
    """Leave the ticket a run waiting on ``lock`` holds, as ``seat_lock`` does."""
    waiters = lock.with_name(f'{lock.name}.waiters')
    waiters.mkdir(parents=True, exist_ok=True)
    token = owner.replace('/', '_').replace(':', '_')
    (waiters / f'{os.getpid()}-{token}.json').write_text(
        json.dumps({'pid': os.getpid(), 'owner': owner, 'since': 'now'}), encoding='utf-8'
    )


def _waiting_run(root: Path, name: str) -> Path:
    """A live run whose synthesis stage is waiting."""
    run_dir = root / 'outputs_root' / name
    run_dir.mkdir(parents=True)
    (run_dir / 'run.json').write_text(
        json.dumps(
            {
                'question': 'q',
                'batch_name': name,
                'status': 'dispatching',
                'owner_pid': os.getpid(),
                'current_stage': 'synthesis',
                'stages': {
                    'openrouter': {'state': 'done', 'exit_code': 0},
                    'synthesis': {'state': 'waiting', 'exit_code': None, 'started_at': 'x'},
                },
            }
        ),
        encoding='utf-8',
    )
    return run_dir


class TestAQueuedRunReportsTheSeat:
    """How many runs wait on the seat, and when this one can expect it (T1f).

    A queued run said only `waiting`: nothing about how long, so a collector
    could not tell a short queue from a stuck one. The lock has no order (any
    waiter may win the next 5 s poll), so a count and a range are all that can
    be promised: the early bound assumes this run goes next, the late bound
    that every other waiter goes first.
    """

    async def test_each_waiter_sees_the_queue_and_a_range_from_the_median(
        self, rooted: Path
    ) -> None:
        for name, seconds in (('run-a', 200.0), ('run-b', 300.0), ('run-c', 400.0)):
            _finished_run(rooted, name, seat_turn_s=seconds)  # median 300 s
        lock = _hold_the_seat(rooted, owner='holder-run/synthesis:1', for_s=60.0)
        waiters = ('first-waiter', 'second-waiter')
        for name in waiters:
            _waiting_run(rooted, name)
            _queue_behind(lock, f'{name}/synthesis:1')

        for name in waiters:
            status = await research_status(str(rooted / 'outputs_root' / name))
            seat = status['seat']
            assert seat['waiting'] == 2
            assert seat['holder'] == 'holder-run/synthesis:1'
            early, late = seat['expected_start_s']
            # 300 s median less the holder's 60 s so far; the clock ran on a little.
            assert 230 <= early <= 240
            assert late - early == 300  # one other waiter, one median turn
            assert seat['reason'] is None

    async def test_with_no_measured_turn_the_range_is_null_with_a_reason(
        self, rooted: Path
    ) -> None:
        lock = _hold_the_seat(rooted, owner='holder-run/synthesis:1', for_s=60.0)
        _waiting_run(rooted, 'lone-waiter')
        _queue_behind(lock, 'lone-waiter/synthesis:1')

        seat = (await research_status(str(rooted / 'outputs_root' / 'lone-waiter')))['seat']

        assert seat['waiting'] == 1
        assert seat['expected_start_s'] is None
        assert seat['reason']

    async def test_a_run_backing_off_rather_than_queued_has_no_seat_block(
        self, rooted: Path
    ) -> None:
        # A stage's `waiting` also covers a rate-limit backoff; only a run that
        # holds a ticket is queued for the seat.
        _hold_the_seat(rooted, owner='holder-run/synthesis:1', for_s=60.0)
        _waiting_run(rooted, 'backing-off')
        status = await research_status(str(rooted / 'outputs_root' / 'backing-off'))
        assert status['state'] == 'running'
        assert 'seat' not in status

    async def test_only_turns_that_held_the_seat_are_measured(self, rooted: Path) -> None:
        _finished_run(rooted, 'measured', seat_turn_s=300.0)
        # A dry run, a failed run and a stage that never took the seat (skipped
        # on a resume) say nothing about how long a seat turn lasts.
        now = _iso(datetime.now(UTC))
        others: tuple[tuple[str, str, dict[str, Any]], ...] = (
            ('dry', 'validated', {'exit_code': 0, 'seat_acquired_at': now, 'finished_at': now}),
            ('broke', 'failed', {'exit_code': 1}),
            ('resumed', 'complete', {'exit_code': 0, 'started_at': now, 'finished_at': now}),
        )
        for name, status, synthesis in others:
            run_dir = rooted / 'outputs_root' / name
            run_dir.mkdir(parents=True)
            (run_dir / 'run.json').write_text(
                json.dumps(
                    {'batch_name': name, 'status': status, 'stages': {'synthesis': synthesis}}
                ),
                encoding='utf-8',
            )
        lock = _hold_the_seat(rooted, owner='holder-run/synthesis:1', for_s=0.0)
        _waiting_run(rooted, 'waiter')
        _queue_behind(lock, 'waiter/synthesis:1')

        seat = (await research_status(str(rooted / 'outputs_root' / 'waiter')))['seat']

        early, late = seat['expected_start_s']
        assert 290 <= early <= 300
        assert late == early


class TestADetachedHandleReportsTheSeat:
    @pytest.fixture(autouse=True)
    def _instant_stages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            'mantis_research.interface.research_service.require_local_claude_seat',
            lambda **_: None,
        )
        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', lambda *a, **k: 0
        )

    async def test_the_handle_carries_the_queue_this_run_would_join(self, rooted: Path) -> None:
        for name, seconds in (('run-a', 200.0), ('run-b', 300.0), ('run-c', 400.0)):
            _finished_run(rooted, name, seat_turn_s=seconds)
        lock = _hold_the_seat(rooted, owner='holder-run/synthesis:1', for_s=60.0)
        _queue_behind(lock, 'other-run/synthesis:1')

        handle = await research('q', assurance='fast', detach=True)

        seat = handle['seat']
        assert seat['waiting'] == 1
        assert seat['holder'] == 'holder-run/synthesis:1'
        early, late = seat['expected_start_s']
        assert 230 <= early <= 240
        # Joining now, this run would sit behind the one already waiting.
        assert late - early == 300

    async def test_a_research_only_handle_has_no_seat_block(self, rooted: Path) -> None:
        handle = await research('q', assurance='research', detach=True)
        assert 'seat' not in handle


class TestAFinishedRunRecordsItsSeatTurn:
    def test_the_record_keeps_when_each_stage_ran_and_took_the_seat(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            'mantis_research.interface.research_service.require_local_claude_seat',
            lambda **_: None,
        )

        def fake(stage: str, cfg: Any, *, on_event: Any = None, **_: Any) -> int:
            if stage == 'synthesis':
                emit(on_event, RunEvent(kind='waiting', message='queued', data={'seat_pid': 1}))
                emit(
                    on_event,
                    RunEvent(
                        kind='seat_acquired',
                        message='took the seat',
                        data={'seat_owner': f'{cfg.batch_name}/synthesis:1'},
                    ),
                )
            return 0

        monkeypatch.setattr('mantis_research.interface.cli.dispatch.dispatch_stage_config', fake)
        run_research('q', assurance='fast', batch_name='timed-run')

        record = json.loads(
            (rooted / 'outputs_root' / 'timed-run' / 'run.json').read_text(encoding='utf-8')
        )
        synthesis = record['stages']['synthesis']
        assert synthesis['exit_code'] == 0
        assert synthesis['started_at'] <= synthesis['seat_acquired_at'] <= synthesis['finished_at']
        assert 'seat_acquired_at' not in record['stages']['openrouter']
        assert record['stages']['openrouter']['exit_code'] == 0


class TestCollectingARunKeepsItsRecord:
    """A collect reads the finished run; it does not run it again (T1f).

    The collect call is the standard way to finish a seat-tier run. It used to
    run every stage again, each skipping, and rewrite `run.json` with that call's
    timings only: the seat turn the expected-start median reads was dropped, and
    `started_at` moved to the collect, which put an old run at the top of the
    newest-first listing.
    """

    @pytest.fixture
    def seat_run(self, rooted: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        monkeypatch.setattr(
            'mantis_research.interface.research_service.require_local_claude_seat',
            lambda **_: None,
        )

        def fake(stage: str, cfg: Any, *, on_event: Any = None, **_: Any) -> int:
            if stage == 'synthesis':
                emit(
                    on_event,
                    RunEvent(
                        kind='seat_acquired',
                        message='took the seat',
                        data={'seat_owner': f'{cfg.batch_name}/synthesis:1'},
                    ),
                )
            return 0

        monkeypatch.setattr('mantis_research.interface.cli.dispatch.dispatch_stage_config', fake)
        return run_research('q', assurance='fast', batch_name='collected-run')

    def test_the_record_is_untouched_and_the_seat_turn_still_counts(
        self, rooted: Path, seat_run: dict[str, Any]
    ) -> None:
        record_path = rooted / 'outputs_root' / 'collected-run' / 'run.json'
        before = record_path.read_bytes()
        assert len(seat_turn_durations(rooted / 'outputs_root')) == 1

        collected = resume_research(Path(seat_run['outputs_dir']))

        assert record_path.read_bytes() == before
        assert len(seat_turn_durations(rooted / 'outputs_root')) == 1
        assert collected == seat_run

    def test_a_collect_does_not_need_the_seat(
        self, rooted: Path, seat_run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(**_: Any) -> None:
            msg = 'the seat must not be consulted to read a finished run'
            raise LocalSeatUnavailableError(msg)

        monkeypatch.setattr(
            'mantis_research.interface.research_service.require_local_claude_seat', refuse
        )
        assert resume_research(Path(seat_run['outputs_dir']))['ok'] is True

    async def test_collecting_an_old_run_leaves_the_listing_order(
        self, rooted: Path, seat_run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_research('newer question', assurance='fast', batch_name='newer-run')
        names = [r['batch_name'] for r in (await research_status())['runs']]
        assert names == ['newer-run', 'collected-run']

        resume_research(Path(seat_run['outputs_dir']))

        names = [r['batch_name'] for r in (await research_status())['runs']]
        assert names == ['newer-run', 'collected-run']

    def test_a_dry_run_resume_still_walks_the_stages(
        self, rooted: Path, seat_run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Only a real call collects; a dry run walks its stages as a dry run.
        calls: list[tuple[str, bool]] = []

        def fake(stage: str, cfg: Any, *, dry_run: bool = False, **_: Any) -> int:
            calls.append((stage, dry_run))
            return 0

        monkeypatch.setattr('mantis_research.interface.cli.dispatch.dispatch_stage_config', fake)
        resume_research(Path(seat_run['outputs_dir']), dry_run=True)
        assert calls == [('openrouter', True), ('synthesis', True)]


class TestAFinishedRecordKeepsTheRunsIdentity:
    """The terminal record kept the manifest and dropped what the run started with.

    `started_at` is what the run listing sorts on and what `age_s` counts from,
    so every finished run fell back to its directory's modification time, which
    any later write moves. `substrates` is what a resume asks the research stage
    for, so a resume of a finished run whose research failed asked the default
    set and bought briefs the caller never asked for.
    """

    def test_the_record_keeps_when_the_run_started(
        self, rooted: Path, delivering_stages: None
    ) -> None:
        run_research('q', assurance='fast', batch_name='finished-run')

        record = json.loads(
            (rooted / 'outputs_root' / 'finished-run' / 'run.json').read_text(encoding='utf-8')
        )
        assert record['status'] == 'complete'
        assert record['started_at'] <= record['finished_at']

    def test_a_resume_of_a_run_whose_research_failed_asks_the_same_substrates(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            'mantis_research.interface.research_service.require_local_claude_seat',
            lambda **_: None,
        )
        asked: list[list[str]] = []

        def fake(stage: str, cfg: Any, **_: Any) -> int:
            if stage != 'openrouter':
                return 0
            asked.append([entry.subslug for entry in cfg.topics[0].stages.openrouter])
            return 1 if len(asked) == 1 else 0

        monkeypatch.setattr('mantis_research.interface.cli.dispatch.dispatch_stage_config', fake)
        first = run_research('q', assurance='fast', substrates=['openai'], batch_name='one-model')
        assert first['ok'] is False

        resume_research(Path(first['outputs_dir']))

        assert asked == [['openai'], ['openai']]


def _exited_pid() -> int:
    proc = subprocess.Popen([sys.executable, '-c', ''])
    proc.wait()
    return proc.pid


def _listed_run(
    rooted: Path, name: str, *, status: str, owner_pid: int, started_ago: timedelta
) -> Path:
    run_dir = rooted / 'outputs_root' / name
    run_dir.mkdir(parents=True)
    (run_dir / 'run.json').write_text(
        json.dumps(
            {
                'question': f'question for {name}',
                'question_slug': f'{name}-slug',
                'batch_name': name,
                'outputs_dir': str(run_dir),
                'status': status,
                'owner_pid': owner_pid,
                'started_at': (datetime.now(UTC) - started_ago).isoformat(),
                'assurance': 'fast',
                'stages': {},
            }
        ),
        encoding='utf-8',
    )
    return run_dir


class TestStatusWithNoArgumentListsRuns:
    """`research_status()` answers "what runs are there?" without a path (T21)."""

    async def test_the_runs_come_back_projected_and_newest_first(self, rooted: Path) -> None:
        # Written oldest-first on purpose, so directory order cannot pass for sorting.
        old = _listed_run(
            rooted, 'abandoned-run', status='dispatching', owner_pid=_exited_pid(),
            started_ago=timedelta(hours=3),
        )  # fmt: skip
        mid = _listed_run(
            rooted, 'finished-run', status='complete', owner_pid=0,
            started_ago=timedelta(hours=2),
        )  # fmt: skip
        new = _listed_run(
            rooted, 'running-run', status='dispatching', owner_pid=os.getpid(),
            started_ago=timedelta(minutes=5),
        )  # fmt: skip

        listing = await research_status()

        runs = listing['runs']
        assert [r['batch_name'] for r in runs] == ['running-run', 'finished-run', 'abandoned-run']
        assert [r['state'] for r in runs] == ['running', 'finished', 'abandoned']
        assert [r['outputs_dir'] for r in runs] == [str(new), str(mid), str(old)]
        assert [r['question_slug'] for r in runs] == [
            'running-run-slug',
            'finished-run-slug',
            'abandoned-run-slug',
        ]
        assert runs[0]['question'] == 'question for running-run'
        assert runs[0]['age_s'] == pytest.approx(300, abs=60)
        assert runs[2]['age_s'] == pytest.approx(3 * 3600, abs=60)
        assert listing['truncated'] == 0
        assert listing['data_root']

    async def test_a_directory_without_a_record_is_not_a_run(self, rooted: Path) -> None:
        _listed_run(
            rooted, 'a-run', status='complete', owner_pid=0, started_ago=timedelta(minutes=1)
        )
        (rooted / 'outputs_root' / 'stray-dir').mkdir()
        (rooted / 'outputs_root' / 'stray-file.txt').write_text('x', encoding='utf-8')

        runs = (await research_status())['runs']

        assert [r['batch_name'] for r in runs] == ['a-run']

    async def test_an_unreadable_record_is_listed_as_unknown(self, rooted: Path) -> None:
        _listed_run(
            rooted, 'good-run', status='complete', owner_pid=0, started_ago=timedelta(minutes=1)
        )
        bad = rooted / 'outputs_root' / 'bad-run'
        bad.mkdir()
        (bad / 'run.json').write_text('{not json', encoding='utf-8')

        runs = (await research_status())['runs']

        by_dir = {Path(r['outputs_dir']).name: r for r in runs}
        assert by_dir['bad-run']['state'] == 'unknown'
        assert by_dir['bad-run']['detail']
        assert by_dir['good-run']['state'] == 'finished'

    async def test_a_record_without_started_at_sorts_by_directory_mtime(self, rooted: Path) -> None:
        stamped = _listed_run(
            rooted, 'stamped', status='complete', owner_pid=0, started_ago=timedelta(hours=1)
        )
        bare = rooted / 'outputs_root' / 'bare'
        bare.mkdir()
        (bare / 'run.json').write_text(
            json.dumps({'batch_name': 'bare', 'status': 'complete'}), encoding='utf-8'
        )
        recent = datetime.now(UTC).timestamp() - 60
        os.utime(bare, (recent, recent))
        os.utime(stamped, (recent - 7200, recent - 7200))

        runs = (await research_status())['runs']

        assert [r['batch_name'] for r in runs] == ['bare', 'stamped']
        assert runs[0]['age_s'] == pytest.approx(60, abs=60)

    async def test_the_listing_is_capped_and_says_how_many_were_left_out(
        self, rooted: Path
    ) -> None:
        for n in range(53):
            _listed_run(
                rooted, f'run-{n:02d}', status='complete', owner_pid=0,
                started_ago=timedelta(minutes=n + 1),
            )  # fmt: skip

        listing = await research_status()

        assert len(listing['runs']) == 50
        assert listing['truncated'] == 3
        assert listing['runs'][0]['batch_name'] == 'run-00'

    async def test_an_empty_outputs_root_lists_nothing(self, rooted: Path) -> None:
        listing = await research_status()

        assert listing['runs'] == []
        assert listing['truncated'] == 0

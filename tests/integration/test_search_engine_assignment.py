"""Each default substrate reads its own web-search index (ADR-0012).

Field evidence, 2026-10-07: DeepSeek and Google both went through OpenRouter's
``exa`` engine and, in 10 of 16 research-tier runs, cited exactly the same
pages. These tests hold the assignment end to end: the config that is built,
the payload that would be sent, the record the run leaves, and the overlap the
tool measures from the briefs it produced.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import pytest
import structlog
from typer.testing import CliRunner

from mantis_research.core.config import load_batch_config
from mantis_research.core.paths import RunDirs, topic_stem
from mantis_research.core.state import OpenRouterResearchState, SubsessionResult
from mantis_research.interface import research_service
from mantis_research.interface.cli import app
from mantis_research.interface.cli.dispatch import dispatch_stage_config
from mantis_research.interface.research_service import (
    build_config,
    resume_research,
    run_research,
)

if TYPE_CHECKING:
    from pathlib import Path

_DEFAULT_ENGINES = {'openai': 'native', 'deepseek': 'parallel', 'google': 'native'}


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


def _record(rooted: Path, batch: str) -> dict[str, Any]:
    path = rooted / 'outputs_root' / batch / 'run.json'
    record: dict[str, Any] = json.loads(path.read_text(encoding='utf-8'))
    return record


def _payload_engines(rooted: Path, batch: str) -> dict[str, str]:
    """subslug -> the ``engine`` in the dry-run request body, from the transcripts."""
    found: dict[str, str] = {}
    for log in (rooted / 'transcripts_root' / batch).glob('*-openrouter.log'):
        match = re.search(r'"engine":\s*"([^"]+)"', log.read_text(encoding='utf-8'))
        for vendor in ('openai', 'deepseek', 'google', 'qwen'):
            if f'-{vendor}-' in log.name and match:
                found[vendor] = match.group(1)
    return found


class TestBuildConfig:
    def _entries(self, substrates: list[str]) -> dict[str, Any]:
        cfg = load_batch_config(
            build_config(
                'q',
                substrates=substrates,
                primary=f'openrouter:{substrates[0]}',
                journal=False,
                batch_name='b',
                assurance='fast',
            )
        )
        return {e.subslug: e for e in cfg.topics[0].stages.openrouter}

    def test_default_substrates_get_the_assigned_engines(self) -> None:
        entries = self._entries(['openai', 'deepseek', 'google'])
        assert {k: e.web_search_engine for k, e in entries.items()} == _DEFAULT_ENGINES

    def test_custom_substrates_get_distinct_engines(self) -> None:
        entries = self._entries(['deepseek', 'qwen', 'openai'])
        assert {k: e.web_search_engine for k, e in entries.items()} == {
            'deepseek': 'parallel',
            'qwen': 'exa',
            'openai': 'native',
        }


class TestRecordedEngines:
    def test_manifest_and_run_record_carry_search_engines(self, rooted: Path) -> None:
        manifest = run_research(
            'q', assurance='fast', batch_name='b', dry_run=True, log_level='CRITICAL'
        )
        assert manifest['search_engines'] == _DEFAULT_ENGINES
        assert _record(rooted, 'b')['search_engines'] == _DEFAULT_ENGINES

    def test_every_write_of_the_record_carries_it(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The record is replaced whole at each write, so a key left out of one
        # write vanishes from the file until the next one restores it.
        seen: list[dict[str, Any]] = []

        def fake_dispatch(stage: str, cfg: object, **kw: Any) -> int:
            seen.append(_record(rooted, 'b'))
            if stage == 'synthesis':
                kw['on_event'](
                    research_service.RunEvent(
                        kind='substrate_done', message='x', data={'substrate': 'openai'}
                    )
                )
                seen.append(_record(rooted, 'b'))
                raise RuntimeError('boom')
            return 0

        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', fake_dispatch
        )
        with pytest.raises(RuntimeError, match='boom'):
            run_research('q', assurance='fast', batch_name='b', log_level='CRITICAL')
        seen.append(_record(rooted, 'b'))
        assert seen[0]['status'] == 'dispatching'
        assert seen[-1]['status'] == 'failed'
        for record in seen:
            assert record['search_engines'] == _DEFAULT_ENGINES, record['status']

    def test_terminal_record_carries_it(self, rooted: Path) -> None:
        run_research('q', assurance='fast', batch_name='b', dry_run=True, log_level='CRITICAL')
        record = _record(rooted, 'b')
        assert record['status'] == 'validated'
        assert record['search_engines'] == _DEFAULT_ENGINES

    def test_a_substrate_with_web_search_off_records_null(self) -> None:
        cfg = load_batch_config(
            {
                'schema_version': 2,
                'batch_name': 'b',
                'models': {'claude': {}},
                'topics': [
                    {
                        'id': '1',
                        'slug': 's',
                        'title': 't',
                        'research_prompt': 'p',
                        'stages': {
                            'claude': {'prompt': ''},
                            'openrouter': [
                                {'subslug': 'a', 'model': 'auto:openai', 'web_search': False},
                                {'subslug': 'b', 'model': 'auto:openai', 'web_search': True},
                                {
                                    'subslug': 'c',
                                    'model': 'auto:deepseek',
                                    'web_search': True,
                                    'web_search_engine': 'firecrawl',
                                },
                            ],
                        },
                    }
                ],
            }
        )
        # An entry that turns search on without naming an engine is sent as
        # 'native' by the stage, so that is what the record says it read.
        assert research_service._search_engines_of(cfg) == {
            'a': None,
            'b': 'native',
            'c': 'firecrawl',
        }

    def test_a_resumed_finished_run_keeps_its_recorded_engines(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', lambda *_a, **_k: 0
        )
        first = run_research('q', assurance='research', batch_name='b', log_level='CRITICAL')
        assert first['search_engines'] == _DEFAULT_ENGINES
        # Rewrite the record to values today's assignment would never produce, so
        # a resume that recomputed instead of keeping could not pass.
        run_json = rooted / 'outputs_root' / 'b' / 'run.json'
        record = json.loads(run_json.read_text(encoding='utf-8'))
        pinned = {'openai': 'exa', 'deepseek': 'perplexity', 'google': 'parallel'}
        record['search_engines'] = pinned
        run_json.write_text(json.dumps(record), encoding='utf-8')
        collected = resume_research(rooted / 'outputs_root' / 'b', log_level='CRITICAL')
        assert collected['search_engines'] == pinned


class TestResumeKeepsEngines:
    """A resume rebuilds the config; the record must still say what was used."""

    @staticmethod
    def _interrupted(rooted: Path, **extra: Any) -> Path:
        run_dir = rooted / 'outputs_root' / 'b'
        run_dir.mkdir(parents=True)
        record = {
            'question': 'q',
            'question_slug': 'q',
            'batch_name': 'b',
            'assurance': 'research',
            'substrates': ['openai', 'deepseek'],
            'layout': 'batch',
            'outputs_dir': str(run_dir),
            'status': 'failed',
            'started_at': 'earlier',
            **extra,
        }
        (run_dir / 'run.json').write_text(json.dumps(record), encoding='utf-8')
        return run_dir

    @staticmethod
    def _research_state(rooted: Path, statuses: dict[str, str]) -> None:
        state_dir = RunDirs('batch', 'b').state('openrouter')
        state_dir.mkdir(parents=True, exist_ok=True)
        state = OpenRouterResearchState(
            id='1',
            slug='q',
            subsessions=[SubsessionResult(subslug=k, status=v) for k, v in statuses.items()],
        )
        (state_dir / '1.json').write_text(state.model_dump_json(), encoding='utf-8')

    def test_a_recorded_assignment_is_used_for_the_substrates_still_to_run(
        self, rooted: Path
    ) -> None:
        # Today's assignment is native/parallel; the run used something else, so
        # neither the payload nor the record may fall back to today's.
        recorded = {'openai': 'exa', 'deepseek': 'perplexity'}
        run_dir = self._interrupted(rooted, search_engines=recorded)
        manifest = resume_research(run_dir, dry_run=True, log_level='CRITICAL')
        assert manifest['search_engines'] == recorded
        assert _record(rooted, 'b')['search_engines'] == recorded
        assert _payload_engines(rooted, 'b') == recorded

    def test_a_record_before_the_field_marks_finished_substrates_unknown(
        self, rooted: Path
    ) -> None:
        run_dir = self._interrupted(rooted)
        self._research_state(rooted, {'openai': 'done', 'deepseek': 'failed'})
        manifest = resume_research(run_dir, dry_run=True, log_level='CRITICAL')
        # openai finished under an engine nobody wrote down; deepseek re-runs
        # under today's assignment, and the record says so.
        assert manifest['search_engines'] == {'openai': None, 'deepseek': 'parallel'}
        assert _record(rooted, 'b')['search_engines'] == {'openai': None, 'deepseek': 'parallel'}

    def test_a_record_before_the_field_with_nothing_finished_gets_the_assignment(
        self, rooted: Path
    ) -> None:
        run_dir = self._interrupted(rooted)
        manifest = resume_research(run_dir, dry_run=True, log_level='CRITICAL')
        assert manifest['search_engines'] == {'openai': 'native', 'deepseek': 'parallel'}

    def test_unknown_stays_unknown_across_a_second_resume(self, rooted: Path) -> None:
        run_dir = self._interrupted(rooted)
        self._research_state(rooted, {'openai': 'done', 'deepseek': 'failed'})
        resume_research(run_dir, dry_run=True, log_level='CRITICAL')
        # The first resume wrote openai's engine as null; with openai still
        # recorded done the second must not invent one.
        self._research_state(rooted, {'openai': 'done', 'deepseek': 'done'})
        manifest = resume_research(run_dir, dry_run=True, log_level='CRITICAL')
        assert manifest['search_engines'] == {'openai': None, 'deepseek': 'parallel'}


class TestPayloadMatchesRecord:
    def test_dry_run_payload_uses_the_recorded_engines(self, rooted: Path) -> None:
        manifest = run_research(
            'q', assurance='research', batch_name='b', dry_run=True, log_level='CRITICAL'
        )
        assert _payload_engines(rooted, 'b') == manifest['search_engines']

    def test_an_entry_without_an_engine_is_still_sent_as_native(self, rooted: Path) -> None:
        # Once `web_search_engine` is a declared field, model_dump() yields None
        # for an entry that omits it; the stage must not forward that None.
        cfg = load_batch_config(
            {
                'schema_version': 2,
                'batch_name': 'b',
                'runner': {'layout': 'batch'},
                'models': {'claude': {}},
                'topics': [
                    {
                        'id': '1',
                        'slug': 's',
                        'title': 't',
                        'research_prompt': 'p',
                        'stages': {
                            'claude': {'prompt': ''},
                            'openrouter': [
                                {'subslug': 'openai', 'model': 'auto:openai', 'web_search': True}
                            ],
                        },
                    }
                ],
            }
        )
        assert dispatch_stage_config('openrouter', cfg, dry_run=True, log_level='CRITICAL') == 0
        assert _payload_engines(rooted, 'b') == {'openai': 'native'}


class TestSharedIndexWarning:
    def test_a_run_whose_substrates_share_an_index_says_so(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warnings: list[dict[str, Any]] = []

        class Recorder:
            def warning(self, event: str, **kw: Any) -> None:
                warnings.append({'event': event, **kw})

            def __getattr__(self, name: str) -> Any:
                return lambda *_a, **_k: None

        monkeypatch.setattr(research_service, 'log', Recorder())
        run_research(
            'q',
            assurance='research',
            substrates=['deepseek', 'qwen', 'mistralai', 'meta-llama'],
            batch_name='b',
            dry_run=True,
            log_level='CRITICAL',
        )
        shared = [w for w in warnings if 'index' in w['event']]
        assert len(shared) == 1
        assert shared[0]['substrates'] == ['deepseek', 'meta-llama']

    def test_distinct_indexes_warn_about_nothing(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warnings: list[str] = []

        class Recorder:
            def warning(self, event: str, **_: Any) -> None:
                warnings.append(event)

            def __getattr__(self, name: str) -> Any:
                return lambda *_a, **_k: None

        monkeypatch.setattr(research_service, 'log', Recorder())
        run_research('q', assurance='research', batch_name='b', dry_run=True, log_level='CRITICAL')
        assert warnings == []


class TestSharedIndexWarningChannel:
    """The warning must not reach stdout, which carries the CLI's manifest JSON."""

    def test_the_warning_goes_to_stderr_and_stdout_stays_one_json_document(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The suite swaps structlog for a null logger. A fresh process has
        # structlog's defaults instead, which print to stdout, so put those back,
        # with a module logger that has not been bound by an earlier test.
        structlog.reset_defaults()
        monkeypatch.setattr(research_service, 'log', structlog.get_logger('research_service'))
        result = CliRunner().invoke(
            app,
            [
                'research',
                'q',
                '--assurance',
                'research',
                '--substrates',
                'deepseek,qwen,mistralai,meta-llama',
                '--batch-name',
                'b',
                '--dry-run',
            ],
        )
        assert result.exit_code == 0, result.stderr
        manifest = json.loads(result.stdout)  # raises if anything else is on stdout
        assert manifest['search_engines']['meta-llama'] == manifest['search_engines']['deepseek']
        assert 'substrates share a search index' in result.stderr


class TestRetrievalOverlap:
    @staticmethod
    def _write_briefs(rooted: Path, batch: str, briefs: dict[str, str]) -> None:
        dirs = RunDirs('batch', batch)
        brief_dir = dirs.output('openrouter') / topic_stem('1', 'q')
        brief_dir.mkdir(parents=True, exist_ok=True)
        for vendor, text in briefs.items():
            (brief_dir / f'{vendor}.md').write_text(text, encoding='utf-8')

    def test_a_dry_run_has_no_overlap_to_report(self, rooted: Path) -> None:
        manifest = run_research(
            'q', assurance='research', batch_name='b', dry_run=True, log_level='CRITICAL'
        )
        assert 'retrieval_overlap' in manifest
        assert manifest['retrieval_overlap'] is None
        assert _record(rooted, 'b')['retrieval_overlap'] is None

    def test_fewer_than_two_briefs_on_disk_is_null(self, rooted: Path) -> None:
        self._write_briefs(rooted, 'b', {'openai': '[a](https://a.example/x)'})
        manifest = research_service._manifest(
            question='q',
            batch_name='b',
            assurance='research',
            slug='q',
            substrates=['openai', 'deepseek', 'google'],
            results={'openrouter': 0},
            dry_run=False,
            search_engines=_DEFAULT_ENGINES,
        )
        assert manifest['retrieval_overlap'] is None

    def test_overlap_is_computed_from_the_briefs_on_disk(self, rooted: Path) -> None:
        self._write_briefs(
            rooted,
            'b',
            {
                'openai': '[a](https://a.example/x) [b](https://b.example/y)',
                'deepseek': '[a](https://a.example/x) [b](https://b.example/y)',
                'google': '[c](https://c.example/z)',
            },
        )
        manifest = research_service._manifest(
            question='q',
            batch_name='b',
            assurance='research',
            slug='q',
            substrates=['openai', 'deepseek', 'google'],
            results={'openrouter': 0},
            dry_run=False,
            search_engines=_DEFAULT_ENGINES,
        )
        overlap = manifest['retrieval_overlap']
        assert overlap == {
            'pairs': [
                {'a': 'openai', 'b': 'deepseek', 'jaccard': 1.0},
                {'a': 'openai', 'b': 'google', 'jaccard': 0.0},
                {'a': 'deepseek', 'b': 'google', 'jaccard': 0.0},
            ],
            'max': 1.0,
        }

    def test_a_brief_that_is_not_utf8_is_scored_not_raised(self, rooted: Path) -> None:
        self._write_briefs(rooted, 'b', {'openai': '[a](https://a.example/x)'})
        brief_dir = RunDirs('batch', 'b').output('openrouter') / topic_stem('1', 'q')
        undecodable = bytes([0xFF, 0xFE])
        (brief_dir / 'deepseek.md').write_bytes(undecodable + b' [a](https://a.example/x)')
        manifest = research_service._manifest(
            question='q',
            batch_name='b',
            assurance='research',
            slug='q',
            substrates=['openai', 'deepseek'],
            results={'openrouter': 0},
            dry_run=False,
            search_engines={'openai': 'native', 'deepseek': 'parallel'},
        )
        assert manifest['retrieval_overlap']['max'] == 1.0

    def test_jaccard_is_rounded_to_three_places(self, rooted: Path) -> None:
        self._write_briefs(
            rooted,
            'b',
            {
                'openai': '[a](https://a.example/1) [b](https://a.example/2)',
                'deepseek': '[a](https://a.example/1) [c](https://a.example/3) [d](https://a.example/4)',
            },
        )
        manifest = research_service._manifest(
            question='q',
            batch_name='b',
            assurance='research',
            slug='q',
            substrates=['openai', 'deepseek'],
            results={'openrouter': 0},
            dry_run=False,
            search_engines={'openai': 'native', 'deepseek': 'parallel'},
        )
        assert manifest['retrieval_overlap']['pairs'][0]['jaccard'] == 0.25
        assert manifest['retrieval_overlap']['max'] == 0.25

    def test_a_substrate_whose_brief_is_missing_is_left_out(self, rooted: Path) -> None:
        self._write_briefs(
            rooted,
            'b',
            {'openai': '[a](https://a.example/x)', 'google': '[a](https://a.example/x)'},
        )
        manifest = research_service._manifest(
            question='q',
            batch_name='b',
            assurance='research',
            slug='q',
            substrates=['openai', 'deepseek', 'google'],
            results={'openrouter': 0},
            dry_run=False,
            search_engines=_DEFAULT_ENGINES,
        )
        pairs = manifest['retrieval_overlap']['pairs']
        assert [(p['a'], p['b']) for p in pairs] == [('openai', 'google')]

    def test_the_terminal_record_carries_the_overlap(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_dispatch(stage: str, cfg: object, **_: Any) -> int:
            self._write_briefs(
                rooted,
                'b',
                {'openai': '[a](https://a.example/x)', 'google': '[a](https://a.example/x)'},
            )
            return 0

        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', fake_dispatch
        )
        manifest = run_research('q', assurance='research', batch_name='b', log_level='CRITICAL')
        assert manifest['retrieval_overlap']['max'] == 1.0
        assert _record(rooted, 'b')['retrieval_overlap'] == manifest['retrieval_overlap']

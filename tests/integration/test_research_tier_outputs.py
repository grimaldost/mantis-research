"""A run's manifest lists a synthesis and sidecar path only when it writes them.

A research-tier manifest used to list ``outputs.synthesis`` and
``outputs.sidecar`` beside the briefs, although that tier runs no synthesis stage
and never writes either file. Every path under ``outputs`` is a destination, and
two destinations that can never be filled are a trap for a caller that opens
them. The keys now follow the rule falsification and evaluation already did: the
stage ran, so the path is listed (ADR-0009 amendment, 2026-10-08).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mantis_research.interface.mcp.server import IncompleteRunError, _agent_result, research_status
from mantis_research.interface.research_service import (
    missing_product,
    resume_research,
    run_research,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


def _record(rooted: Path, batch: str) -> dict[str, Any]:
    record: dict[str, Any] = json.loads(
        (rooted / 'outputs_root' / batch / 'run.json').read_text(encoding='utf-8')
    )
    return record


class TestResearchTierManifest:
    def test_a_research_tier_dry_run_lists_no_synthesis_or_sidecar(self, rooted: Path) -> None:
        manifest = run_research(
            'q', assurance='research', batch_name='b', dry_run=True, log_level='CRITICAL'
        )
        record = _record(rooted, 'b')
        for doc in (manifest, record):
            assert 'synthesis' not in doc['outputs']
            assert 'sidecar' not in doc['outputs']
            assert len(doc['outputs']['briefs']) == 3
            assert doc['produces_sidecar'] is False

    def test_a_fast_tier_dry_run_still_lists_both(self, rooted: Path) -> None:
        manifest = run_research(
            'q', assurance='fast', batch_name='b', dry_run=True, log_level='CRITICAL'
        )
        record = _record(rooted, 'b')
        for doc in (manifest, record):
            assert doc['outputs']['synthesis'].endswith('.md')
            assert doc['outputs']['sidecar'].endswith('.sidecar.json')
            assert doc['produces_sidecar'] is True

    def test_a_tier_stopped_before_synthesis_lists_neither(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The research stage failed, so the loop broke and synthesis never ran:
        # there is no synthesis to point at.
        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', lambda *_a, **_k: 1
        )
        manifest = run_research('q', assurance='fast', batch_name='b', log_level='CRITICAL')
        assert set(manifest['stages']) == {'openrouter'}
        assert 'synthesis' not in manifest['outputs']
        assert 'sidecar' not in manifest['outputs']
        # `produces_sidecar` keeps its meaning (a synthesis stage ran), so this
        # run, which stopped first, owes nothing the refusal could name.
        assert manifest['produces_sidecar'] is False
        assert manifest['ok'] is False


class TestConsumersTolerateTheAbsentKeys:
    @staticmethod
    def _live_research_manifest(rooted: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', lambda *_a, **_k: 0
        )
        return run_research('q', assurance='research', batch_name='b', log_level='CRITICAL')

    def test_a_live_research_tier_run_is_not_missing_a_product(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manifest = self._live_research_manifest(rooted, monkeypatch)
        assert missing_product(manifest) is None

    def test_the_mcp_result_for_a_research_tier_run_does_not_index_the_missing_path(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manifest = self._live_research_manifest(rooted, monkeypatch)
        result = _agent_result(manifest)
        assert result['ok'] is True
        assert result['sidecar_available'] is False
        assert 'synthesis' not in result['outputs']
        assert 'sidecar' not in result['outputs']
        assert result['search_engines'] == manifest['search_engines']
        assert 'retrieval_overlap' in result

    def test_a_run_stopped_before_synthesis_returns_a_result_not_a_keyerror(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', lambda *_a, **_k: 1
        )
        manifest = run_research('q', assurance='fast', batch_name='b', log_level='CRITICAL')
        result = _agent_result(manifest)
        assert result['ok'] is False
        assert result['sidecar_available'] is False

    def test_a_run_that_owes_a_sidecar_and_lists_no_path_is_refused_by_name(self) -> None:
        manifest = {
            'ok': False,
            'dry_run': False,
            'produces_sidecar': True,
            'question': 'q',
            'assurance': 'fast',
            'batch_name': 'b',
            'outputs_dir': '/runs/b',
            'cost': {},
            'stages': {'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 1}},
            'outputs': {'briefs': []},
        }
        with pytest.raises(IncompleteRunError, match='synthesis exited non-zero') as raised:
            _agent_result(manifest)
        assert 'resume=' in str(raised.value)

    def test_a_missing_sidecar_path_on_an_owing_run_reads_as_missing(self) -> None:
        manifest = {
            'dry_run': False,
            'produces_sidecar': True,
            'stages': {'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 0}},
            'outputs': {'briefs': []},
            'sidecar': {'status': 'failed', 'error': 'schema drift'},
        }
        assert missing_product(manifest) == (
            'every stage exited 0 and the sidecar turn failed: schema drift'
        )


class TestOldRecordsKeepWorking:
    """A ``run.json`` written before this change still lists both paths."""

    @staticmethod
    def _old_research_tier_record(rooted: Path) -> Path:
        run = rooted / 'outputs_root' / 'old'
        run.mkdir(parents=True)
        brief_dir = run / 'openrouter' / '01-q'
        record = {
            'question': 'q',
            'question_slug': 'q',
            'batch_name': 'old',
            'assurance': 'research',
            'substrates': ['openai', 'deepseek'],
            'layout': 'batch',
            'outputs_dir': str(run),
            'dry_run': False,
            'produces_sidecar': False,
            'stages': {'openrouter': {'exit_code': 0}},
            'outputs': {
                'briefs': [str(brief_dir / 'openai.md'), str(brief_dir / 'deepseek.md')],
                'synthesis': str(run / 'synthesis' / '01-q.md'),
                'sidecar': str(run / 'synthesis' / '01-q.sidecar.json'),
            },
            'cost': {'available': True, 'cost_usd': 0.1},
            'sidecar': {'status': 'not_owed', 'error': None},
            'ok': True,
            'status': 'complete',
            'started_at': '2026-10-01T00:00:00+00:00',
            'finished_at': '2026-10-01T00:05:00+00:00',
        }
        (run / 'run.json').write_text(json.dumps(record), encoding='utf-8')
        return run

    def test_research_status_reads_it(self, rooted: Path) -> None:
        import asyncio

        run = self._old_research_tier_record(rooted)
        status = asyncio.run(research_status(str(run)))
        assert status['state'] == 'finished'
        assert status['ok'] is True
        assert 'sidecar' in status['outputs']  # shown as recorded

    def test_a_resume_collects_it_without_the_dead_paths(self, rooted: Path) -> None:
        run = self._old_research_tier_record(rooted)
        collected = resume_research(run, log_level='CRITICAL')
        assert collected['ok'] is True
        assert 'synthesis' not in collected['outputs']
        assert 'sidecar' not in collected['outputs']
        assert len(collected['outputs']['briefs']) == 2
        # Recorded before the field existed: unknown, not invented.
        assert collected['search_engines'] is None

    def test_missing_product_accepts_an_old_record_that_lists_the_paths(self, rooted: Path) -> None:
        run = self._old_research_tier_record(rooted)
        record = json.loads((run / 'run.json').read_text(encoding='utf-8'))
        assert missing_product(record) is None

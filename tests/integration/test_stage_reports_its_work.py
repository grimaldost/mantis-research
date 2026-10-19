"""A research stage reports done only over the work it owes (MANT-03).

In the 2026-10-11 field report the openrouter stage exited 0 in 1.7 s with no
brief on disk and a cost of $0, and the run record said nothing about why the
run then failed: ``error`` was null and ``history`` empty, so the cause had to
be read off directory timestamps. The stage judged its own success by whether
anything had failed, not by whether its output contract held.

The stage now checks, before it reports done, that every requested substrate
has a brief on disk and a recorded cost, and fails with a named error
otherwise. The run record and ``research_status`` carry the failing stage's
reason. What ``ok``, the exit codes and the incomplete-run refusal mean is
unchanged.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from mantis_research.core.config import load_batch_config
from mantis_research.interface.cli import dispatch as dispatch_mod
from mantis_research.interface.cli.dispatch import dispatch_stage_config
from mantis_research.interface.mcp.server import research_status
from mantis_research.interface.research_service import build_config, run_research
from mantis_research.interface.stages.openrouter_research import CONTRACT_ERROR
from tests.pipeline_fakes import FakePipeline, install_fake_pipeline

QUESTION = 'Which retry policy fits a flaky upstream?'


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> FakePipeline:
    return install_fake_pipeline(monkeypatch)


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


class TestTheResearchStageChecksItsOutputContract:
    def test_a_substrate_with_no_recorded_cost_fails_the_stage_by_name(
        self, rooted: Path, pipeline: FakePipeline
    ) -> None:
        pipeline.openrouter.usage = None
        manifest = run_research(QUESTION, assurance='research', batch_name='no-cost')
        stage = manifest['stages']['openrouter']
        assert stage['exit_code'] != 0, 'the stage reported success with no cost recorded'
        assert CONTRACT_ERROR in stage['error']
        assert 'no cost recorded' in stage['error']
        assert manifest['ok'] is False

    def test_a_done_substrate_whose_brief_is_gone_is_bought_again(
        self, rooted: Path, pipeline: FakePipeline
    ) -> None:
        # A topic re-entered because one substrate failed: the other's record
        # says done, but its brief is gone. Trusting the record would leave the
        # stage owing a brief it then reports done over.
        raw = build_config(
            QUESTION,
            substrates=['openai', 'deepseek'],
            primary='openrouter:openai',
            journal=False,
            batch_name='lost-brief',
            assurance='research',
        )
        raw['runner']['max_retries_per_stage'] = 0
        cfg = load_batch_config(raw)
        pipeline.openrouter.failing = {'deepseek'}
        assert dispatch_stage_config('openrouter', cfg, log_level='CRITICAL') == 1
        (openai_brief,) = (rooted / 'outputs_root' / 'lost-brief' / 'openrouter').rglob('*.md')
        openai_brief.unlink()

        pipeline.openrouter.failing = set()
        assert dispatch_stage_config('openrouter', cfg, log_level='CRITICAL') == 0
        assert openai_brief.is_file(), 'the lost brief was not produced again'
        models = [model for model, dry in pipeline.openrouter.calls if not dry]
        assert sum('openai' in m for m in models) == 2


class TestTheRecordSaysWhyAStageFailed:
    def test_the_run_record_names_the_failing_stage_reason(
        self, rooted: Path, pipeline: FakePipeline
    ) -> None:
        pipeline.openrouter.usage = None
        manifest = run_research(QUESTION, assurance='fast', batch_name='why')
        record: dict[str, Any] = json.loads(_read(Path(manifest['outputs_dir']) / 'run.json'))
        assert CONTRACT_ERROR in record['stages']['openrouter']['error']
        # The stages that passed carry no reason.
        assert 'error' not in record['stages'].get('synthesis', {})

    async def test_research_status_reports_it(self, rooted: Path, pipeline: FakePipeline) -> None:
        pipeline.openrouter.usage = None
        manifest = await asyncio.to_thread(
            run_research, QUESTION, assurance='research', batch_name='status'
        )
        status = await research_status(manifest['outputs_dir'])
        assert status['state'] == 'finished'
        assert status['ok'] is False
        assert CONTRACT_ERROR in status['stages']['openrouter']['error']

    def test_a_blocked_stage_says_what_it_was_waiting_for(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch, pipeline: FakePipeline
    ) -> None:
        # The field run's synthesis exited 1 because no brief existed, and its
        # record said only that. The reason it was blocked is now on the stage.
        real_dispatch = dispatch_mod.dispatch_stage_config

        def research_left_nothing(stage: str, cfg: Any, **kwargs: Any) -> int:
            if stage == 'openrouter':
                return 0
            return real_dispatch(stage, cfg, **kwargs)

        monkeypatch.setattr(dispatch_mod, 'dispatch_stage_config', research_left_nothing)
        manifest = run_research(QUESTION, assurance='fast', batch_name='blocked')
        synthesis = manifest['stages']['synthesis']
        assert synthesis['exit_code'] == 1
        assert synthesis['error'].startswith('blocked_upstream: missing primary brief')
        assert 'error' not in manifest['stages']['openrouter']

"""A dry run leaves nothing a later real run under the same name reuses (MANT-01).

Reproduced on 0.7.1 through the MCP tool, following the skill's own advice: a
``research(dry_run=true, name=X)`` and then ``research(name=X)``. The real run
"finished" in 2.5 s at $0: the openrouter stage exited 0 with no brief on disk,
and synthesis failed on the missing briefs. A new name worked.

The 2026-08-11 fix made the *topic* record say a dry run wrote it, and
``settled`` ignores such a record. The stage's own record inside it did not:
each substrate's entry said ``done``, and the research stage skips a ``done``
substrate. So the real run re-entered the topic as promised, and then skipped
every substrate in it. The earlier tests drove a fake stage, so the stage's
skip logic never ran; these drive the real stages through fake adapters.

The second half is the reverse: a dry run over a run a real call finished. It
rewrote ``run.json`` as ``validated`` and walked stages that each found their
topic settled and did nothing, so it validated nothing and erased the record of
a finished run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mantis_research.interface.mcp.server import research
from mantis_research.interface.research_service import run_research
from tests.pipeline_fakes import FakePipeline, install_fake_pipeline

QUESTION = 'How should development on the lab be shaped?'


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> FakePipeline:
    return install_fake_pipeline(monkeypatch)


def _missing(paths: list[str]) -> list[str]:
    return [p for p in paths if not Path(p).is_file()]


def _state_files(rooted: Path, batch: str) -> dict[str, bytes]:
    root = rooted / 'state_root' / batch
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob('*.json'))}


class TestARealRunAfterASameNameDryRun:
    async def test_every_stage_executes_and_the_briefs_are_written(
        self, rooted: Path, pipeline: FakePipeline
    ) -> None:
        dry = await research(QUESTION, name='lab-dev-forms', dry_run=True, detach=False)
        assert dry['dry_run'] is True
        assert pipeline.openrouter.live_calls == 0

        real = await research(QUESTION, name='lab-dev-forms', detach=False)

        # One live call per substrate, and the synthesis and sidecar turns.
        assert pipeline.openrouter.live_calls == 3, 'the real run skipped the substrates'
        assert pipeline.claude.live_spawns >= 2
        assert _missing(real['outputs']['briefs']) == []
        assert real['ok'] is True
        assert real['sidecar_available'] is True
        assert real['cost']['cost_usd'] > 0

    def test_the_same_holds_through_the_service_entry(
        self, rooted: Path, pipeline: FakePipeline
    ) -> None:
        # The research tier, which a seatless caller uses: the briefs are the
        # whole product, so a skipped substrate is the whole run lost.
        run_research(QUESTION, assurance='research', batch_name='b', dry_run=True)
        manifest = run_research(QUESTION, assurance='research', batch_name='b')
        assert pipeline.openrouter.live_calls == 3
        assert _missing(manifest['outputs']['briefs']) == []


class TestADryRunOverAFinishedRun:
    @pytest.fixture
    async def finished(self, rooted: Path, pipeline: FakePipeline) -> dict[str, Any]:
        result = await research(QUESTION, name='finished', detach=False)
        assert result['ok'] is True
        pipeline.openrouter.calls.clear()
        pipeline.claude.spawns.clear()
        return result

    async def test_it_leaves_the_run_record_and_the_stage_records_as_they_were(
        self, rooted: Path, finished: dict[str, Any]
    ) -> None:
        record = Path(finished['outputs_dir']) / 'run.json'
        before_record = record.read_bytes()
        before_states = _state_files(rooted, 'finished')

        await research('', resume=finished['outputs_dir'], dry_run=True, detach=False)

        assert record.read_bytes() == before_record
        assert json.loads(record.read_bytes())['status'] == 'complete'
        assert _state_files(rooted, 'finished') == before_states

    async def test_it_still_walks_every_stage(
        self, rooted: Path, finished: dict[str, Any], pipeline: FakePipeline
    ) -> None:
        # Not a silent skip: every substrate and the synthesis are walked as a
        # dry run, which is what a dry run is for.
        result = await research('', resume=finished['outputs_dir'], dry_run=True, detach=False)
        assert result['dry_run'] is True
        assert [dry for _, dry in pipeline.openrouter.calls] == [True, True, True]
        assert pipeline.claude.spawns
        assert all(dry for _, dry in pipeline.claude.spawns)

    async def test_the_finished_run_still_collects_afterwards(
        self, rooted: Path, finished: dict[str, Any], pipeline: FakePipeline
    ) -> None:
        await research('', resume=finished['outputs_dir'], dry_run=True, detach=False)
        collected = await research('', resume=finished['outputs_dir'], detach=False)
        assert collected['ok'] is True
        assert collected['sidecar_available'] is True
        assert pipeline.openrouter.live_calls == 0, 'collecting re-bought the briefs'

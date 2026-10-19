"""A local-seat child reads only the directories the run declares (MANT-02).

The child used to start in the calling project and so read that project's
instructions, anchor and memory whether or not the question had anything to do
with them. It now starts in a neutral directory, and a caller that does want a
child to read something passes it as ``context_dirs``: each directory goes to
every local-seat child through ``--add-dir``, and nothing else from the
caller's project does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mantis_research.interface import research_service
from mantis_research.interface.mcp.server import research
from mantis_research.interface.research_service import resume_research
from tests.pipeline_fakes import FakePipeline, install_fake_pipeline

QUESTION = 'What does the project decide about retries?'


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> FakePipeline:
    return install_fake_pipeline(monkeypatch)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / 'calling-project'
    project.mkdir()
    (project / 'AGENTS.md').write_text('agent rules', encoding='utf-8')
    return project


def _resolved(path: Path) -> Path:
    return path.resolve()


def _spawned_dirs(pipeline: FakePipeline) -> list[list[Path]]:
    return [[Path(d).resolve() for d in options.add_dirs] for options, _ in pipeline.claude.spawns]


class TestContextDirs:
    async def test_a_declared_directory_reaches_every_local_seat_child(
        self, rooted: Path, pipeline: FakePipeline, project: Path
    ) -> None:
        result = await research(
            QUESTION, name='with-context', detach=False, context_dirs=[str(project)]
        )
        assert result['ok'] is True
        spawned = _spawned_dirs(pipeline)
        assert spawned, 'no local-seat child was spawned'
        assert all(_resolved(project) in dirs for dirs in spawned)

    async def test_without_one_no_child_is_given_the_project(
        self, rooted: Path, pipeline: FakePipeline, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(project)
        await research(QUESTION, name='no-context', detach=False)
        resolved = _resolved(project)
        for dirs in _spawned_dirs(pipeline):
            for d in dirs:
                assert d != resolved
                assert resolved not in d.parents

    async def test_a_directory_that_is_not_there_is_refused_before_any_spend(
        self, rooted: Path, pipeline: FakePipeline, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match='context_dirs'):
            await research(
                QUESTION, name='bad', detach=False, context_dirs=[str(tmp_path / 'absent')]
            )
        assert pipeline.openrouter.calls == []

    def test_the_run_record_keeps_them_and_a_resume_passes_them_on(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch, project: Path
    ) -> None:
        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', lambda *_a, **_k: 1
        )
        manifest = research_service.run_research(
            QUESTION, assurance='fast', batch_name='kept', context_dirs=[str(project)]
        )
        record: dict[str, Any] = json.loads(
            (Path(manifest['outputs_dir']) / 'run.json').read_text(encoding='utf-8')
        )
        assert record['context_dirs'] == [str(project.resolve())]

        asked: dict[str, Any] = {}

        def capture(question: str, **kwargs: Any) -> dict[str, Any]:
            asked.update(kwargs)
            return {}

        monkeypatch.setattr(research_service, 'run_research', capture)
        resume_research(Path(manifest['outputs_dir']))
        assert asked['context_dirs'] == [str(project.resolve())]

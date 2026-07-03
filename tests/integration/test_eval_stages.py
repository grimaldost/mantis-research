"""Evaluation + claude-prior stages packaged (spec 0001 §15).

Confirms both stages are in the registry/CLI and exercises evaluation's
upstream gate (blocks without the baseline) and a happy path with fake adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from mantis_research.core.config import load_batch_config
from mantis_research.core.paths import RunDirs
from mantis_research.core.stage import RunContext
from mantis_research.core.state import ClaudePriorState, EvaluationState
from mantis_research.interface.adapters.claude_cli import ClaudeCliOptions, ClaudeCliResult
from mantis_research.interface.cli.dispatch import STAGE_REGISTRY
from mantis_research.interface.stages.claude_prior import ClaudePriorStage
from mantis_research.interface.stages.evaluation import EvaluationStage

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import BatchConfig


def test_both_stages_registered() -> None:
    assert 'evaluation' in STAGE_REGISTRY
    assert 'claude-prior' in STAGE_REGISTRY


@dataclass
class WritingAdapter:
    """Writes a file each turn produces so existence checks pass."""

    eval_path: Path | None = None
    baseline_path: Path | None = None
    eval_json: str = '{"verdict": "PASS", "quality_score_Q_with_penalty": 0.72}'
    calls: list[ClaudeCliOptions] = field(default_factory=list)

    def preflight(self) -> None:
        return None

    async def run(
        self,
        prompt: str,
        options: ClaudeCliOptions,
        transcript_path: Path,
        *,
        dry_run: bool = False,
    ) -> ClaudeCliResult:
        self.calls.append(options)
        if self.eval_path is not None and 'evaluate-topic' in (options.name or ''):
            self.eval_path.parent.mkdir(parents=True, exist_ok=True)
            self.eval_path.write_text(self.eval_json, encoding='utf-8')
        if self.baseline_path is not None and 'claude-prior' in (options.name or ''):
            self.baseline_path.parent.mkdir(parents=True, exist_ok=True)
            self.baseline_path.write_text('# baseline', encoding='utf-8')
        return ClaudeCliResult(success=True, exit_code=0, duration_s=1.0, session_id='s')


def _config() -> BatchConfig:
    return load_batch_config(
        {
            'schema_version': 2,
            'batch_name': 'ev',
            'runner': {'layout': 'batch'},
            'models': {'claude': {'model': 'claude-opus-4-7', 'effort': 'max'}},
            'topics': [
                {
                    'id': '1',
                    'slug': 't',
                    'title': 'A topic title',
                    'high_stakes': True,
                    'stages': {'claude': {'prompt': 'p'}},
                }
            ],
        }
    )


def _ctx(cfg: BatchConfig, tmp_path: Path) -> RunContext:
    return RunContext(
        batch=cfg,
        state_dir=tmp_path / 'state',
        output_dir=tmp_path / 'out',
        transcript_dir=tmp_path / 'tx',
        dry_run=False,
    )


class TestClaudePrior:
    async def test_writes_baseline_from_title(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr('mantis_research.core.paths.outputs_root', lambda: tmp_path)
        baseline = tmp_path / 'ev' / 'claude-prior' / '01-t.md'
        adapter = WritingAdapter(baseline_path=baseline)
        cfg = _config()
        stage = ClaudePriorStage(adapter=adapter)  # type: ignore[arg-type]
        state = ClaudePriorState(id='1', slug='t')
        result = await stage.run_attempt(cfg.topics[0], state, _ctx(cfg, tmp_path))
        assert result.success
        assert baseline.exists()
        assert state.baseline_bytes


class TestEvaluationGate:
    def test_blocks_without_baseline(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr('mantis_research.core.paths.outputs_root', lambda: tmp_path)
        # Synthesis present, baseline absent → blocked.
        (tmp_path / 'ev' / 'synthesis').mkdir(parents=True, exist_ok=True)
        (tmp_path / 'ev' / 'synthesis' / '01-t.md').write_text('syn', encoding='utf-8')
        cfg = _config()
        stage = EvaluationStage()
        ready, reason = stage.upstream_ready('1', 't', _ctx(cfg, tmp_path))
        assert not ready
        assert 'baseline' in (reason or '')

    async def test_happy_path_records_verdict(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr('mantis_research.core.paths.outputs_root', lambda: tmp_path)
        dirs = RunDirs('batch', 'ev')
        for stage_name, name in (('synthesis', '01-t.md'), ('claude-prior', '01-t.md')):
            d = dirs.output(stage_name)
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text('content', encoding='utf-8')
        eval_path = dirs.output('evaluation') / '01-t-eval.json'
        adapter = WritingAdapter(eval_path=eval_path)
        cfg = _config()
        stage = EvaluationStage(adapter=adapter)  # type: ignore[arg-type]
        state = EvaluationState(id='1', slug='t')
        result = await stage.run_attempt(cfg.topics[0], state, _ctx(cfg, tmp_path))
        assert result.success
        assert eval_path.exists()
        assert state.verdict == 'PASS'
        assert state.quality_score == pytest.approx(0.72)

    def test_high_stakes_enables_evaluation(self) -> None:
        cfg = _config()  # high_stakes=True, no explicit evaluation.enabled
        assert EvaluationStage().is_enabled(cfg.topics[0], cfg)

"""Stage 5 (optional) — synthesis evaluation.

Scores the synthesis against a 3-gate + 6-criterion rubric, fresh (no access to
the synthesis-production session), using the synthesis, the primary + secondary
briefs, and the Claude-prior baseline (Gate 3). Writes a structured JSON record
to ``evaluations/NN-slug-eval.json`` and parses the verdict + quality score into
state.

Optional, like falsification: runs when ``stages.evaluation.enabled`` is True,
or when ``high_stakes`` is set (unless explicitly disabled).

Upstream gate: synthesis + primary (Claude) brief + Claude-prior baseline on disk.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from mantis_research.core import prompts as default_prompts
from mantis_research.core.model_policy import resolve_claude_model
from mantis_research.core.paths import RunDirs, topic_stem
from mantis_research.core.stage import AttemptResult
from mantis_research.interface.adapters.claude_cli import (
    ClaudeCliAdapter,
    ClaudeCliOptions,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import BatchConfig, TopicConfig
    from mantis_research.core.stage import RunContext
    from mantis_research.core.state import EvaluationState

log = structlog.get_logger(__name__)


def _briefs_in(dirs: RunDirs, stage_name: str, stem: str) -> list[Path]:
    """Discover a stage's brief files for a topic stem (multi-part dir wins)."""
    base = dirs.output(stage_name)
    multi = base / stem
    if multi.is_dir():
        return sorted(p for p in multi.glob('*.md') if p.is_file())
    single = base / f'{stem}.md'
    return [single] if single.exists() else []


def _synthesis_path(dirs: RunDirs, stem: str) -> Path:
    return dirs.output('synthesis') / f'{stem}.md'


def _claude_path(dirs: RunDirs, stem: str) -> Path:
    return dirs.output('claude') / f'{stem}.md'


def _baseline_path(dirs: RunDirs, stem: str) -> Path:
    return dirs.output('claude-prior') / f'{stem}.md'


class EvaluationStage:
    """Stage 5 (optional) — fresh evaluation of the synthesis against a rubric."""

    name: str = 'evaluation'
    state_subdir: str = 'evaluation'
    output_subdir: str = 'evaluation'

    def __init__(self, adapter: ClaudeCliAdapter | None = None) -> None:
        self._adapter = adapter or ClaudeCliAdapter()

    async def preflight(self) -> None:
        self._adapter.preflight()

    def is_enabled(self, topic: TopicConfig, config: BatchConfig) -> bool:
        ev = topic.stages.evaluation
        if ev.enabled is True:
            return True
        return bool(topic.high_stakes is True and ev.enabled is not False)

    def upstream_ready(self, topic_id: str, slug: str, ctx: RunContext) -> tuple[bool, str | None]:
        dirs = RunDirs(ctx.batch.runner.layout, ctx.batch.batch_name)
        stem = topic_stem(topic_id, slug)
        s = _synthesis_path(dirs, stem)
        if not s.exists():
            return (False, f'missing synthesis: {s.name}')
        b = _baseline_path(dirs, stem)
        if not b.exists():
            return (False, f'missing claude-prior baseline: {b.name} (run claude-prior first)')
        return (True, None)

    async def run_attempt(
        self,
        topic: TopicConfig,
        state: EvaluationState,
        ctx: RunContext,
    ) -> AttemptResult:
        topic_id = topic.id
        slug = topic.slug
        stem = topic_stem(topic_id, slug)
        dirs = RunDirs(ctx.batch.runner.layout, ctx.batch.batch_name)
        eval_dir = dirs.output('evaluation')
        eval_dir.mkdir(parents=True, exist_ok=True)

        synthesis = _synthesis_path(dirs, stem)
        claude = _claude_path(dirs, stem)
        baseline = _baseline_path(dirs, stem)
        eval_path = eval_dir / f'{stem}-eval.json'

        secondaries = _briefs_in(dirs, 'gemini', stem) + _briefs_in(dirs, 'openrouter', stem)
        gemini_block = '\n'.join(
            f'- {p.as_posix()} ({p.stat().st_size / 1024:.1f} KB)' for p in secondaries
        )

        template = (
            topic.stages.evaluation.prompt
            or ctx.batch.default_prompts.evaluation
            or default_prompts.EVALUATION
        )
        # A missing Claude brief (Path B) still evaluates: fall back to the
        # synthesis for the {claude_*} slots so the prompt formats.
        claude_ref = claude if claude.exists() else synthesis
        prompt = template.format(
            topic_id=topic_id,
            synthesis_path=synthesis.as_posix(),
            synthesis_size_kb=synthesis.stat().st_size / 1024,
            claude_path=claude_ref.as_posix(),
            claude_size_kb=claude_ref.stat().st_size / 1024,
            gemini_block=gemini_block,
            baseline_path=baseline.as_posix(),
            baseline_size_kb=baseline.stat().st_size / 1024,
            eval_path=eval_path.as_posix(),
        )

        synth_model_cfg = ctx.batch.models.synthesis or ctx.batch.models.claude
        ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        transcript_path = dirs.transcripts() / f'{stem}-{ts}-evaluation.log'
        options = ClaudeCliOptions(
            model=resolve_claude_model(synth_model_cfg.model),
            effort=synth_model_cfg.effort or 'max',
            session_id=state.session_id or str(uuid.uuid4()),
            name=f'evaluate-topic-{topic_id}',
            add_dirs=(
                dirs.output('synthesis'),
                dirs.output('claude'),
                dirs.output('claude-prior'),
                eval_dir,
            ),
            allowed_tools=('Read', 'Write'),
        )

        result = await self._adapter.run(
            prompt=prompt,
            options=options,
            transcript_path=transcript_path,
            dry_run=ctx.dry_run,
        )
        state.session_id = result.session_id
        state.duration_s = result.duration_s

        if not result.success:
            return AttemptResult.fail(
                error=result.error or 'evaluation turn failed',
                error_output=result.raw_output,
            )
        if not ctx.dry_run and not eval_path.exists():
            return AttemptResult.fail(
                error=f'evaluation JSON not produced at {eval_path.name}',
                error_output=result.raw_output,
            )
        if eval_path.exists():
            state.eval_bytes = eval_path.stat().st_size
            self._record_verdict(eval_path, state)
        return AttemptResult.ok(output_bytes=state.eval_bytes)

    @staticmethod
    def _record_verdict(eval_path: Path, state: EvaluationState) -> None:
        """Parse verdict + quality score from the model's eval JSON (best-effort)."""
        try:
            data = json.loads(eval_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            log.warning('evaluation JSON unparseable', path=str(eval_path))
            return
        if isinstance(data, dict):
            verdict = data.get('verdict')
            state.verdict = verdict if isinstance(verdict, str) else None
            q = data.get('quality_score_Q_with_penalty')
            state.quality_score = float(q) if isinstance(q, (int, float)) else None

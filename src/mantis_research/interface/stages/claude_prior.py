"""Stage 5-input — Claude-prior baseline.

Runs one ``claude -p`` per topic with ONLY the topic title, no sources and no
web search. The output is the generalist baseline Gate 3 of the evaluation
stage scores the synthesis against (training-consensus-parroting detection).
Single turn; no upstream dependency.
"""

from __future__ import annotations

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
    from mantis_research.core.config import BatchConfig, TopicConfig
    from mantis_research.core.stage import RunContext
    from mantis_research.core.state import ClaudePriorState

log = structlog.get_logger(__name__)


class ClaudePriorStage:
    """Stage 5-input — topic-title-only Claude baseline."""

    name: str = 'claude-prior'
    state_subdir: str = 'claude-prior'
    output_subdir: str = 'claude-prior'

    def __init__(self, adapter: ClaudeCliAdapter | None = None) -> None:
        self._adapter = adapter or ClaudeCliAdapter()

    async def preflight(self) -> None:
        self._adapter.preflight()

    def is_enabled(self, topic: TopicConfig, config: BatchConfig) -> bool:
        return True

    def upstream_ready(self, topic_id: str, slug: str, ctx: RunContext) -> tuple[bool, str | None]:
        return (True, None)

    async def run_attempt(
        self,
        topic: TopicConfig,
        state: ClaudePriorState,
        ctx: RunContext,
    ) -> AttemptResult:
        topic_id = topic.id
        slug = topic.slug
        stem = topic_stem(topic_id, slug)
        dirs = RunDirs(ctx.batch.runner.layout, ctx.batch.batch_name)
        output_dir = dirs.output('claude-prior')
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f'{stem}.md'

        title = topic.title
        prompt = default_prompts.CLAUDE_PRIOR.format(
            title=title, output_path=output_path.as_posix()
        )

        models = ctx.batch.models.claude
        ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        transcript_path = dirs.transcripts() / f'{stem}-{ts}-claude-prior.log'
        options = ClaudeCliOptions(
            model=resolve_claude_model(models.model),
            effort=models.effort or 'max',
            session_id=state.session_id or str(uuid.uuid4()),
            name=f'claude-prior-{topic_id}',
            add_dirs=(output_dir,),
            # No web search: the baseline is deliberately from general knowledge.
            allowed_tools=('Write',),
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
                error=result.error or 'claude-prior turn failed',
                error_output=result.raw_output,
            )
        if not ctx.dry_run and not output_path.exists():
            return AttemptResult.fail(
                error=f'baseline not produced at {output_path.name}',
                error_output=result.raw_output,
            )
        state.baseline_bytes = output_path.stat().st_size if output_path.exists() else 0
        return AttemptResult.ok(output_bytes=state.baseline_bytes)

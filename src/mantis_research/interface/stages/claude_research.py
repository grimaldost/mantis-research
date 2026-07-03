"""Stage 1 — Claude research substrate.

Drives one ``claude -p`` invocation per topic with web-search enabled.
Produces ``outputs/claude/NN-slug.md`` (or the legacy ``research-outputs/``
during the transition window). Single turn; no upstream dependency.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from mantis_research.core.model_policy import resolve_claude_model
from mantis_research.core.paths import topic_nn
from mantis_research.core.stage import AttemptResult
from mantis_research.interface.adapters.claude_cli import (
    ClaudeCliAdapter,
    ClaudeCliOptions,
)

if TYPE_CHECKING:
    from mantis_research.core.config import BatchConfig, TopicConfig
    from mantis_research.core.stage import RunContext
    from mantis_research.core.state import ClaudeResearchState

log = structlog.get_logger(__name__)


class ClaudeResearchStage:
    """Stage 1 — Claude research substrate. Implements the Stage Protocol."""

    name: str = 'claude'
    state_subdir: str = 'claude'
    output_subdir: str = 'claude'

    def __init__(self, adapter: ClaudeCliAdapter | None = None) -> None:
        self._adapter = adapter or ClaudeCliAdapter()

    # ── Stage Protocol ────────────────────────────────────────────

    async def preflight(self) -> None:
        # ClaudeCliAdapter.preflight is synchronous (subprocess checks).
        self._adapter.preflight()

    def is_enabled(self, topic: TopicConfig, config: BatchConfig) -> bool:
        # Stage 1 is unconditional — every topic runs Claude research.
        return True

    def upstream_ready(
        self,
        topic_id: str,
        slug: str,
        ctx: RunContext,
    ) -> tuple[bool, str | None]:
        # Stage 1 is the head of the pipeline — no upstream dependency.
        return (True, None)

    async def run_attempt(
        self,
        topic: TopicConfig,
        state: ClaudeResearchState,
        ctx: RunContext,
    ) -> AttemptResult:
        topic_id = topic.id
        slug = topic.slug
        nn = topic_nn(topic_id)

        output_path = ctx.output_dir / f'{nn}-{slug}.md'
        timestamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        transcript_path = ctx.transcript_dir / f'{nn}-{slug}-{timestamp}-turn1.log'

        # TopicConfig's validator resolves this to a concrete string (§10);
        # `or ''` narrows the Optional field type and preserves the existing
        # empty-prompt behavior for Path-B topics that carry claude.prompt="".
        prompt = topic.stages.claude.prompt or ''
        models = ctx.batch.models.claude
        save_instruction = (
            f'When the research is complete and you have produced the full brief, '
            f'use the Write tool to save the complete research document to '
            f'{output_path.as_posix()}. The document should be comprehensive — '
            f'this is reference material for agentic-memory ingestion. Include all '
            f'sections, citations, and the full depth you would provide as a final '
            f'deliverable.'
        )
        options = ClaudeCliOptions(
            # 'auto'/'latest'/absent → the latest-resolving CLI alias ('opus');
            # an explicit pin (e.g. 'claude-opus-4-8') passes through unchanged.
            model=resolve_claude_model(models.model),
            effort=models.effort or 'max',
            add_dirs=(ctx.output_dir,),
            allowed_tools=('WebSearch', 'WebFetch', 'Write', 'Read'),
            append_system_prompt=save_instruction,
            session_id=state.session_id or str(uuid.uuid4()),
            name=f'research-topic-{topic_id}',
        )

        result = await self._adapter.run(
            prompt=prompt,
            options=options,
            transcript_path=transcript_path,
            dry_run=ctx.dry_run,
        )

        # Persist session_id + duration into the state object (orchestrator saves).
        state.session_id = result.session_id
        state.turn_1_duration_s = result.duration_s

        if not result.success:
            return AttemptResult.fail(
                error=result.error or 'unknown subprocess error',
                error_output=result.raw_output,
            )

        if not ctx.dry_run and not output_path.exists():
            log.warning(
                'claude exited 0 but output not written',
                topic_id=topic_id,
                expected=str(output_path),
            )
            return AttemptResult.fail(
                error=f'output file not produced at {output_path.name}',
                error_output=result.raw_output,
            )

        size = output_path.stat().st_size if output_path.exists() else 0
        state.research_file_bytes = size
        return AttemptResult.ok(output_bytes=size)

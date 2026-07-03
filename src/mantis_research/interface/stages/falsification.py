"""Stage 4 (optional) — adversarial counter-evidence pass.

Reads the synthesis at ``outputs/synthesis/NN-slug.md`` and produces a
counter-evidence document at ``outputs/falsification/NN-slug.md``. This is
the third pass in a Main → Falsification iteration chain (Anthropic's
documented research-team pattern).

Stage 4 is optional. It runs only when:
- ``topics[i].stages.falsification.enabled`` is True, OR
- ``topics[i].high_stakes`` is True (default-on for high-stakes topics).
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
    from pathlib import Path

    from mantis_research.core.config import BatchConfig, TopicConfig
    from mantis_research.core.stage import RunContext
    from mantis_research.core.state import FalsificationState

log = structlog.get_logger(__name__)


def _stem_for(topic_id: str, slug: str) -> str:
    return topic_stem(topic_id, slug)


def _synthesis_path(dirs: RunDirs, topic_id: str, slug: str) -> Path:
    return dirs.output('synthesis') / f'{_stem_for(topic_id, slug)}.md'


def _falsification_path(dirs: RunDirs, topic_id: str, slug: str) -> Path:
    return dirs.output('falsification') / f'{_stem_for(topic_id, slug)}.md'


class FalsificationStage:
    """Stage 4 (optional) — adversarial counter-evidence pass."""

    name: str = 'falsification'
    state_subdir: str = 'falsification'
    output_subdir: str = 'falsification'

    def __init__(self, adapter: ClaudeCliAdapter | None = None) -> None:
        self._adapter = adapter or ClaudeCliAdapter()

    # ── Stage Protocol ────────────────────────────────────────────

    async def preflight(self) -> None:
        # ClaudeCliAdapter.preflight is synchronous.
        self._adapter.preflight()

    def is_enabled(self, topic: TopicConfig, config: BatchConfig) -> bool:
        fals = topic.stages.falsification
        if fals.enabled is True:
            return True
        return bool(topic.high_stakes is True and fals.enabled is not False)

    def upstream_ready(
        self,
        topic_id: str,
        slug: str,
        ctx: RunContext,
    ) -> tuple[bool, str | None]:
        dirs = RunDirs(ctx.batch.runner.layout, ctx.batch.batch_name)
        s = _synthesis_path(dirs, topic_id, slug)
        if not s.exists():
            return (False, f'missing synthesis: {s.name}')
        return (True, None)

    async def run_attempt(
        self,
        topic: TopicConfig,
        state: FalsificationState,
        ctx: RunContext,
    ) -> AttemptResult:
        topic_id = topic.id
        slug = topic.slug

        dirs = RunDirs(ctx.batch.runner.layout, ctx.batch.batch_name)
        synthesis = _synthesis_path(dirs, topic_id, slug)
        falsification = _falsification_path(dirs, topic_id, slug)
        falsification.parent.mkdir(parents=True, exist_ok=True)

        template = (
            topic.stages.falsification.prompt
            or ctx.batch.default_prompts.falsification
            or default_prompts.FALSIFICATION
        )
        prompt = template.format(
            synthesis_path=synthesis.as_posix(),
            synthesis_size_kb=synthesis.stat().st_size / 1024,
            falsification_path=falsification.as_posix(),
        )

        synth_model_cfg = ctx.batch.models.synthesis or ctx.batch.models.claude
        ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        transcript_path = dirs.transcripts() / f'{_stem_for(topic_id, slug)}-{ts}-falsification.log'
        options = ClaudeCliOptions(
            model=resolve_claude_model(synth_model_cfg.model),
            effort=synth_model_cfg.effort or 'max',
            session_id=state.session_id or str(uuid.uuid4()),
            name=f'falsification-topic-{topic_id}',
            add_dirs=(dirs.output('synthesis'), dirs.output('falsification')),
            allowed_tools=('WebSearch', 'WebFetch', 'Read', 'Write'),
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
                error=result.error or 'falsification turn failed',
                error_output=result.raw_output,
            )
        if not ctx.dry_run and not falsification.exists():
            return AttemptResult.fail(
                error=f'falsification file not produced at {falsification.name}',
                error_output=result.raw_output,
            )
        state.falsification_bytes = falsification.stat().st_size if falsification.exists() else 0
        return AttemptResult.ok(output_bytes=state.falsification_bytes)

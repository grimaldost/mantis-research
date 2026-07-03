"""Stage 3.5 — journal augmentation (focused depth-passes on top of breadth-first journal).

Single Claude turn per topic. Reads ``outputs/journals/NN-slug-journal.md``
and the synthesis it was built from, picks 3-5 high-leverage angles, and
emits ``outputs/journals/NN-slug-journal-augmented.md``.

Upstream gate: requires both the synthesis brief and the first-pass journal
to exist on disk.
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
    from mantis_research.core.state import JournalPassesState

log = structlog.get_logger(__name__)


def _stem_for(topic_id: str, slug: str) -> str:
    return topic_stem(topic_id, slug)


def _synthesis_path(dirs: RunDirs, topic_id: str, slug: str) -> Path:
    return dirs.output('synthesis') / f'{_stem_for(topic_id, slug)}.md'


def _journal_path(dirs: RunDirs, topic_id: str, slug: str) -> Path:
    return dirs.output('journals') / f'{_stem_for(topic_id, slug)}-journal.md'


def _augmented_path(dirs: RunDirs, topic_id: str, slug: str) -> Path:
    return dirs.output('journals') / f'{_stem_for(topic_id, slug)}-journal-augmented.md'


class JournalPassesStage:
    """Stage 3.5 — focused depth-passes augmentation of the first-pass journal."""

    name: str = 'journal-passes'
    state_subdir: str = 'journal-passes'
    output_subdir: str = 'journals'

    def __init__(self, adapter: ClaudeCliAdapter | None = None) -> None:
        self._adapter = adapter or ClaudeCliAdapter()

    # ── Stage Protocol ────────────────────────────────────────────

    async def preflight(self) -> None:
        # ClaudeCliAdapter.preflight is synchronous.
        self._adapter.preflight()

    def is_enabled(self, topic: TopicConfig, config: BatchConfig) -> bool:
        return True

    def upstream_ready(
        self,
        topic_id: str,
        slug: str,
        ctx: RunContext,
    ) -> tuple[bool, str | None]:
        dirs = RunDirs(ctx.batch.runner.layout, ctx.batch.batch_name)
        s = _synthesis_path(dirs, topic_id, slug)
        j = _journal_path(dirs, topic_id, slug)
        if not s.exists():
            return (False, f'missing synthesis: {s.name}')
        if not j.exists():
            return (False, f'missing first-pass journal: {j.name}')
        return (True, None)

    async def run_attempt(
        self,
        topic: TopicConfig,
        state: JournalPassesState,
        ctx: RunContext,
    ) -> AttemptResult:
        topic_id = topic.id
        slug = topic.slug

        dirs = RunDirs(ctx.batch.runner.layout, ctx.batch.batch_name)
        synthesis = _synthesis_path(dirs, topic_id, slug)
        journal = _journal_path(dirs, topic_id, slug)
        augmented = _augmented_path(dirs, topic_id, slug)
        augmented.parent.mkdir(parents=True, exist_ok=True)

        template = (
            topic.stages.journal_passes.prompt
            or ctx.batch.default_prompts.journal_augmentation
            or default_prompts.JOURNAL_AUGMENTATION
        )
        prompt = template.format(
            synthesis_path=synthesis.as_posix(),
            synthesis_size_kb=synthesis.stat().st_size / 1024,
            journal_path=journal.as_posix(),
            journal_size_kb=journal.stat().st_size / 1024,
            augmentation_path=augmented.as_posix(),
        )

        synth_model_cfg = ctx.batch.models.synthesis or ctx.batch.models.claude
        ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        transcript_path = (
            dirs.transcripts() / f'{_stem_for(topic_id, slug)}-{ts}-journal-augment.log'
        )
        options = ClaudeCliOptions(
            model=resolve_claude_model(synth_model_cfg.model),
            effort=synth_model_cfg.effort or 'max',
            session_id=state.session_id or str(uuid.uuid4()),
            name=f'journal-augment-topic-{topic_id}',
            add_dirs=(dirs.output('synthesis'), dirs.output('journals')),
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
                error=result.error or 'augmentation turn failed',
                error_output=result.raw_output,
            )
        if not ctx.dry_run and not augmented.exists():
            return AttemptResult.fail(
                error=f'augmentation file not produced at {augmented.name}',
                error_output=result.raw_output,
            )
        state.augmentation_bytes = augmented.stat().st_size if augmented.exists() else 0
        return AttemptResult.ok(output_bytes=state.augmentation_bytes)

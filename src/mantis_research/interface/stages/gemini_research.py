"""Stage 2 (legacy) — Gemini research substrate via the OAuth CLI.

Drives one or more ``gemini -p`` subsessions per topic. Each topic config
declares a ``stages.gemini[]`` array of ``{subslug, prompt}``; subsessions
run in sequence and each writes its own brief.

Output layout:
- 1 entry with ``subslug == 'single'`` → ``outputs/gemini/NN-slug.md``
- otherwise → ``outputs/gemini/NN-slug/<subslug>.md``

Per-subsession resume: if a prior attempt completed some subsessions but
not all, the next attempt skips the completed ones (read from
``state.subsessions``).

Note: this Stage will eventually be superseded by ``OpenRouterResearchStage``
(Phase 5) which gives reliable Gemini access via the paid API. Kept here
during the transition window for users who prefer the OAuth subscription.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from mantis_research.core.paths import topic_nn
from mantis_research.core.retry import detect_rate_limit
from mantis_research.core.stage import AttemptResult
from mantis_research.core.state import SubsessionResult
from mantis_research.interface.adapters.gemini_cli import (
    GeminiCliAdapter,
    GeminiCliOptions,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import BatchConfig, TopicConfig
    from mantis_research.core.stage import RunContext
    from mantis_research.core.state import GeminiResearchState

log = structlog.get_logger(__name__)


# Topics carrying this stub prompt are intentionally not authored yet —
# the migration script seeded these to force prompt-author intervention.
STUB_PROMPT_PREFIX: str = 'TODO: author this Gemini sub-prompt'


class GeminiResearchStage:
    """Stage 2 (legacy) — Gemini research via OAuth CLI."""

    name: str = 'gemini'
    state_subdir: str = 'gemini'
    output_subdir: str = 'gemini'

    def __init__(self, adapter: GeminiCliAdapter | None = None) -> None:
        self._adapter = adapter or GeminiCliAdapter()

    # ── Stage Protocol ────────────────────────────────────────────

    async def preflight(self) -> None:
        # GeminiCliAdapter.preflight is synchronous.
        self._adapter.preflight()

    def is_enabled(self, topic: TopicConfig, config: BatchConfig) -> bool:
        # Skip topics whose Gemini sub-prompts are still the migration stub.
        entries = topic.stages.gemini
        if not entries:
            return False
        return not any((e.prompt or '').startswith(STUB_PROMPT_PREFIX) for e in entries)

    def upstream_ready(
        self,
        topic_id: str,
        slug: str,
        ctx: RunContext,
    ) -> tuple[bool, str | None]:
        # Stage 2 has no upstream dependency.
        return (True, None)

    async def run_attempt(
        self,
        topic: TopicConfig,
        state: GeminiResearchState,
        ctx: RunContext,
    ) -> AttemptResult:
        topic_id = topic.id
        slug = topic.slug
        entries = [e.model_dump() for e in topic.stages.gemini]
        if not entries:
            return AttemptResult.fail(error='no gemini entries on this topic')

        output_paths = self._resolve_output_paths(topic_id, slug, entries, ctx)
        # models.gemini may be None (FM-4): guard before reading .model.
        gemini_spec = ctx.batch.models.gemini
        gemini_model = (gemini_spec.model if gemini_spec else None) or 'gemini-3-pro-preview'

        # Initialize per-subsession state on the first attempt.
        if not state.subsessions:
            state.subsessions = [
                SubsessionResult(subslug=str(e['subslug']), status='pending') for e in entries
            ]

        rate_limit_hit = False
        other_failure_msg: str | None = None
        last_raw_output = ''

        for entry, out_path in zip(entries, output_paths, strict=True):
            subslug = str(entry['subslug'])
            prior = next((s for s in state.subsessions if s.subslug == subslug), None)
            if prior is not None and prior.status == 'done' and not ctx.dry_run:
                log.info('subsession already done, skipping', topic_id=topic_id, subslug=subslug)
                continue

            transcript_path = self._transcript_path(ctx.transcript_dir, topic_id, slug, subslug)
            options = GeminiCliOptions(model=gemini_model)
            result = await self._adapter.run(
                prompt=str(entry['prompt']),
                options=options,
                transcript_path=transcript_path,
                dry_run=ctx.dry_run,
            )
            last_raw_output = result.raw_output

            ss = self._build_subsession_result(
                subslug=subslug,
                result=result,
                out_path=out_path,
                dry_run=ctx.dry_run,
            )
            self._upsert_subsession(state, ss)

            if ss.status != 'done':
                if ss.error == 'rate_limit' or detect_rate_limit(result.raw_output):
                    rate_limit_hit = True
                else:
                    other_failure_msg = ss.error or 'subsession failure'

        if rate_limit_hit:
            return AttemptResult.fail(error='rate_limit', error_output=last_raw_output)
        if other_failure_msg:
            return AttemptResult.fail(error=other_failure_msg, error_output=last_raw_output)
        return AttemptResult.ok()

    # ── helpers ────────────────────────────────────────────────────

    @staticmethod
    def _resolve_output_paths(
        topic_id: str,
        slug: str,
        entries: list[dict[str, Any]],
        ctx: RunContext,
    ) -> list[Path]:
        """Compute the output path for each subsession (legacy layout convention)."""
        nn = topic_nn(topic_id)
        if len(entries) == 1 and entries[0].get('subslug') == 'single':
            return [ctx.output_dir / f'{nn}-{slug}.md']
        sub_dir = ctx.output_dir / f'{nn}-{slug}'
        sub_dir.mkdir(parents=True, exist_ok=True)
        return [sub_dir / f'{e["subslug"]}.md' for e in entries]

    @staticmethod
    def _transcript_path(
        transcript_dir: Path,
        topic_id: str,
        slug: str,
        subslug: str,
    ) -> Path:
        nn = topic_nn(topic_id)
        ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        return transcript_dir / f'{nn}-{slug}-{subslug}-{ts}-gemini.log'

    @staticmethod
    def _build_subsession_result(
        *,
        subslug: str,
        result: Any,
        out_path: Path,
        dry_run: bool,
    ) -> SubsessionResult:
        """Convert a GeminiCliResult into a persistable SubsessionResult.

        On success: writes the cleaned brief to ``out_path`` (only if not dry-run)
        and returns ``SubsessionResult(status='done', output_bytes=size)``.
        On failure: returns a 'failed' record with the error reason.
        """
        if not result.success:
            error = (
                'rate_limit'
                if detect_rate_limit(result.raw_output)
                else (result.error or f'exit code {result.exit_code}')
            )
            return SubsessionResult(
                subslug=subslug,
                status='failed',
                duration_s=result.duration_s,
                error=error,
            )
        if not dry_run:
            cleaned = result.cleaned_output.strip()
            if not cleaned:
                return SubsessionResult(
                    subslug=subslug,
                    status='failed',
                    duration_s=result.duration_s,
                    error='empty stdout',
                )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(cleaned + '\n', encoding='utf-8')
            size = out_path.stat().st_size
        else:
            size = 0
        return SubsessionResult(
            subslug=subslug,
            status='done',
            duration_s=result.duration_s,
            output_bytes=size,
            output_path=str(out_path),
        )

    @staticmethod
    def _upsert_subsession(state: GeminiResearchState, new_record: SubsessionResult) -> None:
        for i, s in enumerate(state.subsessions):
            if s.subslug == new_record.subslug:
                state.subsessions[i] = new_record
                return
        state.subsessions.append(new_record)

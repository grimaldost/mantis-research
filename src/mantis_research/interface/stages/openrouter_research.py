"""Stage 2 (new) — research substrate via OpenRouter HTTP.

Drives one or more OpenRouter subsessions per topic. Each subsession picks
a specific model id (``openai/gpt-5.5``, ``deepseek/deepseek-v4-pro``,
``google/gemini-3.1-pro-preview``, etc.) and produces an independent
research brief.

Output layout matches the legacy Gemini stage:
- 1 entry with ``subslug == 'single'`` → ``outputs/openrouter/NN-slug.md``
- otherwise → ``outputs/openrouter/NN-slug/<subslug>.md``

This stage replaces ``GeminiResearchStage`` for users who want reliable
Gemini access via the paid API + access to substrate-different models for
stronger cross-model-disagreement signal in synthesis.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from mantis_research.core.model_policy import resolve_openrouter_model
from mantis_research.core.paths import topic_nn
from mantis_research.core.retry import detect_rate_limit
from mantis_research.core.stage import AttemptResult
from mantis_research.core.state import SubsessionResult
from mantis_research.interface.adapters.openrouter_catalog import OpenRouterCatalog
from mantis_research.interface.adapters.openrouter_http import (
    OpenRouterHttpAdapter,
    OpenRouterHttpOptions,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import BatchConfig, TopicConfig
    from mantis_research.core.stage import RunContext
    from mantis_research.core.state import OpenRouterResearchState

log = structlog.get_logger(__name__)


class OpenRouterResearchStage:
    """Stage 2 (new) — research substrate via OpenRouter HTTP."""

    name: str = 'openrouter'
    state_subdir: str = 'openrouter'
    output_subdir: str = 'openrouter'

    def __init__(
        self,
        adapter: OpenRouterHttpAdapter | None = None,
        catalog: OpenRouterCatalog | None = None,
    ) -> None:
        # Adapter init reads OPENROUTER_API_KEY from settings — fails fast
        # if missing.
        self._adapter = adapter or OpenRouterHttpAdapter()
        # Lazily-fetched live model catalog, used to resolve 'auto'/'latest'
        # subsession models to each vendor's newest frontier id. Fetched once
        # per run on first use; degrades to pinned fallbacks when offline.
        self._catalog = catalog or OpenRouterCatalog()

    # ── Stage Protocol ────────────────────────────────────────────

    async def preflight(self) -> None:
        # OpenRouterHttpAdapter.preflight is async (hits the credits endpoint).
        await self._adapter.preflight()

    def is_enabled(self, topic: TopicConfig, config: BatchConfig) -> bool:
        return bool(topic.stages.openrouter)

    def upstream_ready(
        self,
        topic_id: str,
        slug: str,
        ctx: RunContext,
    ) -> tuple[bool, str | None]:
        return (True, None)

    async def run_attempt(
        self,
        topic: TopicConfig,
        state: OpenRouterResearchState,
        ctx: RunContext,
    ) -> AttemptResult:
        topic_id = topic.id
        slug = topic.slug
        # Subsessions carry dynamic provider knobs (web_search_engine,
        # temperature, …) beyond the declared fields, so dump the typed
        # subsession list to dicts and keep the per-entry logic dict-based.
        entries = [e.model_dump() for e in topic.stages.openrouter]
        if not entries:
            return AttemptResult.fail(error='no openrouter entries on this topic')

        output_paths = self._resolve_output_paths(topic_id, slug, entries, ctx)

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
                log.info(
                    'subsession already done, skipping',
                    topic_id=topic_id,
                    subslug=subslug,
                )
                continue

            transcript_path = self._transcript_path(ctx.transcript_dir, topic_id, slug, subslug)

            # Resolve the model: an explicit id passes through unchanged
            # (backward compat); 'auto'/'latest'/'auto:<vendor>' picks the
            # vendor's newest frontier id from the live catalog, or the pinned
            # fallback when offline. ``vendor`` may also be given as its own
            # config field alongside a bare 'auto'.
            resolution = resolve_openrouter_model(
                entry.get('model'),
                catalog=self._catalog.models(),
                vendor_hint=entry.get('vendor'),
            )
            if resolution.model_id is None:
                ss = SubsessionResult(
                    subslug=subslug,
                    status='failed',
                    error=resolution.notes[0] if resolution.notes else 'model unresolved',
                )
                self._upsert_subsession(state, ss)
                other_failure_msg = ss.error
                continue
            if resolution.source != 'pin':
                log.info(
                    'resolved openrouter model',
                    topic_id=topic_id,
                    subslug=subslug,
                    requested=resolution.requested,
                    resolved=resolution.model_id,
                    source=resolution.source,
                )

            # web_search_engine: 'native' for providers that have it
            # (Anthropic / OpenAI / xAI / Perplexity), 'exa' for everyone
            # else (DeepSeek, Mistral, Qwen, vanilla open-source models).
            engine = entry.get('web_search_engine', 'native')
            options = OpenRouterHttpOptions(
                model=resolution.model_id,
                web_search=bool(entry.get('web_search', False)),
                web_search_engine=engine,
                web_search_max_results=int(entry.get('web_search_max_results', 5)),
                reasoning_effort=entry.get('reasoning_effort'),
                reasoning_max_tokens=entry.get('reasoning_max_tokens'),
                max_tokens=entry.get('max_tokens'),
                temperature=entry.get('temperature'),
            )
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
        return transcript_dir / f'{nn}-{slug}-{subslug}-{ts}-openrouter.log'

    @staticmethod
    def _build_subsession_result(
        *,
        subslug: str,
        result: Any,
        out_path: Path,
        dry_run: bool,
    ) -> SubsessionResult:
        if not result.success:
            error = (
                'rate_limit'
                if detect_rate_limit(result.raw_output)
                else (result.error or f'http {result.status_code}')
            )
            return SubsessionResult(
                subslug=subslug,
                status='failed',
                duration_s=result.duration_s,
                error=error,
            )
        if not dry_run:
            content = result.output.strip()
            if not content:
                return SubsessionResult(
                    subslug=subslug,
                    status='failed',
                    duration_s=result.duration_s,
                    error='empty content',
                )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content + '\n', encoding='utf-8')
            size = out_path.stat().st_size
        else:
            size = 0
        return SubsessionResult(
            subslug=subslug,
            status='done',
            duration_s=result.duration_s,
            output_bytes=size,
            output_path=str(out_path),
            **OpenRouterResearchStage._usage_fields(result),
        )

    @staticmethod
    def _usage_fields(result: Any) -> dict[str, Any]:
        """Extract token/cost fields from an OpenRouter usage block.

        Returns an empty dict (all-None on the record) when the response
        carried no usage. OpenRouter reports reasoning tokens under
        ``completion_tokens_details.reasoning_tokens`` and cost under ``cost``
        (present because the adapter sends ``usage.include=True``).
        """
        usage = getattr(result, 'usage', None)
        if not isinstance(usage, dict):
            return {}
        details = usage.get('completion_tokens_details')
        reasoning = details.get('reasoning_tokens') if isinstance(details, dict) else None
        return {
            'tokens_prompt': usage.get('prompt_tokens'),
            'tokens_completion': usage.get('completion_tokens'),
            'tokens_reasoning': reasoning,
            'cost_usd': usage.get('cost'),
        }

    @staticmethod
    def _upsert_subsession(
        state: OpenRouterResearchState,
        new_record: SubsessionResult,
    ) -> None:
        for i, s in enumerate(state.subsessions):
            if s.subslug == new_record.subslug:
                state.subsessions[i] = new_record
                return
        state.subsessions.append(new_record)

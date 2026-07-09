"""Batch-config (v2 schema) validation via pydantic v2.

The config JSON is the canonical input that drives a batch run. Validating
on load catches structural errors at startup (fail fast principle) instead
of mid-run when a missing field surfaces inside an async task.

The schema is documented for humans in ``docs/batch-config.md`` — the two
change together. Backward-compatibility guarantees (invariant I4):

- Top-level shape: ``schema_version``, ``batch_name``, ``description``,
  ``models``, ``runner``, ``default_prompts``, ``topics`` — must accept
  configs produced by historical batches without modification.
- Per-topic shape: ``id``, ``slug``, ``tier``, ``title``, ``stages.*``.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ── per-topic stage configs ──────────────────────────────────────────


class ClaudeStageConfig(BaseModel):
    """Per-topic Claude research configuration (Stage 1).

    ``prompt`` is Optional: an omitted prompt falls back to the topic's
    ``research_prompt`` at load time (ADR-0008). An explicitly-set prompt —
    *including the empty string* — is kept as-is (163 committed Path-B topics
    carry ``prompt: ""``). The ``TopicConfig`` validator resolves it to a
    concrete string, so stages always read a real value.
    """

    model_config = ConfigDict(extra='allow')
    prompt: str | None = None


class GeminiSubsessionConfig(BaseModel):
    """One Gemini sub-session (allows multi-session per topic)."""

    model_config = ConfigDict(extra='allow')
    subslug: str = 'single'
    prompt: str | None = None  # None → falls back to topic.research_prompt (ADR-0008)


class OpenRouterSubsessionConfig(BaseModel):
    """One OpenRouter sub-session.

    ``model`` is either a pinned OpenRouter id (e.g. ``openai/gpt-5.5``,
    ``deepseek/deepseek-v4-pro`` — used verbatim) OR an auto-latest sentinel
    that resolves to the vendor's newest frontier model at run time:

    - ``'auto:<vendor>'`` / ``'latest:<vendor>'`` (e.g. ``'auto:openai'``) —
      vendor encoded in the value.
    - ``'auto'`` / ``'latest'`` with a separate ``vendor`` field (below).
    - omitted entirely, with a ``vendor`` field — same as ``'auto'``.

    Auto resolution queries the live ``/models`` catalog and degrades to a
    pinned fallback id when offline. See ``core/model_policy.py``. Optional
    knobs control reasoning effort and web-search activation.
    """

    model_config = ConfigDict(extra='allow')
    subslug: str = 'single'
    # None / 'auto' / 'latest' / 'auto:<vendor>' → auto-latest; any other
    # string is a pinned id used as-is.
    model: str | None = None
    # Vendor prefix (e.g. 'openai', 'google', 'deepseek') for the auto-latest
    # policy when ``model`` does not itself encode the vendor. Ignored for a
    # pinned model id.
    vendor: str | None = None
    prompt: str | None = None  # None → falls back to topic.research_prompt (ADR-0008)
    web_search: bool = False
    reasoning_effort: Literal['low', 'medium', 'high', 'xhigh'] | None = None
    max_tokens: int | None = None


class OptionalStageConfig(BaseModel):
    """Per-topic optional stage (synthesis, journal, falsification, journal_passes)."""

    model_config = ConfigDict(extra='allow')
    prompt: str | None = None  # None means "use config.default_prompts.<stage>"
    enabled: bool | None = None  # None means default


class TopicStages(BaseModel):
    """The ``stages`` block under each topic."""

    model_config = ConfigDict(extra='allow')

    claude: ClaudeStageConfig
    gemini: list[GeminiSubsessionConfig] = Field(default_factory=list)
    openrouter: list[OpenRouterSubsessionConfig] = Field(default_factory=list)
    synthesis: OptionalStageConfig = Field(default_factory=OptionalStageConfig)
    journal: OptionalStageConfig = Field(default_factory=OptionalStageConfig)
    journal_passes: OptionalStageConfig = Field(default_factory=OptionalStageConfig)
    falsification: OptionalStageConfig = Field(default_factory=OptionalStageConfig)
    evaluation: OptionalStageConfig = Field(default_factory=OptionalStageConfig)


class TopicConfig(BaseModel):
    """One topic in the batch."""

    model_config = ConfigDict(extra='allow')

    id: str
    slug: str
    tier: str | None = None
    title: str
    high_stakes: bool = False
    # A single research prompt shared by any research subsession that omits its
    # own ``prompt`` (ADR-0008). Lets a multi-substrate topic carry one prompt
    # plus thin per-substrate entries instead of N verbatim copies.
    research_prompt: str | None = None
    stages: TopicStages

    @field_validator('id', mode='before')
    @classmethod
    def id_must_be_string(cls, v: str | int) -> str:
        # Topics may carry numeric IDs in JSON; we normalize to string for
        # consistent state-file-naming downstream. ``mode='before'`` runs
        # prior to type coercion so int → str works.
        return str(v)

    @model_validator(mode='after')
    def _resolve_research_prompts(self) -> Self:
        """Fill each research subsession's prompt, keying on PRESENCE.

        An explicitly-set prompt — *including the empty string* — is kept
        (``is not None``, never truthiness: 163 committed Path-B topics carry
        ``claude.prompt == ""``). Only an omitted (``None``) prompt falls back
        to ``research_prompt``; if that is also absent, loading fails with a
        message naming the topic and subsession (fail-fast, ADR-0008).
        """

        def resolved(current: str | None, subslug: str) -> str:
            if current is not None:
                return current
            if self.research_prompt is not None:
                return self.research_prompt
            msg = (
                f'topic {self.id!r} subsession {subslug!r} has no prompt and the '
                f'topic has no research_prompt fallback'
            )
            raise ValueError(msg)

        self.stages.claude.prompt = resolved(self.stages.claude.prompt, 'claude')
        for entry in self.stages.gemini:
            entry.prompt = resolved(entry.prompt, entry.subslug)
        for entry in self.stages.openrouter:
            entry.prompt = resolved(entry.prompt, entry.subslug)
        return self


# ── top-level config ─────────────────────────────────────────────────


class ModelSpec(BaseModel):
    """Model + effort spec used across stages.

    ``model`` is optional: omit it (or set ``'auto'`` / ``'latest'``) to use
    the latest-resolving model for that stage — for Claude stages this is the
    ``claude --model`` alias ``opus``, which the CLI maps to the newest Opus.
    Any explicit id (e.g. ``claude-opus-4-8``) is used verbatim. See
    ``core/model_policy.py``.
    """

    model_config = ConfigDict(extra='allow')
    model: str | None = None
    effort: str | None = None


class ModelsBlock(BaseModel):
    """The ``models`` block at the top of the config."""

    model_config = ConfigDict(extra='allow')
    claude: ModelSpec
    gemini: ModelSpec | None = None
    openrouter: ModelSpec | None = None
    synthesis: ModelSpec | None = None  # falls back to claude if absent
    # Which research brief the synthesis stage treats as primary (ADR-0005).
    # ``None``/``'claude'`` → the Claude brief (default, today's behavior);
    # ``'openrouter:<subslug>'`` → that OpenRouter subsession's brief, with all
    # other briefs (Claude included, when present) as secondaries. This is how
    # Path B (no Claude research) is expressed without the promote/restore
    # script.
    primary: str | None = None


class RunnerBlock(BaseModel):
    """The ``runner`` block — orchestrator settings."""

    model_config = ConfigDict(extra='allow')
    max_parallel_topics: int = 4
    max_retries_per_stage: int = 2
    rate_limit_backoff_minutes: int = 30
    generic_failure_backoff_minutes: int = 5
    # Run-directory layout (ADR-0006). 'legacy' (default) keeps the flat
    # directories every committed batch uses; 'batch' scopes state/outputs/
    # transcripts under <batch_name>/ so request-level runs never collide.
    layout: Literal['legacy', 'batch'] = 'legacy'


class DefaultPromptsBlock(BaseModel):
    """Global default prompts (used when topic-level prompt is None)."""

    model_config = ConfigDict(extra='allow')
    synthesis: str | None = None
    journal: str | None = None
    journal_augmentation: str | None = None
    falsification: str | None = None
    evaluation: str | None = None


class BatchConfig(BaseModel):
    """Top-level v2 batch config.

    Use ``BatchConfig.model_validate_json(path.read_text())`` to load from
    disk; pydantic raises a clear error pointing at the offending field.
    """

    model_config = ConfigDict(extra='allow')

    schema_version: Literal[2]
    batch_name: str
    description: str = ''
    models: ModelsBlock
    runner: RunnerBlock = Field(default_factory=RunnerBlock)
    default_prompts: DefaultPromptsBlock = Field(default_factory=DefaultPromptsBlock)
    topics: list[TopicConfig]

    @field_validator('topics')
    @classmethod
    def topics_must_have_unique_ids(cls, v: list[TopicConfig]) -> list[TopicConfig]:
        ids = [t.id for t in v]
        if len(ids) != len(set(ids)):
            duplicates = [i for i in ids if ids.count(i) > 1]
            msg = f'duplicate topic ids: {sorted(set(duplicates))}'
            raise ValueError(msg)
        return v

    def topic_by_id(self, topic_id: str) -> TopicConfig | None:
        return next((t for t in self.topics if t.id == topic_id), None)


# ── loader helpers ───────────────────────────────────────────────────


def load_batch_config(path_or_json: Any) -> BatchConfig:
    """Validate and return a BatchConfig from a path-like or JSON string.

    Accepts:
    - ``pathlib.Path`` or ``str`` path → reads file
    - JSON string → parses directly
    - dict → validates structure
    """
    from pathlib import Path

    if isinstance(path_or_json, Path):
        return BatchConfig.model_validate_json(path_or_json.read_text(encoding='utf-8'))
    if isinstance(path_or_json, str):
        # Heuristic: if it looks like a path, read it; else parse as JSON.
        p = Path(path_or_json)
        if p.exists():
            return BatchConfig.model_validate_json(p.read_text(encoding='utf-8'))
        return BatchConfig.model_validate_json(path_or_json)
    return BatchConfig.model_validate(path_or_json)

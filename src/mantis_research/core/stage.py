"""Stage and ProviderAdapter Protocols — the structural contracts of the pipeline.

A **Stage** binds a prompt template + an adapter for one pipeline phase
(e.g., ClaudeResearchStage = Claude prompt + ClaudeCliAdapter). Adding a new
phase is a new module under ``interface/stages/`` implementing this Protocol.

A **ProviderAdapter** wraps the actual model call (subprocess, HTTP, etc.).
Adding a new model provider is a new module under ``interface/adapters/``
implementing the adapter Protocol.

The orchestrator (in ``interface/orchestrator.py``) takes a Stage and runs
it generically: per-topic concurrency, retries, state persistence, signal
handling, progress reporting. None of that lives in stages or adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import BatchConfig, TopicConfig
    from mantis_research.core.state import TopicState


# ── attempt result types ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AttemptResult:
    """The outcome of one Stage.run_attempt call.

    Either ``success`` is True and ``output_bytes`` reflects the produced
    artifact size, OR ``success`` is False and ``error`` carries the
    failure description. The orchestrator uses ``error_output`` (raw
    stdout/stderr) to classify rate-limit vs generic failure.
    """

    success: bool
    error: str | None = None
    error_output: str = ''  # raw subprocess output for rate-limit detection
    output_bytes: int | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, output_bytes: int | None = None, **extras: Any) -> AttemptResult:
        return cls(success=True, output_bytes=output_bytes, extras=extras)

    @classmethod
    def fail(cls, error: str, error_output: str = '') -> AttemptResult:
        return cls(success=False, error=error, error_output=error_output)


# ── run context ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RunContext:
    """Per-batch context handed to a Stage. Stable across attempts.

    The orchestrator constructs one and passes it through every attempt;
    Stages should not mutate it.
    """

    batch: BatchConfig  # the validated batch config (v2 schema)
    state_dir: Path
    output_dir: Path
    transcript_dir: Path
    dry_run: bool = False


# ── Stage Protocol ───────────────────────────────────────────────────


@runtime_checkable
class Stage(Protocol):
    """Contract every pipeline stage implements.

    Property attributes (constants per stage):

    - ``name`` — short identifier (``'claude'``, ``'gemini'``, ``'openrouter'``,
      ``'synthesis'``, ``'journal-passes'``, ``'falsification'``,
      ``'evaluation'``, ``'claude-prior'``).
    - ``state_subdir`` — directory under ``state/`` holding per-topic state.
    - ``output_subdir`` — directory under ``outputs/`` holding generated artifacts.
    """

    name: str
    state_subdir: str
    output_subdir: str

    async def preflight(self) -> None:
        """Verify the stage's provider is reachable and authenticated.

        Called once by the CLI dispatch layer before the orchestrator runs
        (skipped under ``--dry-run``). Each stage delegates to its adapter's
        ``preflight``; the method is async so an HTTP adapter can await, while
        a subprocess adapter's synchronous preflight is called directly inside.
        Raise to abort the run with a clear message.
        """
        ...

    def is_enabled(self, topic: TopicConfig, config: BatchConfig) -> bool:
        """Return True if this stage should run for this topic.

        Stages that are unconditional (Claude/Gemini/OpenRouter/Synthesis/Journal-passes)
        return True. Optional stages (falsification, evaluation) check
        ``topic.high_stakes`` or ``topic.stages.<name>.enabled``.
        """
        ...

    def upstream_ready(self, topic_id: str, slug: str, ctx: RunContext) -> tuple[bool, str | None]:
        """Return (ready, reason_if_blocked).

        Used as the gate for ``BLOCKED_UPSTREAM``. For synthesis,
        upstream-not-ready means the primary brief (``models.primary``) or
        every secondary brief is missing.
        """
        ...

    async def run_attempt(
        self,
        topic: TopicConfig,
        state: TopicState,
        ctx: RunContext,
    ) -> AttemptResult:
        """Execute one attempt for this topic.

        The orchestrator handles state persistence (save before/after this
        call), retries (on AttemptResult.success=False), and rate-limit
        classification (using ``error_output``). Stages should NOT swallow
        exceptions or call sleep — propagate so the orchestrator can retry.
        """
        ...


# ── ProviderAdapter Protocol ─────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ResearchOptions:
    """Parameters passed to a provider adapter for a research call."""

    model: str
    effort: str | None = None  # 'low' | 'medium' | 'high' | 'max'
    web_search: bool = False
    reasoning: bool = False
    max_tokens: int | None = None
    allowed_tools: tuple[str, ...] = ()
    timeout_s: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResearchResult:
    """Outcome of a single provider call."""

    success: bool
    output: str = ''  # the model's text response (for HTTP adapter)
    output_path: Path | None = None  # path the adapter wrote (for CLI adapters)
    output_bytes: int | None = None
    duration_s: float | None = None
    error: str | None = None
    raw_output: str = ''  # full stdout+stderr (for rate-limit detection)


@runtime_checkable
class ProviderAdapter(Protocol):
    """Contract every provider driver implements (Claude CLI, Gemini CLI, OpenRouter HTTP)."""

    name: str

    async def preflight(self) -> None:
        """Verify the provider is reachable and authenticated. Raise on failure."""
        ...

    async def run_research(
        self,
        prompt: str,
        options: ResearchOptions,
        transcript_path: Path,
        dry_run: bool = False,
    ) -> ResearchResult:
        """Execute one research call; persist transcript at ``transcript_path``."""
        ...

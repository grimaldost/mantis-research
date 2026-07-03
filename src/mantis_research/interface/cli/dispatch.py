"""Stage registry + Orchestrator wiring shared by all CLI subcommands.

Single dispatch table that maps a stage name to:
- the Stage class to instantiate
- the per-topic State class
- the legacy directory names (state + output) for the transition window

Every CLI subcommand (``mantis run claude``, ``mantis run synthesis``, …)
goes through ``dispatch_stage(...)``. Adding a new stage is one entry in
``STAGE_REGISTRY``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mantis_research.core.config import load_batch_config
from mantis_research.core.logging import configure_logging
from mantis_research.core.paths import (
    logs_root,
    project_root,
    run_output_dir,
    run_state_dir,
    run_transcript_dir,
)
from mantis_research.core.settings import settings
from mantis_research.core.state import (
    ClaudePriorState,
    ClaudeResearchState,
    EvaluationState,
    FalsificationState,
    GeminiResearchState,
    JournalPassesState,
    OpenRouterResearchState,
    SynthesisState,
    TopicState,
)
from mantis_research.interface.orchestrator import Orchestrator
from mantis_research.interface.stages.claude_prior import ClaudePriorStage
from mantis_research.interface.stages.claude_research import ClaudeResearchStage
from mantis_research.interface.stages.evaluation import EvaluationStage
from mantis_research.interface.stages.falsification import FalsificationStage
from mantis_research.interface.stages.gemini_research import GeminiResearchStage
from mantis_research.interface.stages.journal_passes import JournalPassesStage
from mantis_research.interface.stages.openrouter_research import OpenRouterResearchStage
from mantis_research.interface.stages.synthesis import SynthesisStage

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from mantis_research.core.config import BatchConfig
    from mantis_research.core.stage import Stage


@dataclass(frozen=True, slots=True)
class StageEntry:
    """One row of the stage registry."""

    stage_factory: Callable[[], Stage]
    state_class: type[TopicState]
    legacy_state_name: str
    legacy_output_name: str


# NOTE: ty flags Protocol-variance mismatch on stage_factory entries
# (concrete stages take subclass-typed states; Stage Protocol takes the
# base class). The runtime is correct — the orchestrator passes the right
# subclass via state_class — but the strict static check disagrees. We
# accept the diagnostic here rather than make Stage generic.
STAGE_REGISTRY: dict[str, StageEntry] = {
    'claude': StageEntry(
        stage_factory=ClaudeResearchStage,  # ty: ignore[invalid-argument-type]
        state_class=ClaudeResearchState,
        legacy_state_name='claude',
        legacy_output_name='claude',
    ),
    'gemini': StageEntry(
        stage_factory=GeminiResearchStage,  # ty: ignore[invalid-argument-type]
        state_class=GeminiResearchState,
        legacy_state_name='gemini',
        legacy_output_name='gemini',
    ),
    'openrouter': StageEntry(
        stage_factory=OpenRouterResearchStage,  # ty: ignore[invalid-argument-type]
        state_class=OpenRouterResearchState,
        legacy_state_name='openrouter',
        legacy_output_name='openrouter',
    ),
    'synthesis': StageEntry(
        stage_factory=SynthesisStage,  # ty: ignore[invalid-argument-type]
        state_class=SynthesisState,
        legacy_state_name='synthesis',
        legacy_output_name='synthesis',
    ),
    'journal-passes': StageEntry(
        stage_factory=JournalPassesStage,  # ty: ignore[invalid-argument-type]
        state_class=JournalPassesState,
        legacy_state_name='journal-passes',
        legacy_output_name='journals',
    ),
    'falsification': StageEntry(
        stage_factory=FalsificationStage,  # ty: ignore[invalid-argument-type]
        state_class=FalsificationState,
        legacy_state_name='falsification',
        legacy_output_name='falsification',
    ),
    'evaluation': StageEntry(
        stage_factory=EvaluationStage,  # ty: ignore[invalid-argument-type]
        state_class=EvaluationState,
        legacy_state_name='evaluation',
        legacy_output_name='evaluation',
    ),
    'claude-prior': StageEntry(
        stage_factory=ClaudePriorStage,  # ty: ignore[invalid-argument-type]
        state_class=ClaudePriorState,
        legacy_state_name='claude-prior',
        legacy_output_name='claude-prior',
    ),
}


def _resolve_config_path(raw: Path) -> Path:
    if raw.exists():
        return raw
    rooted = project_root() / raw
    if rooted.exists():
        return rooted
    msg = f'config not found: {raw}'
    raise FileNotFoundError(msg)


async def _run_stage_async(
    name: str,
    cfg: BatchConfig,
    *,
    parallel: int | None,
    dry_run: bool,
    force: bool,
    only: Sequence[str] | None,
) -> int:
    entry = STAGE_REGISTRY[name]
    stage = entry.stage_factory()
    # Stage-owned preflight — the stage delegates to its adapter (async so an
    # HTTP adapter can await; a subprocess adapter's sync preflight is called
    # directly inside the stage). Skipped under --dry-run.
    if not dry_run:
        await stage.preflight()

    # Resolve run directories under the config's layout (ADR-0006). 'legacy'
    # (the default for every committed config) is byte-identical to the old
    # flat directories; 'batch' scopes them under <batch_name>/.
    layout = cfg.runner.layout
    batch = cfg.batch_name
    state_dir = run_state_dir(layout, batch, entry.legacy_state_name)
    output_dir = run_output_dir(layout, batch, entry.legacy_output_name)
    transcript_dir = run_transcript_dir(layout, batch)
    logs_root().mkdir(parents=True, exist_ok=True)

    orchestrator = Orchestrator(
        stage=stage,
        state_class=entry.state_class,
        config=cfg,
        state_dir=state_dir,
        output_dir=output_dir,
        transcript_dir=transcript_dir,
        parallel=parallel,
        dry_run=dry_run,
    )
    return await orchestrator.run(only=only, force=force)


def _check_stage_allowed(name: str) -> None:
    """Guard: reject an unknown stage or one disabled via MANTIS_DISABLED_STAGES.

    Runs before any config is read so a disabled/unknown stage fails fast
    without needing a valid config on disk.
    """
    if name not in STAGE_REGISTRY:
        msg = f'unknown stage: {name!r}. Known: {sorted(STAGE_REGISTRY)}'
        raise ValueError(msg)
    if name in settings.disabled_stages:
        msg = (
            f'stage {name!r} is disabled via MANTIS_DISABLED_STAGES in your .env '
            f'(current value: {settings.DISABLED_STAGES!r}). '
            f'Remove it from that list to re-enable, or pick a different stage. '
            f'See prompts/playbooks/research-path-recommendation.md for the '
            f'recommended substrate set (Path B uses openrouter for all research '
            f'and reserves claude CLI for synthesis + journal-passes).'
        )
        raise RuntimeError(msg)


def dispatch_stage_config(
    name: str,
    cfg: BatchConfig,
    *,
    parallel: int | None = None,
    dry_run: bool = False,
    force: bool = False,
    only: Sequence[str] | None = None,
    log_level: str = 'INFO',
) -> int:
    """Run one stage from an already-built ``BatchConfig`` (no path read).

    This is the seam ``mantis research`` calls once per stage (ADR-0004). It
    carries the same unknown-stage and ``MANTIS_DISABLED_STAGES`` guards and
    logging setup the subcommands get, so the request-level path enforces the
    same gating as the batch subcommands. One top-level ``asyncio.run`` per
    call (invoked sequentially by the façade — no nested event loop).
    """
    _check_stage_allowed(name)
    configure_logging(level=log_level)
    return asyncio.run(
        _run_stage_async(
            name,
            cfg,
            parallel=parallel,
            dry_run=dry_run,
            force=force,
            only=only,
        )
    )


def dispatch_stage(
    name: str,
    config_path: Path,
    *,
    parallel: int | None = None,
    dry_run: bool = False,
    force: bool = False,
    only: Sequence[str] | None = None,
    log_level: str = 'INFO',
) -> int:
    """Synchronous path-based entry point used by every ``mantis run`` subcommand.

    Thin wrapper: guard the stage, load and validate the config from disk, then
    delegate to :func:`dispatch_stage_config`. The guard runs before the load so
    an unknown/disabled stage fails without needing a valid config.
    """
    _check_stage_allowed(name)
    cfg = load_batch_config(_resolve_config_path(config_path))
    return dispatch_stage_config(
        name,
        cfg,
        parallel=parallel,
        dry_run=dry_run,
        force=force,
        only=only,
        log_level=log_level,
    )

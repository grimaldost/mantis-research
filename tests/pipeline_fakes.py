"""The real research and synthesis stages, driven through fake adapters.

Most serving-path tests replace ``dispatch_stage_config`` wholesale, which is
what let the same-name dry-run defect through: the stage-level bookkeeping that
poisoned the real run was never exercised (MANT-01). These fakes sit one seam
lower, at the adapters, so the orchestrator, the state files and the stages'
own skip logic all run as they do in production, and nothing spends money.

``install_fake_pipeline`` swaps the registry's ``openrouter`` and ``synthesis``
entries for the real stage classes built on these adapters, and returns the
adapters so a test can read what was asked of them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mantis_research.core.state import OpenRouterResearchState, SynthesisState
from mantis_research.interface.adapters.claude_cli import ClaudeCliOptions, ClaudeCliResult
from mantis_research.interface.adapters.openrouter_http import (
    OpenRouterHttpOptions,
    OpenRouterHttpResult,
)
from mantis_research.interface.cli import dispatch as dispatch_mod
from mantis_research.interface.cli.dispatch import StageEntry
from mantis_research.interface.stages.openrouter_research import OpenRouterResearchStage
from mantis_research.interface.stages.synthesis import SynthesisStage

if TYPE_CHECKING:
    import pytest

#: A sidecar draft the synthesis stage accepts (same shape as the sidecar tests use).
SIDECAR_DRAFT = json.dumps(
    {
        'sidecar_version': 2,
        'claims': [{'id': 'c1', 'text': 'a claim', 'support': 'direct'}],
        'divergences': [],
        'verification_queue': [],
        'agreements_worth_verifying': [],
        'coverage_notes': [],
    }
)

_SYNTHESIS_TARGET = re.compile(r'Save the synthesis brief to (\S+?) using the Write tool')
_SIDECAR_TARGET = re.compile(r'(\S+\.sidecar(?:\.draft)?\.json)')


class NoCatalog:
    """The live model catalog, offline: every ``auto`` model takes its pinned id."""

    def models(self) -> None:
        return None


@dataclass
class FakeOpenRouter:
    """Answers each substrate call with a brief, a model id and a cost.

    ``calls`` records ``(model, dry_run)`` per call. ``usage`` is the usage block
    every live answer carries; set it to ``None`` to model a response without one.
    """

    calls: list[tuple[str, bool]] = field(default_factory=list)
    usage: dict[str, Any] | None = field(
        default_factory=lambda: {'prompt_tokens': 10, 'completion_tokens': 20, 'cost': 0.01}
    )

    async def preflight(self) -> None:
        return None

    async def run(
        self,
        prompt: str,
        options: OpenRouterHttpOptions,
        transcript_path: Path,
        *,
        dry_run: bool = False,
    ) -> OpenRouterHttpResult:
        self.calls.append((options.model, dry_run))
        if dry_run:
            # What the real adapter returns under a dry run: success, no body.
            return OpenRouterHttpResult(
                success=True, status_code=0, duration_s=0.0, model_used=options.model
            )
        return OpenRouterHttpResult(
            success=True,
            status_code=200,
            duration_s=0.1,
            output=f'# brief from {options.model}\n\nSee https://example.com/{len(self.calls)}.',
            model_used=options.model,
            usage=self.usage,
        )

    @property
    def live_calls(self) -> int:
        return sum(1 for _, dry in self.calls if not dry)


@dataclass
class FakeClaude:
    """Plays the local seat: writes each turn's artifact where the prompt says.

    ``spawns`` records every ``(options, dry_run)`` the stage asked for.
    """

    spawns: list[tuple[ClaudeCliOptions, bool]] = field(default_factory=list)

    def preflight(self) -> None:
        return None

    async def run(
        self,
        prompt: str,
        options: ClaudeCliOptions,
        transcript_path: Path,
        *,
        dry_run: bool = False,
    ) -> ClaudeCliResult:
        self.spawns.append((options, dry_run))
        if not dry_run:
            name = options.name or ''
            if 'sidecar-topic' in name:
                target = _SIDECAR_TARGET.search(prompt)
                assert target is not None, 'the sidecar prompt names no path'
                _write(Path(target.group(1)), SIDECAR_DRAFT)
            elif 'synthesis-topic' in name:
                target = _SYNTHESIS_TARGET.search(prompt)
                assert target is not None, 'the synthesis prompt names no path'
                _write(Path(target.group(1)), '# synthesis\n')
        return ClaudeCliResult(success=True, exit_code=0, duration_s=0.1, session_id='s')

    @property
    def live_spawns(self) -> int:
        return sum(1 for _, dry in self.spawns if not dry)


@dataclass
class FakePipeline:
    openrouter: FakeOpenRouter
    claude: FakeClaude


def install_fake_pipeline(monkeypatch: pytest.MonkeyPatch) -> FakePipeline:
    """Route the ``openrouter`` and ``synthesis`` stages through fake adapters."""
    pipeline = FakePipeline(FakeOpenRouter(), FakeClaude())
    monkeypatch.setitem(
        dispatch_mod.STAGE_REGISTRY,
        'openrouter',
        StageEntry(
            stage_factory=lambda: OpenRouterResearchStage(
                adapter=pipeline.openrouter,  # type: ignore[arg-type]
                catalog=NoCatalog(),  # type: ignore[arg-type]
            ),
            state_class=OpenRouterResearchState,
            legacy_state_name='openrouter',
            legacy_output_name='openrouter',
        ),
    )
    monkeypatch.setitem(
        dispatch_mod.STAGE_REGISTRY,
        'synthesis',
        StageEntry(
            stage_factory=lambda: SynthesisStage(adapter=pipeline.claude),  # type: ignore[arg-type]
            state_class=SynthesisState,
            legacy_state_name='synthesis',
            legacy_output_name='synthesis',
        ),
    )
    return pipeline


def _write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')

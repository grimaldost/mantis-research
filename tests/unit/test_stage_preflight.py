"""Stage-owned preflight (spec 0001 §5).

Two contracts:
- each stage delegates ``preflight`` to its adapter (sync adapters called
  directly, async adapters awaited);
- the CLI dispatch layer calls ``await stage.preflight()`` exactly once when
  not dry-run, and skips it under ``--dry-run``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mantis_research.core.state import ClaudeResearchState, TopicState
from mantis_research.interface.cli import dispatch as dispatch_mod
from mantis_research.interface.cli.dispatch import StageEntry, dispatch_stage
from mantis_research.interface.stages.claude_research import ClaudeResearchStage
from mantis_research.interface.stages.openrouter_research import OpenRouterResearchStage

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.stage import AttemptResult, RunContext


class _RecordingSyncAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def preflight(self) -> None:
        self.calls += 1


class _RecordingAsyncAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def preflight(self) -> None:
        self.calls += 1


class TestStageDelegatesToAdapter:
    async def test_claude_stage_calls_sync_adapter_preflight(self) -> None:
        adapter = _RecordingSyncAdapter()
        stage = ClaudeResearchStage(adapter=adapter)  # type: ignore[arg-type]
        await stage.preflight()
        assert adapter.calls == 1

    async def test_openrouter_stage_awaits_async_adapter_preflight(self) -> None:
        adapter = _RecordingAsyncAdapter()
        stage = OpenRouterResearchStage(adapter=adapter)  # type: ignore[arg-type]
        await stage.preflight()
        assert adapter.calls == 1


class _FakePreflightStage:
    name = 'claude'
    state_subdir = 'claude'
    output_subdir = 'claude'
    preflight_calls = 0

    async def preflight(self) -> None:
        type(self).preflight_calls += 1

    def is_enabled(self, topic: dict[str, Any], config: dict[str, Any]) -> bool:
        return True

    def upstream_ready(self, topic_id: str, slug: str, ctx: RunContext) -> tuple[bool, str | None]:
        return (True, None)

    async def run_attempt(
        self, topic: dict[str, Any], state: TopicState, ctx: RunContext
    ) -> AttemptResult:  # pragma: no cover - no topics, never called
        from mantis_research.core.stage import AttemptResult

        return AttemptResult.ok()


def _empty_config(tmp_path: Path) -> Path:
    cfg = {
        'schema_version': 2,
        'batch_name': 'preflight-test',
        'models': {'claude': {'model': 'claude-opus-4-7', 'effort': 'max'}},
        'topics': [],
    }
    p = tmp_path / 'cfg.json'
    p.write_text(json.dumps(cfg), encoding='utf-8')
    return p


class TestDispatchInvokesPreflight:
    @pytest.fixture(autouse=True)
    def _patch_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _FakePreflightStage.preflight_calls = 0
        monkeypatch.setitem(
            dispatch_mod.STAGE_REGISTRY,
            'claude',
            StageEntry(
                stage_factory=_FakePreflightStage,  # type: ignore[arg-type]
                state_class=ClaudeResearchState,
                legacy_state_name='claude',
                legacy_output_name='claude',
            ),
        )

    def test_preflight_called_when_not_dry_run(self, tmp_path: Path) -> None:
        dispatch_stage('claude', _empty_config(tmp_path), dry_run=False)
        assert _FakePreflightStage.preflight_calls == 1

    def test_preflight_skipped_under_dry_run(self, tmp_path: Path) -> None:
        dispatch_stage('claude', _empty_config(tmp_path), dry_run=True)
        assert _FakePreflightStage.preflight_calls == 0

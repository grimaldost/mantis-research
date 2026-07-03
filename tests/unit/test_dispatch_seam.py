"""Layout-aware dispatch + in-memory-config seam (spec 0001 §18).

``dispatch_stage_config`` runs a stage from an already-built ``BatchConfig``
(the seam ``mantis research`` calls), resolves directories under the config's
layout, and carries the same guards as the path-based subcommands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mantis_research.core.config import load_batch_config
from mantis_research.core.state import ClaudeResearchState, TopicState
from mantis_research.interface.cli import dispatch as dispatch_mod
from mantis_research.interface.cli.dispatch import StageEntry, dispatch_stage_config

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.stage import AttemptResult, RunContext


class _FakeStage:
    name = 'claude'
    state_subdir = 'claude'
    output_subdir = 'claude'

    async def preflight(self) -> None:
        return None

    def is_enabled(self, topic: Any, config: Any) -> bool:
        return True

    def upstream_ready(self, topic_id: str, slug: str, ctx: RunContext) -> tuple[bool, str | None]:
        return (True, None)

    async def run_attempt(self, topic: Any, state: TopicState, ctx: RunContext) -> AttemptResult:
        from mantis_research.core.stage import AttemptResult

        return AttemptResult.ok(output_bytes=1)


@pytest.fixture(autouse=True)
def _fake_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        dispatch_mod.STAGE_REGISTRY,
        'claude',
        StageEntry(
            stage_factory=_FakeStage,  # type: ignore[arg-type]
            state_class=ClaudeResearchState,
            legacy_state_name='claude',
            legacy_output_name='claude',
        ),
    )


def _cfg(layout: str) -> Any:
    return load_batch_config(
        {
            'schema_version': 2,
            'batch_name': 'mybatch',
            'runner': {'layout': layout},
            'models': {'claude': {'model': 'claude-opus-4-7'}},
            'topics': [
                {'id': '1', 'slug': 't', 'title': 'T', 'stages': {'claude': {'prompt': 'p'}}}
            ],
        }
    )


def test_batch_layout_lands_state_under_batch_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr('mantis_research.core.paths.state_root', lambda: tmp_path / 'state')
    monkeypatch.setattr('mantis_research.core.paths.outputs_root', lambda: tmp_path / 'out')
    monkeypatch.setattr('mantis_research.core.paths.transcripts_root', lambda: tmp_path / 'tx')

    rc = dispatch_stage_config('claude', _cfg('batch'), dry_run=True)

    assert rc == 0
    scoped = tmp_path / 'state' / 'mybatch' / 'claude'
    assert (scoped / '1.json').exists()
    assert (scoped / 'progress.json').exists()


def test_legacy_layout_uses_flat_state_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Under legacy, state_root is unused (legacy_state_dir → project_root/state);
    # redirect project_root so the flat 'state' dir lands in tmp.
    monkeypatch.setattr('mantis_research.core.paths.project_root', lambda: tmp_path)

    rc = dispatch_stage_config('claude', _cfg('legacy'), dry_run=True)

    assert rc == 0
    assert (tmp_path / 'state' / '1.json').exists()  # flat, not scoped


def test_seam_carries_disabled_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('DISABLED_STAGES', 'claude')
    import mantis_research.core.settings as settings_mod

    monkeypatch.setattr(dispatch_mod, 'settings', settings_mod.Settings())
    with pytest.raises(RuntimeError, match='disabled'):
        dispatch_stage_config('claude', _cfg('legacy'), dry_run=True)

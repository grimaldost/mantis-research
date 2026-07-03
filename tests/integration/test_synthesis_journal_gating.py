"""Synthesis journal-turn gating (spec 0001 §8).

``stages.journal.enabled = False`` skips Turn 2 (journal); None/True keep it on.
Runs in dry-run so no real files are checked — the fake adapter just counts
``run`` calls (1 = synthesis only, 2 = synthesis + journal). Brief files must
still exist on disk because the synthesis prompt formats their sizes, so the
module's ``legacy_output_dir`` is redirected to a tmp tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from mantis_research.core.config import load_batch_config
from mantis_research.core.stage import RunContext
from mantis_research.core.state import SynthesisState
from mantis_research.interface.adapters.claude_cli import ClaudeCliOptions, ClaudeCliResult
from mantis_research.interface.stages.synthesis import SynthesisStage

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import BatchConfig


@dataclass
class CountingAdapter:
    calls: list[ClaudeCliOptions] = field(default_factory=list)

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
        self.calls.append(options)
        return ClaudeCliResult(
            success=True,
            exit_code=0,
            duration_s=1.0,
            session_id=options.session_id or options.resume_session_id or 'sid',
        )


def _config(journal_enabled: bool | None) -> BatchConfig:
    journal_stage: dict[str, object] = {}
    if journal_enabled is not None:
        journal_stage = {'enabled': journal_enabled}
    return load_batch_config(
        {
            'schema_version': 2,
            'batch_name': 'jtest',
            # Batch layout so brief discovery resolves under the tmp outputs_root
            # the fixture redirects (also exercises §11's layout-aware paths).
            'runner': {'layout': 'batch'},
            'models': {'claude': {'model': 'claude-opus-4-7', 'effort': 'max'}},
            'topics': [
                {
                    'id': '1',
                    'slug': 'test',
                    'title': 'T',
                    'stages': {'claude': {'prompt': 'p'}, 'journal': journal_stage},
                }
            ],
        }
    )


@pytest.fixture
def briefs_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    # Under batch layout, RunDirs.output(stage) == outputs_root()/jtest/stage.
    monkeypatch.setattr('mantis_research.core.paths.outputs_root', lambda: tmp_path)
    for stage in ('claude', 'gemini'):
        d = tmp_path / 'jtest' / stage
        d.mkdir(parents=True, exist_ok=True)
        (d / '01-test.md').write_text(f'{stage} brief', encoding='utf-8')
    return tmp_path


async def _run(cfg: BatchConfig, adapter: CountingAdapter, tmp_path: Path) -> None:
    stage = SynthesisStage(adapter=adapter)  # type: ignore[arg-type]
    ctx = RunContext(
        batch=cfg,
        state_dir=tmp_path / 'state',
        output_dir=tmp_path / 'out',
        transcript_dir=tmp_path / 'tx',
        dry_run=True,
    )
    (tmp_path / 'out').mkdir(parents=True, exist_ok=True)
    await stage.run_attempt(cfg.topics[0], SynthesisState(id='1', slug='test'), ctx)


class TestJournalGating:
    async def test_journal_enabled_false_skips_turn_2(self, briefs_dir: Path) -> None:
        adapter = CountingAdapter()
        await _run(_config(journal_enabled=False), adapter, briefs_dir)
        assert len(adapter.calls) == 1  # synthesis only, no journal turn

    async def test_journal_enabled_none_runs_both_turns(self, briefs_dir: Path) -> None:
        adapter = CountingAdapter()
        await _run(_config(journal_enabled=None), adapter, briefs_dir)
        assert len(adapter.calls) == 2  # synthesis + journal (default-on)

    async def test_journal_enabled_true_runs_both_turns(self, briefs_dir: Path) -> None:
        adapter = CountingAdapter()
        await _run(_config(journal_enabled=True), adapter, briefs_dir)
        assert len(adapter.calls) == 2

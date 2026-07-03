"""Primary-brief selection (spec 0001 §9 / ADR-0005).

Exercises the pure ``_resolve_briefs`` helper against a tmp brief tree. The
briefs are placed under a ``batch``-layout run (``outputs_root`` redirected to
tmp), which also confirms §11's layout-aware discovery resolves correctly.
Default keeps the Claude brief primary; an ``openrouter:<subslug>`` spec
promotes that brief and demotes the rest — including Claude when present.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mantis_research.core.paths import RunDirs
from mantis_research.interface.stages import synthesis as syn

if TYPE_CHECKING:
    from pathlib import Path

_DIRS = RunDirs(layout='batch', batch_name='b')


@pytest.fixture
def brief_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    # Under batch layout, RunDirs.output(stage) == outputs_root()/b/stage.
    monkeypatch.setattr('mantis_research.core.paths.outputs_root', lambda: tmp_path)
    return tmp_path / 'b'


def _write(path: Path, text: str = 'brief') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


class TestDefaultClaudePrimary:
    def test_none_spec_uses_claude_primary(self, brief_root: Path) -> None:
        _write(brief_root / 'claude' / '01-t.md')
        _write(brief_root / 'gemini' / '01-t.md')
        briefs = syn._resolve_briefs(_DIRS, '1', 't', None)
        assert briefs.primary_label == 'claude'
        assert briefs.primary_path == brief_root / 'claude' / '01-t.md'
        assert ('gemini', brief_root / 'gemini' / '01-t.md') in briefs.secondaries

    def test_explicit_claude_spec_matches_default(self, brief_root: Path) -> None:
        _write(brief_root / 'claude' / '01-t.md')
        _write(brief_root / 'openrouter' / '01-t' / 'gpt.md')
        briefs = syn._resolve_briefs(_DIRS, '1', 't', 'claude')
        assert briefs.primary_label == 'claude'
        assert briefs.primary_path == brief_root / 'claude' / '01-t.md'


class TestOpenRouterPrimary:
    def test_openrouter_subslug_promoted_claude_demoted(self, brief_root: Path) -> None:
        _write(brief_root / 'claude' / '01-t.md')
        _write(brief_root / 'openrouter' / '01-t' / 'gpt-5-exa.md')
        _write(brief_root / 'openrouter' / '01-t' / 'deepseek.md')
        briefs = syn._resolve_briefs(_DIRS, '1', 't', 'openrouter:gpt-5-exa')
        assert briefs.primary_label == 'openrouter:gpt-5-exa'
        assert briefs.primary_path == brief_root / 'openrouter' / '01-t' / 'gpt-5-exa.md'
        sec_paths = {p for _, p in briefs.secondaries}
        assert brief_root / 'claude' / '01-t.md' in sec_paths
        assert brief_root / 'openrouter' / '01-t' / 'deepseek.md' in sec_paths
        assert briefs.primary_path not in sec_paths

    def test_path_b_no_claude_brief_still_resolves(self, brief_root: Path) -> None:
        _write(brief_root / 'openrouter' / '01-t' / 'gpt-5-exa.md')
        _write(brief_root / 'openrouter' / '01-t' / 'sonar.md')
        briefs = syn._resolve_briefs(_DIRS, '1', 't', 'openrouter:gpt-5-exa')
        assert briefs.primary_path is not None
        assert briefs.primary_path.exists()
        assert briefs.secondaries  # sonar remains a secondary
        assert all(label != 'claude' for label, _ in briefs.secondaries)

    def test_missing_openrouter_primary_is_none(self, brief_root: Path) -> None:
        _write(brief_root / 'openrouter' / '01-t' / 'sonar.md')
        briefs = syn._resolve_briefs(_DIRS, '1', 't', 'openrouter:not-there')
        assert briefs.primary_path is None  # upstream_ready will block

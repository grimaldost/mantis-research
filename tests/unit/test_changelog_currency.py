"""Changelog-currency gate tests — the gate must be provably able to fail.

The gate script lives under ``scripts/`` (not an importable package), so it is
loaded from its file path, same as the core-purity gate's tests.
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

from mantis_research.core.paths import project_root

if TYPE_CHECKING:
    from types import ModuleType


def _load_gate() -> ModuleType:
    path = project_root() / 'scripts' / 'changelog_currency.py'
    spec = importlib.util.spec_from_file_location('changelog_currency', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestChangelogCurrency:
    def test_source_change_without_changelog_is_unrecorded(self) -> None:
        # The red proof: the gate can actually fail.
        gate = _load_gate()
        changed = ['src/mantis_research/core/state.py', 'README.md']
        assert gate.unrecorded_source_paths(changed) == ['src/mantis_research/core/state.py']

    def test_scripts_count_as_source(self) -> None:
        gate = _load_gate()
        assert gate.unrecorded_source_paths(['scripts/check_core_purity.py'])

    def test_changelog_edit_records_the_change(self) -> None:
        gate = _load_gate()
        changed = ['src/mantis_research/core/state.py', 'CHANGELOG.md']
        assert gate.unrecorded_source_paths(changed) == []

    def test_declaration_trailer_covers_the_change(self) -> None:
        gate = _load_gate()
        messages = 'chore: tidy imports\n\nChangelog: none (no user-visible behavior change)\n'
        changed = ['src/mantis_research/core/state.py']
        assert gate.unrecorded_source_paths(changed, messages) == []

    def test_declaration_requires_a_reason(self) -> None:
        gate = _load_gate()
        messages = 'chore: tidy imports\n\nChangelog: none\n'
        changed = ['src/mantis_research/core/state.py']
        assert gate.unrecorded_source_paths(changed, messages) == changed

    def test_windows_path_separators_are_normalized(self) -> None:
        gate = _load_gate()
        changed = ['src\\mantis_research\\core\\state.py']
        assert gate.unrecorded_source_paths(changed) == ['src/mantis_research/core/state.py']

    def test_docs_only_change_passes(self) -> None:
        gate = _load_gate()
        assert gate.unrecorded_source_paths(['docs/architecture.md', 'README.md']) == []

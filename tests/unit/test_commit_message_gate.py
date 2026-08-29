"""Commit-message attribution gate tests — the gate must be provably able to fail.

The gate script lives under ``scripts/`` (not an importable package), so it is
loaded from its file path, same as the other gates. The AI-name strings below
are adversarial fixtures for the gate, not attributions.
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

from mantis_research.core.paths import project_root

if TYPE_CHECKING:
    from types import ModuleType


def _load_gate() -> ModuleType:
    path = project_root() / 'scripts' / 'check_commit_message.py'
    spec = importlib.util.spec_from_file_location('check_commit_message', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAttributionLines:
    def test_co_authored_by_trailer_is_rejected(self) -> None:
        # The red proof for the trailer arm.
        gate = _load_gate()
        trailer = 'Co-Authored-By: Claude <noreply@anthropic.com>'
        message = f'feat: add a thing\n\n{trailer}\n'
        assert gate.attribution_lines(message) == [trailer]

    def test_standalone_generated_with_line_is_rejected(self) -> None:
        # The red proof for the standalone arm — no trailer syntax involved.
        gate = _load_gate()
        message = 'feat: add a thing\n\nGenerated with Claude Code\n'
        assert gate.attribution_lines(message) == ['Generated with Claude Code']

    def test_generated_with_link_form_is_rejected(self) -> None:
        gate = _load_gate()
        line = 'Generated with [Claude Code](https://claude.com/claude-code)'
        message = f'feat: add a thing\n\n{line}\n'
        assert gate.attribution_lines(message) == [line]

    def test_normal_message_passes(self) -> None:
        # Mentioning the claude CLI as subject matter is not attribution.
        gate = _load_gate()
        message = 'fix(adapter): retry the claude CLI on rate limit\n\nThe adapter now waits.\n'
        assert gate.attribution_lines(message) == []

    def test_human_co_author_passes(self) -> None:
        gate = _load_gate()
        message = 'feat: add a thing\n\nCo-Authored-By: Ada Lovelace <ada@example.com>\n'
        assert gate.attribution_lines(message) == []

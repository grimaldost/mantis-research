"""Agent-serving docs consistency (spec 0002 §6)."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_research_skill_documents_tool_and_tiers() -> None:
    skill = (_ROOT / 'skills' / 'research' / 'SKILL.md').read_text(encoding='utf-8')
    assert 'research' in skill
    for tier in ('fast', 'standard', 'high'):
        assert tier in skill


def test_claude_md_has_mcp_plugin_section() -> None:
    claude_md = (_ROOT / 'CLAUDE.md').read_text(encoding='utf-8')
    assert 'Serving agents (MCP server + plugin)' in claude_md


def test_review_checklist_has_mcp_contract_item() -> None:
    checklist = (_ROOT / 'docs' / 'method' / 'review-checklist.md').read_text(encoding='utf-8')
    assert 'MCP tool-contract additivity' in checklist


def test_changelog_has_distinct_agent_serving_grouping() -> None:
    changelog = (_ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    assert 'agent-serving' in changelog.lower()
    assert '0002-agent-serving-mcp-plugin' in changelog

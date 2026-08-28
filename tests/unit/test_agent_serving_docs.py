"""Agent-serving docs consistency (spec 0002 §6)."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_research_skill_documents_tool_and_tiers() -> None:
    skill = (_ROOT / 'skills' / 'research' / 'SKILL.md').read_text(encoding='utf-8')
    assert 'research' in skill
    for tier in ('fast', 'standard', 'high'):
        assert tier in skill


def test_skill_names_fast_as_the_default_tier() -> None:
    # MANT-B04: the skill is the surface a calling agent actually meets, so the
    # default has to be stated there, not only in the schema.
    skill = (_ROOT / 'skills' / 'research' / 'SKILL.md').read_text(encoding='utf-8')
    assert '`fast` (default)' in skill
    assert '`standard` (default)' not in skill


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


def _skill() -> str:
    return (Path(__file__).resolve().parents[2] / 'skills' / 'research' / 'SKILL.md').read_text(
        encoding='utf-8'
    )


class TestTheSkillDoesNotOverstateLiveness:
    """MANT-B64 — prose and code cite the same number.

    The section shipped in 0.2.0 told an agent that "a silent minute means
    something is wrong; silence is no longer the normal case". Both halves were
    false: a local-seat stage was silent for up to its whole idle window by
    construction, and the seat wait reached no caller at all. This is the second
    rewrite of the same paragraph in two releases, so the claim now has a test
    rather than a third rewrite.
    """

    def test_the_retired_claim_is_gone(self) -> None:
        skill = _skill()
        assert 'silence is no longer the normal case' not in skill
        assert 'A silent minute means something is wrong' not in skill

    def test_the_skill_says_silence_is_normal(self) -> None:
        # Absence alone would stay green if the paragraph were simply deleted.
        assert 'silent while the model thinks' in _skill()

    def test_the_quoted_cadence_is_the_one_the_code_emits(self) -> None:
        from mantis_research.interface.adapters._subprocess import ANNOUNCE_EVERY_S

        assert f'{int(ANNOUNCE_EVERY_S)} s of silence' in _skill()

    def test_the_stale_cost_band_is_gone(self) -> None:
        assert '6** on the default substrate set' not in _skill()

    def test_the_skill_teaches_the_detached_shape(self) -> None:
        skill = _skill()
        assert 'detach: true' in skill
        assert 'research_status' in skill

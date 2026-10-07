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

    def test_the_quoted_seat_sample_is_the_one_the_code_reads(self) -> None:
        from mantis_research.interface.research_service import SEAT_SAMPLE_RUNS

        assert f'the {SEAT_SAMPLE_RUNS} most recent finished runs' in _skill()


def _latency_bullet() -> str:
    skill = _skill()
    start = skill.index('- **Latency:**')
    end = skill.index('\n\n', start)
    return ' '.join(skill[start:end].split())


def _turns_per_tier() -> dict[str, int]:
    """Local-seat turns per tier, derived from the tier registry.

    ``synthesis`` is two turns: the synthesis itself and the sidecar turn that
    follows it inside the same stage.
    """
    from mantis_research.interface.research_service import _TIER_STAGES, LOCAL_SEAT_STAGES

    return {
        tier: sum(
            2 if stage == 'synthesis' else 1 for stage in stages if stage in LOCAL_SEAT_STAGES
        )
        for tier, stages in _TIER_STAGES.items()
    }


class TestTheLatencyBulletCountsTurnsAndNamesTheQueue:
    """T26a/T26b — the Latency bullet's turn counts and queue clause match the code."""

    def test_the_derived_counts_are_the_ones_the_review_measured(self) -> None:
        assert _turns_per_tier() == {'research': 0, 'fast': 2, 'standard': 3, 'high': 5}

    def test_the_bullet_states_the_derived_turn_counts(self) -> None:
        counts = _turns_per_tier()
        sentence = ', '.join(f'`{tier}` {n}' for tier, n in counts.items())
        assert sentence in _latency_bullet()

    def test_the_bullet_adds_one_turn_for_the_journal(self) -> None:
        assert 'plus 1 when journal is on' in _latency_bullet()

    def test_the_retired_count_sentence_is_gone(self) -> None:
        assert '`fast` adds one such turn' not in _skill()

    def test_the_bullet_names_the_seat_queue(self) -> None:
        assert 'one seat lock' in _latency_bullet()

    def test_the_bullet_does_not_claim_the_sidecar_turn_takes_the_lock(self) -> None:
        bullet = _latency_bullet()
        assert 'sidecar turn currently does not' in bullet

    def test_the_bullet_cites_the_constants_the_code_exports(self) -> None:
        from mantis_research.interface.research_service import (
            LOCAL_SEAT_TURN_MEDIAN_MINUTES,
            RESEARCH_STAGE_MINUTES,
        )

        lo, hi = RESEARCH_STAGE_MINUTES
        bullet = _latency_bullet()
        assert f'{lo}{chr(0x2013)}{hi} min' in bullet
        assert f'{LOCAL_SEAT_TURN_MEDIAN_MINUTES} min' in bullet

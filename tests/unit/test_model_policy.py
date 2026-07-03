"""Unit tests for the auto-latest model policy (core.model_policy)."""

from __future__ import annotations

import pytest

from mantis_research.core import model_policy as mp

# A tiny synthetic catalog covering the shapes that trip up a naive
# max(created) picker: a flagship, a newer non-frontier tier, an image model,
# and an off-vendor entry.
_CATALOG: list[dict[str, object]] = [
    {'id': 'openai/gpt-5.4', 'created': 100},
    {'id': 'openai/gpt-5.5', 'created': 200},
    {'id': 'openai/gpt-5.5-pro', 'created': 210},
    {'id': 'openai/gpt-5.5-mini', 'created': 300},  # newer, but demoted tier
    {'id': 'openai/gpt-chat-latest', 'created': 999},  # newest, but a chat alias
    {'id': 'google/gemini-3.1-pro-preview', 'created': 150},
    {'id': 'google/gemini-3.5-flash', 'created': 400},  # newer, flash → demoted
    {'id': 'google/gemini-3.1-flash-image', 'created': 500},  # image → demoted
    {'id': 'deepseek/deepseek-v4-pro', 'created': 120},
    {'id': 'someone-else/model-x', 'created': 9999},
]


class TestIsAuto:
    @pytest.mark.parametrize(
        'value', [None, '', 'auto', 'latest', 'AUTO', ' Latest ', 'auto:openai']
    )
    def test_auto_values(self, value: str | None) -> None:
        assert mp.is_auto(value) is True

    @pytest.mark.parametrize(
        'value', ['openai/gpt-5', 'claude-opus-4-8', 'google/gemini-3.1-pro-preview']
    )
    def test_explicit_ids_are_not_auto(self, value: str) -> None:
        assert mp.is_auto(value) is False


class TestParseAutoVendor:
    def test_qualified_sentinel(self) -> None:
        assert mp.parse_auto_vendor('auto:openai') == 'openai'
        assert mp.parse_auto_vendor('LATEST:Google') == 'google'

    @pytest.mark.parametrize('value', [None, 'auto', 'latest', 'openai/gpt-5', 'claude-opus-4-8'])
    def test_no_vendor_encoded(self, value: str | None) -> None:
        assert mp.parse_auto_vendor(value) is None


class TestResolveClaudeModel:
    def test_auto_resolves_to_latest_alias(self) -> None:
        assert mp.resolve_claude_model('auto') == mp.CLAUDE_LATEST_ALIAS == 'opus'
        assert mp.resolve_claude_model(None) == 'opus'
        assert mp.resolve_claude_model('') == 'opus'

    def test_explicit_pin_passes_through(self) -> None:
        assert mp.resolve_claude_model('claude-opus-4-8') == 'claude-opus-4-8'
        assert mp.resolve_claude_model('sonnet') == 'sonnet'  # an alias is a valid explicit value


class TestSelectOpenRouterFrontier:
    def test_picks_flagship_not_newest(self) -> None:
        # gpt-chat-latest (999) and gpt-5.5-mini (300) are newer but demoted;
        # gpt-5.5-pro (210) is the newest qualifying flagship.
        assert mp.select_openrouter_frontier('openai', _CATALOG) == 'openai/gpt-5.5-pro'

    def test_demotes_flash_and_image(self) -> None:
        assert mp.select_openrouter_frontier('google', _CATALOG) == 'google/gemini-3.1-pro-preview'

    def test_single_qualifier(self) -> None:
        assert mp.select_openrouter_frontier('deepseek', _CATALOG) == 'deepseek/deepseek-v4-pro'

    def test_unknown_vendor_returns_none(self) -> None:
        assert mp.select_openrouter_frontier('acme', _CATALOG) is None

    def test_no_qualifier_returns_none(self) -> None:
        # qwen is a known vendor but absent from this catalog.
        assert mp.select_openrouter_frontier('qwen', _CATALOG) is None

    def test_handles_string_created_timestamps(self) -> None:
        catalog = [
            {'id': 'openai/gpt-5.5', 'created': '200'},
            {'id': 'openai/gpt-5.5-pro', 'created': '210'},
        ]
        assert mp.select_openrouter_frontier('openai', catalog) == 'openai/gpt-5.5-pro'


class TestPinnedFallbacks:
    def test_every_vendor_has_a_self_consistent_pin(self) -> None:
        # Each pinned id must start with its own vendor prefix.
        for vendor, spec in mp.OPENROUTER_FRONTIER.items():
            assert spec.pinned.startswith(f'{vendor}/'), (vendor, spec.pinned)

    def test_pinned_lookup(self) -> None:
        assert mp.pinned_openrouter_frontier('openai') == 'openai/gpt-5.5-pro'
        assert mp.pinned_openrouter_frontier('acme') is None


class TestResolveOpenRouterModel:
    def test_explicit_pin_passes_through(self) -> None:
        r = mp.resolve_openrouter_model('openai/gpt-5', catalog=_CATALOG)
        assert r.source == 'pin'
        assert r.model_id == 'openai/gpt-5'

    def test_auto_qualified_uses_live_catalog(self) -> None:
        r = mp.resolve_openrouter_model('auto:openai', catalog=_CATALOG)
        assert r.source == 'live'
        assert r.model_id == 'openai/gpt-5.5-pro'

    def test_auto_with_vendor_hint(self) -> None:
        r = mp.resolve_openrouter_model('auto', catalog=_CATALOG, vendor_hint='google')
        assert r.source == 'live'
        assert r.model_id == 'google/gemini-3.1-pro-preview'

    def test_offline_falls_back_to_pin(self) -> None:
        # catalog=None simulates the offline path — must never raise.
        r = mp.resolve_openrouter_model('auto:deepseek', catalog=None)
        assert r.source == 'fallback'
        assert r.model_id == 'deepseek/deepseek-v4-pro'

    def test_live_catalog_without_qualifier_falls_back_to_pin(self) -> None:
        # qwen is known but absent from this catalog → pinned fallback, not None.
        r = mp.resolve_openrouter_model('auto:qwen', catalog=_CATALOG)
        assert r.source == 'fallback'
        assert r.model_id == 'qwen/qwen3.7-max'

    def test_auto_without_vendor_is_unresolved(self) -> None:
        r = mp.resolve_openrouter_model('auto', catalog=_CATALOG)
        assert r.source == 'unresolved'
        assert r.model_id is None
        assert r.notes  # carries an actionable message

    def test_auto_unknown_vendor_is_unresolved(self) -> None:
        r = mp.resolve_openrouter_model('auto:acme', catalog=_CATALOG)
        assert r.source == 'unresolved'
        assert r.model_id is None

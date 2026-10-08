"""Which web-search index each research substrate reads (ADR-0012)."""

from __future__ import annotations

import pytest

from mantis_research.core.search_engines import (
    ENGINE_POOL,
    NATIVE_SEARCH_VENDORS,
    assign_search_engines,
)


def _indexes(vendors: list[str]) -> list[str]:
    """The index each vendor reads: its own when native, else the engine's."""
    assignment = assign_search_engines(vendors)
    return [v if assignment.engines[v] == 'native' else assignment.engines[v] for v in vendors]


class TestDefaults:
    def test_default_substrates_read_three_distinct_indexes(self) -> None:
        assert len(set(_indexes(['openai', 'deepseek', 'google']))) == 3

    def test_default_assignment(self) -> None:
        assignment = assign_search_engines(['openai', 'deepseek', 'google'])
        assert assignment.engines == {
            'openai': 'native',
            'deepseek': 'parallel',
            'google': 'native',
        }
        assert assignment.shared == ()

    def test_google_is_native_and_deepseek_is_not_exa(self) -> None:
        assignment = assign_search_engines(['deepseek', 'google'])
        assert 'google' in NATIVE_SEARCH_VENDORS
        assert assignment.engines['google'] == 'native'
        assert assignment.engines['deepseek'] != 'exa'


class TestPool:
    def test_non_native_vendors_take_the_pool_in_order(self) -> None:
        assignment = assign_search_engines(['deepseek', 'qwen', 'openai'])
        assert assignment.engines == {'deepseek': 'parallel', 'qwen': 'exa', 'openai': 'native'}

    def test_pool_order_is_parallel_exa_perplexity(self) -> None:
        assert ENGINE_POOL == ('parallel', 'exa', 'perplexity')

    def test_perplexity_vendor_blocks_the_perplexity_engine(self) -> None:
        # The perplexity vendor reads Perplexity's index natively, so the
        # 'perplexity' engine would read the same one a second time.
        assignment = assign_search_engines(['perplexity', 'deepseek', 'qwen', 'mistral'])
        assert assignment.engines['perplexity'] == 'native'
        assert assignment.engines['deepseek'] == 'parallel'
        assert assignment.engines['qwen'] == 'exa'
        # The pool has run out for the third non-native vendor: it wraps.
        assert assignment.engines['mistral'] == 'parallel'
        assert 'perplexity' not in {e for v, e in assignment.engines.items() if v != 'perplexity'}

    def test_three_distinct_indexes_up_to_the_pool_size(self) -> None:
        assert len(set(_indexes(['deepseek', 'qwen', 'mistral']))) == 3

    def test_every_native_vendor_is_native(self) -> None:
        vendors = sorted(NATIVE_SEARCH_VENDORS)
        assignment = assign_search_engines(vendors)
        assert set(assignment.engines.values()) == {'native'}
        assert assignment.shared == ()

    def test_known_native_set(self) -> None:
        assert {'openai', 'perplexity', 'anthropic', 'x-ai', 'google'} == NATIVE_SEARCH_VENDORS


class TestSharedIndexes:
    def test_exhausted_pool_wraps_and_names_who_shares(self) -> None:
        assignment = assign_search_engines(['deepseek', 'qwen', 'mistral', 'llama'])
        assert assignment.engines == {
            'deepseek': 'parallel',
            'qwen': 'exa',
            'mistral': 'perplexity',
            'llama': 'parallel',
        }
        assert assignment.shared == (('deepseek', 'llama'),)

    def test_perplexity_vendor_shrinks_the_pool(self) -> None:
        assignment = assign_search_engines(['perplexity', 'deepseek', 'qwen', 'mistral'])
        assert assignment.shared == (('deepseek', 'mistral'),)

    def test_no_sharing_when_every_index_differs(self) -> None:
        assert assign_search_engines(['openai', 'google', 'deepseek', 'qwen']).shared == ()

    def test_duplicate_vendor_is_assigned_once(self) -> None:
        assignment = assign_search_engines(['deepseek', 'deepseek'])
        assert assignment.engines == {'deepseek': 'parallel'}
        assert assignment.shared == ()

    def test_empty_input(self) -> None:
        assignment = assign_search_engines([])
        assert assignment.engines == {}
        assert assignment.shared == ()


@pytest.mark.parametrize('vendor', ['openai', 'google', 'anthropic', 'x-ai', 'perplexity'])
def test_native_vendors_never_take_an_engine(vendor: str) -> None:
    assert assign_search_engines([vendor]).engines == {vendor: 'native'}

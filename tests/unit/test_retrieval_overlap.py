"""Cited-URL overlap between research briefs (T5e).

On 2026-09-27 two of three briefs cited the same five URLs and none of the third
brief's ten, so "two of three agree" was one retrieval pool against another. The
synthesis prompt spoke only of shared training substrate, and the synthesizer
found the overlap by counting links by hand. The runner now measures it before
the synthesis turn and prints it in the independence note.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mantis_research.core.retrieval_overlap import (
    extract_urls,
    normalize_reference,
    pairwise_jaccard,
    render_overlap,
)


class TestExtractUrls:
    def test_an_inline_link_is_read(self) -> None:
        assert extract_urls('See [the spec](https://example.org/spec).') == {'example.org/spec'}

    def test_an_angle_autolink_is_read(self) -> None:
        assert extract_urls('Source: <https://example.org/spec>') == {'example.org/spec'}

    def test_a_reference_definition_is_read(self) -> None:
        text = 'As [the spec][1] says.\n\n[1]: https://example.org/spec "Spec"\n'
        assert extract_urls(text) == {'example.org/spec'}

    def test_link_text_in_brackets_is_read(self) -> None:
        # The shape one substrate emits: the domain in brackets as the link text.
        text = 'a claim [[medium.com]](https://medium.com/@someone/a-post).'
        assert extract_urls(text) == {'medium.com/@someone/a-post'}

    def test_a_link_with_a_title_is_read(self) -> None:
        assert extract_urls('[x](https://example.org/a "A title")') == {'example.org/a'}

    def test_balanced_parentheses_stay_in_the_url(self) -> None:
        text = '[x](https://en.wikipedia.org/wiki/Jaccard_(disambiguation))'
        assert extract_urls(text) == {'en.wikipedia.org/wiki/jaccard_(disambiguation)'}

    def test_query_string_and_fragment_are_ignored(self) -> None:
        text = (
            '[a](https://example.org/doc?utm_source=chatgpt.com) '
            '[b](https://example.org/doc#section-2) '
            '[c](https://example.org/doc?x=1#y)'
        )
        assert extract_urls(text) == {'example.org/doc'}

    def test_scheme_www_and_trailing_slash_are_folded(self) -> None:
        text = '[a](http://example.org/doc) [b](https://www.example.org/doc/) <https://Example.org/doc>'
        assert extract_urls(text) == {'example.org/doc'}

    def test_non_web_targets_are_not_citations(self) -> None:
        text = '[top](#intro) [file](./notes.md) [mail](mailto:a@example.org) [x](ftp://h/f)'
        assert extract_urls(text) == frozenset()

    def test_a_bare_url_in_prose_is_not_a_link(self) -> None:
        assert extract_urls('mentioned https://example.org/doc in passing') == frozenset()

    def test_no_links_gives_the_empty_set(self) -> None:
        assert extract_urls('') == frozenset()


class TestNormalizeReference:
    def test_is_the_key_the_sidecar_merges_citations_on(self) -> None:
        from mantis_research.core import sidecar

        assert sidecar.normalize_reference is normalize_reference

    @pytest.mark.parametrize(
        'spelling',
        ['https://www.bcb.gov.br/a/', 'http://bcb.gov.br/a', ' HTTPS://BCB.GOV.BR/A '],
    )
    def test_folds_scheme_www_case_and_trailing_slash(self, spelling: str) -> None:
        assert normalize_reference(spelling) == 'bcb.gov.br/a'


def _brief(urls: list[str]) -> str:
    return '\n'.join(f'- claim {i} [src]({url})' for i, url in enumerate(urls))


class TestPairwiseJaccard:
    def test_the_2026_09_27_shape(self) -> None:
        # Two briefs cite an identical set of five URLs; the third cites ten
        # others. Agreement between the first two is one retrieval pool.
        shared = [f'https://pool.example/{i}' for i in range(5)]
        other = [f'https://elsewhere.example/{i}' for i in range(10)]
        by_label = [
            ('openrouter:deepseek', extract_urls(_brief(shared))),
            ('openrouter:google', extract_urls(_brief(list(reversed(shared))))),
            ('openrouter:openai', extract_urls(_brief(other))),
        ]
        assert pairwise_jaccard(by_label) == [
            ('openrouter:deepseek', 'openrouter:google', 1.0),
            ('openrouter:deepseek', 'openrouter:openai', 0.0),
            ('openrouter:google', 'openrouter:openai', 0.0),
        ]

    def test_partial_overlap(self) -> None:
        pairs = pairwise_jaccard([('a', {'x', 'y', 'z'}), ('b', {'y', 'z', 'w'})])
        assert pairs == [('a', 'b', 0.5)]

    def test_two_empty_sets_are_zero(self) -> None:
        assert pairwise_jaccard([('a', set()), ('b', set())]) == [('a', 'b', 0.0)]

    def test_fewer_than_two_briefs_give_no_pair(self) -> None:
        assert pairwise_jaccard([('a', {'x'})]) == []
        assert pairwise_jaccard([]) == []

    def test_a_repeated_label_keeps_both_briefs(self) -> None:
        pairs = pairwise_jaccard([('gemini', {'x'}), ('gemini', {'x'})])
        assert pairs == [('gemini', 'gemini', 1.0)]


_URLS = st.frozensets(st.sampled_from([f'u{i}' for i in range(16)]), max_size=6)


# The helper is pure and fast, so a deadline or a too-slow check here would
# measure how loaded the machine is, not the code.
_TIMING_FREE = settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])


class TestJaccardProperties:
    @_TIMING_FREE
    @given(_URLS, _URLS)
    def test_symmetric(self, a: frozenset[str], b: frozenset[str]) -> None:
        [(_, _, ab)] = pairwise_jaccard([('a', a), ('b', b)])
        [(_, _, ba)] = pairwise_jaccard([('b', b), ('a', a)])
        assert ab == ba

    @_TIMING_FREE
    @given(_URLS, _URLS)
    def test_bounded(self, a: frozenset[str], b: frozenset[str]) -> None:
        [(_, _, score)] = pairwise_jaccard([('a', a), ('b', b)])
        assert 0.0 <= score <= 1.0

    @_TIMING_FREE
    @given(_URLS.filter(bool))
    def test_identical_non_empty_sets_are_one(self, a: frozenset[str]) -> None:
        assert pairwise_jaccard([('a', a), ('b', set(a))]) == [('a', 'b', 1.0)]

    @_TIMING_FREE
    @given(_URLS, _URLS)
    def test_disjoint_sets_are_zero(self, a: frozenset[str], b: frozenset[str]) -> None:
        assert pairwise_jaccard([('a', a), ('b', b - a)]) == [('a', 'b', 0.0)]

    @_TIMING_FREE
    @given(st.lists(_URLS, max_size=5))
    def test_one_entry_per_pair_in_brief_order(self, sets: list[frozenset[str]]) -> None:
        labels = [f'b{i}' for i in range(len(sets))]
        pairs = pairwise_jaccard(list(zip(labels, sets, strict=True)))
        assert [(a, b) for a, b, _ in pairs] == [
            (labels[i], labels[j]) for i in range(len(labels)) for j in range(i + 1, len(labels))
        ]


class TestRenderOverlap:
    def test_one_line_with_each_pair_and_its_score(self) -> None:
        line = render_overlap(
            [
                ('openrouter:deepseek', 'openrouter:google', 1.0),
                ('openrouter:deepseek', 'openrouter:openai', 0.0),
                ('openrouter:google', 'openrouter:openai', 1 / 3),
            ]
        )
        assert line == (
            'openrouter:deepseek / openrouter:google 1.00; '
            'openrouter:deepseek / openrouter:openai 0.00; '
            'openrouter:google / openrouter:openai 0.33'
        )
        assert '\n' not in line

    def test_no_pairs_says_so(self) -> None:
        assert render_overlap([]) == 'no pair of briefs to compare'

"""Search citations that arrive as response annotations, not as links in the text.

Field evidence, 2026-10-08: Google's native search returned 11 ``url_citation``
annotations and no link in the message text, so the google brief reached every
consumer with no sources. These tests pin the pure half of the fix: reading the
annotations, recognising Google's grounding redirects, and rendering the
citations a brief does not already link.
"""

from __future__ import annotations

from typing import Any

from mantis_research.core.citations import (
    Citation,
    is_grounding_redirect,
    sources_section,
    url_citations,
)
from mantis_research.core.retrieval_overlap import extract_urls

_REDIRECT = 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQF-token=='


def _annotation(url: Any, title: Any = 'A title', **extra: Any) -> dict[str, Any]:
    return {'type': 'url_citation', 'url_citation': {'url': url, 'title': title, **extra}}


class TestUrlCitations:
    def test_reads_url_citation_annotations_in_order(self) -> None:
        message = {
            'content': 'text',
            'annotations': [
                _annotation('https://a.example/one', 'One', start_index=0, end_index=4),
                _annotation('https://b.example/two', 'Two', content='snippet'),
            ],
        }
        assert url_citations(message) == (
            Citation(url='https://a.example/one', title='One'),
            Citation(url='https://b.example/two', title='Two'),
        )

    def test_no_annotations_is_empty(self) -> None:
        assert url_citations({'content': 'text'}) == ()
        assert url_citations({'content': 'text', 'annotations': None}) == ()
        assert url_citations({'content': 'text', 'annotations': []}) == ()

    def test_skips_malformed_entries(self) -> None:
        message = {
            'annotations': [
                'not a dict',
                {'type': 'file_citation', 'file_citation': {'url': 'https://x.example'}},
                {'type': 'url_citation'},
                {'type': 'url_citation', 'url_citation': 'https://x.example'},
                _annotation(None),
                _annotation(''),
                _annotation('ftp://files.example/a'),
                _annotation('not a url'),
                _annotation('https://kept.example/page', title=None),
            ]
        }
        assert url_citations(message) == (Citation(url='https://kept.example/page', title=''),)

    def test_annotations_that_are_not_a_list_are_ignored(self) -> None:
        assert url_citations({'annotations': {'type': 'url_citation'}}) == ()

    def test_dedupes_by_the_extract_urls_key_keeping_the_first(self) -> None:
        message = {
            'annotations': [
                _annotation('https://www.a.example/page/?utm_source=openai', 'First'),
                _annotation('http://a.example/page#section', 'Second'),
                _annotation('https://b.example/', 'Third'),
                _annotation('https://a.example/page', 'Fourth'),
            ]
        }
        assert url_citations(message) == (
            Citation(url='https://www.a.example/page/?utm_source=openai', title='First'),
            Citation(url='https://b.example/', title='Third'),
        )


class TestIsGroundingRedirect:
    def test_google_grounding_redirect(self) -> None:
        assert is_grounding_redirect(_REDIRECT)
        assert is_grounding_redirect(
            'http://VertexAISearch.cloud.google.com/grounding-api-redirect/x'
        )

    def test_other_urls_are_not(self) -> None:
        assert not is_grounding_redirect('https://vertexaisearch.cloud.google.com/other/x')
        assert not is_grounding_redirect('https://example.com/grounding-api-redirect/x')
        assert not is_grounding_redirect(
            'https://evil.example/vertexaisearch.cloud.google.com/grounding-api-redirect/x'
        )
        assert not is_grounding_redirect(
            'ftp://vertexaisearch.cloud.google.com/grounding-api-redirect/x'
        )
        assert not is_grounding_redirect('not a url')


class TestSourcesSection:
    def test_lists_citations_the_brief_does_not_link(self) -> None:
        citations = (
            Citation(url='https://a.example/one', title='One'),
            Citation(url='https://b.example/two', title='Two'),
        )
        section = sources_section(citations, 'A brief with no links.')
        assert section == (
            '\n\n## Sources\n\n- [One](https://a.example/one)\n- [Two](https://b.example/two)\n'
        )
        assert extract_urls(section) == {'a.example/one', 'b.example/two'}

    def test_nothing_to_add_when_every_citation_is_linked(self) -> None:
        citations = (Citation(url='https://a.example/one?utm_source=openai', title='One'),)
        brief = 'As [the study](https://www.a.example/one/) shows.'
        assert sources_section(citations, brief) == ''

    def test_nothing_to_add_without_citations(self) -> None:
        assert sources_section((), 'A brief.') == ''

    def test_only_the_unlinked_citations_are_added(self) -> None:
        citations = (
            Citation(url='https://a.example/one', title='One'),
            Citation(url='https://b.example/two', title='Two'),
        )
        brief = 'See [one](https://a.example/one).'
        assert sources_section(citations, brief) == (
            '\n\n## Sources\n\n- [Two](https://b.example/two)\n'
        )

    def test_title_falls_back_to_the_host(self) -> None:
        citations = (Citation(url='https://www.jfrog.com/blog/post', title='  '),)
        assert sources_section(citations, '') == (
            '\n\n## Sources\n\n- [www.jfrog.com](https://www.jfrog.com/blog/post)\n'
        )

    def test_two_citations_for_one_source_are_listed_once(self) -> None:
        # Two Google redirects can resolve to the same page.
        citations = (
            Citation(url='https://a.example/one', title='One'),
            Citation(url='https://a.example/one/', title='One again'),
        )
        assert sources_section(citations, '') == (
            '\n\n## Sources\n\n- [One](https://a.example/one)\n'
        )

    def test_brackets_and_newlines_in_a_title_do_not_break_the_link(self) -> None:
        citations = (Citation(url='https://a.example/one', title='[PDF] A\nreport]'),)
        section = sources_section(citations, '')
        assert '\n- [\\[PDF\\] A report\\]](https://a.example/one)\n' in section
        assert extract_urls(section) == {'a.example/one'}


class TestParenthesesInUrls:
    def test_unbalanced_parenthesis_is_percent_encoded(self) -> None:
        citations = (Citation(url='https://a.example/note_(draft', title='Note'),)
        section = sources_section(citations, '')
        assert '(https://a.example/note_%28draft)' in section
        assert extract_urls(section) == {'a.example/note_%28draft'}

    def test_unbalanced_closing_parenthesis_is_percent_encoded(self) -> None:
        citations = (Citation(url='https://a.example/note)', title='Note'),)
        section = sources_section(citations, '')
        assert extract_urls(section) == {'a.example/note%29'}

    def test_nested_parentheses_are_percent_encoded(self) -> None:
        citations = (Citation(url='https://a.example/f_(a_(b))', title='Nested'),)
        section = sources_section(citations, '')
        assert extract_urls(section) == {'a.example/f_%28a_%28b%29%29'}

    def test_a_balanced_parenthesis_keeps_the_key_the_brief_would_give(self) -> None:
        # Wikipedia-style titles are common; the link already parses, so the
        # section must not re-spell the URL and defeat de-duplication.
        url = 'https://en.wikipedia.org/wiki/Tit_(film)'
        section = sources_section((Citation(url=url, title='Tit'),), '')
        assert extract_urls(section) == {'en.wikipedia.org/wiki/tit_(film)'}
        brief = 'See [Tit](https://en.wikipedia.org/wiki/Tit_(film)).'
        assert sources_section((Citation(url=url, title='Tit'),), brief) == ''

    def test_an_encoded_url_is_not_listed_twice(self) -> None:
        citations = (
            Citation(url='https://a.example/note_(draft', title='One'),
            Citation(url='https://a.example/note_(draft#frag', title='Two'),
        )
        section = sources_section(citations, '')
        assert section.count('\n- [') == 1

"""Search citations that a response carries as annotations rather than as links.

OpenRouter reports the pages a web search drew on as ``url_citation`` entries in
``choices[0].message.annotations``, for every engine. Most substrates also link
those pages in the text; Google's native search did not (2026-10-08: 11
annotations, no link in the text), so a brief built from the text alone reached
synthesis, the manifest's ``retrieval_overlap`` and readers with no sources.
Google's annotation URLs are also opaque grounding redirects whose title is only
the domain; the adapter resolves them to the real pages.

This module reads the annotations and renders the ones a brief does not already
link as a markdown ``Sources`` section, so every brief carries its sources the
same way. Pure (invariant I1): no I/O; the redirect lookup lives in the adapter.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from mantis_research.core.retrieval_overlap import extract_urls, source_key

if TYPE_CHECKING:
    from collections.abc import Iterable

_GROUNDING_HOST = 'vertexaisearch.cloud.google.com'
_GROUNDING_PATH = '/grounding-api-redirect/'
_WEB_SCHEMES = frozenset({'http', 'https'})
# Characters the link pattern in ``retrieval_overlap`` cannot carry in a URL.
_URL_ESCAPES = str.maketrans({' ': '%20', '<': '%3C', '>': '%3E', '\t': '%09', '\n': '%0A'})
_PAREN_ESCAPES = str.maketrans({'(': '%28', ')': '%29'})
# What the inline-link pattern accepts as a target: parentheses only as
# balanced, unnested pairs (``Tit_(film)``). Anything else ends the link early.
_CARRYABLE_TARGET = re.compile(r'(?:[^()\s<>]|\([^()\s<>]*\))+')


@dataclass(frozen=True, slots=True)
class Citation:
    """One page a web search cited: its URL and the title the provider gave it."""

    url: str
    title: str


def _web_host(url: str) -> str | None:
    """The host of an absolute ``http``/``https`` URL, or None for anything else."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in _WEB_SCHEMES or not parts.hostname:
        return None
    return parts.hostname


def url_citations(message: Mapping[str, Any]) -> tuple[Citation, ...]:
    """The ``url_citation`` annotations of a response message, one per source.

    Entries that are not a well-formed ``url_citation`` with an absolute
    ``http``/``https`` URL are skipped. Two citations of one source (same key as
    :func:`~mantis_research.core.retrieval_overlap.extract_urls` gives, so a
    tracking parameter or an anchor does not make another source) keep the
    first; order is otherwise preserved.
    """
    annotations = message.get('annotations')
    if not isinstance(annotations, list):
        return ()
    seen: set[str] = set()
    found: list[Citation] = []
    for entry in cast('list[object]', annotations):
        if not isinstance(entry, Mapping):
            continue
        annotation = cast('Mapping[str, Any]', entry)
        if annotation.get('type') != 'url_citation':
            continue
        body = annotation.get('url_citation')
        if not isinstance(body, Mapping):
            continue
        fields = cast('Mapping[str, Any]', body)
        url = fields.get('url')
        if not isinstance(url, str) or _web_host(url) is None:
            continue
        url = url.strip()
        key = source_key(url)
        if key in seen:
            continue
        seen.add(key)
        title = fields.get('title')
        found.append(Citation(url=url, title=title if isinstance(title, str) else ''))
    return tuple(found)


def is_grounding_redirect(url: str) -> bool:
    """True for Google's opaque grounding redirect, which answers with the real page."""
    host = _web_host(url)
    if host is None or host.lower() != _GROUNDING_HOST:
        return False
    return urlsplit(url.strip()).path.startswith(_GROUNDING_PATH)


def _link_text(citation: Citation) -> str:
    title = ' '.join(citation.title.split()) or _web_host(citation.url) or citation.url
    return title.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')


def _link_target(url: str) -> str:
    """The URL as it is written inside ``[title](...)`` so ``extract_urls`` reads all of it.

    A URL whose parentheses are balanced and unnested is left as it is (it is
    already read whole, and keeps the key a brief linking it would give); any
    other parenthesis is percent-encoded, as the pattern would stop at it.
    """
    target = url.translate(_URL_ESCAPES)
    if _CARRYABLE_TARGET.fullmatch(target):
        return target
    return target.translate(_PAREN_ESCAPES)


def sources_section(citations: Iterable[Citation], brief_text: str) -> str:
    """A markdown ``Sources`` section listing the citations the brief does not link.

    Returns ``''`` when there is nothing to add, so a brief whose text already
    links every cited page (or that has no citations) is left as it was. A
    citation counts as linked when :func:`extract_urls` finds its key in the
    brief; two citations with one key are listed once. The link text is the
    provider's title, or the URL's host when the title is empty.
    """
    seen = set(extract_urls(brief_text))
    lines: list[str] = []
    for citation in citations:
        target = _link_target(citation.url)
        key = source_key(target)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f'- [{_link_text(citation)}]({target})')
    if not lines:
        return ''
    return '\n\n## Sources\n\n' + '\n'.join(lines) + '\n'

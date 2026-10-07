"""Cited-URL overlap between research briefs.

Two briefs that cite the same URLs drew on one retrieval pool, so their
agreement is one source read twice, not independent confirmation. The synthesis
prompt's independence note used to speak only of shared training substrate; on
2026-09-27 two of three briefs cited an identical set of five URLs, disjoint
from the third brief's ten, and the synthesizer found that by counting links by
hand. This module measures it before the synthesis turn: the URLs each brief
links, folded to one key per source, and the Jaccard overlap of every pair.

Pure (invariant I1): string processing only. The synthesis stage reads the
briefs and renders the result into the prompt.
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Set as AbstractSet

# The target of an inline link, `[text](url)` or `[text](url "title")`. Anchored
# on `](` rather than on the opening bracket, so link text that itself carries
# brackets (`[[example.org]](url)`, one substrate's habit) still matches. One
# level of balanced parentheses stays in the URL, as in Wikipedia titles.
_INLINE_LINK = re.compile(
    r'\]\(\s*<?(https?://(?:[^()\s<>]|\([^()\s<>]*\))+)>?'
    r'(?:\s+(?:"[^"]*"|\'[^\']*\'|\([^()]*\)))?\s*\)',
    re.IGNORECASE,
)
_AUTOLINK = re.compile(r'<(https?://[^<>\s]+)>', re.IGNORECASE)
_REFERENCE_DEFINITION = re.compile(
    r'^ {0,3}\[[^\]]+\]:\s*<?(https?://[^<>\s]+)>?', re.IGNORECASE | re.MULTILINE
)
_QUERY_OR_FRAGMENT = re.compile(r'[?#]')


def normalize_reference(reference: str) -> str:
    """Fold the spellings of one citation into a single key.

    http vs https, a leading ``www.`` and a trailing slash are the same source;
    a brief that cites it one way and another that cites it the other must not
    read as two independent sources.
    """
    key = reference.strip().lower()
    for scheme in ('https://', 'http://'):
        key = key.removeprefix(scheme)
    key = key.removeprefix('www.')
    return key.rstrip('/')


def extract_urls(markdown: str) -> frozenset[str]:
    """Return the web sources a markdown brief links, one key per source.

    Reads inline links, angle autolinks and reference definitions; a bare URL
    in prose is not a link. The query string and fragment are dropped (a
    tracking parameter or a section anchor does not make another source), then
    the rest is folded by :func:`normalize_reference`. Targets that are not
    ``http``/``https`` (anchors, relative paths, ``mailto:``) are not citations.
    """
    keys: set[str] = set()
    for pattern in (_INLINE_LINK, _AUTOLINK, _REFERENCE_DEFINITION):
        for match in pattern.finditer(markdown):
            url = _QUERY_OR_FRAGMENT.split(match.group(1), maxsplit=1)[0]
            key = normalize_reference(url)
            if key:
                keys.add(key)
    return frozenset(keys)


def pairwise_jaccard(
    by_label: Iterable[tuple[str, AbstractSet[str]]],
) -> list[tuple[str, str, float]]:
    """Jaccard overlap of every pair of URL sets, in the order given.

    Takes ``(label, urls)`` pairs rather than a mapping so two briefs that share
    a label are both kept. Two empty sets score 0.0: there is no shared
    retrieval to discount.
    """
    pairs: list[tuple[str, str, float]] = []
    for (label_a, urls_a), (label_b, urls_b) in combinations(by_label, 2):
        union = len(urls_a | urls_b)
        score = len(urls_a & urls_b) / union if union else 0.0
        pairs.append((label_a, label_b, score))
    return pairs


def render_overlap(pairs: Iterable[tuple[str, str, float]]) -> str:
    """One line for the prompt: ``a / b 1.00; a / c 0.00; ...``."""
    parts = [f'{label_a} / {label_b} {score:.2f}' for label_a, label_b, score in pairs]
    return '; '.join(parts) if parts else 'no pair of briefs to compare'

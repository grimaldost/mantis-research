"""Which web-search index each research substrate reads (ADR-0012).

Cross-model checking only counts when the models read different pages. On
2026-10-07, 16 research-tier runs sent DeepSeek and Google through OpenRouter's
``exa`` engine, and in 10 of them the two cited exactly the same pages: three
"independent" checks were two. This module decides the engine per substrate so
that each default substrate reads an index of its own.

A vendor that has native search reads its own provider's index. Every other
vendor goes through an OpenRouter web-plugin engine, and the engines are handed
out one per vendor from a fixed pool so that no two of them share one.

Pure (invariant I1): names in, names out. ``research_service`` applies the
result to the batch config and logs the substrates that still share an index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

#: Vendors whose models search the web themselves, through the provider's own
#: tooling. Google joined the set when `auto:google` began resolving to a Gemini
#: 3.x model, which has native Google Search grounding on OpenRouter.
NATIVE_SEARCH_VENDORS = frozenset({'openai', 'perplexity', 'anthropic', 'x-ai', 'google'})

#: The OpenRouter web-plugin engines handed to vendors without native search, in
#: the order they are taken. ``parallel`` comes first as the cheapest per request
#: ($0.005, the same as ``perplexity``, below ``exa``'s $0.007), and ``perplexity``
#: last because a native vendor can already read its index.
ENGINE_POOL = ('parallel', 'exa', 'perplexity')


@dataclass(frozen=True, slots=True)
class EngineAssignment:
    """The engine chosen for each vendor, and who still shares an index.

    ``engines`` maps each vendor to ``'native'`` or a pool engine. ``shared`` lists
    the groups of two or more vendors that read the same index, in the order the
    group's first member appears; it is empty whenever every vendor reads its
    own.
    """

    engines: dict[str, str]
    shared: tuple[tuple[str, ...], ...]


def assign_search_engines(vendors: Iterable[str]) -> EngineAssignment:
    """Give each vendor a web-search engine, keeping their indexes apart.

    Vendors with native search take ``'native'``. The rest take the next engine
    of :data:`ENGINE_POOL` in order, skipping an engine whose index a native
    vendor in this same set already reads: the ``perplexity`` engine is skipped
    when the ``perplexity`` vendor is a substrate. When there are more
    non-native vendors than engines the assignment wraps around to the start of
    the pool, and the vendors that now read the same index are reported in
    ``shared`` so the caller can say so.

    A vendor named twice is assigned once.
    """
    ordered = list(dict.fromkeys(vendors))
    native = [v for v in ordered if v in NATIVE_SEARCH_VENDORS]
    pool = [engine for engine in ENGINE_POOL if engine not in native]
    engines: dict[str, str] = {}
    taken = 0
    for vendor in ordered:
        if vendor in NATIVE_SEARCH_VENDORS:
            engines[vendor] = 'native'
        else:
            engines[vendor] = pool[taken % len(pool)]
            taken += 1
    return EngineAssignment(engines=engines, shared=shared_indexes(engines))


def shared_indexes(engines: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """Group the vendors by the index they read; keep the groups of two or more.

    A native vendor reads its own index, which is named after the vendor; a
    pool engine's index is named after the engine. The two spellings meet at
    ``perplexity``, which is the same index either way.
    """
    groups: dict[str, list[str]] = {}
    for vendor, engine in engines.items():
        groups.setdefault(vendor if engine == 'native' else engine, []).append(vendor)
    return tuple(tuple(group) for group in groups.values() if len(group) > 1)

"""Centralized "use the newest frontier model" policy (pure logic, no I/O).

Why this module exists
----------------------
Batch configs historically pinned dated model IDs (``claude-opus-4-7``,
``openai/gpt-5``, ``google/gemini-3.1-pro-preview``, …). Those go stale every
vendor release, so a run authored months ago silently uses last-generation
models. This module is the single place that maps a vendor → its current
frontier model, so stages stop carrying scattered hardcoded IDs.

Two vendor paths, two mechanisms
--------------------------------
- **Claude (Anthropic), via the Claude Code CLI.** The ``claude --model`` flag
  accepts the latest-resolving aliases ``opus`` / ``sonnet`` / ``haiku`` /
  ``fable`` (resolved client-side, independent of plan, identical in ``-p``
  headless mode — verified against code.claude.com/docs). The alias *is* the
  "always latest" mechanism, so for Claude we resolve a sentinel to the alias
  ``opus`` and let the CLI pick the newest Opus. No dated ID to maintain.

- **OpenRouter, via the HTTP API.** OpenRouter exposes a live catalog at
  ``GET /api/v1/models`` (confirmed reachable, HTTP 200; each entry has ``id``,
  ``created`` unix-seconds, ``canonical_slug``, ``pricing``, …). There is no
  ``:latest`` convention per vendor, so "newest frontier" is computed: filter
  the catalog to a vendor's *flagship family* (see ``OPENROUTER_FRONTIER``) and
  take the most recently ``created`` match. The pure selection logic lives here
  (``select_openrouter_frontier``); the network fetch + offline fallback live in
  ``interface/adapters/openrouter_catalog.py``.

Naive "max(created) for the vendor prefix" does NOT work — OpenRouter's newest
``openai/*`` is a chat alias, newest ``google/*`` is an image model, newest
``mistralai/*`` is a *medium*-tier model. The per-vendor matcher (required +
demoted substrings) is what keeps the pick on the actual flagship. The pinned
fallback IDs below were each verified present in the live catalog on
2026-06-27; bump them when a vendor ships a new flagship and you are offline.

This module performs NO I/O (architecture invariant: ``core/`` is pure).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

# ── sentinels ────────────────────────────────────────────────────────

#: Config ``model`` values that opt into the auto-latest policy. Any other
#: value is treated as an explicit pin and passes through unchanged (backward
#: compat — every existing ``config/*.json`` keeps working).
AUTO_SENTINELS: frozenset[str] = frozenset({'auto', 'latest'})


def is_auto(model: str | None) -> bool:
    """Return True if ``model`` requests the newest-frontier policy.

    True for ``None``/empty (no pin) and for the ``auto`` / ``latest``
    sentinels (case-insensitive), including the qualified forms
    ``auto:<vendor>`` / ``latest:<vendor>``. False for any explicit model id.
    """
    if model is None:
        return True
    stripped = model.strip().lower()
    if stripped == '' or stripped in AUTO_SENTINELS:
        return True
    head, sep, _ = stripped.partition(':')
    return bool(sep and head in AUTO_SENTINELS)


# ── Claude (Anthropic) path ──────────────────────────────────────────

#: The Claude Code CLI alias that resolves to the newest Opus. Passed straight
#: to ``claude --model``; the CLI upgrades it on each Opus release with no
#: change here. To make the synthesis/research Claude stage default to a
#: different tier, change this to ``'sonnet'`` / ``'haiku'`` / ``'fable'``.
CLAUDE_LATEST_ALIAS: str = 'opus'


def resolve_claude_model(model: str | None) -> str:
    """Resolve a configured Claude model value to what ``--model`` receives.

    An explicit pin (e.g. ``claude-opus-4-8``) passes through unchanged; the
    auto sentinel (or no pin) resolves to the latest-resolving CLI alias.
    """
    # is_auto(None) is True, so reaching the return means model is a real id.
    return CLAUDE_LATEST_ALIAS if is_auto(model) else str(model)


# ── OpenRouter path ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FrontierSpec:
    """How to recognize a vendor's flagship family in the OpenRouter catalog.

    ``require`` / ``demote`` match against the model id's *path* (the part after
    ``vendor/``), case-insensitively. A candidate qualifies when it contains
    every ``require`` substring and none of the ``demote`` substrings; among
    qualifiers the most recently ``created`` wins. ``pinned`` is the offline
    fallback — a known-good flagship id used verbatim when the live catalog is
    unreachable or yields no qualifier.
    """

    pinned: str
    require: tuple[str, ...] = ()
    demote: tuple[str, ...] = ()


#: Per-vendor frontier policy. Keys are OpenRouter vendor prefixes (the part
#: before ``/`` in a model id). Verified on 2026-06-27 against the live
#: ``/api/v1/models`` catalog: each ``require``/``demote`` pair selects the
#: vendor's current flagship, and each ``pinned`` id exists in the catalog.
#:
#: Maintenance: when a vendor renames its flagship family (e.g. a future
#: ``gpt-6`` or ``gemini-4``), update that row's ``require`` tokens and
#: ``pinned`` id. Demote tokens exclude non-frontier tiers (image / mini /
#: nano / flash / lite / fast / free / distil / a vendor's smaller-param SKUs).
OPENROUTER_FRONTIER: dict[str, FrontierSpec] = {
    'openai': FrontierSpec(
        pinned='openai/gpt-5.5-pro',
        require=('gpt-5',),
        demote=('-mini', '-nano', '-image', '-audio', '-chat', '-codex', 'chat-latest'),
    ),
    'google': FrontierSpec(
        pinned='google/gemini-3.1-pro-preview',
        require=('gemini', '-pro'),
        demote=('-image', '-flash', '-lite', '-customtools', 'lyria'),
    ),
    'anthropic': FrontierSpec(
        pinned='anthropic/claude-opus-4.8',
        require=('claude', 'opus'),
        demote=('-fast', 'fable'),
    ),
    'deepseek': FrontierSpec(
        pinned='deepseek/deepseek-v4-pro',
        require=('deepseek-v',),
        demote=('-flash', '-lite', '-exp', '-distill'),
    ),
    'perplexity': FrontierSpec(
        pinned='perplexity/sonar-reasoning-pro',
        require=('sonar',),
        demote=('-deep-research',),
    ),
    'qwen': FrontierSpec(
        pinned='qwen/qwen3.7-max',
        require=('qwen', '-max'),
        demote=(
            '-flash',
            '-lite',
            '-vl',
            '-coder',
            '-a3b',
            '-35b',
            '-thinking',
            '-instruct',
        ),
    ),
    'x-ai': FrontierSpec(
        pinned='x-ai/grok-4.3',
        require=('grok',),
        demote=('-mini', '-fast', '-build', '-multi-agent', '-image', '-vision'),
    ),
    'meta-llama': FrontierSpec(
        pinned='meta-llama/llama-4-maverick',
        require=('llama-4',),
        demote=('-scout', '-guard', ':free', '-vision'),
    ),
    'mistralai': FrontierSpec(
        # "large" beats "medium"/"small"; pin the large family explicitly.
        pinned='mistralai/mistral-large-2512',
        require=('mistral-large',),
        demote=(),
    ),
}


def vendor_of(model_id: str) -> str | None:
    """Return the OpenRouter vendor prefix of a model id, or None.

    ``'openai/gpt-5.5'`` → ``'openai'``; a bare ``'gpt-5.5'`` (no slash) → None.
    """
    prefix, sep, _ = model_id.partition('/')
    return prefix if sep else None


def select_openrouter_frontier(
    vendor: str,
    catalog: Iterable[Mapping[str, object]],
) -> str | None:
    """Pick the newest frontier model id for ``vendor`` from a catalog.

    ``catalog`` is the ``data`` list from ``GET /api/v1/models`` — each item a
    mapping with at least ``id`` (``'vendor/model'``) and ``created`` (unix
    seconds). Returns the qualifying id with the largest ``created``, or None
    if the vendor is unknown to the policy or no catalog entry qualifies (the
    caller then falls back to the pinned id).

    Pure: no network, no mutation of inputs.
    """
    spec = OPENROUTER_FRONTIER.get(vendor)
    if spec is None:
        return None

    best_id: str | None = None
    best_created = float('-inf')
    for entry in catalog:
        raw_id = entry.get('id')
        if not isinstance(raw_id, str) or vendor_of(raw_id) != vendor:
            continue
        path = raw_id.partition('/')[2].lower()
        if not all(tok in path for tok in spec.require):
            continue
        if any(tok in path for tok in spec.demote):
            continue
        created = _as_float(entry.get('created'))
        if created > best_created:
            best_created = created
            best_id = raw_id
    return best_id


def pinned_openrouter_frontier(vendor: str) -> str | None:
    """Return the offline-fallback flagship id for ``vendor`` (or None)."""
    spec = OPENROUTER_FRONTIER.get(vendor)
    return spec.pinned if spec is not None else None


@dataclass(frozen=True, slots=True)
class OpenRouterResolution:
    """Outcome of resolving one OpenRouter ``model`` value.

    ``model_id`` is what the request should use. ``source`` records how it was
    chosen — ``'pin'`` (explicit config id, unchanged), ``'live'`` (selected
    from the fetched catalog), ``'fallback'`` (pinned id; catalog unavailable
    or no qualifier), or ``'unresolved'`` (auto requested but the value carried
    no usable vendor — caller should treat this as an error).
    """

    model_id: str | None
    source: str
    requested: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def resolve_openrouter_model(
    model: str | None,
    *,
    catalog: Sequence[Mapping[str, object]] | None,
    vendor_hint: str | None = None,
) -> OpenRouterResolution:
    """Resolve one OpenRouter subsession ``model`` value to a concrete id.

    Backward compat: an explicit pin (anything that is not an auto sentinel)
    is returned unchanged with ``source='pin'`` — existing configs are
    untouched.

    Auto path (``model`` is ``None`` / ``''`` / ``auto`` / ``latest`` or a
    qualified ``auto:<vendor>``): the vendor comes from the ``auto:<vendor>``
    suffix when present, else from ``vendor_hint``. With a vendor:

    - if ``catalog`` is provided and yields a qualifier → that live id
      (``source='live'``);
    - else the pinned fallback id (``source='fallback'``) — this is the
      offline-safe default and never raises.

    If auto is requested but no vendor can be determined, returns
    ``source='unresolved'`` with ``model_id=None`` so the caller can fail the
    subsession with a clear message rather than send a bad request.
    """
    if not is_auto(model):
        return OpenRouterResolution(model_id=model, source='pin', requested=model)

    vendor = parse_auto_vendor(model) or (vendor_hint.strip().lower() if vendor_hint else None)
    if not vendor:
        return OpenRouterResolution(
            model_id=None,
            source='unresolved',
            requested=model,
            notes=(
                "openrouter 'auto'/'latest' needs a vendor — set "
                "'model' to e.g. 'auto:openai' or pin a concrete id",
            ),
        )

    if vendor not in OPENROUTER_FRONTIER:
        return OpenRouterResolution(
            model_id=None,
            source='unresolved',
            requested=model,
            notes=(f'unknown OpenRouter vendor {vendor!r} for auto-latest',),
        )

    if catalog:
        live = select_openrouter_frontier(vendor, catalog)
        if live is not None:
            return OpenRouterResolution(model_id=live, source='live', requested=model)

    return OpenRouterResolution(
        model_id=pinned_openrouter_frontier(vendor),
        source='fallback',
        requested=model,
        notes=('used pinned fallback (live catalog unavailable or no match)',),
    )


# ── sentinel parsing helper (``auto:openai`` / ``latest:google``) ────


def parse_auto_vendor(model: str | None) -> str | None:
    """Extract the vendor from a qualified auto sentinel, else None.

    ``'auto:openai'`` → ``'openai'``; ``'latest:google'`` → ``'google'``.
    A bare ``'auto'`` / ``'latest'`` / explicit id / None → None (no vendor
    encoded in the value itself).
    """
    if model is None:
        return None
    head, sep, tail = model.strip().lower().partition(':')
    if sep and head in AUTO_SENTINELS and tail:
        return tail
    return None


def _as_float(value: object) -> float:
    """Best-effort numeric coercion for the ``created`` field; -inf on failure."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return float('-inf')
    return float('-inf')

"""Epistemic sidecar schema v1 — the agent-consumable contract (ADR-0003).

Each synthesis produces a ``<stem>.sidecar.json`` alongside the markdown brief.
It carries the pipeline's highest-value signal — divergences, hallucination
flags, a verification queue — as structured data an agent can load without
parsing prose. This module is pure (no I/O, invariant I1); the synthesis stage
(``interface/stages/synthesis.py``) validates and writes it.

Two authorship zones (ADR-0003), marked per field group below:

- **model-authored** — the epistemic content the synthesis model emits:
  ``claims``, ``divergences``, ``verification_queue``,
  ``agreements_worth_verifying``, ``coverage_notes``.
- **runner-authored** — identity and provenance the runner fills in after
  validating the model's part: ``topic_id`` / ``slug`` / ``batch_name`` /
  ``synthesis_path`` / ``generated_at`` and ``provenance``.

The schema evolves additively (I4); an incompatible change bumps
``sidecar_version``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mantis_research.core.state import SubsessionResult

SUPPORT_QUALITY = Literal['direct', 'indirect', 'none']


class SidecarModel(BaseModel):
    """Base for sidecar sub-models — forbids unknown keys so a malformed
    model-authored document fails validation loudly rather than silently
    dropping fields."""

    model_config = ConfigDict(extra='forbid')


# ── model-authored content ───────────────────────────────────────────


class Claim(SidecarModel):
    """One non-trivial claim extracted from the synthesis."""

    id: str
    text: str  # the claim, verbatim from the synthesis
    section: str | None = None  # synthesis section / paragraph reference
    support: SUPPORT_QUALITY = 'none'


class Divergence(SidecarModel):
    """A flagged cross-substrate disagreement (the pipeline's core signal)."""

    id: str
    description: str
    sides: list[str] = Field(default_factory=list)  # steelmanned positions, one per side
    substrates: list[str] = Field(default_factory=list)  # which sources took which side
    assessment: str | None = None  # which is right, or under what conditions each holds


class VerificationItem(SidecarModel):
    """One claim flagged for external verification (hallucination candidate or
    weak cross-model agreement)."""

    id: str
    claim: str
    reason: str  # why it is flagged (disagreement, single-source, training-uniform)
    sources_disagree: list[str] = Field(default_factory=list)


# ── runner-authored provenance ───────────────────────────────────────


class SourceRef(SidecarModel):
    """One research brief that fed the synthesis (runner-authored)."""

    label: str  # e.g. 'claude', 'openrouter:gpt-5-exa'
    path: str
    model_id: str | None = None
    bytes: int | None = None


class Provenance(SidecarModel):
    """Cost/timing provenance the runner fills from state + adapter usage."""

    synthesis_duration_s: float | None = None
    total_tokens_prompt: int | None = None
    total_tokens_completion: int | None = None
    total_cost_usd: float | None = None
    per_source_cost_usd: dict[str, float] = Field(default_factory=dict)

    @classmethod
    def from_subsessions(
        cls,
        subsessions: Iterable[SubsessionResult],
        *,
        synthesis_duration_s: float | None = None,
    ) -> Provenance:
        """Aggregate research provenance from the OpenRouter subsession results.

        Sums usage/cost across the subsessions that reported each metric. A
        metric no subsession reported stays ``None`` — a missing usage block
        must not masquerade as a genuine zero in the agent contract — so the
        Gemini-CLI path (which reports no usage) leaves the totals absent.
        ``per_source_cost_usd`` maps each priced subsession's ``subslug`` to its
        cost. Pure: no I/O; the caller loads the state.
        """
        cost_total = 0.0
        prompt_total = 0
        completion_total = 0
        cost_seen = prompt_seen = completion_seen = False
        per_source: dict[str, float] = {}
        for s in subsessions:
            cost = s.cost_usd
            if cost is not None:
                cost_total += cost
                cost_seen = True
                per_source[s.subslug] = cost
            prompt = s.tokens_prompt
            if prompt is not None:
                prompt_total += prompt
                prompt_seen = True
            completion = s.tokens_completion
            if completion is not None:
                completion_total += completion
                completion_seen = True
        return cls(
            synthesis_duration_s=synthesis_duration_s,
            total_tokens_prompt=prompt_total if prompt_seen else None,
            total_tokens_completion=completion_total if completion_seen else None,
            total_cost_usd=cost_total if cost_seen else None,
            per_source_cost_usd=per_source,
        )


# ── top-level document ───────────────────────────────────────────────


class ResearchSidecar(SidecarModel):
    """The versioned epistemic sidecar (v1).

    ``from_model_json`` validates only the model-authored zone (identity and
    provenance are runner-filled afterward), so the model may omit those; the
    runner sets them before the final write.
    """

    sidecar_version: Literal[1] = 1

    # runner-authored identity
    topic_id: str | None = None
    slug: str | None = None
    batch_name: str | None = None
    synthesis_path: str | None = None
    generated_at: str | None = None  # ISO 8601 UTC, stamped by the runner
    sources: list[SourceRef] = Field(default_factory=list)

    # model-authored epistemic content
    claims: list[Claim] = Field(default_factory=list)
    divergences: list[Divergence] = Field(default_factory=list)
    verification_queue: list[VerificationItem] = Field(default_factory=list)
    agreements_worth_verifying: list[str] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list)

    # runner-authored provenance
    provenance: Provenance = Field(default_factory=Provenance)

    @classmethod
    def from_model_json(cls, text: str) -> ResearchSidecar:
        """Validate a model-written sidecar JSON string (the model-authored
        zone). Raises ``pydantic.ValidationError`` on a malformed document."""
        return cls.model_validate_json(text)

    def to_json(self) -> str:
        """Serialize the merged document for the final on-disk write."""
        return self.model_dump_json(indent=2)


_DEFAULT_MAX_ITEMS = 20
_DEFAULT_MAX_ITEM_CHARS = 1000
_CLIP_MARKER = '…[clipped]'


def _clip_text(value: str, limit: int) -> str:
    """Clip a string to ``limit`` chars, marking the truncation."""
    return value if len(value) <= limit else value[:limit] + _CLIP_MARKER


def _clip_item(item: dict[str, Any], limit: int) -> dict[str, Any]:
    """Clip every free-text field (str, or str element of a list) of an item."""
    out: dict[str, Any] = {}
    for key, val in item.items():
        if isinstance(val, str):
            out[key] = _clip_text(val, limit)
        elif isinstance(val, list):
            out[key] = [_clip_text(v, limit) if isinstance(v, str) else v for v in val]
        else:
            out[key] = val
    return out


def project_for_agent(
    sc: ResearchSidecar,
    *,
    max_items: int = _DEFAULT_MAX_ITEMS,
    max_item_chars: int = _DEFAULT_MAX_ITEM_CHARS,
) -> dict[str, Any]:
    """Project the sidecar's epistemic content into a bounded agent-facing dict (§3/§4).

    Returns the model-authored content — claims, cross-substrate divergences, the
    verification queue, agreements worth verifying, coverage notes — as plain
    JSON-able dicts/lists an MCP tool result can carry. Bounded on two axes so the
    payload fits the MCP result-size limit (§4): at most ``max_items`` per list,
    and each item's free-text fields clipped to ``max_item_chars`` — unbounded
    ``Claim.text`` / ``Divergence.description`` would otherwise overflow the limit
    a count-only cap would pass. Items dropped by the count cap are reported per
    list under ``truncated`` (with an ``any`` flag); the caller keeps the sidecar
    path so the agent can read the full artifact. Pure (no I/O); the MCP server
    (``interface/mcp/server.py``) reads the sidecar off disk and calls this.
    """
    omitted = {
        'claims': max(0, len(sc.claims) - max_items),
        'divergences': max(0, len(sc.divergences) - max_items),
        'verification_queue': max(0, len(sc.verification_queue) - max_items),
    }
    return {
        'claims': [_clip_item(c.model_dump(), max_item_chars) for c in sc.claims[:max_items]],
        'divergences': [
            _clip_item(d.model_dump(), max_item_chars) for d in sc.divergences[:max_items]
        ],
        'verification_queue': [
            _clip_item(v.model_dump(), max_item_chars) for v in sc.verification_queue[:max_items]
        ],
        'agreements_worth_verifying': [
            _clip_text(a, max_item_chars) for a in sc.agreements_worth_verifying[:max_items]
        ],
        'coverage_notes': [_clip_text(c, max_item_chars) for c in sc.coverage_notes[:max_items]],
        'truncated': {'any': any(omitted.values()), **omitted},
    }

"""Epistemic sidecar schema v2 — the agent-consumable contract (ADR-0003).

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
  validating the model's part: ``question`` / ``topic_id`` / ``slug`` /
  ``batch_name`` / ``synthesis_path`` / ``generated_at`` and ``provenance``.

The schema evolves additively (I4); an incompatible change bumps
``sidecar_version``. v2 adds ``question`` (a sidecar with no question is not a
citation surface — a consumer cannot tell which question it answers) and the
typed source-provenance block. Both additions are readable by a v1 consumer,
and v1 documents on disk still validate (I6).

Emission is gated: :func:`missing_required_fields` names what a merged document
still lacks, and :meth:`ResearchSidecar.require_complete` raises rather than let
a hollow artifact ship.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mantis_research.core.state import SubsessionResult

SUPPORT_QUALITY = Literal['direct', 'indirect', 'none']
CITATION_KIND = Literal['url', 'repository', 'package', 'paper', 'other']

#: The schema version the runner writes today. Older versions still validate.
SIDECAR_VERSION = 2

#: Runner-authored fields a written sidecar must carry to be usable at all.
REQUIRED_ON_WRITE: tuple[str, ...] = ('question', 'generated_at', 'sources')


class SidecarContractError(ValueError):
    """A merged sidecar is missing a field the agent contract requires."""


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


class CitedSource(SidecarModel):
    """One artifact a research brief cited."""

    reference: str  # URL, repository slug, package name, or paper title
    kind: CITATION_KIND = 'other'


class SourceCitations(SidecarModel):
    """The citation inventory for one research brief (model-authored).

    ``substrate`` matches a ``sources[].label``, so the inventory joins back to
    the brief and the model id that produced it.
    """

    substrate: str
    cited: list[CitedSource] = Field(default_factory=list)


class SourceOverlap(SidecarModel):
    """One artifact more than one substrate cited.

    This is the pipeline's sharpest measured result and the mechanism that
    survives the counter-evidence against ensembling: not that several models
    agreed, but that two of them cited the same source and read incompatible
    figures out of it while a third never cited it at all — which indicts the
    source. ``substrates`` and ``not_cited_by`` are *derived* from the citation
    inventory; only ``figures_conflict`` / ``conflict`` are the model's
    judgement.
    """

    id: str
    reference: str
    kind: CITATION_KIND = 'other'
    substrates: list[str] = Field(default_factory=list)
    not_cited_by: list[str] = Field(default_factory=list)
    figures_conflict: bool = False
    conflict: str | None = None  # what disagreed, when figures_conflict


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

    sidecar_version: Literal[1, 2] = SIDECAR_VERSION

    # runner-authored identity
    # The question the run answered, verbatim from the run manifest. Without it
    # a frozen sidecar cannot be cited, and worse, can be adopted as the answer
    # to a different question.
    question: str | None = None
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

    # source provenance (v2). The inventory is model-authored — only the model
    # read the briefs. The overlaps are re-derived by the runner from that
    # inventory, so membership is computed; the model's contribution to an
    # overlap is the conflict judgement alone.
    source_citations: list[SourceCitations] = Field(default_factory=list)
    source_overlaps: list[SourceOverlap] = Field(default_factory=list)

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

    def require_complete(self) -> None:
        """Raise unless every :data:`REQUIRED_ON_WRITE` field is populated.

        Called by the runner on the merged document, immediately before the
        final write. These are runner-authored fields, so a gap here is a runner
        defect — re-asking the model cannot fix it, and shipping the document
        anyway produces the hollow artifact this gate exists to stop.
        """
        missing = missing_required_fields(self)
        if missing:
            msg = f'sidecar missing required field(s): {", ".join(missing)}'
            raise SidecarContractError(msg)


def _normalize_reference(reference: str) -> str:
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


def derive_source_overlaps(
    citations: Iterable[SourceCitations],
    *,
    judgements: Iterable[SourceOverlap] = (),
) -> list[SourceOverlap]:
    """Compute which artifacts more than one substrate cited.

    Membership (``substrates``, ``not_cited_by``) is derived from the citation
    inventory, never taken from the model — that is the whole point of typing
    provenance: "two substrates cited the same URL and disagreed about it" is
    computed, not narrated. ``judgements`` supplies the model's
    ``figures_conflict`` / ``conflict`` assessment, matched by normalized
    reference and ignored where it names an artifact no inventory contains.
    Pure; the synthesis stage calls it at merge time.
    """
    inventory = list(citations)
    all_substrates = [entry.substrate for entry in inventory]
    # Preserve first-seen order for both the references and their substrates, so
    # the output is stable across runs with the same inventory.
    cited_by: dict[str, list[str]] = {}
    display: dict[str, tuple[str, CITATION_KIND]] = {}
    for entry in inventory:
        for item in entry.cited:
            key = _normalize_reference(item.reference)
            if not key:
                continue
            display.setdefault(key, (item.reference, item.kind))
            substrates = cited_by.setdefault(key, [])
            if entry.substrate not in substrates:
                substrates.append(entry.substrate)

    verdict = {_normalize_reference(j.reference): j for j in judgements}
    overlaps: list[SourceOverlap] = []
    for key, substrates in cited_by.items():
        if len(substrates) < 2:
            continue
        reference, kind = display[key]
        judgement = verdict.get(key)
        overlaps.append(
            SourceOverlap(
                id=f'o{len(overlaps) + 1}',
                reference=reference,
                kind=kind,
                substrates=substrates,
                not_cited_by=[s for s in all_substrates if s not in substrates],
                figures_conflict=judgement.figures_conflict if judgement else False,
                conflict=judgement.conflict if judgement else None,
            )
        )
    return overlaps


def missing_required_fields(sc: ResearchSidecar) -> list[str]:
    """Return the :data:`REQUIRED_ON_WRITE` fields ``sc`` does not carry.

    Empty and whitespace-only strings count as missing — a blank question is
    exactly as unusable as an absent one. Pure; the synthesis stage calls it.
    """
    missing: list[str] = []
    if not (sc.question or '').strip():
        missing.append('question')
    if not (sc.generated_at or '').strip():
        missing.append('generated_at')
    if not sc.sources:
        missing.append('sources')
    return missing


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
        'source_overlaps': max(0, len(sc.source_overlaps) - max_items),
    }
    return {
        'claims': [_clip_item(c.model_dump(), max_item_chars) for c in sc.claims[:max_items]],
        'divergences': [
            _clip_item(d.model_dump(), max_item_chars) for d in sc.divergences[:max_items]
        ],
        # The full per-substrate citation inventory stays on disk; what an agent
        # needs inline is where the substrates landed on the same source.
        'source_overlaps': [
            _clip_item(o.model_dump(), max_item_chars) for o in sc.source_overlaps[:max_items]
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

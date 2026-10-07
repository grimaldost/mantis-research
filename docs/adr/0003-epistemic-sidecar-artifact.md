# ADR-0003 — Epistemic sidecar as a first-class versioned artifact

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

The synthesis stage already produces the pipeline's highest-value signal — the
`## Synthesis Meta-Observations` section: divergences, hallucination flags,
claims worth external verification, substrate coverage. It exists only as
prose inside the synthesis markdown. Agent consumers (ADR-0002) need that
signal machine-readable: separable from the technical content, addressable,
and cheap to load without parsing markdown. Costs and provenance (which
models, which searches, how many tokens) are known to the runner but currently
discarded.

## Decision

Each synthesis produces a sidecar JSON artifact next to the brief
(`<stem>.sidecar.json`), validated against a versioned pydantic schema
(`core/sidecar.py`, `sidecar_version: 1`). Responsibility is split by who
knows what: the synthesis model authors the epistemic fields (claims,
divergences, verification queue, agreements worth verifying, coverage notes);
the runner fills provenance and cost fields programmatically (sources, models,
byte sizes, durations, token usage) after validating the model-authored part.
An invalid sidecar fails the attempt (the orchestrator retries); the sidecar is
part of the synthesis stage's done-condition. The schema evolves additively
under I4; incompatible changes bump `sidecar_version`.

## Alternatives considered

- **Post-hoc prose parsing** (regex/LLM extraction from the meta-observations
  section) — rejected: parsing prose is the fragile contract this ADR exists
  to remove; a second LLM pass doubles cost and adds a second hallucination
  surface.
- **A separate extraction stage** — rejected: the synthesis session already
  holds full context; a later stage would re-read everything at extra cost and
  could drift from the brief it summarizes.
- **YAML frontmatter inside the synthesis markdown** — rejected: mixes the
  human-readable artifact with the machine contract, caps size awkwardly, and
  changes the existing synthesis-file contract (I6) instead of adding beside it.

## Consequences

Agents get a stable, versioned contract; the synthesis markdown contract is
untouched (additive artifact). The synthesis prompt grows a structured-output
instruction and the stage grows a validate-merge-rewrite step. Downstream
stages (falsification, evaluation) can later consume the sidecar instead of
re-extracting claims — out of scope for this series. Cost persistence
(spec §12) becomes a prerequisite for the runner-filled fields.

## Amendment (2026-10-07): a source check on each source overlap

This amendment applies the decision above; it does not change it. The field is
additive with a default, so `sidecar_version` stays 2 (I4) and every sidecar
already on disk still validates (I6).

`source_overlaps[]` (added with v2) recorded one model judgement per shared
source: `figures_conflict` / `conflict`, whether the briefs read incompatible
figures out of it. That compares the briefs with each other. It has no place
for briefs that agree with each other on something the source does not say. In
the field, two briefs cited one repository and agreed on five named items its
README does not contain, and the overlap carried `figures_conflict: false`,
which reads as clean.

`SourceOverlap` gains `source_check`, a closed vocabulary:

- `confirmed` — the source says what the briefs read out of it;
- `contradicted` — the source says something else;
- `shared_unsupported` — the briefs agree on something the source does not
  contain;
- `not_checked` — the default; nobody compared the briefs with the source.

It is model-authored, like `figures_conflict`, and `derive_source_overlaps`
carries it onto the recomputed overlap by normalized reference; an overlap with
no model judgement reads `not_checked`. The sidecar turn is told to carry over a
verdict only where the synthesis records one and never to infer one from the
briefs agreeing. Neither the synthesis turn nor the sidecar turn can fetch a
page (both run with `Read` and `Write` only), so a verdict can exist only where
the synthesis settled it from what the briefs quote; how often that happens is
checked on the next paid run. A consumer that filters on `figures_conflict`
sees no change; one that wants the brief-against-source verdict reads
`source_check` and treats `not_checked` as "unknown", never as "fine".

# ADR-0001 — Architecture invariants baseline

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

The project has operated since inception under five architecture invariants
recorded in `CLAUDE.md` ("Architecture invariants") but never captured as
decisions with rationale. The pivot series (spec 0001) touches several of them,
and the method requires every invariant a spec touches to have an ADR. This ADR
adopts the existing invariants as the project's coordinate system and adds one
that practice already follows but no document states.

## Decision

We adopt these standing invariants:

- **I1 — core purity.** `src/mantis_research/core/` performs no network
  and no subprocess I/O. File reads/writes appear only in narrow persistence
  helpers (`state.py` save/load). All other I/O lives in `interface/`.
- **I2 — Protocol-typed stages.** A pipeline phase is a module under
  `interface/stages/` implementing the `Stage` Protocol from `core/stage.py`.
- **I3 — Protocol-typed adapters.** A model provider is a module under
  `interface/adapters/` implementing the `ProviderAdapter` contract.
- **I4 — additive-only persisted schemas.** On-disk state JSON
  (`state/**/<id>.json`) and the batch-config schema evolve additively: new
  fields are Optional with backward-compatible defaults; existing fields are
  never renamed or retyped. Existing state files and all configs in `config/`
  must keep loading across releases.
- **I5 — resumability.** Every stage is idempotent under `--force` and resumable
  from its state directory after interruption; work already `done` is skipped.
- **I6 — legacy artifacts stay readable.** Output/state trees produced by past
  batches are never migrated in place by code changes; new layouts are opt-in
  and old trees remain readable by the tools that report on them.

## Alternatives considered

- **Leave the invariants in CLAUDE.md only** — rejected: CLAUDE.md is agent
  context, not a decision log; it records no rationale and no supersession
  path, and spec sections cannot cite it as an ADR.
- **Re-derive invariants per spec** — rejected: repeats analysis, invites
  drift between specs.

## Consequences

Specs cite I1–I6 by key. I1 gains a machine gate in the pivot series
(`scripts/check_core_purity.py`); I4 gains a config-corpus load test and a
golden-file state test. Any future change that must break I4 or I6 requires a
superseding ADR with a migration plan, not an in-place edit.

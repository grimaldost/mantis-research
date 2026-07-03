# ADR-0006 — Batch-scoped run layout (opt-in `runner.layout`)

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

State and outputs live in flat, globally shared directories keyed only by
`NN-slug` (`state/<stage>/…`, `research-outputs*/…`). Topic-id uniqueness
across batches is enforced by hand (900-series ids; `archive/pre-batch-19/`
exists to free id space), and each stage's `progress.json` is overwritten by
whichever batch ran last. A request-level entry point (ADR-0004) would make
collisions routine: auto-generated single-topic runs cannot coordinate id
ranges by hand.

## Decision

Introduce a second, batch-scoped layout selected per config:
`runner.layout: 'legacy' | 'batch'`, default `'legacy'`. Under `'batch'`,
state lives at `state/<batch_name>/<stage>/`, outputs at
`outputs/<batch_name>/<stage>/`, and transcripts at
`transcripts/<batch_name>/`; `progress.json` sits inside the scoped state
directory. Path resolution stays pure in `core/paths.py`, parameterized by
(layout, batch_name, stage). A run resolves every cross-stage read (synthesis
brief discovery, falsification input) within its own layout — no silent
cross-layout fallback. Existing trees are never migrated in place (I6);
`mantis research` always uses `'batch'`.

## Alternatives considered

- **Global rename/migration to the nested layout** (the old "Phase 4" plan) —
  rejected for this series: moving 44 batches' artifacts breaks I6, risks
  in-flight resumes, and buys nothing the opt-in layout doesn't.
- **Keep flat layout + enforce global id uniqueness** — rejected: pushes
  coordination onto authors and onto every future agent caller; progress.json
  clobbering remains.
- **Encode batch into the filename (`<batch>-NN-slug.md`)** — rejected:
  breaks every existing path-derivation helper and grep habit; directories are
  the natural scope boundary.

## Consequences

New runs are collision-free and self-contained (a batch directory can be
archived or deleted atomically). Two layouts must be supported in path
resolution and in `mantis status`/`monitor` reporting; the config-corpus
compatibility test pins that legacy configs stay on the legacy layout.
Cross-layout mixing is a config error by design — a batch upgrades layout only
by re-running from scratch under a new name.

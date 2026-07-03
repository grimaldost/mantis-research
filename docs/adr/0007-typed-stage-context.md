# ADR-0007 — Typed stage context (models across the orchestrator boundary)

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

`core/config.py` validates batch configs into pydantic models, then the
orchestrator immediately downgrades them: `RunContext.config` is a
`model_dump()` dict and `run_attempt` receives the topic as a dict, so every
stage spelunks with `.get('stages', {})` chains. The codebase is otherwise
strictly typed (ruff ANN, mypy strict, ty). The dict boundary exists only as
a leftover of porting the legacy scripts.

## Decision

The stage boundary carries the validated models: `RunContext` gains
`batch: BatchConfig` and `run_attempt` receives `topic: TopicConfig`. The
`config: dict` / `topic: dict` forms are removed in the same change — the
`Stage` Protocol is an internal seam with all implementors in-repo, so no
deprecation window is needed. Stage code reads typed attributes
(`topic.stages.openrouter`, `ctx.batch.models.primary`); `extra='allow'`
keeps unknown config keys accessible where genuinely dynamic.

## Alternatives considered

- **Keep dicts** — rejected: forfeits the validation the config module
  already pays for; typos in key chains surface at runtime mid-batch instead
  of at load.
- **TypedDicts over the dumped shape** — rejected: duplicates the pydantic
  schema as a parallel type universe that will drift.
- **Dual acceptance (models or dicts) during a window** — rejected: internal
  Protocol with no external implementors; a window adds branching with no
  beneficiary.

## Consequences

Stages get attribute access and mypy/ty coverage end-to-end; the Protocol
signature change ripples through all six stages, the orchestrator, dispatch,
and the fake stages in tests — one mechanical wave (spec §6) that later
sections build on. On-disk schemas are untouched (I4 unaffected); this is an
in-memory seam only.

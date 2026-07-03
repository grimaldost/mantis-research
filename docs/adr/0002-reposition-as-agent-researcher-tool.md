# ADR-0002 — Reposition as an agent-facing researcher tool

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

The runner was conceived as the research arm of the mantis memory project:
batches of topics produce syntheses whose journals feed mantis ingestion. Usage
drifted: recent batches are engineering-decision research for other projects,
with prompts already scrubbed of mantis-specific framing. The pipeline's differentiated value — substrate-
diverse research, divergence-preserving synthesis, falsification, verification
queues — is generic to any agent that needs grounded, cross-checked reference
material. The owner has decided to make that the primary purpose.

## Decision

The tool's primary purpose is deep research for agent consumers. The primary
output contract is the synthesis brief plus a machine-readable epistemic
sidecar (ADR-0003). Mantis ingestion (journal + journal-augmentation stages)
becomes an optional output sink: fully supported, on by default only where a
config asks for it, and never a dependency of the research/synthesis path.

## Alternatives considered

- **Stay mantis-only** — rejected: leaves the demonstrated general value
  unexploited and keeps mantis coupling (journal envelope, author identity,
  skill dependency) baked into default prompts where agent consumers would
  inherit it.
- **Full platformization (hosted service, auth, multi-tenant)** — rejected:
  local-first CLI + (later) MCP serves the actual consumers — agents running on
  the owner's machines — without service overhead; subscription-authenticated
  Claude CLI cannot be hosted anyway.

## Consequences

Agent-consumable output becomes a design constraint on every stage (structured
artifacts, stable paths, recorded cost). The journal turn must become
skippable without weakening batch flows (spec §8). README/positioning change.
Mantis keeps its supply: real-use research feeds ingestion as a side effect.

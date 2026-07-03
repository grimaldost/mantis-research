---
description: How to use the mantis-research `research` MCP tool — fan one question out to several models, cross-check them into a single synthesis, and get back an epistemic sidecar (claims, cross-model divergences, a verification queue). Use when you need deeper, cross-validated research than a single model gives.
---

# mantis-research

The `mantis-research` plugin exposes a **`research` MCP tool** that runs one
question through several research models, cross-checks them into a single
synthesis, and returns an epistemic sidecar: the **claims**, the cross-model
**divergences** (where the models disagree, steelmanned), and a **verification
queue** (claims worth checking externally). It is built for agents that want
cross-validated research, not a single model's answer.

## The `research` tool

Arguments:

- `question` (required) — the research question.
- `assurance` — how far the pipeline runs:
  - `fast` — research + synthesis (quickest, cheapest).
  - `standard` (default) — adds a falsification pass.
  - `high` — adds a Claude-prior baseline + evaluation (most thorough).
- `substrates` — optional list of research vendors (defaults to the Path B set).
- `dry_run` — validate orchestration without spending model calls.

It returns the run manifest (output paths, per-stage exit codes, cost), the
sidecar's `claims` / `divergences` / `verification_queue`, and the synthesis and
research briefs **by path** — read those files for full text. A large sidecar is
truncated inline (`truncated` reports what was omitted per list); the complete
sidecar is always on disk at `outputs.sidecar`.

## Requirements

- The synthesis / journal / falsification / evaluation stages drive the local
  `claude` CLI, so run this on a machine with an **authenticated Claude Code
  seat** (ADR-0009 — the tool is local-first).
- The research substrates use OpenRouter over HTTP — set `OPENROUTER_API_KEY`
  (see `.env.template`).
- `uv` must be installed; the server launches via `uv run`.

## Example

Ask for a standard-assurance run:

> Use the research tool with question "What changed in ISO 20022 migration for
> Brazilian banks in 2025?" and assurance "standard".

Start with `dry_run: true` to validate the pipeline end to end without spending
model calls, then drop it for the real run.

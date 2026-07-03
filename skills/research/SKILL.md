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

## Setup (first run)

If the `research` tool or the `mantis` CLI isn't available yet, bootstrap it from
scratch — **no clone needed** (`uv` must be installed):

1. **Install** the published wheel as an isolated tool:
   `uv tool install git+https://github.com/grimaldost/mantis-research`.
   This puts `mantis` (CLI) and `mantis-mcp` (the stdio MCP server) on your `PATH`.
2. **OpenRouter key** — the research substrates need `OPENROUTER_API_KEY`. Check
   `echo $OPENROUTER_API_KEY`; if it's empty, get one at
   <https://openrouter.ai/settings/keys> and set it in the environment
   (`export OPENROUTER_API_KEY=sk-or-…`; on Windows `setx OPENROUTER_API_KEY …`,
   then restart the shell). The installed tool reads the key from the environment;
   a source clone also reads a local `.env` (see `.env.template`).
3. **Claude seat** — synthesis / journal / falsification / evaluation drive the
   local `claude` CLI (`claude --version`), so run on a machine with an
   authenticated Claude Code seat (ADR-0009, local-first). Research-only runs
   (OpenRouter substrates) work without it.
4. **Register as an MCP server** so agents get the `research` tool:
   `claude mcp add mantis-research --scope user -- mantis-mcp`.
5. **Verify** with no spend: `mantis research "smoke test" --dry-run` should print
   a manifest with `"ok": true`.

## Example

Ask for a standard-assurance run:

> Use the research tool with question "What changed in ISO 20022 migration for
> Brazilian banks in 2025?" and assurance "standard".

Start with `dry_run: true` to validate the pipeline end to end without spending
model calls, then drop it for the real run.

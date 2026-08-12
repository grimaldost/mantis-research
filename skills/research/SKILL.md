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

It is deliberately **slow and paid**: a run fans out to several OpenRouter models
(real dollars) and drives a local Claude synthesis (minutes, not seconds). Reach
for it to *ground* a decision, not for quick lookups — see [When not to use
it](#when-not-to-use-it) below.

## The `research` tool

Arguments:

- `question` (required) — the research question.
- `assurance` — how far the pipeline runs. Each tier adds stages (deeper
  checking), not more research breadth:
  - `fast` (default) — research → synthesis. This is what most calls want: the
    cross-model briefs, the merged synthesis and the epistemic sidecar are all
    produced here.
  - `standard` — adds a **falsification** pass: one adversarial Claude turn that
    reads the finished synthesis and hunts for counter-evidence against its
    claims. Escalate to it when the answer will carry a decision you cannot
    cheaply revisit.
  - `high` — also adds a **Claude-prior baseline** (a title-only, no-sources
    answer) and an **evaluation** pass that scores the synthesis against a rubric,
    using that baseline to detect training-consensus parroting (whether the
    sourced research added anything beyond what the model already "knew").
- `substrates` — optional list of research **vendor slugs**; each is run as that
  vendor's newest frontier model. Accepted: `openai`, `google`, `anthropic`,
  `deepseek`, `perplexity`, `qwen`, `x-ai`, `meta-llama`, `mistralai`. Omit (or
  pass `null`) to use the default Path B set: `openai`, `deepseek`, `google`.
  Pass **vendor slugs, not model ids** — e.g. `["openai", "deepseek", "google"]`.
  One dead substrate fails the whole topic, so don't pass unknown slugs;
  `perplexity` is valid but deliberately kept out of the default because its
  auto-picked model 404s — add it explicitly when you want real-time-search
  coverage.
- `primary` — which research brief the synthesis anchors on (everything else
  becomes a secondary it folds in and cross-checks against): `claude` or
  `openrouter:<slug>` (e.g. `openrouter:openai`). Leave it at the empty default —
  it anchors on the first substrate, the right choice here, because this tool runs
  **Path B** (OpenRouter substrates only, no Claude research brief). Pass `claude`
  only for a batch run that separately produced a Claude research brief; via this
  tool there is none, so `claude` fails fast with `missing primary brief`. (The
  `high` tier's Claude-*prior* baseline is a separate title-only artifact used for
  scoring, not a research brief.)
- `journal` — also emit a mantis-ingestion **journal** via a second synthesis
  turn (markedly slower). Off by default; turn it on only when feeding a
  downstream mantis memory store.
- `dry_run` — validate orchestration end-to-end without spending model calls.
  The result is marked `"dry_run": true` and every path under `outputs` is where
  an artifact *would* go: none of them exist. A dry run leaves no state a later
  real run will mistake for finished work, so the same call for real afterwards
  runs the whole pipeline.
- `resume` — re-enter a run that was interrupted, instead of starting a new one.
  Pass its output directory (the `outputs_dir` of the run you lost, e.g.
  `outputs/research-my-question-20260811T101500Z`). Stages that already finished
  are skipped, and the question and settings come from that run's own record, so
  `question` is ignored. Cheaper and more faithful than re-asking: the per-model
  briefs a lost run already paid for are reused rather than bought again.

## What comes back

A single JSON object: the run **manifest**, plus — when a sidecar was produced —
the sidecar's epistemic content merged in at the top level.

- `ok` (bool), `question`, `assurance` — run identity.
- `cost` — `{ cost_usd, tokens_prompt, tokens_completion, available }`, summed
  across the OpenRouter substrates (`available: false` with zeroed totals if the
  cost state was unreadable).
- `stages` — `{ <stage>: { exit_code } }` for each stage that ran.
- `outputs` — file **paths**: `briefs` (one per substrate), `synthesis`,
  `sidecar`, plus `falsification` / `evaluation` when those ran. The synthesis and
  briefs are referenced by path, never inlined — read those files for full text.
- `dry_run` (bool) — whether this was a dry run. When true, every path under
  `outputs` is a destination and none of the files exist.
- `sidecar_available` (bool) — if `false`, none of the sidecar keys below are
  present. On a live run this cannot happen: a run that produced no sidecar
  produced no answer, and the tool **raises** rather than returning the research
  briefs on their own. The error names the failing stage and the run directory to
  pass back as `resume`, so the briefs already paid for are not bought twice.
  `false` therefore only ever accompanies `dry_run: true`.

Sidecar keys (present when `sidecar_available`). Each list is capped at 20 items
and long free-text is clipped:

- `claims` — non-trivial claims from the synthesis; each `{ id, text, section,
  support }` (`support`: `direct` | `indirect` | `none`).
- `divergences` — the cross-model disagreements, the pipeline's core signal; each
  `{ id, description, sides, substrates, assessment }` (`sides` = the steelmanned
  positions; `substrates` = which took which side; `assessment` = which side
  holds, when determinable).
- `verification_queue` — claims worth checking externally; each `{ id, claim,
  reason, sources_disagree }`.
- `source_overlaps` — the sources **more than one substrate cited**; each
  `{ id, reference, kind, substrates, not_cited_by, figures_conflict, conflict }`.
  This is the pipeline's sharpest signal: when two substrates cite the same URL
  and read incompatible figures out of it (`figures_conflict: true`) while a
  third never cites it at all (`not_cited_by`), the *source* is suspect — a
  hallucination class no single-provider run can surface. `substrates` and
  `not_cited_by` are computed from the per-substrate citation inventory, not
  asserted by the model.
- `agreements_worth_verifying`, `coverage_notes` — lists of strings.
- `truncated` — `{ any, claims, divergences, verification_queue, source_overlaps }`:
  how many items each list dropped by the cap. If `any` is true, read the full
  sidecar.

The **complete** sidecar is always on disk at `outputs.sidecar` — including fields
not projected inline: `question` (the question this sidecar answers, verbatim —
so a sidecar you froze months ago is still citable on its own), `sources[]`
(`{ label, path, model_id, bytes }` per brief, so you can see which model
produced which brief), `source_citations[]` (the full per-substrate citation
inventory `source_overlaps` is computed from) and `provenance` (durations,
token/cost totals). Read it when you need the full lists or per-source
attribution.

## Cost & latency

Rough expectations for one question (defaults: Path B, journal off). Dollar cost
is almost entirely OpenRouter research spend — the synthesis / falsification /
evaluation stages run on your **local Claude seat**, adding time, not metered
dollars — so all three tiers cost about the same for a given substrate set:

- **Cost:** roughly **$1–6** on the default substrate set, down to cents on a lean
  or narrow run. Scales with substrate count and question breadth.
- **Latency (estimates):** `fast` ~5–15 min, `standard` ~35–75 min, `high`
  ~50–100+ min — the falsification and evaluation passes are each full Claude
  runs. Substrates run concurrently, so the research stage tracks the slowest one.

Pick the tier by how much checking the answer needs, not by how long you are
willing to wait. Waiting is handled separately, on two axes:

- **The run narrates itself.** Progress notifications go out over the MCP
  channel as the run is named, at each stage boundary, per research substrate as
  it starts and finishes, and every 10 s during any internal backoff. A silent
  minute means something is wrong; silence is no longer the normal case.
- **No single internal wait exceeds half the caller's idle budget**
  (`runner.caller_idle_budget_seconds`, default 1500 s), so a rate-limited
  substrate cannot sit past a client's idle window — a failure that used to look
  like the tier's fault and was never fixed by dropping to `fast`.

Use `dry_run: true` first — it validates the whole pipeline for free, then drop it
for the real run.

## When not to use it

- **A single fact or quick lookup** — a definition, a version number, a port. One
  web search answers it in seconds for free; this pipeline's cost/latency buys
  nothing here.
- **One model would answer confidently** and you don't need the disagreement — the
  tool's value is surfacing where models *disagree*; on settled questions the
  cross-validation is wasted spend.
- **A latency-sensitive path** — anything a user is waiting on live, or a step
  inside a tight agent loop. A `standard`/`high` run is minutes.
- **A cost-sensitive path or running at scale** — each call bills real dollars;
  batch deliberately, not reflexively.
- **The task isn't research** — writing/editing code, running commands, or
  transforming text you already have. This produces a cited brief + epistemic
  sidecar, not a coding or general-purpose agent; use it to *ground* such work,
  not to do it.
- **No local Claude seat** — every assurance tier includes the synthesis stage,
  which drives the local `claude` CLI, so without a usable seat the call is
  refused up front rather than half-run: the tool checks the seat before it
  dispatches anything and raises naming the precondition, so no research is
  bought that could not be synthesised. Fix the seat (`claude auth login`, no
  `--console`) or use `dry_run` to exercise the plumbing offline.

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
   (OpenRouter substrates) work without it. The seat is checked before a run
   dispatches anything, so an expired token is reported as a refusal rather than
   discovered after the research has been paid for. Nesting is fine: a `claude`
   child spawned from inside a Claude Code session runs normally, which is what
   makes calling this tool from an agent session work at all.
4. **Register as an MCP server** so agents get the `research` tool:
   `claude mcp add mantis-research --scope user -- mantis-mcp`.
5. **Verify** with no spend: `mantis research "smoke test" --dry-run` should print
   a manifest with `"ok": true`.

## Example

Ask for a default (`fast`) run:

> Use the research tool with question "What changed in ISO 20022 migration for
> Brazilian banks in 2025?".

Escalate only when the extra checking earns its Claude-seat time:

> …and assurance "standard".

Start with `dry_run: true` to validate the pipeline end to end without spending
model calls, then drop it for the real run.

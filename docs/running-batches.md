# Running batches

The operator guide for batch mode: a curated set of topics driven through the
pipeline stage by stage. For a single question, `mantis research "<question>"`
does all of this in one command (see the [README](../README.md)) — batch mode
earns its ceremony when you have many topics, want per-topic prompts and
substrate choices, or need to re-run subsets.

Commands below use `uv run mantis …` (a source checkout). For an installed
tool (`uv tool install …`), drop the `uv run` prefix; `uv run python -m
mantis_research …` is equivalent everywhere.

## Setup

1. **Environment.** Copy `.env.template` to `.env` (a clone reads it; an
   installed tool reads the process environment) and set `OPENROUTER_API_KEY`.
   Optional: `DISABLED_STAGES` — comma-separated stage names this machine
   refuses to dispatch, e.g. `DISABLED_STAGES=gemini` when no Gemini CLI
   subscription exists here. A disabled stage fails fast with a pointer
   instead of dying mid-run.
2. **Claude seat.** The synthesis / journal-passes / falsification /
   evaluation / claude-prior stages drive the local `claude` CLI against your
   subscription — run where an authenticated Claude Code CLI lives.
   Research-only runs (OpenRouter) work without it.
3. **Working directory.** All state/output directories resolve at the project
   root in a checkout, or under the current working directory for an
   installed tool — `cd` to where you want the run's tree before starting.

## Author the config

Copy [`config/example-batch.json`](../config/example-batch.json) and edit. The
schema reference is [batch-config.md](batch-config.md); prompt authoring is
specified per stage in [`prompts/playbooks/`](../prompts/playbooks/README.md),
and substrate selection per topic class in
[`model-recommendations.md`](../prompts/playbooks/model-recommendations.md).

## The operating loop

Dry-run first — it validates config, orchestration, and paths end to end with
zero model calls, and it never needs an API key:

```bash
uv run mantis run openrouter config/<batch>.json --dry-run
```

Then run the stages in dependency order. For a Path B batch (the default —
all research via OpenRouter):

```bash
uv run mantis run openrouter     config/<batch>.json   # research fan-out
uv run mantis run synthesis      config/<batch>.json   # brief + sidecar (+ journal)
uv run mantis run falsification  config/<batch>.json   # optional, per-topic opt-in
uv run mantis run claude-prior   config/<batch>.json   # optional, evaluation's baseline
uv run mantis run evaluation     config/<batch>.json   # optional, rubric scoring
uv run mantis run journal-passes config/<batch>.json   # optional, journal augmentation
```

`run claude` and `run gemini` (research via the Claude/Gemini CLIs) exist for
the narrow Path A cases — see
[research-path-recommendation.md](../prompts/playbooks/research-path-recommendation.md).
Optional stages only execute for topics that enable them (`high_stakes: true`
or `stages.<name>.enabled: true`); everything else is reported as skipped.

Per-stage flags:

- `--parallel/-p <n>` — override `runner.max_parallel_topics` for this run.
- `--dry-run` — no model calls, no preflight; exercises the whole
  orchestration path.
- `--only <id> --only <id>` — restrict to specific topic ids (repeat the flag
  per id).
- `--force` — clear the stage's state for the selected topics and re-run them
  from scratch.

## Watching a run

```bash
uv run mantis status  config/<batch>.json      # per-stage, per-topic status table
uv run mantis monitor <stage> [--batch-name <name>] [--layout batch]
```

`status` resolves the run's layout from the config and reports every stage,
including evaluation and claude-prior. `monitor` tails a stage's
`progress.json`; give it `--batch-name`/`--layout` for a batch-scoped run.
Logs are structured (structlog) and go to **stderr**; each run also appends to
`logs/`.

## Resume, retries, interruption

Re-running the same command **is** the resume mechanism: topics already `done`
are skipped, everything else (`pending`, `failed`, `rate_limited`,
`blocked_upstream`, a stale `in_flight`) is re-attempted. The status model and
the cross-run rules are described in
[architecture.md](architecture.md#state-and-resumability).

- Within a run, a failing topic retries up to `runner.max_retries_per_stage`
  times. A rate-limited attempt backs off `rate_limit_backoff_minutes`
  (default 30); other failures back off `generic_failure_backoff_minutes`
  (default 5). Both sleeps are interruptible.
- **Ctrl+C is graceful**: scheduling stops, in-flight topics finish, state is
  saved, and the process exits with a per-status summary. Resume later with
  the same command.
- `blocked_upstream` on synthesis means the primary brief or every secondary
  is missing — finish the research stage (or fix `models.primary`) and re-run.

## Where files land

Layout is per config (`runner.layout` — see
[architecture.md](architecture.md#run-layouts)). With `legacy` (the default):

| Stage | State | Outputs |
|---|---|---|
| claude | `state/` | `research-outputs/` |
| gemini | `state-gemini/` | `research-outputs-gemini/` |
| openrouter | `state-openrouter/` | `research-outputs-openrouter/` |
| synthesis | `state-synthesis/` | `research-outputs-synthesis/` + `journals/` |
| journal-passes | `state-journal-passes/` | `journals/` (`*-augmented.md`) |
| falsification | `state-falsification/` | `research-outputs-falsification/` |
| evaluation | `state-evaluation/` | `evaluations/` |
| claude-prior | `state-claude-prior/` | `claude-prior-baselines/` |

With `layout: 'batch'`, the same trees are scoped per batch:
`state/<batch_name>/<stage>/` and `outputs/<batch_name>/<stage>/` (the
journal dir is `outputs/<batch_name>/journals/`), plus
`transcripts/<batch_name>/`. Transcripts for legacy runs land in
`transcripts/`; both layouts share `logs/`.

Every output file is named by topic: `NN-slug.md` (numeric ids zero-padded to
two digits), with per-substrate research briefs at
`…openrouter/<NN-slug>/<subslug>.md` and the sidecar at
`…synthesis/<NN-slug>.sidecar.json`.

## Cost

Research substrates bill through OpenRouter (typically $2–6 per topic on a
4-substrate set — see the cost table in
[model-recommendations.md](../prompts/playbooks/model-recommendations.md));
the Claude-CLI stages consume your subscription seat, not metered dollars.
Per-subsession token/cost usage is persisted in state and aggregated into the
sidecar's provenance block.

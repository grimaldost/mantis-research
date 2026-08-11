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
"Optional" means two different things above. `falsification` and `evaluation`
are per-topic opt-ins: they run only where `high_stakes: true` or
`stages.<name>.enabled: true`, and every other topic is reported as skipped.
`claude-prior` and `journal-passes` are optional only in that you choose
whether to invoke the command — once invoked they run for **every** topic in
the config (`journal-passes` blocks on topics whose first-pass journal is
missing). Use `--only <id>` to restrict them.

Per-stage flags:

- `--parallel/-p <n>` — override `runner.max_parallel_topics` for this run.
- `--dry-run` — no model calls, no preflight; exercises the whole
  orchestration path.
- `--only <id> --only <id>` — restrict to specific topic ids (repeat the flag
  per id).
- `--force` — clear the stage's state for the selected topics and re-run them
  from scratch.

## Exit codes

The commands are scriptable; the process exit code is the contract.

| Command | 0 | 1 | 2 |
|---|---|---|---|
| `mantis run <stage>` | every selected topic done (or already done) | any topic failed, rate-limited, or blocked upstream in a live run (a dry run does not count blocked as a failure) | unknown stage name (typer rejects it as an unknown subcommand) |
| `mantis research` | manifest `ok: true` | manifest `ok: false` — a stage returned non-zero | invalid argument (unknown `--assurance`, empty `--substrates`, a `--resume` directory outside `outputs/` or owned by a live process) |
| `mantis monitor <stage>` | all topics terminal (`ALL_TERMINAL`) | `progress.json` not found | neither a stage nor `--snapshot` given |
| `mantis monitor --snapshot` | the config loaded and the table printed | a missing config path or an invalid config — the error propagates | — |

A stage listed in `DISABLED_STAGES` also exits 1, but not cleanly: the guard in
`interface/cli/dispatch.py` raises `RuntimeError`, so the pointer message
arrives with a traceback rather than as a plain error.

## Watching a run

```bash
uv run mantis monitor --snapshot config/<batch>.json   # per-stage, per-topic table, once
uv run mantis monitor <stage> [--poll-seconds N] [--batch-name <name>] [--layout batch]
```

There is one progress surface (ADR-0010): `mantis status` was folded into
`--snapshot`, which resolves the run's layout from the config and reports every
stage, including evaluation and claude-prior. Without it, `monitor` tails a stage's
`progress.json`; `--poll-seconds` sets the polling interval (default 30), and
`--batch-name`/`--layout` point it at a batch-scoped run.
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
  (default 5). Both sleeps are interruptible, and both are capped at half of
  `caller_idle_budget_seconds` (default 1500) — so the longest a caller waits
  in silence is 12.5 minutes, well inside the MCP client's 1800 s idle window.
- **A mute child is killed.** A spawned Claude CLI child that produces no output
  for `child_idle_timeout_minutes` (default 10) is terminated and its attempt
  fails with a reason, instead of leaving the topic `in_flight` with no error
  forever. The clock is on silence, not runtime — it resets on every line.
- **One local seat, one holder.** The synthesis-family stages drive the machine's
  single authenticated `claude` CLI, so each call takes a lock at
  `state/claude-seat.lock` that records the holder's PID and a name like
  `<batch>/synthesis:<topic>`. Concurrent runs queue and say who they are waiting
  for; a lock whose recorded PID is gone is reclaimed immediately rather than
  waited out.
- **An abandoned topic is `dead`, not `failed`.** Every topic records the PID
  that put it `in_flight`. A later run reads that back, and a topic whose owner
  is no longer a live process is marked `dead` (marker `DD` in the snapshot)
  with a reason naming the vanished owner, then re-attempted. `failed` keeps its
  meaning: an attempt ran and lost.
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

A request-level run (`mantis research`, the MCP `research` tool) also writes
`outputs/<batch_name>/run.json` **before it dispatches anything**: the question
and its slug, the batch name, the assurance tier, the substrate set and
`status: "dispatching"`. When the run finishes it is rewritten with the final
manifest and `status: "complete"`. A run whose caller walked away is therefore
still identifiable on disk — which question it was answering and whether it got
past dispatch — rather than an orphan directory nothing can be matched to.

That record is also what `mantis research --resume outputs/<batch_name>` reads
to re-enter an interrupted run: the question and settings come from it, so
nothing is retyped, completed stages and topics are skipped, and a run whose
`owner_pid` is still a live process is refused rather than run twice. Resuming
an abandoned run appends a `dead` entry to the record's `history` before it
starts, so the record says what happened rather than being overwritten. The
directory offered must be strictly inside `outputs/`.

## Cost

Research substrates bill through OpenRouter (typically $2–6 per topic on a
4-substrate set — see the cost table in
[model-recommendations.md](../prompts/playbooks/model-recommendations.md));
the Claude-CLI stages consume your subscription seat, not metered dollars.
Per-subsession token/cost usage is persisted in state and aggregated into the
sidecar's provenance block.

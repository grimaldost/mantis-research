# Architecture

How the pipeline is built. For what the tool *is* and how to run it, start at
the [project README](../README.md); for operating batches, see
[running-batches.md](running-batches.md). The decisions behind this shape are
recorded as [ADRs](adr/README.md) — this page describes the current state and
links the rationale.

## Data flow

A topic flows through up to six stages: research fans out, synthesis fans in,
and everything after synthesis is optional checking.

```
                research — fan out, one brief per substrate
      ┌───────────────────────┼───────────────────────┐
 openrouter (default)    claude (optional)       gemini (legacy)
 N HTTP subsessions      Claude CLI agent loop   Gemini CLI
      └───────────────────────┼───────────────────────┘
                              ▼
             briefs: one primary + N secondaries (models.primary)
                              ▼
                 synthesis (Claude CLI, multi-turn)
                   ├─▶ synthesis brief (markdown)
                   ├─▶ <stem>.sidecar.json  (epistemic contract)
                   └─▶ journal (optional turn, mantis ingestion)
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
  journal-passes        falsification          evaluation ◀── claude-prior
  (augment journal)     (adversarial          (3-gate + 6-criterion   (title-only
                         re-read)              rubric)                 baseline)
```

- **Research** — one brief per substrate. The default path (Path B) uses
  OpenRouter subsessions only; the Claude and Gemini CLI research stages exist
  for the narrow cases described in
  [research-path-recommendation.md](../prompts/playbooks/research-path-recommendation.md).
- **Synthesis** — reads the primary brief plus every secondary
  ([ADR-0005](adr/0005-primary-brief-selection-in-config.md)) and writes one
  cross-checked brief that preserves disagreements instead of averaging them;
  a dedicated follow-up turn emits the sidecar. The stage reports
  `blocked_upstream` until the primary and at least one secondary brief exist
  on disk.
- **Falsification, evaluation, claude-prior** — optional deeper checking,
  enabled per topic (`high_stakes` or `stages.<name>.enabled`) or by the
  `--assurance` tier of a one-shot run
  ([ADR-0004](adr/0004-request-level-entry-point.md)).

## Code layout — functional core, imperative shell

```
src/mantis_research/
├── core/                  # PURE logic — no network, no subprocess
│   ├── config.py          #   batch-config v2 schema (pydantic)
│   ├── state.py           #   per-topic state models + atomic save/load
│   ├── sidecar.py         #   sidecar schema v1 + agent projection
│   ├── prompts.py         #   packaged default prompt templates
│   ├── model_policy.py    #   auto-latest model selection (pure part)
│   ├── paths.py           #   layout resolvers (legacy | batch)
│   ├── retry.py           #   backoff classification/policy
│   ├── settings.py        #   env-driven settings (pydantic-settings)
│   ├── logging.py         #   structlog config — logs to stderr, never stdout
│   └── progress.py        #   progress.json writer model
└── interface/             # I/O — adapters and entry points
    ├── adapters/          #   claude_cli, gemini_cli, openrouter_http (+ catalog)
    ├── stages/            #   one module per pipeline stage
    ├── orchestrator.py    #   generic asyncio.TaskGroup runner
    ├── research_service.py#   run_research() — shared by CLI and MCP
    ├── transcripts.py     #   transcript persistence
    ├── cli/               #   typer commands: run / research / status / monitor
    └── mcp/               #   stdio MCP server exposing the `research` tool
```

Core purity is machine-enforced: `scripts/check_core_purity.py` AST-walks
`core/` and fails on any network/subprocess import (invariant I1, wired into
pre-commit). Settings come from the environment via pydantic-settings (never
`os.getenv`), and nothing in `src/` prints — structured logs go to stderr so
stdout stays clean for the `mantis research` manifest and the MCP JSON-RPC
stream.

## The contracts

Two Protocols in [`core/stage.py`](../src/mantis_research/core/stage.py) carry
the whole pipeline; the orchestrator knows nothing else.

- **`Stage`** — one pipeline phase: `preflight()` (provider reachable?),
  `is_enabled(topic, config)` (does this topic want this stage?),
  `upstream_ready(topic_id, slug, ctx)` (inputs on disk? else
  `blocked_upstream`), `run_attempt(topic, state, ctx)` (do the work once).
  Stages don't retry, sleep, or persist state — the orchestrator owns that.
- **`ProviderAdapter`** — one way to call a model: `preflight()` and
  `run_research(prompt, options, transcript_path, dry_run)`. Subprocess
  drivers (Claude/Gemini CLIs) and the OpenRouter HTTP driver implement the
  same contract.

The **orchestrator** (`interface/orchestrator.py`) runs any Stage generically:
per-topic concurrency (`runner.max_parallel_topics`), retries with
rate-limit-aware backoff, state persistence around every attempt, graceful
SIGINT handling, and progress reporting. The CLI reaches it through one
dispatch table — `STAGE_REGISTRY` in
[`interface/cli/dispatch.py`](../src/mantis_research/interface/cli/dispatch.py) —
so adding a stage is a new module plus one registry row (invariant I2; see
[CONTRIBUTING.md](../CONTRIBUTING.md)).

## State and resumability

Every stage persists one JSON file per topic (`<id>.json`) in its state
directory, written atomically (temp file + replace) so an interrupt can never
truncate state. A topic is in one of six statuses:

| Status | Meaning | On the next run |
|---|---|---|
| `pending` | not yet attempted | attempted |
| `in_flight` | attempt in progress (transient) | re-attempted |
| `done` | artifact produced and verified | **skipped** |
| `failed` | attempts exhausted this run | re-attempted |
| `rate_limited` | provider limit hit; backoff applied | re-attempted |
| `blocked_upstream` | required input briefs missing | re-attempted |

Only `done` survives across runs — re-running the same command is the resume
mechanism, `--only` narrows it, and `--force` clears state first (invariant
I5). On-disk state schemas evolve additively only (invariant I4), pinned by
golden-file tests, so old state files keep loading across releases.

## Run layouts

Two layouts, chosen per config (`runner.layout`,
[ADR-0006](adr/0006-batch-scoped-run-layout.md)); the resolvers live in
[`core/paths.py`](../src/mantis_research/core/paths.py) and a run never mixes
layouts:

- **`legacy`** (default) — the original flat directories at the project root
  (`research-outputs*/`, `state*/`, `journals/`, …), byte-identical to what
  every historical batch used, so old trees keep resuming (invariant I6).
- **`batch`** — everything scoped under the batch name
  (`state/<batch>/<stage>/`, `outputs/<batch>/<stage>/`,
  `transcripts/<batch>/`), so runs never collide and a batch can be archived
  or deleted atomically. `mantis research` always uses this layout.

The concrete per-stage directory table is in
[running-batches.md](running-batches.md#where-files-land). For an installed
tool (no project tree), directories resolve under the current working
directory; a source checkout resolves them at the repo root.

## Model selection

Configs may pin model ids or opt into the auto-latest policy
(`core/model_policy.py`):

- **Claude stages** — an unpinned model resolves to the Claude CLI alias
  `opus`, which the CLI maps to the newest Opus on every release.
- **OpenRouter subsessions** — `auto:<vendor>` (or a `vendor` field) resolves
  against the live `/models` catalog using per-vendor flagship matchers, with
  pinned fallback ids when offline (`interface/adapters/openrouter_catalog.py`
  does the fetch; the selection logic is pure).

## The epistemic sidecar

Each synthesis writes `<stem>.sidecar.json` next to the brief — the
agent-consumable contract ([ADR-0003](adr/0003-epistemic-sidecar-artifact.md),
schema `core/sidecar.py`, `sidecar_version: 1`). Authorship is split by who
knows what: the synthesis model writes the epistemic fields (claims,
divergences, verification queue, agreements worth verifying, coverage notes);
the runner fills identity, sources, and provenance (durations, token/cost)
after the model-authored part validates. Consumers: the field-by-field guide
is in [skills/research/SKILL.md](../skills/research/SKILL.md);
`core/sidecar.py::project_for_agent` produces the size-bounded projection the
MCP tool returns.

## Serving surfaces

- **CLI** — `mantis run <stage> <config>` (batch mode), `mantis research
  "<question>"` (one-shot façade, ADR-0004), `mantis status` / `mantis
  monitor` (read-only reporting).
- **MCP server** — `mantis-mcp` (or `python -m
  mantis_research.interface.mcp`) serves a `research` tool over stdio,
  wrapping the same `run_research()` the CLI uses. Local-first by design: the
  synthesis-family stages drive the host's authenticated `claude` CLI
  ([ADR-0009](adr/0009-agent-serving-via-mcp-plugin.md)). The MCP tool schema
  and result shape are a public contract and evolve additively, like the
  on-disk schemas.
- **Claude Code plugin** — `.claude-plugin/plugin.json` bundles the server;
  the repo doubles as its own plugin marketplace
  (`.claude-plugin/marketplace.json`).

## Invariants

Adopted in [ADR-0001](adr/0001-architecture-invariants-baseline.md); a change
that must break one requires a superseding ADR with a migration plan.

| Key | Invariant | Enforcement |
|---|---|---|
| I1 | `core/` performs no network or subprocess I/O | `scripts/check_core_purity.py` (pre-commit) |
| I2 | Pipeline phases implement the `Stage` Protocol | type checkers; `STAGE_REGISTRY` |
| I3 | Providers implement the `ProviderAdapter` Protocol | type checkers |
| I4 | Persisted schemas (state JSON, batch config) evolve additively | `tests/unit/test_state_golden.py`, `test_config_corpus.py` |
| I5 | Every stage is resumable and idempotent under `--force` | orchestrator state machine + tests |
| I6 | Legacy artifact trees stay readable; new layouts are opt-in | `legacy` layout is the default (ADR-0006) |

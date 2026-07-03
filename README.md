# mantis-research

A **deep-research tool for agents**. Give it a question; it researches across
several LLMs with different training corpora and search substrates, merges the
briefs into one synthesis that *preserves* their disagreements instead of
smoothing them, and emits a machine-readable **epistemic sidecar** — claims,
cross-model divergences, and a verification queue — that a calling agent can
load without parsing prose. An optional adversarial falsification pass and a
gated evaluation pass are available for higher-stakes questions.

It also drives staged batch runs, and its outputs double as reference material
for downstream [mantis](https://github.com/grimaldost) knowledge
ingestion — but the primary purpose is grounded, cross-checked research for
agent consumers (see [ADR-0002](docs/adr/0002-reposition-as-agent-researcher-tool.md)).

## Why multi-substrate

A single model's confident wrongness is invisible from inside that model.
Running the same question across substrate-diverse models — open-weight and
closed, different RLHF traditions, real-time vs. semantic search — makes
hallucinations surface as *disagreement*, and the synthesis flags those
disagreements rather than averaging them away. The sidecar turns that signal
into structured data.

## Requirements

- **Python ≥ 3.13** and [uv](https://docs.astral.sh/uv/).
- An **OpenRouter API key** (`OPENROUTER_API_KEY`) — the research substrates
  route through it.
- For the **synthesis / journal / falsification / evaluation / claude-prior**
  stages: a local, authenticated [Claude Code CLI](https://code.claude.com)
  (`claude`) — these stages drive it against your Claude subscription. This tool
  is **local-first**: run it where an authenticated `claude` lives.
  Research-only runs (OpenRouter substrates) work without it.

## Install

Install the wheel as an isolated CLI tool — **no clone needed**:

```bash
uv tool install git+https://github.com/grimaldost/mantis-research
```

This puts two commands on your `PATH`: **`mantis`** (the CLI) and **`mantis-mcp`**
(the stdio MCP server agents connect to). Or run it without installing:

```bash
uvx --from git+https://github.com/grimaldost/mantis-research mantis research "…"
```

Or add it as a dependency of another project
(`uv add git+https://github.com/grimaldost/mantis-research`), or work from a
clone for development (`git clone … && uv sync`, then `uv run mantis …`). The
installed tool reads `OPENROUTER_API_KEY` from the environment; a clone also
reads a local `.env`.

## Quickstart — one question

```bash
# After `uv tool install …` (above), set your OpenRouter key in the environment:
export OPENROUTER_API_KEY=sk-or-...      # Windows: setx OPENROUTER_API_KEY sk-or-...

# Research a question end-to-end; prints a result manifest (JSON) to stdout:
mantis research "How does ISO 20022 migration work for correspondent banking?"

# Validate the plumbing offline first (no model calls):
mantis research "…" --dry-run
```

(From a clone instead of an install: `uv run mantis research "…"`, with the key
in a local `.env` copied from `.env.template`.)

Assurance tiers select how far the pipeline runs:

| `--assurance` | Stages |
|---|---|
| `fast` | research → synthesis (+ sidecar) |
| `standard` (default) | + adversarial falsification |
| `high` | + claude-prior baseline + gated evaluation |

Other flags: `--substrates openai,deepseek,google,perplexity` (the default Path
B set, each resolved to the vendor's newest frontier model), `--primary
openrouter:openai` (which brief anchors the synthesis), `--journal` (also emit
a mantis-ingestion journal), `--batch-name`, `--dry-run`.

The manifest lists every output path (briefs, synthesis, sidecar, falsification,
evaluation), each stage's exit code, and best-effort token/cost totals.

## Serve to agents (MCP tool + plugin)

Agents consume the tool through a local **stdio MCP server** exposing a
`research` tool, packaged as a **Claude Code plugin**
([ADR-0009](docs/adr/0009-agent-serving-via-mcp-plugin.md)):

```bash
# Register the installed server in your Claude Code stack (after `uv tool install`):
claude mcp add mantis-research --scope user \
  --env OPENROUTER_API_KEY=$OPENROUTER_API_KEY -- mantis-mcp

# …or install the bundled plugin from a clone (per session):
claude --plugin-dir /path/to/mantis-research

# …or run the stdio server directly — installed, or from a clone:
mantis-mcp
uv run python -m mantis_research.interface.mcp
```

The agent calls the `research` tool (`question`, `assurance`, optional
`substrates` / `dry_run`) and gets back the run manifest plus the sidecar's
`claims` / `divergences` / `verification_queue` (bounded to the MCP result-size
budget), with synthesis and briefs referenced by path. Because the server runs
locally, its synthesis stages inherit your authenticated `claude` seat (see
Requirements). Reference skill: `skills/research/SKILL.md`.

## The epistemic sidecar

Each synthesis writes `<stem>.sidecar.json` next to the markdown brief — the
agent-consumable contract ([ADR-0003](docs/adr/0003-epistemic-sidecar-artifact.md),
schema in `core/sidecar.py`, `sidecar_version: 1`):

- **model-authored** — `claims`, `divergences`, `verification_queue`,
  `agreements_worth_verifying`, `coverage_notes`.
- **runner-authored** — run identity, `sources`, and `provenance` (durations,
  token/cost), merged in after the model's JSON validates.

An agent consumes the sidecar for structured signal and reads the markdown only
when it needs the prose.

## Batch mode

For a curated set of topics, author a v2 batch config (see `config/*.json`) and
run stages explicitly:

```bash
uv run python -m mantis_research run openrouter    config/<batch>.json
uv run python -m mantis_research run synthesis     config/<batch>.json
uv run python -m mantis_research run falsification config/<batch>.json
uv run python -m mantis_research status            config/<batch>.json
uv run python -m mantis_research monitor synthesis
```

Every stage is resumable: re-run the same command and topics already `done` are
skipped. `--only <ids>` re-runs a subset; `--force` clears state and re-runs.

| Stage | Subcommand |
|---|---|
| Research (Claude CLI) | `run claude` |
| Research (Gemini CLI, legacy) | `run gemini` |
| Research (OpenRouter HTTP) | `run openrouter` |
| Synthesis + sidecar (+ optional journal) | `run synthesis` |
| Journal augmentation | `run journal-passes` |
| Falsification | `run falsification` |
| Claude-prior baseline | `run claude-prior` |
| Evaluation | `run evaluation` |

### Config knobs worth knowing

- `runner.layout: 'legacy' | 'batch'` — `legacy` (default) uses the flat output
  directories; `batch` scopes a run's state/outputs/transcripts under
  `<batch_name>/` so runs never collide ([ADR-0006](docs/adr/0006-batch-scoped-run-layout.md)).
- `models.primary: 'claude' | 'openrouter:<subslug>'` — which research brief
  anchors the synthesis; `openrouter:<sub>` is Path B, no promote script
  ([ADR-0005](docs/adr/0005-primary-brief-selection-in-config.md)).
- `topics[].research_prompt` — one prompt inherited by any research subsession
  that omits its own, so a multi-substrate topic isn't N verbatim copies
  ([ADR-0008](docs/adr/0008-research-prompt-templating.md)).

## Architecture

Functional core + imperative shell:

```
src/mantis_research/
├── core/          # PURE logic (no network/subprocess I/O): state, retry,
│                  # prompts, config schema, sidecar schema, path resolvers
└── interface/     # I/O adapters and entry points
    ├── adapters/  # provider drivers (claude_cli, gemini_cli, openrouter_http)
    ├── stages/    # one Stage per pipeline phase (Protocol-typed)
    ├── orchestrator.py  # generic asyncio.TaskGroup runner
    └── cli/       # typer entry points (run / research / status / monitor)
```

Core purity (no I/O in `core/`) is machine-enforced by
`scripts/check_core_purity.py`. The architecture invariants are recorded in
[ADR-0001](docs/adr/0001-architecture-invariants-baseline.md).

## Development

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src                       # primary type checker
uv run python -m pytest -q
uv run python scripts/check_core_purity.py
uv run python -m pre_commit run --all-files
```

(`mypy` is a CI-only secondary fallback and is not installed locally.)

This project is developed under a governed method — decisions are ADRs
(`docs/adr/`), changes are specified and pre-mortem-certified before
implementation, and the pipeline is decomposed into a reviewed PR series. See
`docs/method/` and `docs/specs/`.

## Cost and subscription notes

Research substrates bill through OpenRouter (roughly a few dollars per
multi-substrate question). Synthesis, journal, falsification, evaluation, and
claude-prior run on the Claude Code CLI against your Claude subscription. The
manifest and per-subsession state record token/cost so you can see what a run
cost.

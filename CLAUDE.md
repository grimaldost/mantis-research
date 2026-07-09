# Claude Code context — mantis-research

## Project shape

Deep-research tool for agents (ADR-0002): one question fans out across
substrate-diverse models, the synthesis preserves their disagreements, and
every run emits a machine-readable epistemic sidecar. Drives Claude Code CLI,
Gemini CLI (legacy), and OpenRouter HTTP through staged runs; outputs also
double as reference material for downstream agentic-memory ingestion (an
optional sink, not the primary purpose).

Docs map: `docs/README.md` — architecture (`docs/architecture.md`), operator
guide (`docs/running-batches.md`), config reference (`docs/batch-config.md`),
contributor guide (`CONTRIBUTING.md`). When this file and those disagree, the
docs are the home — fix this file.

**Layout** — application layout (functional core + imperative shell):

```
src/mantis_research/
├── core/          # PURE logic (no I/O): state, retry, prompts, config schema
└── interface/     # I/O adapters and entry points
    ├── adapters/  # provider drivers (claude_cli, gemini_cli, openrouter_http)
    ├── stages/    # one Stage per pipeline phase, binds prompt + adapter
    ├── orchestrator.py  # generic asyncio.TaskGroup runner
    └── cli/       # typer entry points
```

## Build / test commands

```bash
uv sync                      # install all deps (PEP 735 default group)
uv run pytest                # run tests
uv run ruff check src tests  # lint
uv run ruff format src tests # format (single-quotes for code, double for docstrings)
uv run ty check src          # type check (Astral's ty, primary)
uvx mypy src                 # mypy cross-check (not in the dev group; no hosted CI)
uv run python scripts/check_core_purity.py  # invariant I1: no I/O imports in core/
uv run pip-audit             # CVE scan
uv run python -m pre_commit run --all-files  # all hooks (ruff-format, ruff, core-purity)
```

## Code style

- **Single quotes for code, double for docstrings** (ruff-enforced both ways).
- `from __future__ import annotations` at module top (until project bumps to 3.14+).
- `typing.Protocol` for interfaces, dataclasses for data, pydantic v2 for schemas.
- `asyncio.TaskGroup` over `asyncio.gather`.
- Structured logging via `structlog` — never `print` in src/ (ruff `T20` enforces this).
- pydantic-settings for config — never `os.getenv` in src/.

## Architecture invariants

1. **`core/` has no I/O.** No subprocess, no httpx, no file writes outside pure helpers.
   I/O lives exclusively in `interface/adapters/` and `interface/stages/`.
2. **Stages are Protocol-typed.** Adding a new stage = new module under
   `interface/stages/` implementing the `Stage` Protocol from `core/stage.py`.
3. **Adapters are Protocol-typed.** Adding a new provider = new module under
   `interface/adapters/` implementing the `ProviderAdapter` Protocol.
4. **State files on disk are stage-specific JSON.** The on-disk schema must be
   stable across releases — new fields default-Optional, never rename.
5. **Resumability is a feature.** Every stage must be idempotent on `--force`
   and resumable from its state directory after interruption.
6. **Legacy artifacts stay readable.** Output/state trees from past batches are
   never migrated in place; new layouts are opt-in (ADR-0006).

## Pipeline stages

| Stage | Subcommand | Outputs to (legacy layout) | State at (legacy) |
|---|---|---|---|
| 1 | `mantis run claude` | `research-outputs/` | `state/` |
| 2a | `mantis run gemini` | `research-outputs-gemini/` | `state-gemini/` |
| 2b | `mantis run openrouter` | `research-outputs-openrouter/` | `state-openrouter/` |
| 3 | `mantis run synthesis` | `research-outputs-synthesis/` + `journals/` | `state-synthesis/` |
| 3.5 | `mantis run journal-passes` | `journals/*-augmented.md` | `state-journal-passes/` |
| 4 | `mantis run falsification` | `research-outputs-falsification/` | `state-falsification/` |
| 5 | `mantis run evaluation` | `evaluations/` | `state-evaluation/` |
| 5-input | `mantis run claude-prior` | `claude-prior-baselines/` | `state-claude-prior/` |

All stages are packaged `mantis run <stage>` subcommands (see
`interface/cli/dispatch.py` `STAGE_REGISTRY`). Paths above are the default
`legacy` layout; `runner.layout: 'batch'` scopes them under
`state|outputs/<batch_name>/<stage>/` plus `transcripts/<batch_name>/`
(full table: `docs/running-batches.md` § Where files land).

### Operating a batch

Dry-run first to validate orchestration without spending model calls, then run
for real; resume is just re-running the same command (topics already `done` are
skipped, everything else is re-attempted). Failed / rate-limited topics can be
re-run in isolation with `--only`:

```bash
uv run python -m mantis_research run claude config/<batch>.json --dry-run
uv run python -m mantis_research run claude config/<batch>.json
uv run python -m mantis_research run claude config/<batch>.json --only 42 --only 31
```

Rate-limit backoff (30 min) and generic-failure backoff (5 min) are
interruptible with Ctrl+C, which stops scheduling new topics, finishes
in-flight ones, saves state, and exits with a per-status summary.

## Interface gating (.env)

Settable in `.env`:

- `DISABLED_STAGES=<comma,separated>` — refuses to dispatch listed stages,
  fail-fast at the CLI before any config is read. Valid names are the
  `STAGE_REGISTRY` keys: claude, gemini, openrouter, synthesis,
  journal-passes, falsification, evaluation, claude-prior. **This machine's
  `.env` sets `DISABLED_STAGES=gemini`** (Gemini Advanced subscription dropped
  2026-05-04) — use Gemini-via-OpenRouter (`auto:google`) in batch configs
  instead. The package default disables nothing.

Other env vars: `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`,
`MANTIS_HTTP_REFERER`, `MANTIS_APP_TITLE`, `LOG_LEVEL`. See `.env.template`.

## Request-level entry + config knobs

- `mantis research "<question>"` — one-shot: builds a single-topic batch config
  in memory and runs the stage sequence in-process. `--assurance
  fast|standard|high` picks the depth; prints a manifest JSON. (ADR-0004.)
- `runner.layout: 'legacy' | 'batch'` — `legacy` (default) = the flat output
  dirs every committed config uses; `batch` scopes state/outputs/transcripts
  under `<batch_name>/`. Resolvers live in `core/paths.py` (`run_*` +
  `RunDirs`). (ADR-0006.)
- `models.primary: 'claude' | 'openrouter:<subslug>'` — which brief the
  synthesis treats as primary. `openrouter:<sub>` is Path B without the
  deprecated `_promote_or_to_primary.py` script. (ADR-0005.)
- `topics[].research_prompt` — a topic-level prompt inherited by any research
  subsession that omits its own `prompt`. Resolution keys on **presence**
  (`is not None`): an explicit empty-string prompt is kept. (ADR-0008.)
- Each synthesis emits `<stem>.sidecar.json` (schema `core/sidecar.py`,
  `sidecar_version: 1`) — the agent-consumable epistemic contract. (ADR-0003.)

Decisions are recorded as ADRs in `docs/adr/`; the pivot spec + method live in
`docs/specs/` and `docs/method/`.

## Serving agents (MCP server + plugin)

The tool is served to agents as a **local stdio MCP server** exposing a
`research` tool, packaged as a **Claude Code plugin** (ADR-0009, spec
`docs/specs/0002-agent-serving-mcp-plugin.md`).

- **Server:** `interface/mcp/` — `build_server()` registers the async `research`
  tool; `python -m mantis_research.interface.mcp` runs it over stdio. The
  tool wraps `run_research()` (`interface/research_service.py`, the shared
  orchestrator extracted from `mantis research`) and returns the run manifest +
  the sidecar's claims / divergences / verification_queue (bounded to the MCP
  size budget via `core/sidecar.py::project_for_agent`), with synthesis + briefs
  by path.
- **Plugin:** `.claude-plugin/plugin.json` bundles the server inline (launched
  via `uv run --project ${CLAUDE_PLUGIN_ROOT} python -m …mcp`); the reference
  skill is `skills/research/SKILL.md`. Install for local testing with `claude
  --plugin-dir .`.
- **Local-first:** the synthesis-family stages drive the local `claude` CLI, so
  the server must run co-located with an authenticated Claude Code seat; a
  seatless/remote deployment (`ANTHROPIC_API_KEY` synthesis) is deferred
  (ADR-0009). The tool handler runs `run_research` off the event loop via
  `asyncio.to_thread` (`dispatch_stage_config` nests `asyncio.run` per stage).
- **Logs go to stderr, never stdout** (`core/logging.py`) — stdout carries the
  stdio MCP JSON-RPC stream and the `mantis research` manifest.

## Playbooks

Markdown reference docs in `prompts/playbooks/` — these are the canonical
specs for prompt authoring. When changing a default prompt template in
`src/mantis_research/core/prompts.py`, update the corresponding playbook.

Key playbooks:

- `prompts/playbooks/research-path-recommendation.md` — **Path B is the
  default** (4 OR research substrates + Claude CLI synthesis). Path A
  (Claude-CLI research) only for narrow cases.
- `prompts/playbooks/model-recommendations.md` — substrate cheat sheet
  by topic class. Start from the 4-substrate default template; drop Sonar
  for stable methodology/math topics.

## Examples

- `config/example-batch.json` — a two-topic Path B batch demonstrating the
  config schema (full reference: `docs/batch-config.md`). Copy and edit for
  your own runs, or use `mantis research "<question>"` for a one-shot request.

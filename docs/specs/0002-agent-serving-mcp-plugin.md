# Spec — Agent-serving via an MCP server in a Claude Code plugin

- **Date:** 2026-07-03
- **Status:** done
- **Audience:** the implementing PR series + the blind pre-mortem reviewer
- **Output artifact(s):** `src/mantis_research/interface/research_service.py`, `src/mantis_research/interface/mcp/`, `.claude-plugin/plugin.json`, `.mcp.json`, `skills/research/SKILL.md`

## Context

ADR-0009 decided how agents consume this tool: a **local stdio MCP server**
exposing a `research` tool, packaged as a **Claude Code plugin**, built
MCP-first. ADR-0004 added the `mantis research` façade and the in-memory-config
seam `dispatch_stage_config` (`src/mantis_research/interface/cli/dispatch.py:196`)
expressly so an MCP tool could wrap that logic. ADR-0003 made the epistemic
sidecar the agent-consumable return contract. This spec implements ADR-0009 over
that seam.

The pipeline is local-first: the synthesis-family stages shell out to `claude
-p` and consume the host's Claude subscription seat, so a local stdio subprocess
inherits that auth with no extra wiring. OpenRouter research is portable HTTP.

## Goal

Ship a local stdio MCP server whose `research` tool runs the existing pipeline
(through an extracted `run_research()` orchestrator) and returns a bounded,
agent-facing result built from the run manifest plus the epistemic sidecar,
distributed as a Claude Code plugin.

## Gate commands

All must exit 0 (the mantis-research gate battery, `docs/method/definition-of-done.md`):

- `uv run ruff format --check src tests`
- `uv run ruff check src tests`
- `uv run ty check src`
- `uv run python -m pytest -q`
- `uv run python scripts/check_core_purity.py`

`mypy` is CI-only and is not run on this machine. Direct `.exe` shims are blocked
by Windows Application Control here — every tool is invoked via `uv run python -m`.

## Non-goals

- **Remote / seatless deployment** and the `ANTHROPIC_API_KEY` synthesis fallback —
  ADR-0009 deferred these; the server is local-first only.
- **Any change to the stages, adapters, orchestrator, or the on-disk state /
  sidecar schema.** This spec adds a wrapper surface, not pipeline behavior.
- **Concurrent multi-provider execution** — an ADR-0004 consequence needing
  per-provider bulkheads first; unchanged here.
- **Marketplace publication mechanics** — the plugin is built and locally
  installable; publishing/distribution is out of scope.
- **A human-facing CLI redesign** — `mantis research` behavior is unchanged; §1
  is a transparent extraction.

## Invariants touched

- **I1 core purity** (ADR-0001) — all new code lives under `interface/`; any pure
  result-projection helper may live in `core/`, which stays I/O-free.
- **MCP tool contract additivity** (ADR-0009) — the `research` tool's argument
  schema and result shape become an agent-facing public contract, evolved
  additively (new optional arguments / result fields only, never a rename or a
  removal), the same discipline invariant I4 applies to on-disk schemas.

## Enforcement status

| Invariant | Status | Gate/mechanism |
|---|---|---|
| I1 core purity | enforced | `scripts/check_core_purity.py` (pre-commit + gate battery) |
| MCP tool contract additivity | review-only | `docs/method/review-checklist.md`; no machine gate (as with I4 schema additivity) |

## Concept → module map

| Concept introduced/changed | Module / file it lives in |
|---|---|
| `run_research()` shared orchestrator (extracted from `research_cmd`) | `src/mantis_research/interface/research_service.py` (to be created) |
| MCP stdio server + `research` tool registration | `src/mantis_research/interface/mcp/server.py` (to be created) |
| MCP module entry point (`python -m …interface.mcp`) | `src/mantis_research/interface/mcp/__main__.py` (to be created) |
| Bounded agent-facing result assembly | `src/mantis_research/interface/mcp/server.py` (to be created) |
| Pure sidecar→result projection helper | `src/mantis_research/core/sidecar.py` |
| Plugin manifest + bundled MCP launch config | `.claude-plugin/plugin.json`, `.mcp.json` (to be created) |
| Reference skill | `skills/research/SKILL.md` (to be created) |

## Numbered sections

### §1 Extract `run_research()` into a shared service module

Move the request-level orchestration currently inline in `research_cmd`
(`src/mantis_research/interface/cli/research.py:142`) — config build,
per-stage dispatch loop, manifest assembly — plus its helpers (`build_config`,
`_manifest`, `_read_cost`, `_slugify`, `_substrate_entry`, the tier→stages map)
into a new `src/mantis_research/interface/research_service.py`, exposing
`run_research(question, *, assurance, substrates, primary, journal, batch_name,
dry_run, log_level) -> dict`. `run_research` is **synchronous** (it drives
`dispatch_stage_config`, which owns an `asyncio.run` per stage) and raises **no**
`typer.Exit`: input validation and exit-code mapping (invalid assurance → 2,
empty substrates → 2, ok → 0/1) stay in the `research_cmd` wrapper — which
becomes a thin typer shell that parses options, calls `run_research`, echoes the
manifest JSON, and sets the exit code — while `run_research` signals a bad
argument by raising `ValueError`. Because it is synchronous and nests
`asyncio.run`, callers must invoke it off any running event loop (see §3).
`build_config` **and** `_TIER_STAGES` stay importable from `cli/research.py` (via
re-export) and `research_cmd` stays defined there, so
`tests/integration/test_research_cmd.py:12` (which imports `_TIER_STAGES`,
`build_config`, `research_cmd`) and
`src/mantis_research/interface/cli/__init__.py:24` keep resolving.
**Reuse:** `src/mantis_research/interface/cli/dispatch.py::dispatch_stage_config`.
**Acceptance criterion:** `tests/integration/test_research_cmd.py` passes
unchanged, and a new test calls `run_research(...)` in dry-run against a clean
state dir and asserts the returned manifest dict has the `outputs`, `stages`,
`cost`, and `ok` keys, with `cost['available']` being `True` and
`cost['cost_usd']` equal to `0.0` (a dry run still writes the OpenRouter state via
the orchestrator's unconditional `save`, so `_read_cost` finds `1.json` and
reports it available with zero recorded cost).

### §2 Stand up the MCP server skeleton with its dependency

Add the `mcp` Python SDK to `pyproject.toml` dependencies. **Its API is a
hypothesis until source-read** — before §3/§4 build on it, pin the exact installed
surface against the real package (after `uv add mcp`): the import path (expected
`mcp.server.fastmcp.FastMCP`), how a tool is registered and how registered tools
are introspected, how the server runs over stdio (expected `.run(transport='stdio')`),
how a structured return value is produced, and whether a synchronous tool runs off
the event loop (in a worker thread) or inline on it — which decides §3's sync-vs-async
handler choice; record those pinned facts in the PR.
Then create the package `src/mantis_research/interface/mcp/__init__.py`, the
server module `src/mantis_research/interface/mcp/server.py` with a
`build_server()` (a local constructor that instantiates the SDK server and registers
a `research` tool), and the entry
`src/mantis_research/interface/mcp/__main__.py` that runs the server so
`python -m mantis_research.interface.mcp` starts it. The tool body may be a
stub returning a fixed payload at this section. **Acceptance criterion:** the pinned
SDK-API facts are recorded in the PR; a unit test calls `build_server()` and asserts
a `research` tool is registered via the installed SDK's own introspection API, and
`uv run python -c "import mantis_research.interface.mcp.server"` imports
without error.

### §3 Wire the `research` tool to `run_research` and assemble the structured result

The `research` tool handler accepts `question`, `assurance` (`fast|standard|high`),
and optional `substrates` / `primary` / `journal` / `dry_run`, and runs
`run_research(...)` **off the server's event loop**: `run_research` is synchronous
and `dispatch_stage_config` owns an `asyncio.run` per stage
(`src/mantis_research/interface/cli/dispatch.py:216`), so calling it directly
in an `async` handler awaited on the running loop raises `RuntimeError: asyncio.run()
cannot be called from a running event loop`. The handler therefore offloads the
call — either it is `async` and does `await asyncio.to_thread(run_research, ...)`, or
it is a synchronous tool the SDK runs in a worker thread; §2's SDK-pinning step
decides which. It then builds the agent-facing result: the manifest — including its
`cost` block, assembled by `_read_cost` at
`src/mantis_research/interface/cli/research.py:120` (the sidecar has no
top-level `cost` field; per-run cost lives in the manifest) — plus the sidecar's
structured content (claims, divergences, verification_queue) read from the emitted
`<stem>.sidecar.json`, with the synthesis and brief markdown referenced by path
rather than inlined. A pure projection helper on the sidecar model shapes the
structured part. **Reuse:** `src/mantis_research/core/sidecar.py::ResearchSidecar`.
**Acceptance criterion:** one test invokes the handler with `run_research`
monkeypatched to write a fake sidecar and return a manifest, asserting the result
carries the manifest, the sidecar's claims / divergences / verification_queue, the
manifest `cost` block, and a path (not inline text) for the brief; a second test
invokes the real handler inside a live asyncio event loop in dry-run (no monkeypatch)
and asserts it returns without `RuntimeError`.

### §4 Bound the tool result to the MCP size budget

Cap the inline structured content on **two** axes: a maximum number of claims /
divergences / verification items, AND a per-item plus total character budget over
their free-text fields (`Claim.text` (`src/mantis_research/core/sidecar.py:51`),
`Divergence.description`, `Divergence.sides` are unbounded free text, so a handful of
very long items overflows the MCP result-size limit that a count-only cap would
pass). When either axis trips, truncate — drop items beyond the count cap and clip
over-long text with a marker — set a truncation flag with the omitted count, and
always include the sidecar and synthesis paths so the agent can read the full
artifact. **Acceptance criterion:** a test with many small items asserts each inline
list is at most the count cap; a second test with few-but-huge items (one claim whose
`text` far exceeds the per-item budget) asserts the serialized result stays within the
total character budget, the truncation flag with the omitted count is set, and the
sidecar path is present.

### §5 Package the server as a Claude Code plugin

Add `.claude-plugin/plugin.json` (name, description, version) and the bundled MCP
launch config (`.mcp.json` or an inline `mcpServers` block) whose command runs
the server in-process via `uv run … python -m mantis_research.interface.mcp`
— never a blocked `.exe` shim (ADR-0004). The command MUST anchor the project
explicitly, because Claude Code launches a bundled MCP server from an unspecified
working directory and a bare `uv run` resolves the project (and its venv) from cwd:
bind `--project` (or `--directory`) to the plugin/repo root via the path variable
the installed Claude Code exposes to plugin MCP configs (e.g. `${CLAUDE_PLUGIN_ROOT}`),
pinned in this section against the installed client. **Acceptance criterion:** a test
loads `plugin.json` and the MCP launch config as JSON, asserts both are well-formed
and declare a server for the `research` tool, and asserts the launch command both
contains `-m mantis_research.interface.mcp` and carries an explicit
project/directory anchor (not a bare `uv run`).

### §6 Reference skill, docs, and CHANGELOG

Add `skills/research/SKILL.md` documenting the `research` tool, the three
assurance tiers, one example invocation, and the local-seat requirement; add an
MCP / plugin subsection to `CLAUDE.md`; add an "MCP tool-contract additivity" item
to `docs/method/review-checklist.md` (the Enforcement-status table names that
checklist as the review-only mechanism for this invariant, so the line must
exist); add a CHANGELOG entry under a **new grouping for this agent-serving work**
— the current `Unreleased` block is scoped to the spec-0001 pivot series
(`CHANGELOG.md:10`), so this spec-0002 change gets its own labeled sub-section
rather than appending under that header. **Acceptance criterion:**
`skills/research/SKILL.md` exists and names the `research` tool and the
`fast|standard|high` tiers, `CLAUDE.md` gains an MCP / plugin subsection,
`docs/method/review-checklist.md` gains an MCP tool-contract-additivity item, and
the CHANGELOG gains an entry under a distinct agent-serving grouping (not under the
spec-0001 pivot heading).

## PR ↔ section manifest

| PR | Implements section | One concern? |
|---|---|---|
| PR01 | §1 | yes |
| PR02 | §2 | yes |
| PR03 | §3 | yes |
| PR04 | §4 | yes |
| PR05 | §5 | yes |
| PR06 | §6 | yes |

## Definition of Done (this spec)

- All six acceptance criteria met and every gate command green.
- `python -m mantis_research.interface.mcp` starts a stdio server that
  exposes the `research` tool.
- A `dry_run` invocation of the tool (or `run_research`) returns a valid manifest
  without spending model calls (the local smoke test).
- The plugin loads locally: `plugin.json` + the MCP launch config validate and
  name the `research` server.
- Release-notes-in-wave: the CHANGELOG "Added" entry and the `CLAUDE.md`
  MCP / plugin subsection land in the same wave as the code (§6).
- No change to the core-purity gate status; no on-disk state or sidecar schema
  change.

## Pre-mortem certification

- **Reviewer:** two blind `keel:pre-mortem-review` passes (non-author). Round 1 (combined DESIGN + SERIES) returned NEEDS-REVISION with FM-1..FM-9 (2 BLOCKER, 5 MAJOR, 2 MINOR); all folded. Round 2 (convergence, attacking round 1's folds under the rising bar) returned CONDITIONAL-CERTIFY: 8 of 9 folds verified clean, one surviving MAJOR (FM-A) — the FM-9 fold had inverted the dry-run cost assertion — plus two advisories (FM-B, FM-C).
- **Verdict:** CERTIFIED — FM-A corrected (a dry run DOES write the OpenRouter state via the orchestrator's unconditional `save`, so `_read_cost` reports `available: True, cost_usd: 0.0`; §1's assertion and the FM-9 ledger row are fixed) and the FM-B/FM-C advisories folded (§2 pins the SDK sync-tool threading fact; §6 adds the review-checklist item). No blocking failure mode remains after round 2.
- **Operator:** n/a (round 2's CONDITIONAL-CERTIFY was resolved by applying the single surviving MAJOR fix, not by deferring it).
- **Date:** 2026-07-03
- **Reviewed against:** the `mcp` Python SDK — API empirically pinned via an ephemeral `uv run --with mcp` probe (`mcp.server.fastmcp.FastMCP`, `@tool()`, `run(transport='stdio')`, sync `_tool_manager.list_tools()` introspection, structured `dict` output); §2 records these before §3/§4 build on them (FM-2).
- **Post-fold coherence:** re-read §1–§6 end to end across both rounds. FM-1 + FM-4 fold into §1 + §3; FM-5 + FM-7 into §3 + §4; FM-A corrected §1's dry-run assertion (grounded at `src/mantis_research/interface/orchestrator.py:182` — the unconditional dry-run `save` — and the existing `tests/integration/test_research_cmd.py:115`). No finding narrowed scope, so the §↔PR bijection (6/6) and the DoD are unchanged.
- **Failure modes considered & folded in:** round 1 FM-1..FM-9 + round 2 FM-A/FM-B/FM-C — all folded.

### Fold ledger

| Finding | Target section | artifact:line | Confirmed |
|---|---|---|---|
| FM-1 event-loop conflict (`asyncio.run` in a running loop) | §1, §3 | `src/mantis_research/interface/cli/dispatch.py:216` | yes |
| FM-2 `mcp` SDK capability claims unverified | §2 | `pyproject.toml:5` | yes |
| FM-3 re-export surface (`_TIER_STAGES` / `build_config` / `research_cmd`) | §1 | `tests/integration/test_research_cmd.py:12` | yes |
| FM-4 `typer.Exit` must not leak into the service | §1 | `src/mantis_research/interface/cli/research.py:163` | yes |
| FM-5 cost source (manifest block, not a sidecar top-level field) | §3 | `src/mantis_research/interface/cli/research.py:120` | yes |
| FM-6 plugin launch command needs a project anchor | §5 | `docs/specs/0002-agent-serving-mcp-plugin.md:180` | yes |
| FM-7 §4 must bound bytes, not only item counts | §4 | `src/mantis_research/core/sidecar.py:51` | yes |
| FM-8 CHANGELOG grouping (Unreleased scoped to spec 0001) | §6 | `CHANGELOG.md:10` | yes |
| FM-9 dry-run cost assertion (corrected to `available` is `True`, cost 0 — round 2 FM-A) | §1 | `src/mantis_research/interface/orchestrator.py:182` | yes |

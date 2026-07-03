# ADR-0009 — Serve the tool to agents via a local stdio MCP server, packaged as a Claude Code plugin

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

The pivot (ADR-0002) repositioned the tool as an agent-facing deep-research
tool; ADR-0003 made the epistemic sidecar the agent-consumable return contract;
ADR-0004 added the `mantis research "<question>"` façade and **explicitly
deferred** the agent integration surface: "an MCP tool is the natural agent
integration, but it would wrap exactly this command's logic; building the CLI
façade first gives both a human entry point and the seam MCP will call." This
ADR takes that deferred decision.

Two properties of the pipeline constrain the answer:

1. **The auth-seat split.** `synthesis` / `journal` / `falsification` /
   `evaluation` / `claude-prior` shell out to the `claude -p` CLI and consume
   the host machine's **Claude Code subscription seat**. OpenRouter research is
   portable HTTP (`OPENROUTER_API_KEY`). So synthesis can only run where an
   authenticated `claude` CLI lives — the tool is **local-first**. A host with
   no seat cannot synthesize without an `ANTHROPIC_API_KEY` (API auth, not
   subscription) or a redesign.
2. **A single request runs for minutes** (async `TaskGroup` orchestration) and
   returns a potentially large structured JSON sidecar.

The near-term consumer is Claude Code agents co-located with the seat (and, via
the same MCP unit, the Agent SDK and claude.ai connectors later). The
`dispatch_stage_config(name, cfg: BatchConfig) -> int` seam (ADR-0004) already
runs a stage from an in-memory config with no path read — the wrapper wraps
this, it does not re-implement orchestration.

## Decision

Expose the tool through a **local stdio MCP server** with one primary tool,
`research(question, assurance)`, and **package that server as a Claude Code
plugin**. Build the MCP server first (the substance); the plugin is the
distribution layer over it.

- **Core — the MCP server.** A stdio server (module inside this package, e.g.
  `python -m mantis_research.interface.mcp`) exposes a `research` tool
  whose arguments are the request-level knobs (`question`, `assurance:
  fast|standard|high`, and the same optional substrate/primary/journal tuning).
  It calls a `run_research(...) -> manifest_dict` orchestrator **extracted from
  `research_cmd`** (today the manifest is assembled inside the typer command;
  the extraction is a prerequisite so both the CLI and the MCP server share one
  tested path). The tool result is the manifest plus the structured sidecar
  content (claims / divergences / verification_queue), with the long markdown
  brief referenced by path to stay within MCP result-size limits.
- **Local-first, seat-inheriting.** Stdio is chosen precisely because a local
  subprocess inherits the host's authenticated `claude` CLI — the synthesis
  stages consume the subscription seat with no extra auth wiring, and stdio
  servers are exempt from the MCP idle timeout, so a multi-minute run is fine.
- **Distribution — the plugin.** A `.claude-plugin/plugin.json` bundles the MCP
  server (`.mcp.json` / inline `mcpServers`) so one `/plugin install` registers
  the `research` tool automatically, plus a thin reference skill (usage,
  examples, the assurance-tier map). Agents discover the tool via tool search;
  it also travels to the Agent SDK / claude.ai as the same MCP unit.

## Alternatives considered

- **Standalone MCP server, no plugin** — the server is the substance either way;
  a plugin only adds one-command install + marketplace distribution. Kept as the
  build order (MCP first) but not the final shape: the plugin wrapper is cheap
  and is the idiomatic install path, so ship it.
- **Skill-based delivery** — rejected: a skill loads its body into the session
  and a multi-minute `research` call would **block the agent's context** for the
  duration; skills also aren't auto-discovered as tools and are Claude-Code-only.
  A skill is kept only as optional reference material inside the plugin.
- **Bare CLI-shelling** (agents run `mantis research` via Bash) — rejected as the
  primary surface: it works today but has no tool discovery, no typed schema, and
  no portability to non-CLI agents. It remains a valid fallback for a terminal.
- **Remote MCP with API-key synthesis** — deferred, not rejected: running
  synthesis on a seatless host needs an `ANTHROPIC_API_KEY` branch (API auth,
  different cost model) or synthesis-via-SDK, and there is no concrete remote use
  case yet. A future ADR revisits portability if one appears.

## Consequences

- Agents get one discoverable, typed `research` tool that returns the epistemic
  sidecar — the pivot's agent-consumable contract now has an agent-native caller.
- **A new public contract appears: the MCP tool schema and result shape.** Like
  the on-disk schemas (I4) and the sidecar (ADR-0003), it must evolve additively
  — new optional arguments/result fields, never a rename or a removed field —
  because agent callers will depend on it.
- `run_research(...)` must be extracted from `research_cmd` before the server can
  wrap it; the CLI then calls the same function (no behavior change intended).
- The local-seat coupling is now an explicit product property: the plugin's
  synthesis tiers require a co-located authenticated `claude` CLI. This is
  documented for installers; portability (API-key/remote) is out of scope here.
- Result-size handling (bounded structured return + brief-by-path) becomes a
  design requirement of the tool, not an afterthought.
- Depends on ADR-0004 (the seam), ADR-0003 (the sidecar as the return payload),
  and the Windows-Application-Control note in ADR-0004 (wrap in-process Python,
  never a blocked `.exe` shim). Implementation is specified and built as a
  separate governed change (a [keel](https://github.com/grimaldost/keel) spec), where the tool schema, result shape,
  error mapping, and dry-run/timeout behavior are pinned and pre-mortemed.

# ADR-0004 — Request-level entry point (`mantis research`) as a façade over stages

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

The only way to run the pipeline is batch-major: author a JSON config (in
practice via a one-off builder script), then invoke each stage as a separate
subcommand in order. Agent consumers (ADR-0002) think request-level: one
question, one call, one result. They will not author configs or sequence five
subcommands.

## Decision

Add `mantis research "<question>"`: a typer command that builds a single-topic
`BatchConfig` in memory (batch-scoped layout per ADR-0006, auto-generated
batch name), expands the question into per-substrate prompts via the config
templating of ADR-0008, runs the existing stages sequentially in-process
(research → synthesis+sidecar → optional falsification) through the same
dispatch/orchestrator path the subcommands use, and prints a result manifest
JSON (paths to briefs, synthesis, sidecar, falsification; totals for duration
and recorded cost) to stdout. An `--assurance` flag selects the stage subset:
`fast` = research + synthesis; `standard` (default) = + falsification;
`high` = + evaluation with claude-prior baseline. The journal turn defaults
OFF here (ADR-0002) and ON remains the batch-config default.

## Alternatives considered

- **A second orchestrator for one-shot runs** — rejected: duplicates the
  retry/state/progress machinery; the existing orchestrator already handles a
  1-topic batch.
- **MCP server first** — deferred, not rejected: an MCP tool is the natural
  agent integration, but it would wrap exactly this command's logic; building
  the CLI façade first gives both a human entry point and the seam MCP will
  call.
- **Shell script wrapper over subcommands** — rejected: no typed config
  authoring, no manifest, spawns N processes, and Windows Application Control
  on this machine blocks `.exe` shims — in-process is the reliable path.

## Consequences

Agents (and humans) get one call from question to cross-checked synthesis.
Stage sequencing lives in one tested place. The command depends on ADR-0006
(layout), ADR-0008 (templating), and spec §15 (evaluation stages in the
package) for the `high` tier. Provider concurrency stays within one stage at a
time, so the existing single semaphore suffices; a future concurrent
multi-provider mode would need per-provider bulkheads before it ships.

# Architecture decision records

One numbered file per decision, in the format of
[`docs/method/adr-template.md`](../method/adr-template.md): status, date,
context, decision, alternatives considered, consequences.

ADRs are immutable records. When a decision changes, a **new** ADR names what
it supersedes; the old file keeps its content and gains only a status update.
Specs cite ADRs — and the I1–I6 invariant keys from ADR-0001 — instead of
re-deriving decisions.

## Index

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-architecture-invariants-baseline.md) | Adopt invariants I1–I6 (core purity, Protocol-typed stages/adapters, additive-only persisted schemas, resumability, legacy artifacts stay readable) as the project's coordinate system. | Accepted |
| [0002](0002-reposition-as-agent-researcher-tool.md) | The tool's primary purpose is deep research for agent consumers; mantis journal ingestion becomes an optional output sink. | Accepted |
| [0003](0003-epistemic-sidecar-artifact.md) | Every synthesis emits a versioned, machine-readable sidecar (`<stem>.sidecar.json`); the model authors the epistemic fields, the runner authors identity and provenance. | Accepted |
| [0004](0004-request-level-entry-point.md) | `mantis research "<question>"` is a façade that builds a one-topic config in memory and runs the existing stages; `--assurance` selects the stage subset. | Accepted |
| [0005](0005-primary-brief-selection-in-config.md) | `models.primary` selects which research brief anchors the synthesis, making Path B a config field instead of a file-shuffle script. | Accepted |
| [0006](0006-batch-scoped-run-layout.md) | `runner.layout: 'batch'` scopes a run's state/outputs/transcripts under `<batch_name>/`; `legacy` (the flat directories) stays the default. | Accepted |
| [0007](0007-typed-stage-context.md) | Stages receive validated `BatchConfig` / `TopicConfig` models across the orchestrator boundary, not dicts. | Accepted |
| [0008](0008-research-prompt-templating.md) | `topics[].research_prompt` is inherited by any research subsession that omits its own prompt; resolution keys on presence, never truthiness. | Accepted |
| [0009](0009-agent-serving-via-mcp-plugin.md) | Agents consume the tool through a local stdio MCP server exposing a `research` tool, packaged as a Claude Code plugin; the MCP contract evolves additively. | Accepted |

## Writing a new ADR

Copy [`docs/method/adr-template.md`](../method/adr-template.md) to the next
number. An ADR is warranted for any decision a future change could plausibly
relitigate: a new invariant, a public-contract change, a serving surface, a
default that users will build on.

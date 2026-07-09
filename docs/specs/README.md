# Specs

Execution-grade specifications for governed multi-PR changes, written to
[`docs/method/spec-template.md`](../method/spec-template.md): numbered
sections, gate commands, invariants touched, a PR ↔ section manifest, a
Definition of Done, and a pre-mortem certification. A spec passes the
Definition-of-Ready gate ([`docs/method/definition-of-ready.md`](../method/definition-of-ready.md))
before it is decomposed into PRs, and it is a historical record once executed —
like ADRs, specs are not edited after the fact.

## Index

| Spec | Change | Shipped in |
|---|---|---|
| [0001](0001-agent-researcher-pivot.md) | The agent-researcher pivot: epistemic sidecar, request-level entry point, run layouts, prompt templating, typed stage context, packaged evaluation stages, plus review remediations (19 sections). | 0.1.0 |
| [0002](0002-agent-serving-mcp-plugin.md) | Agent-serving: `run_research()` extraction, the stdio MCP server, result-size bounding, the Claude Code plugin, and the reference skill. | 0.1.0 / 0.1.1 |

Small changes don't need a spec — an ADR (when a decision is involved) plus a
normal PR is enough. The spec machinery earns its cost when a change
decomposes into several dependent PRs.

# Documentation map

Start with the [project README](../README.md) — what the tool is, install,
the one-question quickstart, serving to agents, and the sidecar contract.
This page says where everything else lives.

## By task

| You want to… | Read |
|---|---|
| Run one research question end to end | [README](../README.md), § Quickstart |
| Call the tool from an agent (MCP tool / plugin) | [README](../README.md), § Serve to agents, and [skills/research/SKILL.md](../skills/research/SKILL.md) |
| Run a curated multi-topic batch | [running-batches.md](running-batches.md) |
| Author or edit a batch config | [batch-config.md](batch-config.md), then [prompts/playbooks/](../prompts/playbooks/README.md) for prompt content |
| Pick substrates/models for a topic | [model-recommendations.md](../prompts/playbooks/model-recommendations.md) |
| Understand how the pipeline is built | [architecture.md](architecture.md) |
| See why a design decision was made | [adr/](adr/README.md) |
| Contribute a change | [CONTRIBUTING.md](../CONTRIBUTING.md) |

## Directory guide

| Path | Contents |
|---|---|
| [architecture.md](architecture.md) | How the pipeline is built: stages, adapters, state, layouts, contracts. |
| [running-batches.md](running-batches.md) | Operator guide for batch mode: environment, operating loop, resume semantics, where files land. |
| [batch-config.md](batch-config.md) | Reference for the v2 batch-config JSON schema. |
| [adr/](adr/README.md) | Architecture decision records (immutable; indexed in that README). |
| [specs/](specs/README.md) | Execution specs for governed multi-PR changes (immutable records). |
| [method/](method/README.md) | Tool-agnostic templates for the development method (ADR, spec, DoR, DoD, review checklist). |
| [feedback/](feedback/README.md) | Dogfooding feedback reports and their generated index. |
| [../prompts/playbooks/](../prompts/playbooks/README.md) | Canonical prompt-authoring specs, one per pipeline role. |
| [../skills/research/SKILL.md](../skills/research/SKILL.md) | The reference skill shipped with the Claude Code plugin. |

## Conventions

- **One home per fact.** Each topic is documented in one place; other
  documents link to it instead of restating it. If two documents disagree,
  the home named above wins — fix the other one.
- **ADRs and specs are records, not living docs.** They capture a decision or
  an executed change as it was. Corrections arrive as new ADRs that supersede
  old ones, never as edits.
- **Playbooks track `core/prompts.py`.** Changing a default prompt template
  means updating the matching playbook in the same change, and vice versa.
- **`CLAUDE.md` is agent context.** It compresses the operational surface for
  coding agents working on this repo. It duplicates by design, but must stay
  true — when it drifts from the homes above, the homes win.

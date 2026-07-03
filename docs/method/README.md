# Method toolkit

The portable kit that operationalizes the method (see the method doctrine). Copy these
into a new project. The kit embodies the method *and* the method upgrades.

## Portability slots → files

The method (§7) needs these slots filled in any project. Each maps to a template:

| Slot | Template | Notes |
|---|---|---|
| ADR home | `adr-template.md` | one numbered file per decision |
| Spec format | `spec-template.md` | numbered sections; DoR-ready by construction |
| Guardrails + gate commands | `definition-of-done.md` | the exit-of-review gate |
| Review checklist | `review-checklist.md` | injected into the reviewer, blocking |

## Upgrade artifacts

| Upgrade | Template |
|---|---|
| DoR gate | `definition-of-ready.md` |
| Pre-mortem | `pre-mortem-prompt.md` |
| Wave budget | `series-toml-skeleton.md` (`[budget]` block) |

## Using the kit in a new project

1. Copy `adr-template.md`, `spec-template.md`, the two gate checklists, and
   `review-checklist.md` into the project's docs.
2. Bind each slot to a concrete mechanism (CI command, script, agent).
3. Wire the gates: DoR before decomposition, DoD before merge.
4. An apply-method helper, if your toolchain provides one, walks an agent through this.

Source of truth for orchestration (`series.toml`, hooks, scoring) stays with
your series orchestrator — these templates link to it, they
don't restate it. Without an orchestrator, the templates still work as manual
checklists.

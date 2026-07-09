# mantis-research feedback — closing the agent-discoverability gap (0.1.1)

- **Date:** 2026-07-04
- **Tool/version:** mantis-research 0.1.1 (`.claude-plugin/plugin.json`, `pyproject.toml`),
  running as a Claude Code plugin installed from GitHub
  (`grimaldost/mantis-research`, marketplace-in-repo).
- **Context:** resumed an agent-discoverability audit of the `research` MCP tool
  + `skills/research/SKILL.md` — the plugin's entire agent-facing surface (no
  commands, no subagents). Found and closed 6 documentation gaps, shipped 0.1.1,
  then converted the repo into its own plugin marketplace so production installs
  are pinned to GitHub and decoupled from the local working tree.
- **Outcome:** a blind-agent probe (two independent runs) found that `primary`
  and `journal` — live, working tool arguments — carried **zero description
  anywhere** (schema or skill), and that the `substrates` vendor-slug vocabulary,
  cost/latency, negative triggers, and several sidecar fields were undocumented.
  None of this had been caught by R1 (pre-launch fresh-eyes review), R2
  (fresh-agent real-world test), or the 0.1.0 launch itself — because none of
  those three tested "can an agent discover and correctly use every feature from
  the docs alone", only "does it work". Closed all 6 gaps, re-probed to
  confirmation, shipped 0.1.1, and separately avoided shipping an unnecessary
  0.1.2 by verifying a plausible-but-wrong packaging theory against ground truth.

## What worked

- **The blind-probe technique found real, load-bearing gaps a working review
  missed.** Two independent `general-purpose` agents, given *only* the rendered
  tool schema + `SKILL.md` verbatim (no repo access), were asked to enumerate
  every parameter and mark anything the material didn't state as
  `UNDER-DOCUMENTED` rather than guess. Both converged on the same 6 gaps
  independently, and both explicitly said they'd leave `primary`/`journal` at
  their defaults forever because nothing justified changing them — i.e. an
  actual capability was dead for any agent that only reads the shipped docs.
- **Grounding before writing docs caught a real internal disagreement.** A
  parallel Workflow of 8 concurrent research agents extracted facts from the
  codebase (substrate vocabulary, `primary`/`journal` semantics, tier→stage
  mapping, cost/latency, the full sidecar schema, the exact FastMCP
  `Annotated[…, Field(…)]` idiom) before any prose was written. Two of the eight
  agents disagreed on whether `journal=True` does anything at the request-tool
  level; reading `research_service.py` + `synthesis.py` directly (rather than
  trusting either agent's claim) resolved it in ~2 minutes and avoided
  documenting a feature incorrectly.
- **The closing blind probe closed the loop empirically, not just by
  inspection.** After implementing the fix, I re-ran the same probe against the
  new surfaces; it marked all 8 checked items `DOCUMENTED` with the exact
  quoting sentence for each. This is a cheap, repeatable acceptance test for
  "did the doc fix actually land where an agent looks", distinct from — and a
  useful complement to — reading the diff.
- **`claude mcp list` as ground truth avoided a spurious 0.1.2.** Packaging the
  repo as its own plugin marketplace, `claude plugin details <plugin>` reported
  "MCP servers (0)" for the freshly-installed plugin, which looked like proof
  the inline `mcpServers` block in `plugin.json` wasn't being registered (all 3
  official reference plugins I checked use a separate `.mcp.json` instead). I
  was about to ship a 0.1.2 to move the declaration. Before doing that,
  `claude mcp list` showed the plugin's server `✔ Connected` under a
  `plugin:mantis-research:mantis-research` entry — the inline form works fine;
  "MCP servers (0)" is a display quirk of the `details` subcommand specifically.
  Checking the cheaper, more authoritative signal first saved an unnecessary
  release.

## Friction

- **[LOW]** No pre-existing `docs/feedback/` in this repo — this is the tool's
  first tool-feedback report. Created the directory this session.
- **[LOW]** The `feedback-targets` binding's `extras` for mantis-research cites
  `docs/method/reflection-triage.md` as the registered triage template. That
  file no longer exists — it was one of the private-tool-binding files removed
  during the P2 pre-launch trim (2026-07-03, commit range around `fc6e00a`).
  The binding table is stale; either restore a triage template at that path or
  update the binding to point at `session-workflow:feedback-triage`'s generic
  flow (which is what this report falls back to, per the skill's own guidance
  for a missing cited format doc).

## Misses

- **[MED] phase: pre-launch review / DoD.** The R1 fresh-eyes review and R2
  fresh-agent real-world test (2026-07-03) both verified "does the tool work",
  not "can an agent discover and correctly use every parameter from the shipped
  docs alone". Neither is a substitute for the other, but the project's
  pre-launch checklist (`docs/method/review-checklist.md` /
  `docs/method/definition-of-done.md`) had no item for the latter, so a
  documentation-completeness class of gap shipped in 0.1.0 and went undetected
  through an entire review + real-world-test + launch cycle.
- **[LOW] phase: schema authoring.** The original `research()` MCP tool
  signature (0.1.0) had bare, undescribed parameters for `substrates`,
  `primary`, and `journal` even though the function's own docstring and the
  skill both existed — nothing enforced "every schema parameter carries a
  `Field(description=...)`" at write time. The new regression test
  (`test_research_tool_schema_documents_every_parameter`,
  `tests/unit/test_mcp_server.py`) closes this going forward, but only for this
  one tool; it's a pattern other Claude Code plugin authors will hit too (see
  the companion craft-collection report).

## Vacuous gates

None observed — the gates that ran (ruff, ty, mypy, pytest, core-purity,
pre-commit) all did real work; the miss was a class of check none of them was
designed to perform (agent-facing documentation completeness is not a lint
rule).

## Proposed promotions / changes

1. **[MED]** Add a **"blind-agent discoverability probe"** step to
   `docs/method/definition-of-done.md` (or `review-checklist.md`) for any
   release that changes the MCP tool schema or `skills/research/SKILL.md`:
   spawn a fresh agent with *only* the rendered tool schema + skill body, ask it
   to enumerate every parameter and mark gaps as `UNDER-DOCUMENTED`, and require
   every item to come back `DOCUMENTED` before tagging. This is the concrete gap
   R1/R2 didn't cover (see Misses) and is now proven cheap (~2 parallel agent
   calls) and repeatable (used for both the finding and the closing
   verification this session).
2. **[LOW]** Fix the stale `feedback-targets` binding for mantis-research in the
   user's CLAUDE.md: `docs/method/reflection-triage.md` no longer exists
   post-P2-trim. Point the binding at `session-workflow:feedback-triage`'s
   generic flow, or restore a triage template at that path if a
   project-specific one is still wanted.
3. **[LOW]** The FastMCP `Annotated[T, Field(description=...)]` idiom (verified
   empirically against the installed `mcp` 1.28.1 SDK this session — defaults
   still work, the parameter stays optional, and the description surfaces in
   `list_tools()`'s `inputSchema`) is worth a short note in this repo's own
   `CLAUDE.md` "Code style" section so a future contributor adding a tool
   parameter reaches for it by default instead of rediscovering it.

## Cost

Not an engine/eval run; approximate agent-call economy for this round:

| Activity | Agents | Notes |
|---|---|---|
| Initial blind-probe pair (gap-finding) | 2 | `general-purpose`, ~39k tokens each, ~45–65s |
| Grounding Workflow (fact extraction before writing docs) | 8 concurrent | ~584k tokens total, ~170s wall-clock (parallel) |
| Closing blind probe (gap-closure verification) | 1 | ~41k tokens, ~62s |
| Plugin-packaging verification agent (MCP mechanism doc lookup) | 1 | ~57k tokens |
| OpenRouter research spend | 0 | none this round — all agent calls were Claude subagents; no `research` tool dry_run/real calls incurred OpenRouter cost beyond the free `dry_run: true` smoke tests |

No dollar OpenRouter spend this round (all verification calls used `dry_run`).
Main-loop + subagent Claude token spend was the dominant cost, concentrated in
the 8-agent grounding Workflow.

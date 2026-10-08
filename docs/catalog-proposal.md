# Proposed catalogue entry text

Text for the owner's tool-catalogue session to paste into this tool's
catalogue entry (`tools/mantis-research.toml`). This repo does not edit the
catalogue. The key source is the stack-radar repository
(github.com/grimaldost/stack-radar, read at commit `58a48ac`):
`src/stack_radar/radar_lib.py` (entry validation, `TELEMETRY_KEYS`,
`OPPORTUNITY_KEYS`) and `src/stack_radar/field_report.py` (how
`sessions_with_use`, opportunity sessions and `error_rate` are computed).

## 1. Exit criteria

This is a pre-registration for the owner's open decision on the cross-provider
check (keep or drop it: several non-Claude research briefs cross-checked
against each other). It is not the decision.

What the radar does with it. This entry is at `ring = "own"`. `radar_lib.py`
accepts `[pilot_exit]` on an own-ring entry and validates it (it requires
`review_after_days`, `adopt_if` and `decline_if`). `field_report.py` evaluates
the block only for `ring = "pilot"`; on any other ring it prints the block
verbatim and a note that the criteria are retained and not evaluated. So here
the block is a dated record. The numeric thresholds (`min_sessions_with_use`,
`max_error_rate`) and the `review_after_days` due check would be inert, so the
block below leaves the thresholds out and keeps the three keys the validator
requires.

Context. On 2026-10-07, 16 research-tier questions changed 0 verdicts. The
review flagged 50 suspected fabrications, almost all of them
mischaracterisations of real sources rather than invented ones. In 10 of the
16 runs, two of the three default substrates cited exactly the same pages
because both read one search index. The release that adds `search_engines`
(0.7.0) fixes that: each default substrate reads its own index, `run.json`
records a `search_engines` map (substrate to engine, null when web search is
off or the engine is unknown), and the manifest records a pairwise
`retrieval_overlap` Jaccard. The 10-question count therefore starts at the
first run whose record shows it: only runs whose `run.json` carries a
`search_engines` map with no null engine count. Records from before the change
have no such key, so they do not count.

```toml
# Pre-registration for the owner's open decision on the cross-provider check.
# Recorded, not evaluated by `radar field` on ring = "own". The decision is made
# by hand: count the next 10 questions run at a cross-checked tier whose run.json
# carries a search_engines map with no null engine, from the run records
# (<outputs_dir>/run.json), not from radar session counts.
# On 2026-10-07: 16 questions, 0 changed verdicts, 50 suspected fabrications
# (mostly mischaracterised real sources).
[pilot_exit]
review_after_days = 60
adopt_if = "keep the cross-provider check: over the first 10 questions at a cross-checked tier whose run.json carries a search_engines map with no null engine, counted by hand from run records, at least 1 confirmed error or changed decision was caught only by a non-Claude brief (cite the run), with the unconfirmed citations those briefs introduced reported as cost alongside."
decline_if = "drop the cross-provider check: over the first 10 questions at a cross-checked tier whose run.json carries a search_engines map with no null engine, counted by hand from run records, no confirmed error or changed decision was caught only by a non-Claude brief; the cross-check then reduces to the Claude brief plus its own verification queue."
```

Choices:

- No `min_sessions_with_use`. The radar's `sessions_with_use` counts any
  session that matches the entry: `research_status` polls, the `mantis` CLI
  including dry runs, and the skill. It does not track the 10-question window,
  so a threshold on it would measure something else.
- `review_after_days = 60` is a calendar backstop only. At the observed rate
  the 10 questions may not arrive in 60 days; if so the review reports the
  count so far and extends, rather than deciding on fewer.
- `decline_if` is the exact complement of `adopt_if`, so one count decides the
  outcome and not a judgement afterwards. A suspected or unconfirmed catch is
  not a catch: note it beside the count, and count the unconfirmed citations
  it introduced as cost.

## 2. Error rate and what it can measure

The entry carries no `max_error_rate` (see section 1). The radar still reports
an error rate for the entry, so the caveat belongs in the entry as a comment:

```toml
# Error-rate caveat. In the 2026-07-26..09-26 window the research tool's own
# calls errored 15 of 37; the radar's entry-wide figure (all matched tools, the
# CLI and the skill) was 15 of 110. The 15 are 14 client idle aborts on
# 0.1.2 / 0.3.0 and 1 resume refusal on 0.4.0. Since 0.4.0 a detached run's
# failure does not show as a tool error, and since 0.6.0 every seat-tier call
# detaches by default; research-tier and dry-run calls still block and fail as
# tool errors. A detached run's failure shows in research_status / run.json
# (ok, stage exit codes). An error rate read from tool results alone therefore
# measures transport, not outcome.
```

Proposal for the catalogue session: have the measure join each detached
handle to its run outcome. There is no `run_id` in the research result; the
join key is the `outputs_dir` (or `batch_name`) in the handle a detached call
returns, and the record is `<outputs_dir>/run.json` (`status`, `ok`, and the
exit code of each stage). Skip dry runs (`dry_run` true). Outcome rule for
the join, checked against `research_service.py` and `mcp/server.py` on main:

- Success: `status` is `complete`, `ok` is true and, for a tier that owes a
  sidecar (`produces_sidecar` true), `sidecar.status` is not `failed`.
- Everything else is a failed outcome: a `failed` record, `ok` false, a
  non-zero stage exit code, a failed sidecar, and a record still
  `dispatching` (an abandoned run) when the session ends.

Failures before dispatch (no local seat, bad arguments, a refused resume) still
come back as tool errors on a detached call, so the tool-result error rate
measures transport plus pre-dispatch refusals, not run outcomes. Until the
join exists, read the entry's error rate as a transport check and do not use
it as evidence on the cross-provider check.

## 3. Opportunity matcher

Add these two keys to the entry's existing `[telemetry]` table (`match`,
`match_skill`, `match_command`, `since`). They are not a second `[telemetry]`
header, which would be invalid TOML.

```toml
# OPPORTUNITY. A WebSearch call is a research question answered from one
# model's view, which is the occasion this tool applies to. WebFetch is left
# out: it is dominated by documentation lookups, which context7 already claims.
# The deep-research skill is the built-in alternative reached for the same need.
opportunity_match = ["WebSearch"]
opportunity_match_skill = ["anthropic-skills:deep-research"]
```

Notes:

- Known bias. This tool spawns `claude -p` sessions of its own, and some of
  them allow `WebSearch`: the falsification stage
  (`interface/stages/falsification.py`) and the Claude research stage
  (`interface/stages/claude_research.py`) pass `allowedTools` with `WebSearch`
  (the default in `ClaudeCliOptions`), and `claude_cli.py` passes
  `--session-id <uuid>` and never `--no-session-persistence`, so each spawn
  leaves a transcript. A spawned session that searches would count as an
  opportunity session, and the radar notes that headless spawns are
  transcripts too. Falsification runs at the `standard` and `high` tiers, so
  the bias grows with use: more runs add opportunity sessions the tool created
  itself, and `taken_ratio` drifts down. The claude-prior stage allows only
  `Write` and is not affected. This is read from the code and has not been checked
  against transcripts.
- Remedy, as a separate future change and not made here: either the
  single-turn stages pass `--no-session-persistence` (listed in `claude --help`
  as print-mode only; whether it combines with `--session-id` is unverified,
  and the synthesis stage resumes its session, so it must keep persistence), or
  the radar excludes sessions whose first prompt comes from this tool's stage
  prompts.
- context7 also lists `WebSearch` in its `opportunity_match`. The two
  denominators overlap on purpose: one search can be an occasion for either
  tool, and each entry's `taken_ratio` answers its own question. Read them
  side by side, not summed.
- The radar entry for repomix names this tool's research call as its own
  opportunity matcher. That is the reverse direction (repomix's intended
  consumer is this tool) and does not affect the matcher above.
- `WebSearch` is a coarse marker: many searches are lookups that need no
  cross-check. The `taken_ratio` will therefore be low even when the tool is
  used where it should be. Treat it as a trend across windows, not a target.

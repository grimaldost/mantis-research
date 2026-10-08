# Proposed catalogue entry text

Text for the owner's tool-catalogue session to paste into this tool's
catalogue entry (`tools/mantis-research.toml`). This repo does not edit the
catalogue. The key source is the stack-radar repository
(github.com/grimaldost/stack-radar, read at commit `58a48ac`):
`src/stack_radar/radar_lib.py` (entry validation, `TELEMETRY_KEYS`,
`OPPORTUNITY_KEYS`) and `src/stack_radar/field_report.py` (how
`sessions_with_use`, opportunity sessions and `error_rate` are computed).

## 1. Exit criteria

The owner decided the rule on 2026-10-08 for the cross-provider check (several
non-Claude research briefs cross-checked against each other, kept or retired).
The rule, as decided:

> For each batch of at least 8 questions costing at most US$0.40 each, keep the
> cross-provider check when at least 1 in 4 questions yields a weighty source
> found only by a non-Claude brief and confirmed on opening, or a changed
> decision. Unconfirmed citations from those briefs count as cost. Retire the
> check after two batches below the threshold.

Open point: the number of providers in the check (two or three) is decided
after the per-model search engines are fixed. They were fixed in 0.7.0.

What the radar does with it. This entry is at `ring = "own"`. `radar_lib.py`
accepts `[pilot_exit]` on an own-ring entry and validates it (it requires
`review_after_days`, `adopt_if` and `decline_if`). `field_report.py` evaluates
the block only for `ring = "pilot"`; on any other ring it prints the block
verbatim and a note that the criteria are retained and not evaluated. So here
the block is a dated record. The numeric thresholds (`min_sessions_with_use`,
`max_error_rate`) and the `review_after_days` due check would be inert, so the
block below leaves the thresholds out and keeps the three keys the validator
requires.

How a question is scored. For each question, open every citation in the
non-Claude briefs and class it: confirmed, does not support the statement,
dead, or blocked. A find counts only if all of these hold: the source is absent
from the Claude side's sources, by URL and by title; it is confirmed on opening;
it is an authoritative kind of source (official documentation, a specification
or changelog, a paper or standard, an engineering write-up with data, or a
maintainer-authored repository); and it bears on a load-bearing answer (it
contradicts the answer, adds a fact the answer lacked, or independently
corroborates a claim that rested on one source or none). Every proposed find
goes to an independent refuter and counts only if upheld. Citations classed
other than confirmed are the cost side of the rule.

Baseline. The batch of 2026-10-07 (mantis 0.6.1, research tier, 16 questions at
US$0.26-0.37 each) was scored with this procedure on 2026-10-08, after it ran.
Aggregate result:

- 13 of 16 questions met the find criterion (Wilson 95% interval 0.57-0.93).
- 0 questions changed a decision.
- 43 of 341 brief citations were not confirmed on opening: 13 did not support
  the statement, 5 were dead, 25 were blocked.
- Upheld finds were cited by the openai brief in 10 questions, google in 4 and
  deepseek in 3. On 0.6.1 deepseek and google shared one search index.

That batch was not pre-registered before it ran, so whether it counts as one of
the rule's batches is the owner's call. From 0.7.0 on, each default substrate
reads its own search index and `run.json` records the `search_engines` map
(substrate to engine, null when web search is off or the engine is unknown).
From 0.7.1, a brief also lists the citations a native search returns only as
API annotations (Google's does; on 0.7.0 the google brief carried no links), so
the manifest's pairwise `retrieval_overlap` covers every brief. Later batches
therefore record what the first one could not.

```toml
# The owner's decided rule for the cross-provider check (2026-10-08). Recorded,
# not evaluated by `radar field` on ring = "own". The decision is made by hand,
# batch by batch, from the run records (<outputs_dir>/run.json) and the scoring
# procedure in docs/catalog-proposal.md, not from radar session counts.
# Baseline, scored retroactively on 2026-10-08 (the 2026-10-07 batch, mantis
# 0.6.1; not pre-registered, so whether it counts is the owner's call): 13 of 16
# questions met the find criterion, 0 changed decisions, 43 of 341 brief
# citations unconfirmed on opening.
[pilot_exit]
review_after_days = 60
adopt_if = "keep the cross-provider check: in a batch of at least 8 questions costing at most US$0.40 each, at least 1 in 4 questions yields a weighty source found only by a non-Claude brief and confirmed on opening, or a changed decision. Unconfirmed citations from those briefs count as cost."
decline_if = "retire the cross-provider check after two batches (each of at least 8 questions costing at most US$0.40 each) below that threshold."
```

Choices:

- No `min_sessions_with_use`. The radar's `sessions_with_use` counts any
  session that matches the entry: `research_status` polls, the `mantis` CLI
  including dry runs, and the skill. It does not track batches or questions, so
  a threshold on it would measure something else.
- `review_after_days = 60` is a calendar backstop only. If a qualifying batch
  has not been scored by then, the review reports what exists and extends,
  rather than deciding on fewer than 8 questions.
- `decline_if` is not the complement of `adopt_if`: one batch below the
  threshold neither keeps nor retires the check. Retirement needs two such
  batches. A suspected or unconfirmed find is not a find: note it beside the
  count, and count the unconfirmed citations as cost.

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

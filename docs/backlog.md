# Improvement backlog

Leverage-ordered. The top of **Now** is the next thing to build; everything below
it is ordered by expected value per unit of effort, not by severity alone.

This is a living document, unlike the ADRs and specs next to it. Items are
appended with the next free ID and never renumbered; a shipped item moves to
**Landed** with the release or commit that closed it, so a reader can tell a
completed item from a dropped one.

## How to read an item

| Field | Meaning |
|---|---|
| **ID** | `MANT-Bnn`, stable for the life of the item. |
| **Claim** | One line: what changes and why it matters. |
| **Cause / evidence** | Where the finding came from, and what was checked in source. |
| **Change** | The proposed edit, with its home. |
| **Effort** | `S` ≈ one sitting · `M` ≈ a focused change with tests · `L` ≈ a campaign. |
| **Source** | `triage` (dogfooding reports) · `review` (feature review) · `research` (external briefs) · `cross-review` (cross-project consistency pass). |

Where the two internal sources disagree, the item says so rather than picking a
winner silently.

## Inputs

1. **Feedback triage, 2026-08-11** — nine dogfooding reports, 2026-07-04 to
   2026-08-11, clustered by underlying cause. Reports are cited by stem. Two
   stems are cited by date instead (`2026-07-10 mcp-idle-timeout report`,
   `2026-07-11 deep-review report`, `2026-08-10 six-topic-batch report`) because
   their original slugs name an environment-scoped internal tool that does not
   belong in this repo's text.
2. **Feature review, 2026-08-11** — an independent audit of every shipped
   surface against current model and harness capability, using the 19 on-disk
   runs and 15 sidecars as behavioural evidence. Cited as `feature review`.
3. **Ecosystem and landscape briefs, August 2026** — the native-capability
   baseline and the competitive landscape for multi-model research. Cited as
   `research`.
4. **Cross-project consistency review, 2026-08-11** — a pass over the sibling
   backlogs in the same collection of tools, reconciling items that name each
   other, solve the same problem twice, or disagree about who owns a shared
   contract. Cited as `cross-review`, and cross-repo items are cited by their
   own IDs (`KEEL-`, `CONV-`, `FATH-`, `CRAF-`). Its findings are recorded as
   notes on the items they touch; one incoming dependency is an item in its own
   right (MANT-B56).

Findings the operator reported directly, with no report behind them, are cited
as `operator observation`.

## Grounding corrections

Three claims in the inputs were checked against current source and are recorded
here so they are not re-derived:

- The sidecar's `question` is not empty — **`ResearchSidecar` has no `question`
  field at all** (`core/sidecar.py`). Consumers saw absence, not a blank value.
  This makes MANT-B06 a one-field addition in the runner-authored zone, additive
  under invariant I4, and it does not touch the model-authored zone that
  `extra='forbid'` validates.
- `.git/hooks/` is not empty — it holds the stock `*.sample` files and **no
  installed `pre-commit` hook**. The conclusion in MANT-B11 stands; the
  observation was imprecise.
- `core/progress.py` cannot feed an MCP progress channel. It is state-count
  aggregation for `progress.json` and has no notification role. MANT-B01 is new
  plumbing through the request context, not a rewire of an existing signal.

---

# Now

The tool's research output is repeatedly credited as decision-grade. Every item
here is in the delivery envelope around that output — the pipeline does not
complete over its own primary transport, and the artifacts it does produce are
written for the machine that made them.

**Empty as of the 0.2.0 wave.** Every item that stood here — MANT-B01 through
B08, plus B11 and B13 — is in **Landed** below. The delivery envelope is the
work that closed: the pipeline now reports progress over MCP, no wait outlasts
the caller, a run is named before it dispatches and can be resumed after an
interruption, a mute child is killed rather than left in flight, and the sidecar
carries the question and typed source provenance. Promote from **Next** when
this section is refilled.

**0.3.0 arrived from the field rather than from this list.** Two defects found
in use on 2026-08-11 — a dry run settling a topic, and the serving path
returning a briefs-only run as a result — were fixed directly and are recorded
in **Landed**. Neither had a backlog item, and neither was findable from one:
both are gaps between what a run reported and what it produced, which only real
use exposes. The new item they did generate is MANT-B57, in **Later**.

---

# Next

### MANT-B09 — Reconcile the default substrate set to one home

- **Cause / evidence.** The substrate default has three homes that disagree:
  `research_service._DEFAULT_SUBSTRATES` is `('openai', 'deepseek', 'google')`,
  `prompts/playbooks/model-recommendations.md`'s post-batch-44 default is a
  different four-substrate rotation, and the README's flag table is a third. The
  home the code reads is the one the evidence superseded. The repo has an
  explicit one-home-per-fact convention with a stated tiebreaker; it is not
  being applied to this fact.
- **Change.** Pick one home — the playbook is the natural owner, since it is
  where the per-substrate failure signatures live — and have the code read it or
  cite it. Then re-run the substrate audit: it is dated 2026-05-15 and the
  playbooks' own D6 says quarterly. Record in the playbook that divergence yield
  is not proportional to spend, so the cheap substrates stay in the default set
  on epistemic grounds rather than as budget filler — one substrate took 95% of
  spend while the cheapest supplied one side of two of five divergences
  (`2026-07-11 deep-review report`, `2026-07-25-community-tools-discovery-sweep`).
- **Effort.** S
- **Source.** review + triage (T6d)

### MANT-B10 — Execute what the docs teach, in the pre-commit lane

- **Cause / evidence.** `docs/method/definition-of-done.md`'s entire Docs gate is
  one line with no execution or measurement requirement, so commands, env var
  names, stage names and directory paths drift from the code. Six executable doc
  claims contradicted the code and survived two releases
  (`2026-07-09-docs-overhaul`). `scripts/check_core_purity.py` plus
  `.pre-commit-config.yaml` establish the script-in-hook precedent, so the
  mechanised rung is reachable rather than aspirational.
- **Change.** `scripts/check_docs_truth.py`: execute every command a doc teaches
  at the `--help` / `--dry-run` tier, and assert that every quoted env var,
  stage name and directory resolves in its defining module. Wire it into
  `.pre-commit-config.yaml` alongside the purity check. It replaces the one-line
  Docs gate rather than sitting beside it.
- **Effort.** M
- **Source.** triage (T6a)
- **Sequencing note.** This lands work *inside* `docs/method/`, which
  MANT-B48 proposes retiring. Move the concrete gate bindings to
  `CONTRIBUTING.md` first, or do both in one change.

### MANT-B12 — Recalibrate the quoted cost, latency and concurrency numbers to measured bands

- **Cause / evidence.** Quoted cost is 10–30× the measured band
  (`2026-08-10 six-topic-batch report`, confirmed by
  `2026-08-11-t7-scenarios-consumption`). The latency figure reads as
  research-dominated; observed, research is ~5.5 minutes and everything after it
  is local (`2026-07-11 deep-review report`). Concurrency behaviour is
  undocumented despite being measured clean at three-way
  (`2026-07-24-dispatch-research-batch`, `2026-07-30-finmodel-triple-research`).
- **Change.** In `skills/research/SKILL.md` and the README cost section, replace
  the "$1–6 per question" and undifferentiated "35–75 min" claims with measured,
  stage-resolved bands: roughly $0.15–0.25 for a focused technical question and
  $1–6 for broad or real-time ones; latency broken out by stage; CLI concurrency
  documented as safe at three or more. Keep the README's existing register —
  observed ranges from past runs, not a quote.
- **Effort.** S
- **Source.** triage (T6c, 4 reports)

### MANT-B14 — Measure whether the evaluation gate can reject anything

- **Cause / evidence.** The evaluation stage has run once in 19 runs, and that
  record is a vacuous-gate signature: verdict PASS, Q = 0.944, all three gates
  untriggered, five of six criteria at 3/3. Criterion C5 scores the presence of a
  section only the retired Path-A scaffold produced — and scored 3/3 anyway,
  which is direct evidence the rubric is not discriminating. The template's
  source blocks still name inputs a Path-B run does not produce, and it
  hardcodes an evaluator model literal the model overrode in the one real
  record. A gate that has fired once and passed at 94% has not demonstrated it
  can reject.
- **Change.** Replay the rubric against five archived syntheses plus two
  deliberately degraded ones (inject a fabricated citation; inject a vacuous
  claim). If gates 1 and 2 do not trigger on the degraded pair, the gate is
  decoration — retire it with MANT-B50. If they do, the rubric is already
  corrected.
- **Half of this landed in 0.2.0** (`ce73a95`). The three fixes that rested on
  inspection rather than on the replay are done: C5 scores actionable content
  instead of a retired section, the `claude-original` / `gemini-originals`
  blocks became one N-peer-brief block, and the hardcoded evaluator literal is
  gone. What remains is the measurement itself — can gates 1 and 2 reject a
  deliberately degraded synthesis — and it is what MANT-B50 waits on. The gates
  and verdict logic were left untouched so the replay measures the gate that has
  been running, not a new one.
- **Effort.** M
- **Source.** review
- **Note.** The triage corpus is silent on evaluation — no report exercised it —
  so this rests on the review's behavioural evidence alone. That is a reason to
  measure before deciding, not a reason to discount it.

### MANT-B15 — Measure whether the sidecar's item counts carry information

- **Cause / evidence.** Across all 15 sidecars the counts are uniform:
  divergences 3–8, verification queue 5–7, agreements 3–6. The synthesis prompt
  asks for "3–5 specific claims where the models disagree" and "2–3 non-trivial
  claims where they AGREE", so the observed counts track the prompt's own quotas
  almost exactly. The same prompt then says not to manufacture divergences to
  satisfy a count — prose asking the model to override a number the prompt
  supplies. Spot-checked content is substantive, so this is not obviously
  quota-filling, but as it stands the count carries no information.
- **Change.** Re-run five archived questions with the numeric quotas removed and
  compare counts and content against the archived sidecars. If counts collapse
  or scatter, the quotas were manufacturing signal; if they hold, the numbers
  are real and the prompt can drop them anyway. Fold the result into MANT-B05 if
  both are still open.
- **Effort.** M
- **Source.** review

### MANT-B16 — Record sidecar paths relative to the run root

- **Cause / evidence.** Absolute machine paths had to be hand-normalised when a
  frozen sidecar moved machines (`2026-08-11-t7-scenarios-consumption`).
- **Change.** Write `sources[].path` and `synthesis_path` relative to the run
  root, in the same write path MANT-B06 edits.
- **Effort.** S
- **Source.** triage (T4b)

### MANT-B17 — Flip the run-layout default to `batch` and say so

- **Cause / evidence.** `legacy` is documented as the default in both `CLAUDE.md`
  and the README, while `research_service.build_config` hardcodes
  `'layout': 'batch'` for every request-level run — and all 19 runs on disk are
  batch-scoped. The documented default is a layout nothing produces.
- **Change.** Make `batch` the default in code and docs. Keep the legacy
  resolver so old trees stay readable per invariant I6.
- **Effort.** S
- **Source.** review

### MANT-B18 — Extend the release probe from discoverability to completion

- **Cause / evidence.** The blind-agent probe that shipped with 0.1.1 covers
  whether an agent can *find* the parameters; it says nothing about whether the
  call *completes* (`2026-07-10 mcp-idle-timeout report`). The failure that has
  cost the most is on the second axis.
- **Change.** Make a blind-agent probe a release gate whenever the MCP schema or
  `skills/research/SKILL.md` changes, and require it to confirm the tool returns
  either a manifest or a structured, resumable timeout at its own default
  assurance. This displaces the one-line Docs gate that MANT-B10 mechanises.
- **Effort.** S
- **Source.** triage (T6b)

### MANT-B19 — Structured fields on verification-queue items

- **Cause / evidence.** One scripted pass over a verification queue resolved 5 of
  7 items and caught a repository that does not exist — the strongest measured
  payoff of any item still unbuilt. The items are free text, so every consumer
  re-parses them.
- **Change.** Optional `check_kind` (`repo_exists | metric | license |
  url_resolves`) and `target` on `VerificationItem`, with the sidecar prompt
  populating them. Additive under invariant I4; natural to ship alongside
  MANT-B07.
- **Effort.** S
- **Source.** triage (T4d, held at watch pending a second report — promoted here
  on the strength of the measured payoff and its shared edit site with B07)

### MANT-B20 — A batch entry point for `mantis research`

- **Cause / evidence.** `--parallel` exists on `mantis run <stage>` for batch
  configs, but `mantis research` takes one question and has no batch entry
  point, so every multi-question session hand-rolls a launcher: a shell loop
  plus a mid-batch cutover script (`2026-07-24-dispatch-research-batch`), three
  hand-managed background runs (`2026-07-30-finmodel-triple-research`), six
  detached processes monitored by log and pid (`2026-08-10 six-topic-batch
  report`). Filed as a proposal once; paid for in three sessions.
- **Change.** `mantis research --questions-file <toml|jsonl>` with `--parallel N`
  (default 3, sequential fallback), in `interface/cli/research.py`.
- **Effort.** M
- **Source.** triage (T7a)
- **Sequencing note.** After MANT-B01. The hand-rolled detached launcher is
  currently the standing workaround for the transport defect; fixing that
  changes what this surface should look like.

### MANT-B56 — Record the incoming consumer KEEL-B31 creates, and hold its second call pattern

- **Cause / evidence.** KEEL-B31 deletes that repo's bespoke external-review
  scripts and names this tool as their replacement. That makes it the first
  consumer of this tool outside the operator's own sessions, and it arrives with
  a dependency and a shape. The dependency: that deletion cannot land until
  MANT-B01 and MANT-B02 do, because a review that aborts at the client's idle
  window is worse than the scripts it would replace, and the consuming repo has
  no way to tell an abort from a hang. The shape: the enrichment panel is a
  second call pattern alongside research — the tool is called to enrich an
  artifact that already exists, not to answer a fresh question.
- **Change.** Record the dependency in both directions so neither side finds it
  late: this item is the note on this side, and MANT-B01/B02 are the blocking
  edge on the other. Keep the enrichment pattern in view when MANT-B01's
  progress surface and MANT-B04's default assurance are settled — an enrichment
  call is shorter and more frequent than a research call, so a default tuned
  only to the research shape will be wrong for it, and the progress stages a
  panel wants to see are not the same stages. No code change is implied yet;
  the second call pattern is captured before it is designed for rather than
  after.
- **Effort.** S
- **Source.** cross-review
- **The blocking edge cleared in 0.2.0.** MANT-B01 and MANT-B02 have landed, so
  KEEL-B31's deletion is no longer blocked on this side. The second call pattern
  is still uncaptured in design: an enrichment call is shorter and more frequent
  than a research call, so `fast` as the default (MANT-B04) suits it, but the
  progress stages a review panel wants to see are not the research stages, and
  `core/progress.py`'s `RunEventKind` is now the place that would name them.

---

# Later

### MANT-B57 — Make it impossible for a test to reach a live provider

A test written during the 0.3.0 wave called `run_research(dry_run=False)` with
the dispatch seam unpatched. It passed — by fanning out to three OpenRouter
substrates and then driving a real `claude` synthesis and sidecar turn. $0.070
and about eight minutes of seat time, spent by `uv run pytest`. The only reason
it was noticed is that it later timed out under a narrower invocation; a
green suite reported nothing. `tests/conftest.py` already keeps the suite off
the machine's real Claude seat with an autouse fixture, so the shape of the
guard is established — what is missing is the same guard for the paid path.
Blank `settings.OPENROUTER_API_KEY` per test by default, with the adapter tests
that need a key opting back in, so a test that reaches the real provider fails
on preflight instead of billing. Held out of the 0.3.0 wave deliberately: it
touches the openrouter adapter tests, and a defect-fix release is the wrong
place to churn them. **S** · *operator observation*

### MANT-B21 — Stamp the assurance tier in the synthesis header

A `fast` synthesis is structurally indistinguishable from a falsified one
(`2026-07-24-dispatch-research-batch`), so a consumer can equal-weight them. A
prominent "UNFALSIFIED (fast)" banner in the synthesis template fixes it. **S** ·
*triage (T4c)*

### MANT-B22 — Refuse to start a stage when its predecessor's artifact is absent

`core/stage.py`'s preflight is adapter-level — binary and credential
availability — so nothing gates a stage on its predecessor's output. That is how
falsification children spawned against a synthesis that was never written. Fail
loudly with `status: failed` instead. **S** · *triage (T3b)*

### MANT-B23 — Stop rooting artifacts in the invoking working directory

`core/paths.py` resolves its root from `Path.cwd()`, so a run launched inside a
git work tree litters it (`2026-08-10 six-topic-batch report`). Default to a data
root, or warn once when the root resolves inside a work tree. **S** ·
*triage (T4e)*

### MANT-B24 — Make "Not found" comparable across briefs

A "Not found" from a substrate with a narrow retrieval scope means something
different from one with a broad scope, and the synthesis cannot tell them apart.
Share one retrieval pool, unconstrain the secondaries, or — cheapest — stamp each
brief with its retrieval scope. **M** · *triage (T5c)*

### MANT-B25 — Unbuffered stage-transition lines on stderr

Detached and background callers currently parse state files to see progress
(`2026-07-30-finmodel-triple-research`). One line per stage transition on stderr
covers them without the MCP channel. **S** · *triage (T1c)*

### MANT-B26 — Pin by test what error messages and version declarations claim

A prefix-only assertion let a misnamed env var survive two releases; and the two
surviving version declarations are each asserted present but never asserted
equal. Two small tests, same class: assert the token, not its neighbourhood.
**S** · *triage (T6e, T6f)*

### MANT-B27 — A fallback tier behind the watchdog for local stages

So a single model's outage cannot stall the pipeline indefinitely. Held
deliberately: the alias design this would replace was independently credited for
surviving model turnover (`2026-08-10 six-topic-batch report`), so only the
no-fallback-under-outage half stands, and it has one report behind it. Its
predicate is met: MANT-B08 landed in 0.2.0, so the watchdog it sits behind now
exists. **M** · *triage (T3c)*

### MANT-B28 — Let a run pin its resolved model ids

`core/model_policy.py` is working and self-updating — verified live, the catalog
path selects past the pinned fallback — but the same substrate resolved to two
different dated ids across runs, so substrate identity is not stable run to run.
The sidecar records the resolved id; nothing pins it. Add an option to freeze
resolved ids for a repeat run. **S** · *review*

### MANT-B29 — Compress `CLAUDE.md` to what only it can supply

It is always-on context that restates the layout, the full stage table, the gate
commands and the config knobs already documented in their homes — the context
bloat and skill leakage pattern the ecosystem brief measures at 42% and 35% of
surveyed repos. Keep the invariants, the code style rules, the gate commands and
pointers to the homes; delete the stage table and the env-gating section rather
than updating them after the retirements. **S** · *review + research*

### MANT-B30 — Commit exercised batch configs, or demote batch mode in the docs map

`config/` holds exactly one file, the example. Every batch config the playbooks
cite as evidence is absent, and all 19 on-disk runs are single-question
request-level runs — roughly 340 lines of operator documentation for a path with
no live consumers. Commit two or three real configs, or present batch mode as a
documented secondary path. Do not delete it: the resume and `--only` semantics
would be expensive to rebuild. **S** · *review*

### MANT-B31 — One install story for the plugin

`plugin.json` launches `uv run --project ${CLAUDE_PLUGIN_ROOT}`, which needs a
clone; the README's preferred install is `uv tool install` plus the `mantis-mcp`
entry point. Pick one and make the other a documented alternative. **S** ·
*review*

### MANT-B32 — Align the names

The directory is `mantis-research-runner`, the repo is `mantis-research`, the
package is `mantis_research`, and the installed binary is the bare `mantis`. The
binary is the confusing part — a generic name on PATH says nothing about
research. Rename it to `mantis-research`, keep `mantis` as an alias for one
release, and align the local directory with the repo name. Low urgency, real
navigation cost. **S** · *review*

### MANT-B33 — Move the legacy top-level trees under one archive root

Eight top-level output and state directories hold history from a layout no run
produces, alongside `archive/`, `comparison/` and a stale autonomous-log tree.
Invariant I6 says legacy artifacts stay readable, which is right — but readable
does not require them at the repo root competing with live directories.
**S** · *review + operator observation*

### MANT-B34 — Narrow the README's multi-substrate argument to the mechanism the runs demonstrate

The README argues fan-out generally. The observed value is more specific and
much stronger: cross-provider fan-out earns its cost by exposing that two
substrates cited the same source and disagreed about it, not by averaging. The
landscape brief reaches the same conclusion and supplies the counter-evidence
that makes the general claim untenable. Rewrite the section around the
provenance mechanism once MANT-B07 gives it a typed home. **S** ·
*review + research*

### MANT-B35 — Compress the falsification playbook

266 lines of playbook for a 50-line prompt is more than the density discipline it
preaches allows. The stage itself is keep — genuinely exercised in 13 of 19 runs,
substrate-neutral, and it demands an explicit negative result rather than
accepting silence. **S** · *review*

### MANT-B36 — Blind A/B the tool against a single-provider deep-research run

The suite owns an eval harness built to A/B a tool armed versus bare against a
held-out bank, and it has never been pointed at this tool. The two measurements
worth more than any further reading are: how often a divergence changed a
decision, and cost per decision changed against a single-provider run on the
same questions. The landscape brief's hardest counter-evidence — one good model
dominating fusion on quality-per-token at 8.8× cost — is unanswered until this
runs. The playbooks' own D6 declares a quarterly re-evaluation discipline that
has never been executed. **L** · *review + research*

**Cross-review gate.** Do not run this until the harness's own FATH-B01 and
FATH-B02 close. The first is an arming defect that produced a confident 100%
score; the second is a bank that could not discriminate between the arms. Each
has already cost a paid run on that harness. This is the most expensive item on
the list, and running it before those close buys the same two defects a third
time — at this tool's expense, and with a number that reads as a measurement of
this tool rather than of the harness.

**Status: UNMEASURED.** The moat-precondition bank is authored and validated,
and it has **never run** — there is no number here, in either direction. What
exists is a staged $2 pilot in the harness's own repo, sized to check whether
the serving defect fixed in 0.3.0 reproduces inside a spawned trial before the
full bank's ~$70 is committed. Nothing about the moat claim has been tested
yet, and the item should not be read as partially answered.

**Whatever the bank returns while the serving defect is live is a reproduction
of that defect, not a refutation of the moat claim.** The defect returned
research briefs with no synthesis and no sidecar in a shape that reads as a
complete result — so a trial scoring that output is scoring an amputated
pipeline while believing it scored the whole one, and would report the fusion
arm as adding nothing. That is the exact conclusion the landscape brief's
counter-evidence predicts, which is what makes the confusion expensive: the
wrong answer here is indistinguishable from the answer the reviewer already
half-expects. Read any pre-0.3.0 pilot result as evidence about the harness's
arming and this tool's serving path, and re-run before it is read as evidence
about fusion. The 0.3.0 fix is what makes a spawned trial's silence
impossible — the run now raises rather than handing back the briefs — so the
pilot's first job is to confirm that refusal actually surfaces through the
harness, not to produce a score.

---

# Retire / fold candidates

Each row names what replaces it. Nothing here is deleted without an ADR
recording the retirement — per the repo's own convention, corrections arrive as
new records, never as edits to old ones.

### MANT-B37 — Retire the Path-A research stage

Stage module, adapter research path, state class, registry row and config field.
`research_service.build_config` hardcodes an empty prompt for it and never
dispatches it; exactly 1 of 19 runs on disk has the output directory. The
project's own batch-12 experiment concluded Path B is the default and Path A
wins only in three narrow cases, none of which its test topics fit.
**Replaced by:** the `anthropic` substrate slug through OpenRouter for the
lineage, and the harness's own research for the local-brief case. **M** ·
*review*

### MANT-B38 — Retire the Gemini CLI research stage

Stage module, adapter, state class, registry row. The subscription was dropped
2026-05-04, this machine disables the stage, the README labels it legacy, and
zero runs on disk used it. **Replaced by:** the `google` substrate through
OpenRouter, already one of the three defaults. **M** · *review*

### MANT-B39 — Retire `DISABLED_STAGES`

Its only documented and only actual use is disabling the Gemini stage. Once
MANT-B37 and MANT-B38 land it is a config knob whose purpose is to disable dead
code. **Replaced by:** nothing — remove the setting, its `.env.template` block
and the `CLAUDE.md` section together with the two stage retirements. **S** ·
*review*

### MANT-B40 — Retire the journal turn and its template

All 15 `journals/` directories on disk are empty: `synthesis.py` calls
`journal_dir.mkdir` unconditionally while `build_config` defaults the journal to
disabled, so the directories are an artifact and the turn has zero output in the
entire request-level history. Its prompt also instructs the model to use a skill
that is not in scope when this repo drives the CLI — a brief presupposing a tool
the agent lacks, which is a measured harm, not a neutral no-op. ADR-0002 had
already demoted journal ingestion to an optional sink. **Replaced by:** direct
ingestion of the synthesis markdown and the sidecar by the downstream memory
corpus, which owns the ingestion contract and the skill. Make the `mkdir`
conditional in the same change so runs stop littering. **S** · *review*

### MANT-B41 — Retire the journal-passes stage and its augmentation template

Same missing-skill dependency, plus a live data-contract violation: the template
hardcodes a third copy of the downstream journal envelope inside
`core/prompts.py`, and that copy has already drifted — four entry types against
the contract's nine, three fields missing. The corpus guards its own two copies
with a drift test; this one sits outside it. The prompt is further stuffed with
retired-corpus specifics that no longer describe anything. **Replaced by:** the
same direct ingestion as MANT-B40, with the envelope living next to its contract
and its drift test in the corpus repo. **M** · *review*

**Cross-review note — name one owner before the copy is deleted.** Two backlogs
name different owners for the same envelope. This item puts it in the corpus
repository, next to its contract and the drift test that already guards the two
copies there; the collection's backlog keeps the versioned schema in its
journaling skill and calls it a real machine contract. On the arguments as they
stand the versioned schema is the better-argued owner — it carries a version and
is already treated as a contract rather than as documentation — with the
corpus's two copies and this repo's drifted third as consumers of it. Either
resolution works; two owners do not, which is how a third copy came to exist in
the first place. Whichever is named, sequence this deletion after that owner's
drift test actually covers the envelope. Deleting the drifted copy while the
owner is still contested removes the visible symptom and leaves the contract
with nothing guarding it.

### MANT-B42 — Fold `claude-prior` into the evaluation stage

It exists solely to supply one input to the evaluation rubric's parroting check
and has no standalone consumer — one run on disk, alongside the one evaluation
run — yet costs a module, a state class, a registry row and a tier entry.
**Replaced by:** an internal preparatory turn inside the evaluation stage. Its
fate then follows MANT-B14. **S** · *review*

### MANT-B44 — Retire the Path-A research playbook

360 lines governing the stage MANT-B37 retires. It is also the source of the
section scaffold that leaked into the evaluation rubric and the augmentation
prompt, where it mines a section Path-B briefs never contain. (The rubric's
half of that leak is closed — MANT-B14's C5 no longer scores the section — so
what remains here is the playbook and the augmentation prompt.)
**Replaced by:** salvage the block-scaffold section into
`prompts/playbooks/README.md`, which already cites it as governing
`research_prompt` generally, then delete the file. **S** · *review*

### MANT-B45 — Retire the Gemini research playbook

326 lines governing a stage disabled since 2026-05-04 that never ran.
**Replaced by:** move its decomposition section — cross-referenced from the
playbooks README — into that README first, then delete. **S** · *review*

### MANT-B46 — Retire the journal playbook

Documents a stage that produced zero files and depends on a skill the session
cannot see. **Replaced by:** nothing; delete with MANT-B40. **S** · *review*

### MANT-B47 — Fold the research-path recommendation into the substrate playbook

A completed experiment whose verdict is already implemented in code and recorded
in ADR-0005, now reading as a live recommendation for a closed decision — and
recommending Path A for three narrow cases whose stage is being retired.
**Replaced by:** the surviving substrate-comparison evidence moves into
`model-recommendations.md` as a record, and ADR-0005 carries the decision.
**S** · *review*

### MANT-B48 — Replace `docs/method/` with a pointer

A hand-copied fork of an externally maintained method. The directory's own README
says it operationalises a method whose owning plugin is installed here and walks
an agent through the same artifacts. Worse, `series-toml-skeleton.md` is an
unregistered fourth mirror of a schema maintained elsewhere, sitting outside the
maintained mirror table, so a schema refresh will not visit it and it will drift
silently. **Replaced by:** a one-line pointer to the installed method and
execution plugins, with `definition-of-done.md`'s concrete gate commands moved
into `CONTRIBUTING.md` where project-specific bindings belong. **S** ·
*review + research*
**Conflict to resolve first.** MANT-B10 and MANT-B18 both land work inside
`definition-of-done.md`. Move the gate bindings to `CONTRIBUTING.md` before
retiring the directory, or sequence this last.

**Cross-review note — record the absence in the registry.** Once this retires,
this repo carries no method copy and no schema mirror of any kind. That has to
be an explicit entry in the collection's bindings file (CRAF-B13) rather than
silence, or a later pass reads the gap as an omission and helpfully re-adds a
mirror — which is exactly how the unregistered fourth mirror this item found
came to exist. This backlog is the only document in the cross-project pass that
spotted an unregistered mirror, and a registry is the only place that
observation is worth anything to the other repos. The registry edit is
follow-through in another repo; the retirement is not finished until it lands.

### MANT-B49 — Compress the playbook disciplines

Of ten declared disciplines, three carry non-inferable content wired to actual
machinery — cross-model agreement as weak signal (implemented as a sidecar
field), producer-must-not-validate (implemented as a separate evaluation
session), and verifying domain terminology against primary sources before
locking it into a prompt. The rest are generic prompt-engineering virtue that a
current frontier model does not need told, which the ecosystem brief identifies
as the weakest-evidence category there is. D6 mandates quarterly re-evaluation
that has never run — the discipline that would have caught MANT-B05.
**Replaced by:** those three plus the config anti-pattern table; when D6 goes,
either wire it to MANT-B36 or stop claiming it. **S** · *review + research*

### MANT-B50 — Conditionally retire the evaluation stage

Sentenced only if MANT-B14 shows the gate cannot reject a deliberately degraded
synthesis. **Replaced by:** the falsification stage, which is genuinely
exercised and carries the adversarial-second-lens mechanism on its own.
`evaluation-prompt.md` holds until the measurement returns, then either goes
with the stage or is rewritten alongside a corrected rubric. **M** · *review*

---

# Declined

Recorded so they are not relitigated.

### MANT-B51 — Documenting the client's idle timeout as the remedy

Declined as out of charter. The MCP client's tool idle timeout is an environment
setting a running agent cannot change, so the suggested remedy is unreachable
from inside the tool. This is recorded because it is precisely why MANT-B02
exists: the tool must fit inside a budget it does not control, rather than
documenting a knob its caller cannot turn. *triage*

### MANT-B52 — A `CLAUDE.md` note on the MCP field-description idiom

Declined. The failure it guards against is already held by a mechanism —
`test_research_tool_schema_documents_every_parameter` fails any parameter added
without a description. The note would add a clause to the style section without
displacing one, and prose behind a passing test is the weakest available rung.
*triage*

### MANT-B53 — Serialising concurrent local-seat stages

Retired on evidence, not judgement. `2026-07-24-dispatch-research-batch` ran the
falsifying experiment — three simultaneous CLI runs, 3/3 clean — so concurrency
is not the trigger for the hang, and the proposal's own text said it dies if the
hang does not reproduce. Its weight passes to MANT-B08. Note that MANT-B08 still
carries a seat lock, but for legibility and fair scheduling, not as a fix for
the hang. *triage*

### MANT-B54 — "`docs/feedback/` holds no reports despite 19 runs"

Not a gap. `docs/feedback/README.md` is the registered *format* doc; the reports
themselves live in the operator's own feedback directory outside this repo,
which is where all nine reports behind this backlog were written and triaged.
The in-repo directory holding only its README is the convention working as
designed. *review, corrected against the registry*

### MANT-B55 — A registered triage template at `docs/method/reflection-triage.md`

Asked for across three reports, and resolved outside this repo: the operator-side
registry moved and no longer cites that path. Not re-proposed — and it would
conflict with MANT-B48 in any case. *triage*

---

# Landed

Reconciled against `CHANGELOG.md` (0.1.0 → 0.2.0) and history through
`b4050b2`. Recorded here so the same findings are not re-proposed.

| What | Release | Closes |
|---|---|---|
| Progress over the MCP channel: the handler takes the FastMCP `Context` and a `RunEvent` bridge carries run-named, per-stage, per-substrate and backoff-heartbeat events onto the session's loop | 0.2.0 (`f4140d7`) | **MANT-B01.** The notification path, per the recorded decision; whether a poll tool is still wanted is now answerable, since B02 and B03 have landed |
| `RetryPolicy.caller_idle_budget_seconds` (default 1500, configurable, `null` to disable) caps every wait at half the budget | 0.2.0 (`413a899`) | **MANT-B02.** The 30-minute rate-limit backoff was exactly the client's 1800 s idle window |
| `outputs/<batch>/run.json` written before dispatch, a `run_named` event ahead of the first stage, `question_slug` / `outputs_dir` on the manifest, and the run's identity on stderr from `mantis research` | 0.2.0 (`3e0ebf9`) | **MANT-B03.** An aborted call now leaves an identified run |
| The `research` MCP tool defaults to `assurance: "fast"`; `standard` / `high` are explicit escalations, and `SKILL.md` § Cost & latency is written tier-independently | 0.2.0 (`8d8144f`) | **MANT-B04.** Shipped on its own merits, *not* as the timeout fix — the abort reproduced at `fast`, 2/2 |
| The synthesis template is substrate-neutral: brief count, labels and substrate list come from the run; the pre-pivot router note, structure-follows-the-primary rule and two-model independence paragraph are gone; agreement on an untraceable named artifact is a co-hallucination flag. Shorter than it went in; playbook rewritten with it | 0.2.0 (`4a95550`) | **MANT-B05.** The numeric quotas stay until MANT-B15 measures them — removing them now would destroy that comparison |
| `question` on the sidecar, filled verbatim from the topic, and `require_complete()` failing the synthesis stage on a missing `question` / `generated_at` / `sources` (`sidecar_version: 2`) | 0.2.0 (`c41090d`) | **MANT-B06.** Also removes the misattribution hazard: a sidecar can no longer be adopted as the answer to a different question |
| `source_citations` and `source_overlaps` on the sidecar, with overlap membership recomputed by the runner from the inventory and `source_overlaps` in the MCP projection | 0.2.0 (`7522e12`) | **MANT-B07.** "Two substrates cited the same URL and disagreed about it" is computed, not narrated |
| Liveness for local-seat children: a watchdog on silence (`runner.child_idle_timeout_minutes`, default 10), a PID-stamped seat lock at `state/claude-seat.lock`, and a `dead` topic status distinct from `failed` | 0.2.0 (`91a6405`) | **MANT-B08**, in the sibling engine's shape rather than a second design. MANT-B27 stays blocked on nothing now |
| The pre-commit hook checked in at `scripts/git-hooks/pre-commit`, invoking `uv run python -m pre_commit`, wired with `core.hooksPath`; README and `CONTRIBUTING.md` corrected | 0.2.0 (`5b5e8c9`) | **MANT-B11.** The working form belongs in the collection's exemption list (CRAF-B26) — that entry is still owed |
| `mantis research --resume <run-dir>` and a `resume` argument on the MCP tool, under strict-ancestor containment and an owner-liveness refusal | 0.2.0 (`4594b35`) | **MANT-B13.** A consumer of state that already existed |
| The evaluation rubric's C5 scores actionable content rather than a retired section, the two named source blocks become one N-peer-brief block, and the hardcoded evaluator literal is gone | 0.2.0 (`ce73a95`) | **MANT-B14, partially** — the rubric half, justified by inspection. The replay measurement is still open, and MANT-B50 still waits on it |
| `mantis status` folded into `mantis monitor --snapshot <config>` (ADR-0010) | 0.2.0 (`b4050b2`) | **MANT-B43.** One progress surface |
| A dry run no longer settles a topic: `TopicState.dry_run` records which kind of run wrote a record and `settled` disregards a dry run's `done`, so a real run under the same batch name re-executes instead of skipping. The manifest and `run.json` carry `dry_run` too | 0.3.0 | No item — found in field use 2026-08-11, not on this list. `state/research-test-20260811T175640Z/openrouter/1.json` is the artifact: `status: "done"` beside an `outputs/` tree holding only `run.json` |
| The `research` MCP tool raises `IncompleteRunError` rather than returning a run with no sidecar, and `require_local_claude_seat` refuses a tier whose local seat is unusable before any stage dispatches | 0.3.0 | No item — found in field use 2026-08-11. Also settles the nesting question by measurement: a `claude` child spawned from inside a Claude Code session runs normally, so nothing scrubs the parent environment |
| The watchdog's trip path is tested where a stage reads it — the translation into `ClaudeCliResult`, not just `run_streaming` | 0.3.0 | The gap MANT-B08 left open in 0.2.0 |
| Per-parameter descriptions on every `research` tool argument, and the full agent-facing surface in `skills/research/SKILL.md`, guarded by a schema test | 0.1.1 (2026-07-04) | The undescribed-parameter finding as a class — the test holds it, not prose |
| Six documentation falsehoods fixed as instances: the env var named correctly in the runtime error, the stage table and `--only` syntax, mypy guidance, invariant I6 restored, the playbooks README rewritten to the shipped pipeline, and a docs information architecture | 0.1.2 (2026-07-09) | Every instance in `2026-07-09-docs-overhaul`. The *gate* that would have caught them is MANT-B10, still open |
| `__version__` derived from installed distribution metadata (three copies became two) and a `mantis version` subcommand | Unreleased (2026-07-31) | Partially — the `--version` flag alias and the cwd-relative artifact root remain (MANT-B23), as does the equality assertion between the two survivors (MANT-B26) |
| `config/example-batch.json` no longer pins a sentinel the code's own note reports as resolving to a model that 404s | Unreleased (2026-07-31) | The example-config contradiction. Its substrate set updates with MANT-B09 |

Deliberately kept, with no action: the ADR practice (ids appear in the
docstrings of the modules they govern), the execution specs (failure-mode
identifiers are traceable to the lines that mitigate them), `check_core_purity.py`
and invariant I1, the retry policy, the typed config schema and stage context,
the state files and resumability, the request-level CLI, the stage registry, the
research-request prompt template, the sidecar prompt template, the plugin and
marketplace manifests, and the visual identity. One convention is worth writing
into `CONTRIBUTING.md` before MANT-B48 removes the directory that currently
implies it: **failure-mode identifiers from a spec belong in the code that
mitigates them**. It is the most transferable practice in the repo.

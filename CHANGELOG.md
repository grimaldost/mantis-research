# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project is
pre-1.0, so changes accumulate under **Unreleased** and are cut into tagged
releases (starting with 0.1.0).

## [Unreleased]

### Added

- **Hosted CI.** Every push to main and every pull request now runs the gate
  battery — lock check, formatting, lint, `ty`, the suite, core purity — on
  Ubuntu and Windows (`.github/workflows/ci.yml`). Until now the pre-commit
  hook was the only mechanical gate, its own comment said so, and
  `--no-verify` had nothing behind it. A PR-only changelog-currency job
  (`scripts/changelog_currency.py`, ported from keel's working gate) fails a
  diff that touches `src/`, `scripts/` or `skills/` without a `CHANGELOG.md` entry or a
  `Changelog: none (<reason>)` declaration — the rule this file's own
  convention stated but nothing enforced. A version arm on the same job fails
  a PR whose release cut moves the newest heading backwards; the version-site
  equality tests then hold every copy to that heading in the same run.
- **The suite joined the commit lane, and the message got a gate.** The hooks
  ran ruff and the purity check but not the tests, so a commit that broke the
  suite passed them — "pre-commit plus these commands are the gate" was half
  manual. The hermetic suite (~17 s) now runs on every commit, and a new
  checked-in `scripts/git-hooks/commit-msg` hook holds messages to
  Conventional Commits and rejects AI-attribution lines — Co-Authored-By
  trailers and standalone generated-with lines alike
  (`scripts/check_commit_message.py`, test-covered like the other gates) —
  wired through the same `core.hooksPath` install as the existing hook.
- **Version sites agree by test, not convention.** `test_plugin_manifest.py`
  asserted only that the plugin manifest *has* a version; the release
  checklist called the copies "kept in sync by convention". It now asserts
  `pyproject.toml`, `.claude-plugin/plugin.json`, the `uv.lock` root-package
  entry, and the newest CHANGELOG release heading name the same version, so a
  drifted copy fails the suite instead of shipping.

### Fixed

- **The MCP research tool died at dispatch on unix hosts.** First run of the
  new ubuntu CI leg: the orchestrator wires SIGINT with
  `loop.add_signal_handler`, which unix accepts only on the process's main
  thread — and the MCP server runs every research call on a worker thread
  (`asyncio.to_thread`, the detach thread). The Windows arm of the same
  function already suppressed its main-thread refusal; the unix arm never got
  the equivalent, so the suite this repo only ever ran on Windows could not
  see it. Signal wiring is now skipped off the main thread on both platforms
  — there is nothing to wire there; Ctrl-C reaches the server's own loop,
  which owns shutdown for the runs it hosts.
- **A raw JSON config string crashed the loader on unix.** `load_batch_config`
  probes its string argument with `Path.exists()` to decide path-versus-JSON,
  and a JSON document longer than the filesystem's name limit makes that probe
  raise `ENAMETOOLONG` on Linux where Windows answers False. The probe now
  treats an unstatable string as what it is — not a path.

### Changed

- **CI workflow token scoped to read.** The workflow declared no
  `permissions:` block, so its `GITHUB_TOKEN` carried the default writable
  grant; both jobs only check out the repo and run local commands, and the
  token is now `contents: read`.
- **Release ritual tightened.** CONTRIBUTING now states what practice mostly
  already did: the release commit is metadata-only (CHANGELOG roll, the two
  version copies, `uv.lock`) — the 0.4.0 release commit carried the whole
  detach feature, which is the slip this rule closes — and the tag is
  annotated on the release PR's merge commit, with the exact command given.

## [0.4.0] - 2026-08-28

Everything the 0.2.0 delivery-envelope wave promised shipped, and the envelope
still did not close: across every recorded transcript, 18 of 18 non-dry-run MCP
calls hit the client's ceiling and none returned. This release is what a triage
delta over the two releases since found — including that one of 0.2.0's own
fixes had become the largest single cause of failure.

### Fixed

- **The child watchdog measured total runtime, and killed healthy work.** It
  reads the spawned child's stdout line by line and kills it after 600 s
  without one, but the child was spawned with `--output-format text`, which
  emits nothing until the turn ends. So the "silence" clock was a cap on
  runtime, and its ceiling sat below the real duration of **66 of the 237**
  local-seat stages this tool has completed (min 131 s, median 429 s, max
  2601 s). In the field on 2026-08-23 it produced 12 attempts and zero bytes
  across four runs. Measured on `claude` 2.1.251 with the adapter's own read
  pattern: under `text` the longest gap between lines was 11.8 s of a 16.1 s
  run; under `stream-json` it was 3.7 s, and that gap was startup.

  The fix is not the default string. The format and the timeout were chosen for
  different reasons, lived on one dataclass, and nothing related them. Output
  cadence now travels with the format, `run_streaming` requires the caller to
  declare it, and pairing a silence watchdog with a child that is mute by
  design raises instead of being configured. (MANT-B58)
- **A retry could only spend time.** Retry count is now a function of the
  failure's class: a rate limit is transient, so waiting is the fix; a watchdog
  kill is not, and retrying an abandoned child spawns a live tree beside the one
  still running. Both are `PRECONDITION` and get one attempt rather than three.
  The classifier could not have known — it scanned the child's *output*, so the
  one failure that produces none read as generic and drew the transient budget.
  The producer now declares the kind, with the text scan as the fallback. A
  retry also mints its own session: reusing the dead one made two of three
  retries in the original incident die on `Session ID ... is already in use`
  rather than on the cause, destroying the evidence of the failure being
  retried. (MANT-B59)
- **The seat wait reached nobody, and outlived its child.** `seat.py` emits a
  `waiting` event on every poll, with a comment saying it reaches an MCP client;
  the one call site that acquires the seat passed no callback, so the emit was
  unreachable. Four runs queued behind each other across 2.5 hours in silence.
  The reap after a kill was also unbounded while the seat lock sat on the
  enclosing exit stack, so a child that resisted termination held the machine's
  single seat — one attempt recorded `turn_1_duration_s: 4502` against a 600 s
  watchdog. The wait is bounded and an unreaped child is reported by pid; its
  exit code is no longer invented either, since `returncode or 0` read a child
  that is still running as a clean exit. (MANT-B63)
- **Two concurrent runs could share one state tree.** A run was named after the
  question's first 48 characters plus a timestamp to the second, and its
  directory was created with `exist_ok=True`. On 2026-08-23 four of five
  questions carried a shared preamble and were dispatched within ten seconds:
  five requests, three directories. That is not a lost run but a misattributed
  one — the correctness class the sidecar's `question` field was added to close.
  Names now carry a random suffix, the run root is claimed with
  `exist_ok=False`, and an explicit `--batch-name` landing on an existing run is
  accepted only for the same question. (MANT-B62)
- **A dry run reached the network and overstated what it did.** The model
  resolver asked the live OpenRouter catalog for every subsession with no
  dry-run guard, so the free validation pass was a DNS lookup away from that
  claim being false; it is now fetched only on a real run, and hoisted out of
  the loop. A dry run also settled its record as `status: "complete"` beside
  paths nothing had written, and now records `validated`. (MANT-B64/B65)

### Added

- **`assurance: "research"`** — the cross-model briefs and their cost, with no
  local-seat stage and no seat probe. `assurance` was naming two different
  things, how much checking the answer gets and which stages run, so "just the
  research" could not be asked for and every tier ended in a synthesis that
  cannot finish inside an MCP client's window. This is the tier that ran where
  the others could not on 2026-08-23. The serving path's sidecar refusal learns
  the difference: a manifest records whether a sidecar was owed, and absence
  reads as owed, which is what every earlier tier meant. (MANT-B60)
- **`detach` on the `research` tool, and a `research_status` tool.** A single
  tool call cannot outlive the client's ceiling and a full run usually does.
  `detach: true` returns the run's identity immediately; `research_status`
  reports state, per-stage exit codes, cost and output paths by reading the
  artifacts that already exist, and reports a failed run rather than raising at
  a caller who only asked how it went. The blocking default is unchanged, so no
  existing caller is affected. A detached run is bound to the server's lifetime;
  a run lost with its session is re-entered through `resume`. (MANT-B61)
- **A `name` argument on the `research` tool**, and an inline
  `RESEARCH QUESTION (<key>)` marker the slug prefers, so questions sharing a
  long preamble are distinguishable. (MANT-B62)
- **A per-request acceptance journal** at `logs/requests.jsonl`, written before
  any run directory exists. One 2026-08-23 caller waited its full window for a
  run with no trace anywhere on disk. (MANT-B62)
- **The local seat's cost is recorded.** The seat is a subscription, so nothing
  metered it per run; the `stream-json` result line carries `total_cost_usd`.
  (MANT-B58)
- **A `thinking` run event.** Progress bridging shipped in 0.2.0 and did reach
  the MCP path, but nothing was emitted between a stage starting and finishing,
  so the longest phase of a run was still silence. A local-seat stage now
  reports roughly every 20 s while its child works. (MANT-B58)
- **The test suite cannot reach a live provider.** The guard refuses at the HTTP
  send and the child spawn rather than at their callers, and derives from
  `BaseException` because the orchestrator catches `Exception` twice on the
  attempt path — a catchable guard would turn a hermeticity breach into three
  retries. Turning it on is what found the dry-run network call above. A green
  suite had previously concealed a real, paid, eight-minute production run.
  (MANT-B65)
- **A Definition-of-Done clause**: a claimed liveness or timing property ships
  an offline adversarial repro, and prose and test cite the same constant. 0.2.0
  declared the idle-timeout lineage closed on a deferred paid run that was never
  bought, and production found the lineage open twelve days later. (MANT-B65)

### Changed

- **`skills/research/SKILL.md` § Cost & latency**, rewritten shorter than it
  was. It told an agent that "a silent minute means something is wrong; silence
  is no longer the normal case" — false in two places at once. It now says a
  local-seat stage is silent while the model thinks, quotes the cadence the code
  actually emits (pinned by a test), teaches the detached shape, and carries the
  measured cost band of $0.15–0.50 for a focused technical question rather than
  $1–6. The README's band is recalibrated with it. (MANT-B64)
- **`session_id` moves onto `TopicState`.** Six state classes declared it
  identically and the retry contract has to be able to clear it. Additive and
  Optional under invariant I4; historical state files load unchanged.


## [0.3.0] - 2026-08-12

Two defects found in real field use on 2026-08-11, both in the gap between what
a run reported and what it had actually produced. One let a dry run settle a
topic, so a real run under the same batch name skipped the work and reported
success over an empty tree. The other let the primary serving path hand back
research briefs, with the synthesis and its sidecar missing, in a shape a caller
reads as an answer. Neither announced itself: the first surfaced as a downstream
failure pointing at the wrong stage, the second as a research result that was
quietly half a product.

Minor rather than patch: the state schema gains a field, `--dry-run` no longer
leaves a topic looking finished, and the `research` tool now raises where it
previously returned. Existing state files and past runs are unaffected —
the new field is additive and Optional under invariant I4.

### Fixed

- **A briefs-only run is reported as a failure instead of returned as a
  result.** The `research` MCP tool assembled its result from whatever the run
  left behind, so a run whose synthesis stage failed came back as a structured
  object carrying three real brief paths, a `synthesis` and `sidecar` path that
  pointed at nothing, and a `sidecar_available: false` next to an `ok` flag —
  a shape an agent has every reason to read as an answer. It happened in the
  field on 2026-08-11: `outputs/vf-selfverif-live/run.json` records `synthesis`
  at `exit_code: 1`, and the transcript beside it ends `Failed to authenticate.
  API Error: 401 OAuth access token has expired`. The epistemic sidecar **is**
  the product (ADR-0003), so a live run that produced none now raises
  `IncompleteRunError`, naming the missing sidecar, the stage that did not
  deliver it, and the run directory to pass back as `resume` — the briefs are
  already paid for and must not be bought twice. A dry run is exempt on the
  manifest's own `dry_run` flag, which now travels to the caller.
- **The local Claude seat is checked before anything is dispatched.** Every
  assurance tier ends in a stage that drives the machine's authenticated
  `claude` CLI, but nothing asked whether that seat was usable until the
  synthesis stage reached its own preflight — which is *after* the OpenRouter
  research stage has run and been paid for. Three runs on 2026-08-11 bought
  their briefs and only then found the seat's token had expired; the briefs are
  still on disk and the syntheses were never written.
  `require_local_claude_seat` now probes the seat up front for any tier
  containing a `LOCAL_SEAT_STAGES` member and raises
  `LocalSeatUnavailableError` naming the precondition, so a run that cannot
  deliver its product stops before it spends. The probe is the `SeatProbe`
  Protocol (`core/stage.py`), so the check is testable without a seat.
  Nesting is **not** the precondition: a `claude` child spawned from inside a
  Claude Code session runs normally, confirmed end to end on CLI 2.1.228 with
  `CLAUDECODE=1` set (synthesis and sidecar turns both exit 0), so nothing
  scrubs the parent's environment for the child.
- **A dry run can no longer be mistaken for a completed run.** `--dry-run`
  short-circuits every adapter but the orchestrator still wrote terminal
  `status: "done"` into the batch state directory, so a real run under the same
  batch name skipped every topic: the stage reported `exit_code: 0` and the
  manifest listed brief paths that did not exist, and the only visible symptom
  was a downstream synthesis failure pointing at the wrong stage. `done` is
  skippable precisely because it means the artifact is on disk, so this was
  invariant I5 read backwards — resume is "re-run the same command", and the
  state directory was lying to it. Every record now carries `dry_run`, which
  says which kind of run wrote it; `TopicState.settled` — the query the
  orchestrator skips on — disregards a `done` a dry run wrote, and a real run
  clears the marker it inherits, so the tree self-corrects on the next live
  invocation. The run manifest and `run.json` carry `dry_run` for the same
  reason: every path under `outputs` is where an artifact goes, not proof one is
  there. Additive and Optional under invariant I4 — the field is absent from
  every historical state file, which reads as "a real run wrote this".

## [0.2.0] - 2026-08-11

The delivery envelope around the research output. Every **Now** item in
`docs/backlog.md` closed: the pipeline reports progress over its own primary
transport, no internal wait outlasts the caller, a run is named before it
dispatches and resumable after an interruption, a mute child is killed rather
than left in flight, and the sidecar carries the question and typed source
provenance. The synthesis prompt stops describing a pipeline that no longer
exists.

`mantis status` is gone — see **Removed**.

### Changed

- **The sidecar carries the question, and the write is gated** —
  `sidecar_version` 2. `ResearchSidecar` had no `question` field at all, so
  seven of seven sidecars across two runs were unusable as a citation surface
  and an unidentifiable run's sidecar could be adopted as the answer to a
  different question. The runner now fills `question` verbatim from the topic,
  and `require_complete()` fails the synthesis stage when `question`,
  `generated_at` or a non-empty `sources` is missing rather than shipping a
  hollow artifact. Additive under invariant I4; `sidecar_version: 1` documents
  on disk still validate. (MANT-B06)
- **A run is named before it dispatches.** `run_research` minted `batch_name`
  and the run directories before dispatch but returned them only in the final
  manifest, so an aborted call could not say whether it had spent money or
  written anything, and a completed run on disk could not be matched to the
  question that produced it — a correctness hazard, not only a lost run. It now
  writes `outputs/<batch_name>/run.json` (`status: "dispatching"`, rewritten to
  `"complete"` at the end) and emits a `run_named` event before the first stage.
  `run_research` takes an `on_event` callback and the manifest carries
  `question_slug` and `outputs_dir`; `mantis research` prints the run's identity
  to stderr as soon as it exists. (MANT-B03)
- **Source provenance has a typed home** — `source_citations` (a per-substrate
  citation inventory) and `source_overlaps` (which substrates cited the same
  artifact, who never cited it, and whether they read incompatible figures out
  of it) on the sidecar, with `source_overlaps` surfaced in the MCP projection.
  `SourceRef` typed only `label / path / model_id / bytes`, so the pipeline's
  sharpest measured result — two substrates citing the identical URL with
  incompatible figures while a third never cited it, indicting the source —
  could only be narrated, improvised into `Divergence.substrates` as free text.
  Overlap membership is recomputed by the runner from the inventory; the model
  supplies the conflict judgement alone. (MANT-B07)
- **The `research` MCP tool defaults to `assurance: "fast"`** (was `standard`).
  `standard` and `high` stay as explicit escalations; the tier is a choice about
  how much checking the answer needs, not about how long the call takes.
  `mantis research` on the CLI keeps its `standard` default — a shell caller has
  no idle window to fit inside. (MANT-B04)

### Added

- **`mantis research --resume <run-dir>`, and a `resume` argument on the MCP
  tool.** Invariant I5 already promised per-stage resumability and the state
  files already delivered it — both runs that died at the client timeout had
  written their per-model briefs — but nothing consumed that state, so recovery
  meant harvesting the briefs by hand every time. Resume reads the run's own
  record for the question and settings (nothing to retype, nothing to silently
  disagree), skips what finished, and refuses a run whose owner process is still
  alive. The offered directory must be *strictly* contained by the outputs root,
  the same containment rule the sibling series engine resumes under. (MANT-B13)

### Removed

- **`mantis status` is folded into `mantis monitor --snapshot <config>`**
  (ADR-0010). Two commands reported run progress — a follower and a snapshot —
  answering the same question in two shapes, on a batch path with no live
  consumers. There is now one progress surface; `interface/cli/status.py`
  becomes `interface/cli/snapshot.py` and `status_cmd` becomes
  `print_snapshot`. `mantis monitor` with neither a stage nor `--snapshot`
  exits 2 naming both. (MANT-B43)

### Fixed

- **The `research` tool reports progress instead of going silent.** The handler
  never accepted a request context and never reported anything: the whole
  multi-stage run hid behind one `asyncio.to_thread` await, so a client saw
  silence from call to return and answered it the only way a client can — by
  giving up. Six MCP invocations aborted at the 1800 s idle window while the
  same questions succeeded 3/3 over the CLI. The handler now takes the FastMCP
  `Context` (injected, not an agent-supplied parameter) and a `RunEvent` bridge
  carries the run's boundaries onto the session's loop: the run being named,
  each stage starting and finishing, each research substrate starting and
  finishing, and a heartbeat every 10 s inside any backoff. A broken listener
  cannot fail a run. (MANT-B01)
- **The evaluation rubric scores what a Path-B run produces.** The stage has run
  once in 19 runs and that record is a vacuous-gate signature — verdict PASS,
  Q = 0.944, all three gates untriggered, five of six criteria at 3/3. Criterion
  C5 scored the presence of a `§ 7` section that only the retired Path-A
  scaffold produced, and scored 3/3 against a synthesis that could not contain
  one. Fixed by inspection: C5 now scores actionable content rather than a
  section, the `claude-original` / `gemini-originals` source blocks become one
  N-peer-brief block, and the hardcoded `claude-opus-4-7` evaluator literal (the
  model overrode it in the one real record) is gone. Whether the gates can
  reject a deliberately degraded synthesis is still the open measurement, and
  the stage's retirement stays conditional on it. (MANT-B14, partial)
- **The synthesis prompt describes the run it is actually in.** The Path-B pivot
  reached the code and the docs but never the prompt bodies: `SYNTHESIS` still
  opened "merge two LLM-produced briefs", asked for divergences "between the
  Claude and Gemini briefs", asserted "the structure follows Claude's brief",
  explained a Gemini router quirk, and closed with an independence paragraph
  describing one model integrating its own brief plus a cross-check. On a
  default three-substrate run none of that was true — the model was told a false
  story about its own inputs on every run, and every synthesis in one six-topic
  batch independently detected and corrected the label mismatch. The template is
  now substrate-neutral, takes its brief count, labels and substrate list from
  the run, and carries a hard rule that agreement on a **named artifact** no
  brief traces to a verifiable primary source is a co-hallucination flag rather
  than corroboration — covering repository slugs, package names and URLs, not
  only citations. It came out shorter than it went in. The playbook is rewritten
  with it, and `tests/unit/test_synthesis_prompt.py` holds the neutrality.
  (MANT-B05)
- **Spawned local-seat children have a liveness contract.** No timeout, kill or
  wait-for existed on the main CLI spawn, so a child producing zero output left
  its topic `in_flight` with `last_error: null` indefinitely — three synthesis
  children ran mute for 75+ minutes, the falsification children that spawned
  against their never-written artifact hung identically, and all six were killed
  by hand. Three additions, in the shape the sibling series engine already uses
  rather than a second design: a watchdog on **silence** (`runner.child_idle_
  timeout_minutes`, default 10) that kills a mute child and fails the attempt
  with a reason; an explicit seat lock at `state/claude-seat.lock` carrying the
  holder's PID, so concurrent runs queue visibly and a lock left by a dead owner
  is reclaimed rather than waited out; and a `dead` topic status, distinct from
  `failed`, set when a topic's recorded `owner_pid` is no longer a live process.
  `dead` is not `done`, so such a topic is still re-attempted (I5). (MANT-B08)
- **A backoff can no longer outlast the caller.** `rate_limit_backoff_minutes`
  defaults to 30, exactly the MCP client's 1800 s idle window, so a rate-limited
  substrate guaranteed the abort at every assurance tier. `RetryPolicy` now
  carries `caller_idle_budget_seconds` (default 1500, configurable under
  `runner`, `null` to disable) and waits `min(backoff, budget / 2)`. (MANT-B02)
- **The pre-commit gate is installed in a form that runs.** `.git/hooks/` held
  only the stock samples: `pre-commit install` writes a hook that calls the bare
  `pre-commit` shim, which Application Control blocks on the development
  machine, so the project's only enforcement layer was advisory. The hook is now
  checked in at `scripts/git-hooks/pre-commit`, invokes
  `uv run python -m pre_commit`, and is wired with
  `git config core.hooksPath scripts/git-hooks`. (MANT-B11)

- `mantis version` reported a stale number. `mantis_research.__version__` was a
  hand-maintained third copy of the version, left at `0.1.0` while
  `pyproject.toml` and `.claude-plugin/plugin.json` moved to `0.1.2`; it now
  reads the installed distribution's metadata, so a release bump touches two
  files rather than three. `CONTRIBUTING.md`'s release checklist is updated to
  match, including the `uv lock` / re-sync step the derived version needs.
- `config/example-batch.json` set `web_search: true` on its Sonar entry and
  pinned the `auto:perplexity` sentinel, which the code's own note reports as
  resolving to a model that 404s on the completions endpoint — both
  contradicting the playbook the file's documentation points at. The entry now
  pins `perplexity/sonar-reasoning-pro` with `web_search: false`.

### Documentation

- The visual identity is wired in: a light/dark hero and a badge row at the top
  of the README, with the assets and their usage rules under `assets/`.
- Corrected claims that had drifted from the code: which stages honour a
  per-topic `enabled` flag (`claude-prior` and `journal-passes` run for every
  topic once invoked — `docs/running-batches.md`, `docs/batch-config.md`);
  where the default synthesis prompt lives (`core/prompts.py`, not
  `default_prompts.synthesis` — `prompts/playbooks/synthesis-prompt.md`); that
  `LOG_LEVEL` / `LOG_FORCE_JSON` are declared but unread, the level coming from
  `mantis research --log-level` (`CLAUDE.md`); and the example batch's own
  description, which claimed four substrates for both of its topics.
- Removed the last two pointers at `run_journal_only.py`, deleted in the pivot
  (`prompts/playbooks/journal-prompt.md`, `falsification-prompt.md`), and the
  `scripts/run_*_batch.py` shim note in the CLI module docstring — which also
  omitted `run claude-prior`, `run evaluation`, and `research`.
- Documented surfaces that had none: process exit codes for every command
  (`docs/running-batches.md`), `mantis research --log-level`, `mantis monitor
  --poll-seconds`, and the `mantis version` subcommand. The README's one-shot
  flags are now a table.

## [0.1.2] - 2026-07-09

### Documentation

- **A docs information architecture**: `docs/README.md` maps all documentation
  by task and directory; new homes for the architecture
  (`docs/architecture.md`), batch operation (`docs/running-batches.md`), and
  the batch-config schema (`docs/batch-config.md`); index READMEs for
  `docs/adr/` and `docs/specs/`; a root `CONTRIBUTING.md`
  (setup, gates, style, invariants, common changes, release steps). The README
  gains a Documentation section and links into the new homes.
- **`prompts/playbooks/README.md` rewritten to the shipped pipeline**: its
  header still described the pre-pivot world — removed `run_batch*.py` /
  `evaluate_synthesis.py` runners, Claude+Gemini-only stage gating, a stale
  copy of the config schema. It now reflects Path B and the `mantis run
  <stage>` surface, and links `docs/batch-config.md` instead of duplicating
  the schema. The D1–D10 disciplines and the methodology references are kept.
- **Truth fixes against the code**:
  - The stage-disabled error message and nearby comments misnamed the env var
    as `MANTIS_DISABLED_STAGES`; the real name is `DISABLED_STAGES`
    (`interface/cli/dispatch.py`, `core/settings.py`). The valid-stage lists
    in `.env.template` and `settings.py` now also include `evaluation` and
    `claude-prior`.
  - `CLAUDE.md`'s stage table advertised `outputs/<stage>/` + `state/<stage>/`
    paths that matched neither run layout; it now shows the real legacy
    directories and notes the batch-layout scoping. Its invariants list gains
    I6 (adopted in ADR-0001 but never copied back), and the `--only` example
    uses the syntax that actually parses (`--only 42 --only 31` — the
    space-separated form is rejected by the CLI).
  - `mypy` guidance corrected everywhere: a secondary cross-check, not in the
    dev dependency group, and there is no hosted CI — run it as `uvx mypy src`.
  - `pyproject.toml`'s `description` updated from the pre-pivot framing to
    the agent-researcher one (ADR-0002).
  - Stale docstrings: `core/config.py` (cited removed authoring/migration
    scripts), `core/stage.py` (`journal-augment`; synthesis gating described
    as Claude+Gemini), `core/paths.py` ("the 44 committed configs"); three
    playbooks no longer claim `claude-opus-4-7` as the default model
    (unpinned configs resolve to the newest Opus via the `opus` alias).

## [0.1.1] - 2026-07-04

Agent-discoverability: document the full agent-facing surface so a fresh agent
can use every feature, not just the basics. A blind-agent probe of the plugin's
two surfaces (the `research` tool schema + `skills/research/SKILL.md`) found that
`primary` and `journal` were live tool arguments carrying no description anywhere,
the `substrates` vocabulary was unstated, and cost/latency, negative triggers, the
assurance-tier stage sequences, and the deeper sidecar fields were undocumented.

### Documentation

- **Per-parameter descriptions in the `research` MCP tool schema**
  (`interface/mcp/server.py`): every argument now carries a description in the tool
  `inputSchema` — the agent's first-glance surface — via `Annotated[…, Field(…)]`,
  and the docstring covers `substrates` / `primary` / `journal` (previously
  omitted).
- **`skills/research/SKILL.md` now documents the whole surface**: `primary` and
  `journal`; the accepted substrate vendor slugs and the default Path B set; what
  each assurance tier's extra stages do; cost/latency expectations; a "When not to
  use it" section; and the deeper sidecar fields (`agreements_worth_verifying`,
  `coverage_notes`, `truncated`, and the on-disk `sources[].model_id` /
  `provenance`).
- README's served-tool argument list now names `primary` / `journal`.
- Regression guard `test_research_tool_schema_documents_every_parameter` asserts
  every parameter carries a schema description and the substrate vocabulary reaches
  the agent.

No behavior or contract change: the MCP tool contract is additive (spec 0002), so
these arguments and fields already shipped in 0.1.0 — this release documents them.

### Packaging

- **The repository is now a Claude Code plugin marketplace**
  (`.claude-plugin/marketplace.json`): the production plugin installs straight from
  GitHub (`/plugin marketplace add grimaldost/mantis-research` →
  `/plugin install mantis-research@mantis-research`), pinned to the published repo
  and decoupled from a local working tree — so local development no longer
  perturbs a production install.

## [0.1.0] - 2026-07-03

First tagged release, bundling everything to date: the agent-researcher pivot,
agent-serving (MCP server + Claude Code plugin), and this pre-launch review round.

Pre-launch review round: fixes from a fresh-eyes review plus the P6 follow-ups.

### Security — pre-launch review

- **Scrubbed personal absolute paths from tracked files**: three
  `tests/data/golden_state/*.json` fixtures and `docs/method/method-bindings.md`
  embedded `C:\Users\…` paths (a username + a private project's location).
  Fixtures now use neutral relative paths.
- **Trimmed the private-tool method scaffolding** from `docs/method/`: removed the
  files that bound the templates to private tooling (`method-bindings.md`,
  `reflection-triage.md`) and the `pr-series/` orchestrator artifacts; the
  remaining ADR / spec / DoR / DoD / pre-mortem templates are now tool-agnostic.

### Fixed — pre-launch review

- **Blocked-upstream topics no longer report success** (`interface/orchestrator.py`):
  `_final_summary` counted only FAILED / RATE_LIMITED as failures, so a live run
  whose synthesis blocked (e.g. a single-substrate request → no secondary brief)
  exited 0 and the `research` tool / CLI returned `ok: true` with no synthesis and
  no sidecar. A blocked topic now fails a live run; a dry run (whose adapters
  legitimately produce no artifacts) still passes.
- **Sidecar sources now carry the model id + a substrate label**
  (`core/state.py`, `interface/stages/{openrouter_research,synthesis}.py`): the
  resolved/served OpenRouter model is persisted per subsession and threaded into
  `sources[].model_id`, and each brief is labelled `openrouter:<subslug>` instead
  of a bare `openrouter`. The synthesis prompt no longer hard-codes stale model
  names (`claude-opus-4-7` / a Gemini id) that mislabelled every Path-B brief.
- **OpenRouter list-typed message content no longer crashes the parse**
  (`interface/adapters/openrouter_http.py`): a provider returning OpenAI-style
  content parts (a list) is concatenated rather than hitting `AttributeError` on
  `content.strip()`.
- **State writes are atomic** (`core/state.py`): `save()` writes a temp file then
  `replace`s it into place, so a crash mid-write can no longer truncate an existing
  state file and break resume (I5).

## Agent-serving

Agent-serving via MCP server + plugin (`docs/specs/0002-agent-serving-mcp-plugin.md`).

### Added — agent-serving

- **`research` MCP tool + Claude Code plugin** (ADR-0009): a local stdio MCP
  server (`interface/mcp/`, launched by `python -m
  mantis_research.interface.mcp`) exposing a `research` tool, bundled as a
  plugin (`.claude-plugin/plugin.json`) installable with `claude --plugin-dir .`.
  The tool runs the pipeline via the shared `run_research` orchestrator and
  returns the run manifest plus the epistemic sidecar's claims / divergences /
  verification queue (bounded to the MCP result-size budget, truncation
  reported), with synthesis + briefs referenced by path. Local-first: the
  synthesis stages consume the host's authenticated `claude` seat. A reference
  skill lives at `skills/research/SKILL.md`.
- **`run_research()`** (`interface/research_service.py`): the request-level
  orchestrator extracted from the `mantis research` CLI, callable off any event
  loop (raises `ValueError`, never `typer.Exit`), so both the CLI and the MCP
  tool run one tested path.

### Changed — agent-serving

- **Logs now go to stderr, not stdout** (`core/logging.py`): stdout is reserved
  for program output — the `mantis research` manifest and, critically, the stdio
  MCP server's JSON-RPC stream, which structured logs on stdout would corrupt.
- **Default substrate set drops `perplexity`** (`interface/research_service.py`):
  its `auto:` pick (`sonar-pro-search`) 404s on the completions endpoint, and a
  topic fails if any one substrate fails — so a dead default nuked the whole paid
  run. Add it back explicitly with a working Sonar model if you want it.

### Fixed — agent-serving

- **The installed tool can now run from anywhere** (`core/paths.py`): `project_root()`
  derived every runtime data dir from the package's `__file__`, so an isolated
  `uv tool install` (no project tree) crashed with `project root not found` on the
  first stage — the documented install path (and the MCP server / plugin) could
  not run. It now falls back to the current working directory when there is no
  project tree; a source checkout is unchanged.
- **`--dry-run` no longer needs an API key** (`interface/adapters/openrouter_http.py`):
  the adapter checked `OPENROUTER_API_KEY` eagerly in `__init__`, and the stage is
  constructed even for a dry run, so the credential-free plumbing check the docs
  advertise actually failed without a key. The key is now resolved lazily, at the
  first real request only.

---

Agent-researcher pivot series (`docs/specs/0001-agent-researcher-pivot.md`).
Each PR appends its entry here in the same wave that lands the change.

### Added

- `mantis research "<question>"` — the request-level entry point (ADR-0004): one
  question in, one cross-checked synthesis + epistemic sidecar out. It builds a
  single-topic batch config in memory (Path B by default: 4 OpenRouter
  substrates via `auto:<vendor>`, an OpenRouter primary, journal off), runs the
  stage sequence in-process through the §18 seam, and prints a result manifest
  (output paths, per-stage exit codes, cost totals) as JSON. `--assurance
  fast|standard|high` selects how far the pipeline runs (research+synthesis →
  +falsification → +claude-prior+evaluation); `--substrates` / `--primary` /
  `--journal` / `--batch-name` / `--dry-run` tune it.

- Epistemic sidecar schema v1 (`core/sidecar.py`, ADR-0003): a pure, versioned
  pydantic contract (`ResearchSidecar`) carrying the synthesis's claims,
  divergences, verification queue, agreements-worth-verifying, coverage notes,
  and runner-filled provenance (durations, token/cost totals). Two authorship
  zones — model-authored epistemic content vs runner-authored identity/
  provenance. This is the agent-consumable output the pivot is built around;
  emission wiring lands in §14.
- Sidecar provenance now carries the real research cost, not just timing
  (`Provenance.from_subsessions`, `core/sidecar.py`): the synthesis stage reads
  the OpenRouter per-subsession usage/cost persisted in
  `state/<batch>/openrouter/<id>.json` and aggregates it into the sidecar's
  `total_cost_usd`, `total_tokens_prompt`, `total_tokens_completion`, and
  per-substrate `per_source_cost_usd` (keyed by subslug). A metric no subsession
  reported stays `null` rather than a misleading zero, so the Gemini-CLI path
  (which reports no usage block) leaves the totals absent. Previously only
  `synthesis_duration_s` was filled; the token/cost totals stayed `null`.
- The synthesis stage now honors `stages.journal.enabled`: setting it to
  `false` skips the journal (Turn 2) and the attempt succeeds on the synthesis
  brief alone; `null`/`true` keep the journal on (the batch default, ADR-0002).
- Config-corpus compatibility test (`tests/unit/test_config_corpus.py`):
  parametrized over every `config/*.json`, asserting each still loads — the
  real-data guard for invariant I4 that later config-schema PRs rely on.
- Core-purity gate (`scripts/check_core_purity.py`): AST-walks
  `src/mantis_research/core/` and fails if any module imports a
  network/subprocess module (`httpx`, `subprocess`, `socket`, `requests`,
  `aiohttp`, `asyncio.subprocess`), making architecture invariant I1
  machine-enforced. Wired into a new `.pre-commit-config.yaml` alongside
  ruff-format and ruff-check (local hooks driving the project's uv-pinned
  tools, scoped to `src tests`).

### Removed

- Dead pre-pivot batch runners now superseded by `mantis run <stage>`
  subcommands (post-pivot cleanup, item A2): `scripts/run_batch.py`,
  `run_batch_gemini.py`, `run_synthesis_batch.py`, `run_falsification_batch.py`,
  `run_journal_passes_batch.py`, `run_journal_only.py`,
  `run_research_topic_test.py`, `run_research_topic_test_gemini.py`,
  `run_synthesis_topic_test.py`, plus `_monitor_batch_progress.py` (→ `mantis
  monitor`), the one-time `migrate_config_v1_to_v2.py`, and the two stale
  `*.legacy.bak` backups. Git history preserves them; the three src docstrings
  that pointed at the removed runners were reworded to drop the dangling paths.
- Dead path helpers `stage_state_dir` / `stage_output_dir` (`core/paths.py`) and
  their unit tests (post-pivot cleanup, item A5). They returned a
  `state/<stage>/` layout that no run used — orphaned when ADR-0006 formalized
  the `legacy` vs `batch` layouts (`run_state_dir` / `run_output_dir` are the
  canonical resolvers).
- The superseded standalone scripts (post-pivot cleanup, items A3/A4):
  `scripts/evaluate_synthesis.py` and `scripts/generate_claude_prior.py` (full
  deprecated implementations now packaged as `mantis run evaluation` /
  `mantis run claude-prior`), `scripts/_promote_or_to_primary.py` (superseded by
  `models.primary`, ADR-0005), the shared `scripts/_default_prompts.py` (its only
  importers were the removed scripts), and the 38 one-off batch-authoring scripts
  (`_build_batch_*.py`, `author_batch_*.py`) whose output configs are committed
  under `config/`. `scripts/` now holds only the `check_core_purity.py` gate.
  Docs that pointed at the removed scripts were updated to the packaged commands
  (`CLAUDE.md`, `prompts/playbooks/evaluation-prompt.md`,
  `research-path-recommendation.md`, the two stage docstrings); the now-empty
  `scripts/author_batch_*.py` ruff exclude was dropped. Archival `config/*.json`
  descriptions and the historical notes/ADRs that mention the promote script are
  left intact — they record how past batches were actually run.

### Fixed

- `preflight` is now part of the `Stage` Protocol: the CLI dispatch layer calls
  `await stage.preflight()` instead of reaching through `stage._adapter` with a
  duck-typed `hasattr` check. Each stage delegates to its adapter (Claude/Gemini
  sync, OpenRouter async). No behavior change; the coupling smell is gone.
- Non-numeric topic ids no longer crash stage path-building. The eight
  `int(topic_id)` filename-formatting sites across six stages now use the
  `topic_nn` / `topic_stem` helpers, which zero-pad numeric ids exactly as
  before but pass non-numeric ids (which the config schema permits) through
  verbatim instead of raising `ValueError`.
- Rate-limit detection no longer misclassifies network errors: the bare
  `resets` pattern (which matched "connection resets by peer" and forced a
  30-minute backoff) is replaced by the anchored `limit resets` /
  `limit · resets` forms. Genuine Claude usage-limit banners still classify as
  rate limits.

### Added

- `mantis status` and `mantis monitor` are now layout-aware (§19): status reads
  the run's `runner.layout` / `batch_name` and resolves each stage's state dir
  through the layout resolver (and now also reports the evaluation and
  claude-prior stages); monitor gains optional `--batch-name` / `--layout` to
  watch a batch-scoped `progress.json`. Bare `mantis monitor <stage>` is
  unchanged.
- Layout-aware dispatch + an in-memory-config seam (§18): `_run_stage_async`
  now resolves run directories through the §11 layout resolvers (legacy stays
  byte-identical), and a new `dispatch_stage_config(name, cfg, …)` runs a stage
  from an already-built `BatchConfig` with no path read — the seam
  `mantis research` calls once per stage, carrying the same unknown-stage and
  `MANTIS_DISABLED_STAGES` guards as the subcommands. The path-based
  `dispatch_stage` is now a thin wrapper over it.
- The evaluation and claude-prior stages are now packaged (§15): `mantis run
  evaluation` scores the synthesis against the 3-gate + 6-criterion rubric
  (parsing verdict + quality score into state), and `mantis run claude-prior`
  produces the topic-title-only baseline that Gate 3 needs. Both implement the
  Stage Protocol and are in `STAGE_REGISTRY`; the legacy `evaluate_synthesis.py`
  / `generate_claude_prior.py` scripts are deprecated in place. Evaluation
  opt-in mirrors falsification (`stages.evaluation.enabled` or `high_stakes`);
  a `stages.evaluation` config slot is added (additive, I4).
- The synthesis stage now emits the epistemic sidecar (ADR-0003, §14): after
  the brief is written, a dedicated sidecar turn has the model write
  `<stem>.sidecar.json`, which the stage validates against the v1 schema and
  merges with runner-authored identity + provenance. A malformed sidecar never
  re-runs the expensive synthesis — it re-asks up to a bounded budget, and an
  orchestrator retry skips Turn 1 when the brief already exists. `SynthesisState`
  gains `sidecar_bytes`. The `SYNTHESIS_SIDECAR` prompt brace-escapes its JSON
  example so `str.format` cannot break on it.
- Batch-scoped run layout (`runner.layout`, ADR-0006): `legacy` (default)
  keeps the flat directories every committed batch uses; `batch` scopes a run's
  state / outputs / transcripts under `<batch_name>/` so request-level runs and
  reruns never collide and each batch's tree can be archived or deleted
  atomically. New pure resolvers (`run_state_dir` / `run_output_dir` /
  `run_transcript_dir` and a `RunDirs` helper) in `core/paths.py`; the
  synthesis / falsification / journal-passes stages now resolve every directory
  they touch through one layout, so a run never mixes layouts. `legacy` is
  byte-identical to the previous paths (the config corpus stays there).
- Research-prompt templating (`topics[].research_prompt`, ADR-0008): a
  research subsession (Claude / Gemini / OpenRouter) may omit its own `prompt`
  and inherit the topic's `research_prompt`, so a multi-substrate topic carries
  one prompt plus thin per-substrate entries instead of N verbatim copies.
  Resolution keys on **presence** (`is not None`), never truthiness — an
  explicit empty-string prompt is kept (163 committed Path-B topics rely on
  this), and only a fully-omitted prompt with no `research_prompt` fails
  loading (naming the topic and subsession).
- Primary-brief selection is now a config field (`models.primary`, ADR-0005):
  `null`/`"claude"` keeps the Claude brief primary (default); an
  `"openrouter:<subslug>"` value promotes that OpenRouter brief to primary and
  demotes the rest (Claude included, when present) to secondaries. This makes
  Path B (no Claude research) a one-line config change instead of the
  `_promote_or_to_primary.py` file-shuffle, which is now deprecated in place.
  The synthesis prompt gains `{primary_path}` / `{primary_size_kb}` /
  `{primary_label}` variables; the legacy `{claude_path}` / `{claude_size_kb}`
  keys are aliased to the resolved primary so every existing template still works.
- OpenRouter per-subsession usage/cost is now persisted: the adapter requests
  `usage.include=true` and `SubsessionResult` gains additive optional
  `tokens_prompt` / `tokens_completion` / `tokens_reasoning` / `cost_usd`
  fields (None when the provider returns no usage block). A golden-file test
  (`tests/unit/test_state_golden.py`) loads verbatim pre-series state files for
  every stage class, pinning that the additive change stays I4-compatible.

### Changed

- README rewritten for what the tool now is — an agent-facing deep-research
  tool (question in, cross-checked synthesis + epistemic sidecar out) — with
  the `mantis research` quickstart, assurance tiers, the sidecar contract,
  batch mode, and the layout/primary/research_prompt config knobs. `CLAUDE.md`
  documents the same knobs; the superseded "Phase 4 will rename" note in
  `core/paths.py` is removed (the batch layout is opt-in, not a migration).
- The `Stage` boundary is now typed end-to-end (ADR-0007): `RunContext.config`
  (a `model_dump()` dict) became `RunContext.batch: BatchConfig`, and
  `Stage.run_attempt` / `Stage.is_enabled` receive `TopicConfig` / `BatchConfig`
  instead of dicts. Stages read validated attributes (`ctx.batch.models.claude`,
  `topic.stages.synthesis.prompt`) rather than `.get()` chains. No behavior
  change; the whole test suite passes with its assertions unchanged. Optional
  `ModelSpec.effort` is read as `effort or 'max'` (not bare, which would pass
  `None`), and the possibly-`None` `models.gemini` is guarded before use.
- Docs now match the shipped CLI: the pipeline-stage table in `CLAUDE.md` no
  longer advertises `mantis run` subcommands that the stage registry does not
  expose (`journal-augment` corrected to `journal-passes`; `evaluation` and
  `claude-prior` marked as legacy scripts pending their packaging in §15).
- Removed the unused, misleading `TopicStatus.is_terminal` property (it claimed
  FAILED / RATE_LIMITED / BLOCKED_UPSTREAM are "terminal", contradicting the
  actual cross-run behavior where only DONE is skipped). The state-module
  docstring now documents both the within-run and cross-run transition rules;
  a test pins that non-DONE prior states are re-attempted on the next run.

### Removed

- Stale root docs `CLAUDE_CODE_PROMPT.md`, `CLAUDE_CODE_VALIDATION_PROMPT.md`,
  and `BATCH_RUNNER.md` (the still-current operating notes moved into
  `CLAUDE.md`).

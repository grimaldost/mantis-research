# Spec — Agent-researcher pivot + review remediations

- **Date:** 2026-07-03
- **Status:** done (all 19 PRs merged; DoD met; 273 tests green)
- **Audience:** per-PR implementer subagents, reviewers, and the series operator
- **Output artifact(s):** `docs/specs/0001-agent-researcher-pivot.md` (this file), 19 PRs on `master`, `pr-series/series.toml`

## Context

The 2026-07-01 architecture review confirmed the runner's differentiated value
(substrate-diverse research, divergence-preserving synthesis, falsification)
and found one strategic gap — outputs are optimized for humans and mantis
ingestion, not for agent consumers — plus a family of remediable defects:
doctrine ahead of code (Path B via file-promotion scripts), an unfinished
package migration (evaluation/claude-prior still legacy scripts), a globally
flat run namespace, verbatim prompt duplication in configs, a discarded typed
config at the stage boundary, and several small correctness items.

Decisions are recorded in `docs/adr/0001-architecture-invariants-baseline.md`
through `docs/adr/0008-research-prompt-templating.md`. This spec turns them
into one governed series.

Contract stance (data-engineering discipline): the persisted state schema, the
batch-config schema, the existing output trees, the synthesis markdown format,
the legacy `progress.json` shape, and the existing CLI surface are protected
contracts — every change to them in this series is additive, and every
deliberate divergence is named in the section that makes it.

## Goal

Make the runner a request-level research tool for agent consumers — one
command from question to cross-checked synthesis plus a machine-readable
epistemic sidecar — while fixing every defect the review found, without
breaking any existing batch, config, or on-disk artifact.

## Gate commands

Run from the project root; all must exit 0:

- `uv run ruff format --check src tests`
- `uv run ruff check src tests`
- `uv run ty check src` — primary type checker (Astral's ty)
- `uv run python -m pytest -q`
- `uv run python scripts/check_core_purity.py` — from §7 onward (file is created there)

`mypy` is a **CI-only** secondary fallback (per `CLAUDE.md`); it is not in the
project's dependency groups, so `uv run mypy src` fails locally with "program
not found" on this machine — do NOT list it as a local gate. `ty` is the
gating type checker; a PR that needs the mypy fallback runs it in CI, not as a
local exit condition.

Windows note: `.exe` shims (`pytest`, `mantis`, `keel`) are blocked by
Application Control on this machine — invoke via `uv run python -m …` forms
only. The CLI smoke form is `uv run python -m mantis_research …`.

## Non-goals

- No MCP server in this series (ADR-0004 defers it; the CLI façade is the seam).
- No in-place migration or renaming of existing output/state trees (I6); the
  old "Phase 4 git mv" plan is superseded by ADR-0006.
- No deletion of legacy scripts (deprecation pointers only; removal is a later
  cleanup series).
- No per-topic primary override (ADR-0005 defers it).
- No concurrent multi-provider execution inside one stage run (ADR-0004 names
  the bulkhead precondition; out of scope).
- No changes to mantis ingestion itself, to the journal envelope format, or to
  the Gemini OAuth adapter.
- No renaming of the package or project.

## Invariants touched

All from `docs/adr/0001-architecture-invariants-baseline.md`; the sidecar
contract from `docs/adr/0003-epistemic-sidecar-artifact.md`.

- **I1 core purity** — touched by §7 (gate script), §13 (new pure module).
- **I2/I3 Protocol seams** — touched by §5 (preflight joins the Stage
  Protocol), §6 (typed signatures), §15 (two new stages), §18 (dispatch seam
  passes `BatchConfig`).
- **I4 additive-only persisted schemas** — touched by §8, §9, §10, §11, §12
  (config fields), §12 (state fields).
- **I5 resumability** — touched by §11 (layout-scoped state dirs), §14
  (sidecar sub-loop + idempotent re-entry keep synthesis resumable).
- **I6 legacy artifacts stay readable** — touched by §11 (dual layout), §9
  (promote-script deprecation), §18/§19 (legacy invocations unchanged under the
  new layout-aware dispatch/reporting).
- **Sidecar v1 contract** — created by §13/§14.

## Enforcement status

| Invariant | Status | Gate/mechanism |
|---|---|---|
| I1 core purity | planned | `scripts/check_core_purity.py`, created by §7, then a listed gate command |
| I2/I3 Protocol seams | review-only | `docs/method/review-checklist.md` |
| I4 additive-only persisted schemas | planned | config-corpus load test (§8) + golden-file state test (§12) |
| I5 resumability | enforced | `tests/integration/test_orchestrator.py` + openrouter subsession-skip behavior |
| I6 legacy artifacts stay readable | review-only | pre-mortem + review checklist |
| sidecar v1 contract | planned | pydantic validation inside the synthesis stage (§14) |

## Concept → module map

| Concept introduced/changed | Module / file it lives in |
|---|---|
| CHANGELOG (release-notes-in-wave) | `CHANGELOG.md` — to be created (§1) |
| Rate-limit pattern set | `src/mantis_research/core/retry.py` |
| Status-transition semantics | `src/mantis_research/core/state.py` |
| Topic stem naming (`topic_stem`) | `src/mantis_research/core/paths.py` |
| Stage-owned preflight | `src/mantis_research/core/stage.py` |
| Typed stage context | `src/mantis_research/core/stage.py`, `src/mantis_research/interface/orchestrator.py` |
| Core-purity gate | `scripts/check_core_purity.py` — to be created (§7) |
| Pre-commit wiring | `.pre-commit-config.yaml` — to be created (§7) |
| Journal-turn gating | `src/mantis_research/interface/stages/synthesis.py` |
| Config-corpus compatibility test | `tests/unit/test_config_corpus.py` — to be created (§8) |
| Primary-brief selection (`models.primary`) | `src/mantis_research/core/config.py`, `src/mantis_research/interface/stages/synthesis.py` |
| Research-prompt templating (`research_prompt`) | `src/mantis_research/core/config.py` |
| Batch-scoped layout resolvers | `src/mantis_research/core/paths.py` (config field in `core/config.py`, orchestrator wiring) |
| Layout-aware dispatch + in-memory-config seam | `src/mantis_research/interface/cli/dispatch.py` |
| Layout-aware status + monitor | `src/mantis_research/interface/cli/status.py`, `src/mantis_research/interface/cli/monitor.py` |
| Usage/cost persistence | `src/mantis_research/interface/adapters/openrouter_http.py`, `src/mantis_research/core/state.py`, `src/mantis_research/interface/stages/openrouter_research.py` |
| Golden-file state compatibility test | `tests/unit/test_state_golden.py` — to be created (§12) |
| Sidecar schema (v1) | `src/mantis_research/core/sidecar.py` — to be created (§13) |
| Sidecar emission + merge | `src/mantis_research/interface/stages/synthesis.py`, `src/mantis_research/core/prompts.py` |
| Evaluation stage (packaged) | `src/mantis_research/interface/stages/evaluation.py` — to be created (§15) |
| Claude-prior stage (packaged) | `src/mantis_research/interface/stages/claude_prior.py` — to be created (§15) |
| Request-level entry (`mantis research`) | `src/mantis_research/interface/cli/research.py` — to be created (§16) |
| Positioning + operator docs | `README.md`, `CLAUDE.md` |

## Numbered sections

### §1 Docs-truth baseline and CHANGELOG bootstrap
Create `CHANGELOG.md` (Keep-a-Changelog style, seeded with an Unreleased
section); correct `CLAUDE.md` where it currently overstates the CLI: the
pipeline-stage table advertises `mantis run evaluation` and
`mantis run claude-prior` subcommands that do not exist in
`src/mantis_research/interface/cli/run.py` (the registry ends at
falsification, `src/mantis_research/interface/cli/dispatch.py:99`
`    'falsification': StageEntry(`) — mark those two rows "legacy script;
packaged by §15 of docs/specs/0001-agent-researcher-pivot.md" until §15 lands.
Also delete the stale root docs `CLAUDE_CODE_PROMPT.md` and
`CLAUDE_CODE_VALIDATION_PROMPT.md` and fold anything still true from
`BATCH_RUNNER.md` into a short "operating a batch" note inside `CLAUDE.md`
(the README rewrite itself is §17, not here). Every later PR in this series
appends its CHANGELOG entry in its own wave.
**Acceptance criterion:** `CHANGELOG.md` exists with an Unreleased section;
`CLAUDE.md` no longer names a `mantis run` subcommand absent from
`STAGE_REGISTRY`; the two stale prompt docs are gone from the root; gate
commands pass.

### §2 Rate-limit classification tightening
`src/mantis_research/core/retry.py:35` `        'resets',  # 'resets 12:50am'`
classifies ANY output containing "resets" as a rate limit (30-minute backoff)
— e.g. "connection resets by peer" from a network failure. Replace the bare
`'resets'` member with the two anchored variants observed from the Claude CLI
("limit · resets", already present at `src/mantis_research/core/retry.py:36`,
plus a plain `'limit resets'`), keeping every other pattern unchanged.
**Acceptance criterion:** a regression test asserts
`classify_failure('error: connection resets by peer') is FailureKind.GENERIC`
and that the known Claude usage-limit phrasings still classify as
`RATE_LIMIT`; full suite green.

### §3 Status-transition semantics cleanup
`src/mantis_research/core/state.py:50` `    def is_terminal(self) -> bool:`
is unused in `src/` and its docstring ("not retried by the orchestrator")
contradicts actual cross-run behavior — the orchestrator re-runs everything
except DONE (`src/mantis_research/interface/orchestrator.py:279`
`        return state.status is not TopicStatus.DONE`). Delete the property and
**delete** its sole consumer, the 6-case parametrized test
`test_terminal_classification`
(`tests/unit/test_state.py:36-48` `    def test_terminal_classification(self, status: TopicStatus, is_terminal: bool) -> None:`)
— that test is not "updated": its whole premise (FAILED/RATE_LIMITED/
BLOCKED_UPSTREAM are terminal) is the very contradiction §3 removes, so it is
deleted with the property, not adapted. Rewrite the transition diagram in the
module docstring
(`src/mantis_research/core/state.py:15-19`) to state both scopes:
within one run (retry loop) and across runs (everything except DONE is
re-attempted; BLOCKED_UPSTREAM re-gates).
**Acceptance criterion:** `is_terminal` no longer exists in `src/` and
`test_terminal_classification` no longer exists in `tests/`; the docstring
transition table names the cross-run rule; a new unit test pins "non-DONE
states are selected as pending" via `Orchestrator._is_pending` or an
equivalent public observation; suite green.

### §4 Non-numeric topic-id stem handling
Stages format stems with `int(topic_id)`
(`src/mantis_research/interface/stages/synthesis.py:38`
`    return f'{int(topic_id):02d}-{slug}'`), which raises `ValueError` for
non-numeric ids that `TopicConfig` explicitly permits
(`src/mantis_research/core/config.py:107-113` normalizes int→str).
Add `topic_stem(topic_id, slug)` to `src/mantis_research/core/paths.py`:
zero-pad to two digits when the id is all digits (preserving every existing
path), pass the id through verbatim otherwise. Replace **all eight** `int(topic_id)` stem-formatting sites, which live in
**six** files under `src/mantis_research/interface/stages/` —
`synthesis.py` (1), `claude_research.py` (1), `openrouter_research.py` (2),
`falsification.py` (1), `journal_passes.py` (1), and `gemini_research.py` (2,
`src/mantis_research/interface/stages/gemini_research.py:149`
`        nn = f'{int(topic_id):02d}'`) — with the helper. The file list must
include `gemini_research.py` (the site the first draft omitted); the acceptance
grep below is the backstop that no site is missed.
**Acceptance criterion:** unit tests pin `topic_stem('7', s) == '07-'+s`,
`topic_stem('901', s) == '901-'+s`, and `topic_stem('a5', s) == 'a5-'+s`; a
repo grep for `int(topic_id)` under
`src/mantis_research/interface/stages/` returns zero hits (was eight);
suite green.

### §5 Stage-owned preflight
The dispatch layer reaches into a private attribute to find an adapter
preflight (`src/mantis_research/interface/cli/dispatch.py:133`
`    if not dry_run and hasattr(stage, '_adapter') and hasattr(stage._adapter, 'preflight'):`).
Add `async def preflight(self) -> None` to the `Stage` Protocol in
`src/mantis_research/core/stage.py`; each stage implements it by
delegating to its adapter (sync adapter preflights are called directly inside
the async method); dispatch calls `await stage.preflight()` when not dry-run
and stops touching `_adapter`.
**Acceptance criterion:** `hasattr(stage, '_adapter')` no longer appears in
`dispatch.py`; each registered stage exposes `preflight`; a unit test asserts
dispatch invokes it (fake stage records the call) and that `--dry-run` skips
it; suite green.

### §6 Typed stage context (ADR-0007)
Replace the dict boundary: `RunContext.config`
(`src/mantis_research/core/stage.py:66`
`    config: dict[str, Any]  # parsed batch config (v2 schema)`) becomes
`batch: BatchConfig`, and `Stage.run_attempt` receives `topic: TopicConfig`
instead of `dict` (the orchestrator currently dumps both:
`src/mantis_research/interface/orchestrator.py:109`
`            config=self.config.model_dump(),` and
`src/mantis_research/interface/orchestrator.py:190`
`                result = await self.stage.run_attempt(topic.model_dump(), state, ctx)`).
Migrate all six stages, `is_enabled` signatures, the orchestrator, dispatch,
and the fake stages in tests (`FakeStage`/`CountingStage` in
`tests/integration/test_orchestrator.py:44-67` and `:309-324` read
`topic['id']`/`topic.get('id')` and are in scope) to typed attribute access.
Behavior is identical — this is a refactor with no semantic change; any
semantic fix discovered mid-migration is deferred to its own section, not
folded in.

**Translation invariant (not one-for-one).** A dict `.get(key, DEFAULT)`
must become `model.attr or DEFAULT`, **not** bare `model.attr`, wherever the
model field is Optional-with-None-default — otherwise the default silently
becomes `None`. The load-bearing sites: `models.get('effort', 'max')` at
**four** stages — `claude_research.py`, `synthesis.py`, `journal_passes.py`,
`falsification.py` (gemini and openrouter carry no effort default), e.g.
`src/mantis_research/interface/stages/synthesis.py:166`
`        effort = synth_model_cfg.get('effort', 'max')` — where
`ModelSpec.effort` defaults to `None`
(`src/mantis_research/core/config.py:131` `    effort: str | None = None`),
and the gemini model fallback
(`src/mantis_research/interface/stages/gemini_research.py:90`
`        gemini_model = ctx.config['models'].get('gemini', {}).get('model', 'gemini-3-pro-preview')`)
where `models.gemini` may itself be `None`
(`src/mantis_research/core/config.py:139` `    gemini: ModelSpec | None = None`).
**Acceptance criterion:** no `model_dump()` call remains on the
orchestrator→stage path; `run_attempt` signatures take `TopicConfig`; a new
test pins `effort == 'max'` when a config omits `models.effort` (proving the
`or 'max'` fallback survived the rewrite) and pins the gemini model default
when `models.gemini is None`; the full suite passes unchanged in its
behavioral assertions (test plumbing may change, expected values may not);
`uv run ty check src` passes.

### §7 Core-purity gate (I1 becomes a machine check)
Create `scripts/check_core_purity.py`: AST-walk every module under
`src/mantis_research/core/` and exit 1 if any imports `httpx`,
`subprocess`, `socket`, `requests`, `aiohttp`, or `asyncio.subprocess`
(direct or `from` form). Create `.pre-commit-config.yaml` wiring ruff-format,
ruff, and the purity script (local hook); document both as gate commands.
**Acceptance criterion:** the script exits 0 on the current tree; a test
fixture proves it exits 1 when a core module imports `httpx` (tmp tree);
`uv run pre-commit run --all-files` passes; the script is listed in this
spec's gate commands and in `CLAUDE.md`'s build/test table.

### §8 Journal turn honors `enabled` (+ config-corpus test)
The synthesis stage always runs Turn 2
(`src/mantis_research/interface/stages/synthesis.py:206`
`        # ── Turn 2 — journal (resumes same session) ────────────────`)
even though the schema already carries an ignored switch
(`src/mantis_research/core/config.py:78`
`    enabled: bool | None = None  # None means default`). Honor it:
`stages.journal.enabled is False` skips Turn 2 (state records
`journal_bytes = None`; the attempt succeeds on synthesis alone);
`None`/`True` keep today's behavior — the batch default stays ON (ADR-0002).
Because this is the first config-semantics PR, it also adds
`tests/unit/test_config_corpus.py`: a parametrized test that
`load_batch_config` accepts every `config/*.json` in the repo (I4's
real-data gate).
**Acceptance criterion:** a stage test proves `enabled=False` produces a
synthesis but no journal call (fake adapter records one run, not two) and
`enabled=None` produces both; the corpus test passes over all committed
configs; suite green.

### §9 Primary-brief selection in config (ADR-0005)
Add `primary: str | None = None` to `ModelsBlock`
(`src/mantis_research/core/config.py:134-141`): `None`/`'claude'` =
today's behavior; `'openrouter:<subslug>'` selects that subsession's brief as
the synthesis primary. Rework the synthesis stage: `upstream_ready` requires
the primary brief plus ≥1 other brief (today it hard-requires Claude:
`src/mantis_research/interface/stages/synthesis.py:103`
`        if not _claude_path(topic_id, slug).exists():`); prompt formatting
gains `{primary_path}` / `{primary_size_kb}` / `{primary_label}` with the
legacy `{claude_path}` / `{claude_size_kb}` keys bound to the primary as
aliases, and the primary is excluded from the secondary block. Deprecate
`scripts/_promote_or_to_primary.py` in place (module docstring points here;
no behavior change to the script).
**Acceptance criterion:** stage tests cover both modes — default (unchanged
paths and gating, proven by existing tests staying green) and
`primary='openrouter:gpt-5-exa'` (upstream gate passes with no Claude brief on
disk; the formatted prompt's `{claude_path}` equals the OR primary's path);
config corpus still loads; suite green.

### §10 Research-prompt templating (ADR-0008)
Add optional `research_prompt: str | None` to `TopicConfig` and make
subsession prompts optional with fallback: `OpenRouterSubsessionConfig.prompt`
(`src/mantis_research/core/config.py:67` `    prompt: str`),
`GeminiSubsessionConfig.prompt`, and `ClaudeStageConfig.prompt`
(`src/mantis_research/core/config.py:30` `    prompt: str`) become
`str | None = None`.

**Resolution keys on PRESENCE, not truthiness (load-bearing).** The rule is
"an explicitly-set prompt — *including the empty string* — wins; the
`research_prompt` fallback fires only when the field is `None` (omitted)."
This is not optional polish: **163 of the 232 topics** in the committed corpus
carry `"claude": {"prompt": ""}` (Path B configs where Claude does no research
— e.g. `config/batch-12-or-research.json:37`), all valid under today's
`prompt: str`. A truthiness resolution (`self.prompt or topic.research_prompt`)
makes `''` fall through to an absent `research_prompt` and raises on all 163 —
so the resolver must test `is not None`, never truthiness. ADR-0008 backs this
("an explicit per-subsession prompt always wins"; `''` is explicit, not
omitted). Resolution happens in a model validator on `TopicConfig` so stages
keep seeing a concrete prompt string (no stage code change). Because this PR
must not merge before the corpus gate exists, PR10 depends on PR08.
**Acceptance criterion:** unit tests pin four cases (own non-empty prompt wins;
own **empty-string** prompt wins — no fallback, no error; `None` field →
`research_prompt` fills; `None` field + no `research_prompt` → `ValidationError`
naming topic id and subslug); every existing config still validates via the
corpus test (all 44 load, none regressed); suite green.

### §11 Batch-scoped run layout (ADR-0006)
Add pure resolvers to `src/mantis_research/core/paths.py`:
`run_state_dir(layout, batch_name, stage)`, `run_output_dir(...)`,
`run_transcript_dir(...)` where `layout='legacy'` reproduces today's mapping
(`src/mantis_research/core/paths.py:73` `LEGACY_OUTPUT_DIRS: dict[str, str] = {`)
and `layout='batch'` yields `state/<batch_name>/<stage>/`,
`outputs/<batch_name>/<stage>/`, `transcripts/<batch_name>/`. Add
`layout: Literal['legacy','batch'] = 'legacy'` to `RunnerBlock`. This section
delivers the pure resolvers, the config field, and the orchestrator wiring
only; the dispatch seam that threads layout into a run is §18, and the
layout-aware reporting CLIs are §19 (both split out because they are distinct
concerns touching distinct modules). The cross-stage discovery helpers inside
the synthesis / falsification / journal-passes stages
(`_synthesis_path`, `_briefs_in_stage_dir`, etc.) take the run's
(layout, batch_name) so a run never mixes layouts. `layout='legacy'` must
reproduce today's mapping exactly (`LEGACY_OUTPUT_DIRS`,
`src/mantis_research/core/paths.py:73`).
**Acceptance criterion:** path unit tests pin both layouts; an orchestrator
test runs a fake stage under `layout='batch'` and asserts state and
progress.json land under `state/<batch>/<stage>/`; legacy-layout tests remain
byte-identical in expected paths (the whole 44-config corpus stays on
`layout='legacy'` by default); suite green.

### §12 Usage and cost persistence
The OpenRouter adapter already parses `usage`
(`src/mantis_research/interface/adapters/openrouter_http.py:69`
`    usage: dict[str, int] | None = None  # tokens in / out / cached / reasoning`)
but nothing persists it. Request cost accounting (`body['usage'] =
{'include': True}`) in `_build_body`, and extend `SubsessionResult`
(`src/mantis_research/core/state.py:141-149`) with additive optional
fields `tokens_prompt: int | None`, `tokens_completion: int | None`,
`tokens_reasoning: int | None`, `cost_usd: float | None`; the openrouter stage
fills them from the adapter result. Add `tests/unit/test_state_golden.py`
loading verbatim copies of real pre-series state files (one per stage state
class, copied under `tests/data/state-golden/`) to pin I4.
**Acceptance criterion:** a stage test asserts a successful subsession
persists token/cost fields when the response carries usage and leaves them
`None` when absent; golden-file tests load unmodified pre-series state JSON
for every state class; suite green.

### §13 Sidecar schema v1 (ADR-0003)
Create `src/mantis_research/core/sidecar.py` (pure, I1): pydantic
models for `ResearchSidecar` v1 — `sidecar_version: Literal[1]`, run identity
(topic id/slug/batch name, synthesis path, generated-at), `sources` (label,
path, model id, bytes), `claims` (stable id, verbatim text, section ref,
support: direct/indirect/none), `divergences` (id, description, substrates on
each side, assessment), `verification_queue` (id, claim, why flagged, which
sources disagree), `agreements_worth_verifying`, `coverage_notes`, and
runner-filled `provenance` (durations, token/cost totals per source from §12).
Two authorship zones are explicit in the model docstrings: model-authored
(epistemic fields) vs runner-authored (identity + provenance) per ADR-0003.
**Acceptance criterion:** unit tests round-trip a full v1 document and reject
a wrong `sidecar_version` and a claim without an id;
`uv run python scripts/check_core_purity.py` still passes (no new I/O in
core); suite green.

### §14 Sidecar emission in the synthesis stage
A new `SYNTHESIS_SIDECAR` template block in
`src/mantis_research/core/prompts.py` instructs the model to Write
`<stem>.sidecar.json` with ONLY the model-authored fields. The stage appends
it to the synthesis prompt (so existing custom synthesis prompts in configs
keep working and still get a sidecar).

**Brace-escaping (mandatory).** The stage `.format()`s the whole prompt
(`src/mantis_research/interface/stages/synthesis.py:141` `        synth_prompt = synth_template.format(`),
so every literal `{`/`}` in the SIDECAR block's JSON example MUST be doubled
`{{`/`}}` exactly as the `EVALUATION` template already does
(`src/mantis_research/core/prompts.py:173` `Save the evaluation record to {eval_path} as STRUCTURED JSON with this exact shape:`
followed by its `{{`-escaped body). The sidecar path is exposed as a single
real `.format` key (`{sidecar_path}`). A test formats the composed prompt and
asserts no `KeyError`/`ValueError` — a bare brace would break EVERY synthesis,
not just custom-prompt ones.

**Sidecar failure must NOT re-run the expensive 2-turn session (I5).** A
synthesis attempt is two Claude turns (brief + journal,
`src/mantis_research/interface/stages/synthesis.py:170-231`); a
malformed sidecar is a cheap, model-fallible step and must not trigger a full
re-run. Two mechanisms, both in this section:
1. **Bounded in-attempt sidecar sub-loop.** After the brief is written the
   stage runs a sidecar resume-turn; on schema-validation failure it re-asks
   on the same session, feeding back the validation error, up to 2 re-asks.
   Only if the sub-loop exhausts does the attempt fail.
2. **Idempotent re-entry.** `run_attempt` skips Turn 1 when the brief already
   exists on disk AND `state.synthesis_bytes` is set. The skip guard goes
   **before** the Turn-1 adapter call at
   `src/mantis_research/interface/stages/synthesis.py:186`
   `        t1 = await self._adapter.run(` (not at the post-turn failure guard
   at `:199-203`, which only checks the brief was produced), so an
   orchestrator-level retry resumes at the sidecar/journal steps rather than
   regenerating a good brief.

This refines ADR-0003's retry model: the orchestrator still retries on
sub-loop exhaustion, but re-entry is cheap (Turn 1 skipped), so an invalid
sidecar never re-runs the expensive synthesis — the ADR's "an invalid sidecar
fails the attempt" holds, with the attempt's cost bounded.

On success the stage fills the runner-authored identity/provenance fields
(from state + §12 usage data) and rewrites the file atomically; the merged
sidecar joins the synthesis done-condition alongside the brief.

**Resumability / --force note (I5/I6).** A synthesis marked DONE by a
pre-§14 run is skipped before `run_attempt`
(`src/mantis_research/interface/orchestrator.py:148`
`            if state.status is TopicStatus.DONE:`), so it never retro-acquires
a sidecar — consistent with I6 (old artifacts stay readable; the sidecar is
additive). `--force` clears state and re-runs, producing a sidecar. Update
`prompts/playbooks/synthesis-prompt.md` to document the sidecar contract.
**Acceptance criterion:** stage tests with a fake adapter cover: valid
model-written sidecar → merged file contains both zones and attempt succeeds;
first sidecar invalid then valid on re-ask → attempt still succeeds with no
second Turn-1 call (fake adapter records exactly one brief turn); sidecar
invalid through the whole sub-loop → `AttemptResult.fail` with the brief left
intact; a retry after that failure does NOT re-call Turn 1; the composed-prompt
`.format()` test passes; `SynthesisState` gains additive
`sidecar_bytes: int | None`; playbook updated; suite green.

### §15 Evaluation and claude-prior stages join the package
Port `scripts/evaluate_synthesis.py` and `scripts/generate_claude_prior.py`
onto the Stage Protocol: `src/mantis_research/interface/stages/evaluation.py`
(needs synthesis + claude-prior baseline on disk; writes
`evaluations/<stem>.json`; parses verdict/quality-score into `EvaluationState`
which already exists at `src/mantis_research/core/state.py:194-201`) and
`src/mantis_research/interface/stages/claude_prior.py`
(topic-title-only baseline brief; a
`CLAUDE_PRIOR` template joins `core/prompts.py`). Register both in
`STAGE_REGISTRY`, add `mantis run evaluation` / `mantis run claude-prior`
subcommands, reuse the legacy output dir names already mapped at
`src/mantis_research/core/paths.py:80-81`. The legacy scripts get
deprecation docstrings pointing at the subcommands. `is_enabled` for
evaluation follows the falsification opt-in pattern
(`high_stakes` or explicit enable). Update the `CLAUDE.md` rows §1 marked as
pending.
**Acceptance criterion:** both stages appear in `STAGE_REGISTRY` and the CLI
help; stage tests cover upstream gating (evaluation blocks without baseline)
and a happy path with fake adapters; `CLAUDE.md` stage table now matches the
real CLI; suite green.

### §16 `mantis research` one-shot command (ADR-0004)
Create `src/mantis_research/interface/cli/research.py`:
`mantis research "<question>"` with
`--assurance fast|standard|high` (default `standard`), `--substrates`
(default: the 4-substrate Path B set from
`prompts/playbooks/model-recommendations.md`, using `auto:<vendor>` model
sentinels), `--primary` (default the Path B recommendation), `--journal/--no-journal`
(default off, ADR-0002), `--batch-name` (default derived from a slugified
question + date), `--dry-run`. It builds a `BatchConfig` in memory
(`schema_version 2`, `layout='batch'`, topic id `1`, `research_prompt` set
from the question through a generic research template added to
`core/prompts.py`), then runs the stage sequence by calling the **§18
in-memory-config seam** once per stage in dependency order (research
substrates → synthesis+sidecar → falsification when ≥ standard → claude-prior +
evaluation when high). It does NOT re-implement dispatch and does NOT assume
`dispatch_stage` accepts a config object — that seam is created in §18, which
this section depends on. Each seam call is its own top-level `asyncio.run`
(the sync `dispatch_stage` pattern,
`src/mantis_research/interface/cli/dispatch.py:181`
`    return asyncio.run(`), invoked sequentially — no nested event loop. The
command is registered in `src/mantis_research/interface/cli/__init__.py`
via `app.command(name='research')` (alongside the existing
`status`/`monitor`/`version` registrations,
`src/mantis_research/interface/cli/__init__.py:37-38`
`app.command(name='status')(status_cmd)`) — creating `research.py` alone leaves
the command unreachable. It prints a manifest JSON to stdout: paths (briefs,
synthesis, sidecar, falsification, evaluation), per-source and total durations,
token/cost totals (§12), and per-stage exit status. Exit code 0 only when
every requested stage succeeded.
**Acceptance criterion:** `uv run python -m mantis_research research
"test question" --dry-run` completes offline, `mantis --help` lists `research`,
the run creates the batch-scoped state tree, and prints a manifest whose paths
all follow the `layout='batch'` resolvers; a unit test builds the in-memory
config and asserts tier→stage mapping for the three assurance levels; suite
green.

### §17 README rewrite and CLAUDE.md refresh
Rewrite `README.md` for what the tool now is (README today still describes
the pre-pipeline single-topic test harness): positioning (agent-facing
researcher, ADR-0002), quickstart (`mantis research`, then batch mode), the
stage table, the sidecar contract (pointer to `core/sidecar.py` and the
playbook), layout modes, cost notes, and the method pointer
(`docs/method/`). Refresh `CLAUDE.md`: gate commands including the purity
script, the two new subcommands, `runner.layout`, `models.primary`,
`research_prompt`, and remove the superseded "Phase 4 rename" note in
`src/mantis_research/core/paths.py:59-64` comments (comment update in
the same PR).
**Acceptance criterion:** README contains no claim contradicted by the CLI
(`--help` surfaces match the documented commands); CLAUDE.md's build/test
block equals this spec's gate list; the paths.py legacy comment no longer
promises the abandoned in-place rename; suite green.

### §18 Layout-aware dispatch + in-memory-config seam
The dispatch layer today only accepts a path and hardwires legacy dirs:
`dispatch_stage(name, config_path: Path, ...)`
(`src/mantis_research/interface/cli/dispatch.py:156`
`def dispatch_stage(`) calls `_run_stage_async`, which builds
`legacy_state_dir`/`legacy_output_dir` unconditionally
(`src/mantis_research/interface/cli/dispatch.py:138-139`
`    state_dir = legacy_state_dir(entry.legacy_state_name)`). Two changes,
one concern (the run seam):
1. **Layout-aware directory resolution.** `_run_stage_async` resolves state/
   output/transcript dirs via the §11 resolvers
   (`run_state_dir(cfg.runner.layout, cfg.batch_name, stage)`, etc.) instead of
   the `legacy_*` helpers — `layout='legacy'` yields byte-identical paths.
2. **In-memory-config entry point.** Add `dispatch_stage_config(name, cfg:
   BatchConfig, *, parallel, dry_run, force, only)` that runs a stage from an
   already-built `BatchConfig` (no path read); the existing path-based
   `dispatch_stage` becomes a thin wrapper that loads the config then delegates
   to it. This is the seam §16 calls once per stage. The unknown-stage guard,
   the `DISABLED_STAGES` guard, and `configure_logging` currently living only
   in `dispatch_stage`
   (`src/mantis_research/interface/cli/dispatch.py:167`
   `    if name not in STAGE_REGISTRY:`) move **into** `dispatch_stage_config`
   so the §16 seam path enforces the same gating as the subcommands (ADR-0004:
   "the same dispatch path the subcommands use").
Depends on §11 (resolvers) and §6 (typed context — the seam passes
`BatchConfig` through).
**Acceptance criterion:** `dispatch_stage_config` exists and runs a fake-stage
batch from an in-memory `BatchConfig`; a `layout='batch'` dispatch lands state
under `state/<batch>/<stage>/`; every existing dispatch/disabled-stage test
stays green (legacy paths unchanged); `hasattr(stage, '_adapter')` is already
gone from §5; suite green.

### §19 Layout-aware status and monitor
Both reporting CLIs are layout-blind. `mantis status` holds the config but
calls `legacy_state_dir(dir_name)` unconditionally
(`src/mantis_research/interface/cli/status.py:77`
`            sd = legacy_state_dir(dir_name)`) — fix in place: resolve via
`run_state_dir(cfg.runner.layout, cfg.batch_name, stage)`. `mantis monitor`
receives only a stage name and no config
(`src/mantis_research/interface/cli/monitor.py:20-26`
`def monitor_cmd(`), so it structurally cannot locate a batch-scoped
progress file — add an optional `--batch-name` and `--layout` (defaulting to
`legacy` + no batch, preserving today's behavior and its
`state/STAGE/progress.json` fallback) and route the progress-file lookup
through `run_state_dir`. Neither change alters legacy invocations.
**Acceptance criterion:** a batch-layout run followed by
`mantis status CONFIG` shows real per-stage markers (not all `.`);
`mantis monitor synthesis --batch-name demo --layout batch` finds
`state/demo/synthesis/progress.json`; a bare `mantis monitor synthesis`
invocation behaves exactly as today; suite green.

## PR ↔ section manifest

| PR | Implements section | One concern? |
|---|---|---|
| PR01 | §1 | yes — docs tell the truth at series start |
| PR02 | §2 | yes — rate-limit classification |
| PR03 | §3 | yes — status semantics |
| PR04 | §4 | yes — stem/id handling |
| PR05 | §5 | yes — preflight seam |
| PR06 | §6 | yes — typed context |
| PR07 | §7 | yes — purity gate |
| PR08 | §8 | yes — journal gating (+ its I4 test) |
| PR09 | §9 | yes — primary selection |
| PR10 | §10 | yes — prompt templating |
| PR11 | §11 | yes — batch layout |
| PR12 | §12 | yes — usage/cost persistence |
| PR13 | §13 | yes — sidecar schema |
| PR14 | §14 | yes — sidecar emission |
| PR15 | §15 | yes — packaged evaluation stages |
| PR16 | §16 | yes — request-level entry |
| PR17 | §17 | yes — positioning docs |
| PR18 | §18 | yes — layout-aware dispatch seam |
| PR19 | §19 | yes — layout-aware status + monitor |

Dependency DAG (for series.toml): PR06 → {PR08, PR09, PR10, PR11, PR12, PR13,
PR14, PR15, PR16, PR18, PR19}; PR08 → {PR09, PR10} (the config-corpus gate must
exist before any later config-schema PR can prove it did not regress the 44
configs); PR12, PR13 → PR14; PR11 → {PR18, PR19}; PR18 → PR16; PR09, PR10 →
PR16; PR14, PR15 → PR16; PR14, PR15, PR16, PR18, PR19 → PR17. PR01–PR05, PR07
are independent of each other. Note: §16 no longer depends on §11 directly —
it reaches the layout through the §18 seam (PR11 → PR18 → PR16).

## Definition of Done (this spec)

- All 19 PRs merged to `master`, each with all gate commands green and a
  blocking review against `docs/method/review-checklist.md` closed.
- The full suite plus the two contract tests (config corpus, golden state)
  pass on the final tree.
- Offline smokes pass: (a) `uv run python -m mantis_research run claude
  config/batch-12-or-research.json --dry-run` — a **config-load + legacy-layout
  regression** check only (this config sets no `models.primary` and its
  `claude.prompt` is `''`, so it does NOT exercise §9's selection path; the §9
  primary path is covered by §9's own stage tests, not this smoke); (b) the §16
  dry-run manifest smoke (batch layout); (c) a `layout='batch'` dry-run then
  `mantis status <cfg>` shows non-empty markers (§19).
- `CHANGELOG.md` carries one entry per behavior-changing PR, landed in the
  same PR (release-notes-in-wave).
- Every deliberate divergence from a protected contract is named in its
  section above; none exist outside them.
- Reflections written per PR under `docs/method/reflections/` and triaged at
  series close.

## Pre-mortem certification

*The externalized correctness pass (`docs/method/pre-mortem-prompt.md`), signed by a fresh
reviewer who did NOT author this spec. `keel check-ready` does not pass until the
verdict is `CERTIFIED` (ADR-0002 of keel). A freshly-scaffolded spec is, correctly, not Ready.*

- **Reviewer:** keel `pre-mortem-review` blind agent — non-author, three
  independent passes: round 1 DESIGN (NEEDS-REVISION, 10 findings), round 2
  confirm-fold (NEEDS-REVISION, 1 MAJOR + 5 advisory), round 3 convergence
  (CERTIFIED, zero findings). Each pass ran read-only against the committed
  tree with no access to the author's session.
- **Verdict:** CERTIFIED (round 3, rising-bar terminating pass — zero new
  BLOCKER/MAJOR, no notable MINOR)
- **Operator:** Grimaldo Stanzani
- **Date:** 2026-07-03
- **Reviewed against:** repo at commits d2c30c1 → b48c76d (ADRs + two fold
  rounds); no external-dependency SHAs reasoned against (offline; provider
  model ids are resolved at run time, not pinned in this spec).
- **Post-fold coherence:** performed after each round. Round-1 fold split the
  over-scoped §11/§16 into §18/§19 and grew the series 17→19 PRs; the manifest
  was re-derived to a 19↔19 bijection, the DAG re-checked acyclic, and all
  "17 PRs" counts updated. Round-2 fold tightened §10 to presence-based
  resolution and added the PR08→PR10 edge; re-read confirmed no cycle
  (PR06→PR08→PR10 chain) and no dependent count left stale. Round 3 verified
  every folded anchor resolves and the FM-1 mechanism is buildable at the
  `TopicConfig` validator level.
- **Failure modes considered & folded in:** two BLOCKERs (missing dispatch
  seam / layout-blind monitor), five MAJORs (sidecar retry-storm,
  brace-escaping, Optional-None translation, missed `int(topic_id)` sites,
  and the 163-topic empty-prompt resolution), and nine MINOR/advisory items —
  all folded; see ledger.

### Fold ledger

| Finding | Target section | artifact:line | Confirmed |
|---|---|---|---|
| R1 FM-1: monitor is layout-blind (no config/batch-name) | §19 | `src/mantis_research/interface/cli/monitor.py:20` | yes |
| R1 FM-2: no in-memory-config dispatch seam; legacy dirs hardwired | §18 | `src/mantis_research/interface/cli/dispatch.py:156` | yes |
| R1 FM-3: sidecar failure re-runs the 2-turn synthesis | §14 | `src/mantis_research/interface/stages/synthesis.py:186` | yes |
| R1 FM-4: `.get(k,DEFAULT)` → bare `attr` drops the default | §6 | `src/mantis_research/core/config.py:131` | yes |
| R1 FM-5: omitted `int(topic_id)` sites in gemini_research | §4 | `src/mantis_research/interface/stages/gemini_research.py:149` | yes |
| R1 FM-6: SIDECAR JSON block must brace-escape for `.format()` | §14 | `src/mantis_research/core/prompts.py:173` | yes |
| R1 FM-7: research command left unregistered | §16 | `src/mantis_research/interface/cli/__init__.py:37` | yes |
| R1 FM-9: `test_terminal_classification` contradicts cross-run rule | §3 | `tests/unit/test_state.py:47` | yes |
| R1 FM-10: status calls `legacy_state_dir` unconditionally | §19 | `src/mantis_research/interface/cli/status.py:77` | yes |
| R2 FM-1: 163/232 topics carry empty Claude prompt (presence-not-truthiness) | §10 | `src/mantis_research/core/config.py:30` | yes |
| R2 FM-3: gemini anchor quote mismatch | §6 | `src/mantis_research/interface/stages/gemini_research.py:90` | yes |
| R2 FM-5: dispatch guards must move into the seam | §18 | `src/mantis_research/interface/cli/dispatch.py:167` | yes |

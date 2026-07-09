# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project is
pre-1.0, so changes accumulate under **Unreleased** and are cut into tagged
releases (starting with 0.1.0).

## [Unreleased]

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

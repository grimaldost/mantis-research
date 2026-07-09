# mantis-research feedback — docs overhaul (deep review + reorganization)

- **Date:** 2026-07-09
- **Tool/version:** mantis-research 0.1.1 (read from `pyproject.toml`;
  `.claude-plugin/plugin.json` agrees)
- **Context:** full documentation review + reorganization: every doc read
  (README, CHANGELOG, CLAUDE.md, 9 ADRs, 2 specs, method kit, 8 playbooks,
  skill, plugin manifests, `.env.template`, example config) and cross-checked
  against code truth (`paths.py`, `settings.py`, `dispatch.py`, `config.py`,
  `stage.py`, `model_policy.py`, `synthesis.py`, orchestrator, CLI modules).
  Shipped a docs information architecture (`docs/README.md` map,
  `architecture.md`, `running-batches.md`, `batch-config.md`, ADR/spec/feedback
  indexes, root `CONTRIBUTING.md`), rewrote the pre-pivot playbooks README, and
  fixed truth drift in place. Maintaining the tool's own repo — counts as
  exercising it; the CLI was also run twice (`mantis run claude … --dry-run`)
  to verify documented syntax. Working-tree copy exercised throughout.
- **Outcome:** docs now have one home per fact and every quoted command was
  executed or grepped against code; six classes of shipped-doc falsehoods were
  found and fixed — all had survived the 0.1.0 pre-launch review and the 0.1.1
  discoverability round.

## What worked

- **The ADR discipline paid for itself.** Nine ADRs in one uniform format
  (Status/Date/Context/Decision/Alternatives/Consequences), one decision each,
  cross-linked to specs — indexing them took minutes, and the I1–I6 invariant
  keys made every downstream architecture claim citable instead of re-derived.
- **CHANGELOG-as-ground-truth.** The per-PR append discipline reconstructed the
  pivot's removals precisely; it is what exposed `prompts/playbooks/README.md`
  as pre-pivot (citing runners the 0.1.0 entry records as deleted).
- **`--dry-run` needing no API key made doc verification free.** Two CLI calls
  ($0, ~1 s each) empirically settled the `--only` syntax question — the 0.1.0
  fix "dry-run no longer needs a key" earned its keep in a way its authors
  probably didn't anticipate (doc QA).
- **Single-source code truth.** The pydantic schema (`config.py`),
  `STAGE_REGISTRY`, and `paths.py` were centralized enough that a faithful
  config reference (`docs/batch-config.md`) could be extracted without
  archaeology.

## Friction

- **[LOW]** The docs corpus had no map: 42 markdown files across five roots
  (`docs/`, `prompts/`, `skills/`, repo root, `.claude-plugin/`) with no index,
  so inventory required touching every file. Fixed this session
  (`docs/README.md`); listed so triage sees the cause — files accreted
  per-change with no home assignment.
- **[LOW]** README and CLAUDE.md taught different invocation forms
  (`mantis …` vs `uv run python -m mantis_research …`) without stating they are
  equivalent — a small verification detour. `docs/running-batches.md` now
  states the equivalence once.

## Misses

- **[MED] phase: docs-truth baseline (spec 0001 §1) / DoD.** Six doc claims
  contradicted the code and shipped through two releases:
  1. `prompts/playbooks/README.md` still described the pre-pivot pipeline —
     removed `run_batch*.py` / `evaluate_synthesis.py` runners, Claude+Gemini
     stage gating, a stale schema copy.
  2. `CLAUDE.md`'s stage table advertised `outputs/<stage>/` +
     `state/<stage>/` — paths matching *neither* the legacy nor the batch
     layout.
  3. The stage-disabled runtime error message and the `settings.py` /
     `dispatch.py` comments named the env var `MANTIS_DISABLED_STAGES`; the
     real name is `DISABLED_STAGES` — a user following the error text got a
     silently ignored setting.
  4. `CLAUDE.md` taught `--only 42 31`; the CLI rejects it ("Got unexpected
     extra argument") — the working syntax is `--only 42 --only 31`.
  5. mypy documented as a "CI-only secondary fallback" invoked via
     `uv run mypy src` — there is no CI in the repo and mypy is not in the dev
     group, so the documented command fails.
  6. `CLAUDE.md`'s invariants list stopped at I5 after ADR-0001 adopted six.
  Root pattern: docs asserted *executable* claims (commands, env vars, paths,
  registry names) that were never executed or grepped against their defining
  module.

## Vacuous gates

None observed — ruff / ty / pytest / core-purity all did real work on the code
side. The miss class (doc truth) simply has no gate yet; that is proposal #1.

## Proposed promotions / changes

1. **[MED]** extends `2026-07-04-agent-discoverability-0.1.1#1` — the
   documentation-completeness DoD item should be a **docs-truth sweep**, not
   only the blind-agent probe of the MCP surface: this round found six
   *operator/contributor*-doc falsehoods the probe class doesn't cover. Shape:
   every command a doc teaches is executed once at the `--dry-run`/`--help`
   tier, and every env var / directory / stage name a doc quotes is grepped
   against its defining module. Measured cost this session: 2 CLI calls plus a
   handful of greps for the whole corpus. Home:
   `docs/method/definition-of-done.md`.
2. **[MED]** When an error message names a config surface, a test pins that
   name: `test_disabled_stages.py` matched only the prefix
   `stage 'gemini' is disabled`, so the misnamed env var in the same message
   survived two releases. Add an assertion that `DISABLED_STAGES` (the
   actionable token) appears in the raised message. Home:
   `tests/unit/test_disabled_stages.py`.
3. **[LOW]** The version is declared in two manifests (`pyproject.toml`,
   `.claude-plugin/plugin.json`) with no sync gate — `test_plugin_manifest.py`
   asserts presence only. Add an equality assertion so a release can't bump
   one and ship the other stale. Home: `tests/unit/test_plugin_manifest.py`.
4. **[LOW]** extends `2026-07-04-agent-discoverability-0.1.1#2` — new evidence
   only: the user-side `feedback-targets` binding still cites
   `docs/method/reflection-triage.md` (removed in 0.1.0), and this session
   again fell back to the generic template. In-repo, `docs/feedback/README.md`
   (new this session) now records the dir's conventions, but the binding
   itself remains stale.

## Cost

No research runs this session; per the binding's cost-table requirement:

| Activity | Spend |
|---|---|
| OpenRouter research | $0 — none run |
| `mantis run claude … --dry-run` × 2 (CLI syntax verification) | $0, no API key, ~1 s each |
| Subagents / workflows | 0 spawned — single main-loop session |

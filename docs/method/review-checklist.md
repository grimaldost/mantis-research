# Review checklist (starter)

Injected into the reviewer and blocking: any unchecked item is `REQUEST_CHANGES`.
Start from these project-agnostic items and add project-specific ones.

This file is also the **promotion target for recurring traps**: when a trap
recurs across rounds, add a line here so it is caught mechanically next time.
That is how "a bug bites once" actually holds.

## Generic items

- [ ] **Scope** — single concern; cites exactly one spec section; no unrelated
      refactor ("while I'm here").
- [ ] **Correctness** — does what the cited section's acceptance criterion says.
- [ ] **Invariants** — respects every boundary/lock/immutability/contract named in
      the spec's "Invariants touched".
- [ ] **Typing** — fully typed; no new type-checker suppressions without reason.
- [ ] **Errors** — no silent `except`; failures surface; user-facing errors use the
      project's error format.
- [ ] **Tests** — behavior changes have tests; tests assert behavior, not
      implementation; no skip/xfail added to mask a real failure.
- [ ] **Docs** — public API/config/contract changes are documented.
- [ ] **No coupling smell** — no reaching through `getattr`/private attrs to dodge
      a boundary.
- [ ] **Gate completion** — every type/lint/test gate ran to completion (exit 0, no
      "fatal" / "source file found twice" halt), not merely error-count ≤ baseline; a
      checker that bailed early must fail the gate, not pass it.

## Project-specific items

- [ ] **I1 core purity** — nothing under `src/mantis_research/core/` imports
      httpx/subprocess/socket/requests/aiohttp; `uv run python scripts/check_core_purity.py`
      ran (once §7 lands).
- [ ] **I4 additive schemas** — no field of a persisted state model or of the batch-config
      schema renamed/retyped/removed; new fields are Optional with backward-compatible
      defaults; config-corpus + golden-state tests green (once §8/§12 land).
- [ ] **MCP tool-contract additivity** — the `research` MCP tool's argument schema and
      result shape (`interface/mcp/server.py`, `core/sidecar.py::project_for_agent`) evolve
      additively only: new optional arguments / result fields, never a rename or removal
      (agent callers depend on it; same discipline as I4, spec 0002 / ADR-0009).
- [ ] **I6 legacy readable** — no code path moves/renames existing on-disk batch artifacts;
      layouts never mix within one run.
- [ ] **Style** — single quotes code / double docstrings (ruff-enforced); `structlog`, never
      `print` in `src/`; `from __future__ import annotations` except in typer CLI modules
      (typer needs runtime annotations — see `interface/cli/run.py` note).
- [ ] **Seams** — new stages/adapters implement the Protocols from `core/stage.py`; no stage
      imports another stage; adapters own all I/O.
- [ ] **Release notes in-wave** — behavior-changing PR carries its `CHANGELOG.md` entry
      (once §1 lands).
- [ ] **Windows invocation** — no gate/script/doc introduced by the PR depends on a bare
      `.exe` shim (`pytest`, `mantis`); use `uv run python -m …` forms.

---
*Keep this file in version control with the project. Each promoted reflection
should cite the round/PR that motivated it, in a comment.*

# Method bindings — mantis-research

The method is project-agnostic; this file binds each slot and upgrade to a
concrete mechanism in THIS project. Filling it is how the method ports.

## Portability slots

| Slot (what it must provide) | This project |
|---|---|
| **ADR home** — a numbered decision log | `docs/adr/` |
| **Spec format** — numberable sections, acceptance criteria | `docs/specs/NNNN-<slug>.md` per `docs/method/spec-template.md` |
| **Guardrails + gate commands** — deterministic pass/fail | `uv run ruff format --check src tests` · `uv run ruff check src tests` · `uv run ty check src` · `uv run mypy src` · `uv run python -m pytest -q` · `uv run python scripts/check_core_purity.py` (once landed). Direct `.exe` shims (`pytest`, `keel`, `mantis`) are blocked by Windows Application Control on this machine — always invoke via `uv run python -m <module>` / `python -c`. |
| **Review checklist** — project-specific, blocking | `docs/method/review-checklist.md` |
| **Reflection sink** — feeds the next round | `docs/method/reflections/` (one md per PR), triaged via `docs/method/reflection-triage.md` (keel-triage) |

## Upgrade bindings

| Upgrade | What it must provide | This project |
|---|---|---|
| **DoR gate** | spec-readiness check before decompose | `docs/method/definition-of-ready.md` + `keel check-ready` — invoked as `uv run --project C:/Users/grima/Documents/keel python -c "from keel.cli import main; import sys; sys.argv=['keel','check-ready','<spec>']; main()"` |
| **Pre-mortem** | a stateless adversarial pass | keel's bundled `pre-mortem-review` agent (blind subagent, Read/Grep/Glob only); two-pass cadence (DESIGN ⊕ SERIES) for shared-contract waves |
| **Wave budget** | forecast + drift gate | `[budget]` block in `pr-series/series.toml` (pr-pilot schema) |
| **Edit-time invariant hook** | block edits that violate a boundary | **unbound** (no edit-time hook). Compensating control: gate-time `scripts/check_core_purity.py` (core/ may not import network/subprocess) — added by the pivot series. |

## Orchestrator

| | mantis-research |
|---|---|
| Series runner | pr-pilot (in-session executor: `pr-pilot:pr-pilot-executor`); series tables double as manual checklists |
| Single-unit discipline | humblepowers (test-driven-development, verification-before-completion, systematic-debugging) |
| Cross-series memory | `.remember/` (remember plugin) + Claude Code auto-memory + `session-workflow:journaling-sessions` |

*A slot left unbound is a method-not-fully-applied warning. The edit-time hook slot
is consciously unbound; every other row is bound before the pivot series runs.*

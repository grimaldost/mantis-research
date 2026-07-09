# Contributing

Orientation first: [docs/README.md](docs/README.md) maps all documentation;
[docs/architecture.md](docs/architecture.md) explains how the pipeline is
built; decisions live in [docs/adr/](docs/adr/README.md). This file covers the
mechanics of making a change land cleanly.

## Setup

```bash
git clone https://github.com/grimaldost/mantis-research
cd mantis-research
uv sync                                # installs the dev dependency group
uv run python -m pre_commit install    # wire the local hooks
```

Python ≥ 3.13; [uv](https://docs.astral.sh/uv/) provisions it. Run Python
through `uv run` so the pinned interpreter and dependencies apply.

## Gates

There is no hosted CI — pre-commit plus these commands **are** the gate; keep
them green locally before pushing:

```bash
uv run ruff format --check src tests        # formatting
uv run ruff check src tests                 # lint
uv run ty check src                         # types (primary checker)
uv run python -m pytest -q                  # tests
uv run python scripts/check_core_purity.py  # invariant I1 gate
uv run pip-audit                            # CVE scan
uv run python -m pre_commit run --all-files # everything the hooks run
```

mypy is a secondary cross-check with strict config in `pyproject.toml`; it is
not in the dev group — run it as `uvx mypy src` when you want the second
opinion. Integration tests marked `integration` need external CLIs / network;
deselect with `-m "not integration"` when working offline.

## Style

Enforced by ruff (line length 100):

- Single quotes for code, double for docstrings.
- `from __future__ import annotations` at module top.
- No `print` in `src/` (T20) — structured logs via `structlog`, and logs go
  to **stderr only**: stdout belongs to the `mantis research` manifest and the
  MCP JSON-RPC stream.
- Config via pydantic-settings (`core/settings.py`) — never `os.getenv`.
- `typing.Protocol` for interfaces, dataclasses for data, pydantic v2 for
  schemas, `asyncio.TaskGroup` over `gather`.
- MCP tool parameters carry a description at the schema level
  (`Annotated[T, Field(description=…)]`) — the agent's first-glance surface;
  `test_research_tool_schema_documents_every_parameter` pins it.

## Architecture rules

The six invariants (ADR-0001) shape most reviews. Short form: `core/` does no
network/subprocess I/O (machine-checked); stages and adapters are
Protocol-typed; persisted schemas evolve additively; every stage resumes; old
artifact trees stay readable. Details and enforcement:
[docs/architecture.md § Invariants](docs/architecture.md#invariants).

## Common changes

- **A new pipeline stage** — a module under `interface/stages/` implementing
  the `Stage` Protocol; a state class in `core/state.py`; one row in
  `STAGE_REGISTRY` (`interface/cli/dispatch.py`); a subcommand in
  `interface/cli/run.py`. Update the stage tables in
  [docs/running-batches.md](docs/running-batches.md) and `CLAUDE.md`, and add
  a playbook if the stage has a prompt.
- **A new provider adapter** — a module under `interface/adapters/`
  implementing `ProviderAdapter`, wired into the stage that uses it.
- **A config-schema change** — additive only (I4): new fields optional with
  compatible defaults, never a rename or retype. Update
  [docs/batch-config.md](docs/batch-config.md) and
  `config/example-batch.json`; `test_config_corpus.py` must keep passing.
- **A persisted-state change** — additive only; extend the golden files under
  `tests/data/golden_state/` and `test_state_golden.py`.
- **A default-prompt change** — `core/prompts.py` and the matching playbook in
  `prompts/playbooks/` change together, in the same commit.
- **An MCP-surface change** — the tool schema and result shape are a public
  contract (ADR-0009): additive only, every parameter described, and
  `skills/research/SKILL.md` + the README's served-tool section updated with
  it.

## Decisions, specs, changelog

- A decision a future change could relitigate gets an **ADR**
  ([docs/adr/README.md](docs/adr/README.md)).
- Work that decomposes into several dependent PRs gets a **spec** first
  ([docs/specs/README.md](docs/specs/README.md)), gated by the
  Definition-of-Ready checklist in [docs/method/](docs/method/README.md).
- Every user-visible change appends to `CHANGELOG.md` under **Unreleased**
  (Keep a Changelog format), in the same change that lands it.

## Releases

1. Move the Unreleased entries under a new version heading with today's date.
2. Bump `version` in `pyproject.toml` and mirror it in
   `.claude-plugin/plugin.json` (kept in sync by convention — the manifest
   test only checks presence).
3. Tag `vX.Y.Z` and push. The documented install paths (`uv tool install
   git+…`, the plugin marketplace) pick releases up from GitHub.

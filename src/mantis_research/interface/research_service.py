"""Shared request-level research orchestration (spec 0002 §1 / ADR-0009).

``run_research`` builds a single-topic batch config in memory and runs the
assurance tier's stage sequence through the ``dispatch_stage_config`` seam,
returning the result manifest as a plain dict. It is the one tested path both
the ``mantis research`` CLI (``interface/cli/research.py``) and the MCP
``research`` tool (``interface/mcp/``) call — the CLI adds typer option parsing
and exit-code mapping, the MCP tool adds the structured-result projection.

Synchronous by design: ``dispatch_stage_config`` owns an ``asyncio.run`` per
stage, so callers must invoke ``run_research`` off any running event loop (the
MCP tool offloads it via ``asyncio.to_thread``). Raises ``ValueError`` — never
``typer.Exit`` — on an invalid argument, so non-CLI callers get an ordinary
exception (spec 0002 §1 / FM-4).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mantis_research.core.config import load_batch_config
from mantis_research.core.logging import configure_logging
from mantis_research.core.paths import RunDirs, topic_stem
from mantis_research.core.progress import RunEvent, emit
from mantis_research.core.prompts import RESEARCH_REQUEST
from mantis_research.core.state import OpenRouterResearchState

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.progress import ProgressCallback

#: The run-level record, written before dispatch and rewritten at the end. Its
#: presence is what turns an abandoned call into an identified run.
RUN_RECORD_NAME = 'run.json'

# Default Path B substrate set (model-recommendations.md): each vendor resolves
# to its newest frontier model via the `auto:<vendor>` sentinel at run time.
# `perplexity` is intentionally NOT a default: its `auto:` pick
# (`sonar-pro-search`) 404s on the completions endpoint, and because a topic
# fails if any one substrate fails, a dead default would nuke the whole (paid)
# run. Add it explicitly (`--substrates …,perplexity`) with a working Sonar
# model for real-time-search coverage.
_DEFAULT_SUBSTRATES = ('openai', 'deepseek', 'google')
# Providers with a native web-search plugin; everyone else routes through Exa.
_NATIVE_SEARCH = frozenset({'openai', 'perplexity', 'anthropic', 'x-ai'})

# assurance tier → the stage sequence to run, in dependency order.
_TIER_STAGES: dict[str, list[str]] = {
    'fast': ['openrouter', 'synthesis'],
    'standard': ['openrouter', 'synthesis', 'falsification'],
    'high': ['openrouter', 'synthesis', 'falsification', 'claude-prior', 'evaluation'],
}


def _slugify(text: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return (s[:48] or 'question').rstrip('-')


def _substrate_entry(vendor: str) -> dict[str, Any]:
    return {
        'subslug': vendor,
        'model': f'auto:{vendor}',
        'web_search': True,
        'web_search_engine': 'native' if vendor in _NATIVE_SEARCH else 'exa',
    }


def build_config(
    question: str,
    *,
    substrates: list[str],
    primary: str,
    journal: bool,
    batch_name: str,
    assurance: str,
) -> dict[str, Any]:
    """Build the in-memory single-topic batch config for one research request."""
    slug = _slugify(question)
    return {
        'schema_version': 2,
        'batch_name': batch_name,
        'runner': {'layout': 'batch'},
        'models': {'claude': {}, 'primary': primary},
        'topics': [
            {
                'id': '1',
                'slug': slug,
                'title': question,
                'research_prompt': RESEARCH_REQUEST.format(question=question),
                'stages': {
                    # Path B: Claude does no research (never dispatched); an
                    # explicit empty prompt keeps the config valid.
                    'claude': {'prompt': ''},
                    'openrouter': [_substrate_entry(v) for v in substrates],
                    'journal': {'enabled': journal},
                    'falsification': {'enabled': assurance in ('standard', 'high')},
                    'evaluation': {'enabled': assurance == 'high'},
                },
            }
        ],
    }


def _manifest(
    *,
    question: str,
    batch_name: str,
    assurance: str,
    slug: str,
    substrates: list[str],
    results: dict[str, int],
) -> dict[str, Any]:
    dirs = RunDirs('batch', batch_name)
    stem = topic_stem('1', slug)
    or_dir = dirs.output('openrouter') / stem
    outputs: dict[str, Any] = {
        'briefs': [str(or_dir / f'{v}.md') for v in substrates],
        'synthesis': str(dirs.output('synthesis') / f'{stem}.md'),
        'sidecar': str(dirs.output('synthesis') / f'{stem}.sidecar.json'),
    }
    if 'falsification' in results:
        outputs['falsification'] = str(dirs.output('falsification') / f'{stem}.md')
    if 'evaluation' in results:
        outputs['evaluation'] = str(dirs.output('evaluation') / f'{stem}-eval.json')

    return {
        'question': question,
        'question_slug': slug,
        'batch_name': batch_name,
        'assurance': assurance,
        'layout': 'batch',
        'outputs_dir': str(dirs.root()),
        'stages': {stage: {'exit_code': rc} for stage, rc in results.items()},
        'outputs': outputs,
        'cost': _read_cost(dirs, stem),
        'ok': all(rc == 0 for rc in results.values()),
    }


def _write_run_record(dirs: RunDirs, record: dict[str, Any]) -> Path:
    """Write the run-level record atomically, creating the run root if needed."""
    root = dirs.root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / RUN_RECORD_NAME
    tmp = path.with_name(f'{RUN_RECORD_NAME}.tmp')
    tmp.write_text(json.dumps(record, indent=2), encoding='utf-8')
    tmp.replace(path)
    return path


def _read_cost(dirs: RunDirs, stem: str) -> dict[str, Any]:
    """Best-effort per-run cost/token totals from the OpenRouter state (§12)."""
    state_path = dirs.state('openrouter') / '1.json'
    totals = {'cost_usd': 0.0, 'tokens_prompt': 0, 'tokens_completion': 0}
    if not state_path.exists():
        return {**totals, 'available': False}
    try:
        state = OpenRouterResearchState.model_validate_json(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {**totals, 'available': False}
    for sub in state.subsessions:
        totals['cost_usd'] += sub.cost_usd or 0.0
        totals['tokens_prompt'] += sub.tokens_prompt or 0
        totals['tokens_completion'] += sub.tokens_completion or 0
    return {**totals, 'available': True}


def run_research(
    question: str,
    *,
    assurance: str = 'standard',
    substrates: list[str] | None = None,
    primary: str = '',
    journal: bool = False,
    batch_name: str = '',
    dry_run: bool = False,
    log_level: str = 'INFO',
    on_event: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run one research question end-to-end; return the result manifest dict.

    Builds the in-memory config, runs the assurance tier's stages sequentially
    through the dispatch seam, and returns the manifest (output paths, per-stage
    exit codes, cost totals, ``ok``). ``substrates=None`` uses the default Path B
    set. Raises ``ValueError`` on an invalid argument (the CLI maps it to an exit
    code; the MCP tool surfaces it as an error) and never ``typer.Exit``.
    Synchronous — call it off any running event loop.

    ``on_event`` receives a :class:`RunEvent` at every boundary worth hearing
    about. The first is always ``run_named``, emitted after the config is built
    and *before* any stage is dispatched, alongside a run record on disk — so a
    call the caller abandons still leaves a run it can name, rather than an
    orphan directory it cannot match to a question.
    """
    # Lazy import: importing cli.dispatch runs cli/__init__, which imports
    # research_cmd -> cli.research -> back to this module. Deferring dispatch to
    # call time breaks that cycle (it is only needed once we run a stage).
    from mantis_research.interface.cli.dispatch import dispatch_stage_config

    if assurance not in _TIER_STAGES:
        msg = f'invalid assurance {assurance!r}; choose fast|standard|high'
        raise ValueError(msg)
    source = substrates if substrates is not None else list(_DEFAULT_SUBSTRATES)
    subs = [s.strip() for s in source if s.strip()]
    if not subs:
        msg = 'no substrates given'
        raise ValueError(msg)
    primary_ref = primary or f'openrouter:{subs[0]}'
    ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    name = batch_name or f'research-{_slugify(question)}-{ts}'

    cfg_dict = build_config(
        question,
        substrates=subs,
        primary=primary_ref,
        journal=journal,
        batch_name=name,
        assurance=assurance,
    )
    cfg = load_batch_config(cfg_dict)
    slug = cfg.topics[0].slug
    configure_logging(level=log_level)

    # ── name the run, before anything is dispatched ────────────────
    dirs = RunDirs('batch', name)
    identity = {
        'question': question,
        'question_slug': slug,
        'batch_name': name,
        'assurance': assurance,
        'substrates': subs,
        'layout': 'batch',
        'outputs_dir': str(dirs.root()),
    }
    _write_run_record(dirs, {**identity, 'status': 'dispatching', 'started_at': _now_iso()})
    stages = _TIER_STAGES[assurance]
    emit(
        on_event,
        RunEvent(
            kind='run_named',
            message=f'run {name} dispatching {len(stages)} stage(s) into {dirs.root()}',
            step=0,
            total=len(stages),
            data=identity,
        ),
    )

    results: dict[str, int] = {}
    for index, stage in enumerate(stages, start=1):
        emit(
            on_event,
            RunEvent(
                kind='stage_start',
                message=f'{stage} starting',
                step=index - 1,
                total=len(stages),
                data={'stage': stage, 'batch_name': name},
            ),
        )
        rc = dispatch_stage_config(stage, cfg, dry_run=dry_run, log_level=log_level)
        results[stage] = rc
        emit(
            on_event,
            RunEvent(
                kind='stage_done',
                message=f'{stage} finished (exit {rc})',
                step=index,
                total=len(stages),
                data={'stage': stage, 'exit_code': rc, 'batch_name': name},
            ),
        )
        # Research and synthesis are load-bearing — stop the pipeline if either
        # fails (later stages depend on their outputs).
        if rc != 0 and stage in ('openrouter', 'synthesis'):
            break

    manifest = _manifest(
        question=question,
        batch_name=name,
        assurance=assurance,
        slug=slug,
        substrates=subs,
        results=results,
    )
    _write_run_record(dirs, {**manifest, 'status': 'complete', 'finished_at': _now_iso()})
    emit(
        on_event,
        RunEvent(
            kind='run_done',
            message=f'run {name} complete (ok={manifest["ok"]})',
            step=len(stages),
            total=len(stages),
            data={'batch_name': name, 'ok': manifest['ok'], 'outputs_dir': str(dirs.root())},
        ),
    )
    return manifest


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()

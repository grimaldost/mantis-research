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

import re
from datetime import UTC, datetime
from typing import Any

from mantis_research.core.config import load_batch_config
from mantis_research.core.logging import configure_logging
from mantis_research.core.paths import RunDirs, topic_stem
from mantis_research.core.prompts import RESEARCH_REQUEST
from mantis_research.core.state import OpenRouterResearchState

# Default Path B substrate set (model-recommendations.md): each vendor resolves
# to its newest frontier model via the `auto:<vendor>` sentinel at run time.
_DEFAULT_SUBSTRATES = ('openai', 'deepseek', 'google', 'perplexity')
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
        'batch_name': batch_name,
        'assurance': assurance,
        'layout': 'batch',
        'stages': {stage: {'exit_code': rc} for stage, rc in results.items()},
        'outputs': outputs,
        'cost': _read_cost(dirs, stem),
        'ok': all(rc == 0 for rc in results.values()),
    }


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
) -> dict[str, Any]:
    """Run one research question end-to-end; return the result manifest dict.

    Builds the in-memory config, runs the assurance tier's stages sequentially
    through the dispatch seam, and returns the manifest (output paths, per-stage
    exit codes, cost totals, ``ok``). ``substrates=None`` uses the default Path B
    set. Raises ``ValueError`` on an invalid argument (the CLI maps it to an exit
    code; the MCP tool surfaces it as an error) and never ``typer.Exit``.
    Synchronous — call it off any running event loop.
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

    results: dict[str, int] = {}
    for stage in _TIER_STAGES[assurance]:
        rc = dispatch_stage_config(stage, cfg, dry_run=dry_run, log_level=log_level)
        results[stage] = rc
        # Research and synthesis are load-bearing — stop the pipeline if either
        # fails (later stages depend on their outputs).
        if rc != 0 and stage in ('openrouter', 'synthesis'):
            break

    return _manifest(
        question=question,
        batch_name=name,
        assurance=assurance,
        slug=slug,
        substrates=subs,
        results=results,
    )

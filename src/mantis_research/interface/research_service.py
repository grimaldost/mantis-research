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
import os
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mantis_research.core import paths
from mantis_research.core.config import load_batch_config
from mantis_research.core.logging import configure_logging
from mantis_research.core.paths import RunDirs, topic_stem
from mantis_research.core.progress import RunEvent, emit
from mantis_research.core.prompts import RESEARCH_REQUEST
from mantis_research.core.state import OpenRouterResearchState
from mantis_research.interface.seat import process_is_alive

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mantis_research.core.progress import ProgressCallback
    from mantis_research.core.stage import SeatProbe

#: The run-level record, written before dispatch and rewritten at the end. Its
#: presence is what turns an abandoned call into an identified run.
RUN_RECORD_NAME = 'run.json'

#: Stages driven by the machine's single authenticated ``claude`` CLI, and so by
#: the local seat this deployment is built around (ADR-0009, local-first). Any
#: tier containing one of these needs that seat before it is worth spending a
#: cent on research.
LOCAL_SEAT_STAGES = frozenset(
    {'claude', 'synthesis', 'journal-passes', 'falsification', 'evaluation', 'claude-prior'}
)


class LocalSeatUnavailableError(RuntimeError):
    """The run needs the local ``claude`` seat and that seat is not usable.

    Raised at dispatch, before any stage runs, so a caller is told the
    precondition rather than handed a briefs-only result to interpret.
    """


def require_local_claude_seat(
    *,
    stages: Sequence[str],
    probe: SeatProbe | None = None,
) -> None:
    """Refuse the run up front if its tier needs a local seat it cannot have.

    The synthesis family drives the local ``claude`` CLI, so a tier containing
    any of :data:`LOCAL_SEAT_STAGES` cannot deliver its product without one.
    Nothing asked that question until the synthesis stage reached its own
    ``preflight`` — which is *after* the OpenRouter research stage has run and
    been paid for. Three runs on 2026-08-11 bought their briefs and only then
    found the seat's OAuth token had expired; the briefs are still on disk and
    the syntheses were never written.

    Raising here is deliberate over the alternative of making the child spawn
    work by other means: the failure this guards is a precondition of the
    deployment, and a run that cannot produce a sidecar must stop before it
    spends rather than return what it managed to buy.
    """
    needed = [s for s in stages if s in LOCAL_SEAT_STAGES]
    if not needed:
        return
    if probe is None:
        # Imported at call time: the adapter pulls in the subprocess and
        # transcript machinery, and a research-only tier never needs it.
        from mantis_research.interface.adapters.claude_cli import ClaudeCliAdapter

        probe = ClaudeCliAdapter()
    try:
        probe.preflight()
    except RuntimeError as exc:
        msg = (
            f'this run needs the local claude CLI seat for {", ".join(needed)}, '
            f'and that seat is not usable: {exc}. '
            f"The synthesis family drives the machine's authenticated `claude` "
            f'CLI (ADR-0009), so the run is refused before it spends anything on '
            f'research it could not synthesise. Fix the seat (`claude auth login`, '
            f'no --console) and re-run, or pass dry_run to exercise the '
            f'orchestration offline.'
        )
        raise LocalSeatUnavailableError(msg) from exc


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
    dry_run: bool,
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
        # Every path under ``outputs`` is *where an artifact goes*, not proof one
        # is there — under a dry run none of them exist. Saying so on the
        # manifest and in the run record is what stops a dry run's result being
        # read, by an agent or by a person, as a finished one.
        'dry_run': dry_run,
        'stages': {stage: {'exit_code': rc} for stage, rc in results.items()},
        'outputs': outputs,
        'cost': _read_cost(dirs, stem),
        'ok': all(rc == 0 for rc in results.values()),
    }


def read_run_record(run_dir: Path) -> dict[str, Any]:
    """Read a run's record, or raise ``ValueError`` naming what is wrong."""
    path = run_dir / RUN_RECORD_NAME
    if not path.exists():
        msg = f'no run record at {path} — that directory is not a mantis run'
        raise ValueError(msg)
    try:
        record: dict[str, Any] = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        msg = f'run record at {path} is unreadable: {exc}'
        raise ValueError(msg) from exc
    return record


def _write_run_record(dirs: RunDirs, record: dict[str, Any]) -> Path:
    """Write the run-level record atomically, carrying its history forward.

    ``history`` accumulates terminal facts about the run — notably that a
    previous owner abandoned it. Each write preserves what is already there, so
    a resume appends to the run's story rather than overwriting the evidence of
    why it needed resuming.
    """
    root = dirs.root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / RUN_RECORD_NAME
    prior: list[Any] = []
    if path.exists():
        try:
            prior = json.loads(path.read_text(encoding='utf-8')).get('history') or []
        except (OSError, ValueError):
            prior = []
    merged = {**record, 'history': [*prior, *record.get('history', [])]}
    tmp = path.with_name(f'{RUN_RECORD_NAME}.tmp')
    tmp.write_text(json.dumps(merged, indent=2), encoding='utf-8')
    tmp.replace(path)
    return path


def resolve_resume_dir(candidate: Path) -> Path:
    """Resolve and validate a run directory offered for ``--resume``.

    The directory must be **strictly contained** by the outputs root: strict, so
    the root itself is rejected, because resuming "the outputs tree" is not a
    run and would let one resume reach across every run on the machine. This is
    the same containment rule the sibling series engine resumes under, taken
    rather than re-derived as a path-equality check that a ``..`` would walk
    straight through.
    """
    # Resolved through the module, not a bound name: the outputs root is
    # redirectable (tests, an installed CLI's CWD fallback), and a name bound at
    # import time would silently validate against the wrong tree.
    root = paths.outputs_root().resolve()
    resolved = candidate.expanduser().resolve()
    if resolved == root or root not in resolved.parents:
        msg = f'{candidate} is not inside the outputs root ({root}) — refusing to resume it'
        raise ValueError(msg)
    if not resolved.is_dir():
        msg = f'no run directory at {resolved}'
        raise ValueError(msg)
    return resolved


def resume_research(
    run_dir: Path,
    *,
    dry_run: bool = False,
    log_level: str = 'INFO',
    on_event: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Re-enter an existing run, skipping the stages and topics already done.

    Invariant I5 already promised per-stage resumability and the state files
    already deliver it — both runs that died at the client timeout had written
    their per-model briefs. What was missing was a way in, so recovery meant
    harvesting those briefs by hand. This is that entry point: a consumer of
    state that already exists, not new bookkeeping.
    """
    resolved = resolve_resume_dir(run_dir)
    record = read_run_record(resolved)
    try:
        question = str(record['question'])
        batch_name = str(record['batch_name'])
    except KeyError as exc:
        msg = f'run record at {resolved} is missing {exc.args[0]!r}'
        raise ValueError(msg) from exc

    history: list[dict[str, Any]] = []
    if record.get('status') == 'dispatching':
        owner = record.get('owner_pid')
        alive = isinstance(owner, int) and process_is_alive(owner)
        if alive:
            msg = (
                f'run {batch_name} is still owned by a live process (pid {owner}) — '
                f'resuming it would run two owners over one state tree'
            )
            raise ValueError(msg)
        # Terminal record for the abandoned attempt, appended rather than
        # overwriting the state it was left in (MANT-B08's vocabulary).
        history.append(
            {
                'status': 'dead',
                'at': _now_iso(),
                'note': f'owner pid {owner} was gone at resume',
            }
        )

    return run_research(
        question,
        assurance=str(record.get('assurance') or 'fast'),
        substrates=list(record.get('substrates') or []) or None,
        batch_name=batch_name,
        dry_run=dry_run,
        log_level=log_level,
        on_event=on_event,
        _resume_history=history,
    )


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
    _resume_history: list[dict[str, Any]] | None = None,
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
    stages = _TIER_STAGES[assurance]
    # Before anything is minted or dispatched: a tier that cannot deliver its
    # product must say so rather than buy the research half of it. A dry run
    # spends nothing and spawns nothing, so it is exempt for the same reason
    # ``--dry-run`` already skips every stage preflight.
    if not dry_run:
        require_local_claude_seat(stages=stages)
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
        'dry_run': dry_run,
    }
    _write_run_record(
        dirs,
        {
            **identity,
            'status': 'dispatching',
            'started_at': _now_iso(),
            # Written in so a later run can read it back and tell an owner that
            # is still working from one that is gone (MANT-B08).
            'owner_pid': os.getpid(),
            'history': _resume_history or [],
        },
    )
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
        rc = dispatch_stage_config(
            stage, cfg, dry_run=dry_run, log_level=log_level, on_event=on_event
        )
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
        dry_run=dry_run,
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

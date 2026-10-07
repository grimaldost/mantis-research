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
import secrets
import statistics
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from mantis_research.core import paths
from mantis_research.core.config import load_batch_config
from mantis_research.core.logging import configure_logging
from mantis_research.core.paths import RunDirs, topic_stem
from mantis_research.core.progress import RunEvent, emit, seat_start_range
from mantis_research.core.prompts import RESEARCH_REQUEST
from mantis_research.core.sidecar import SidecarOutcome
from mantis_research.core.state import OpenRouterResearchState, SynthesisState
from mantis_research.interface.seat import process_is_alive, seat_queue

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mantis_research.core.progress import ProgressCallback
    from mantis_research.core.stage import SeatProbe
    from mantis_research.interface.seat import SeatQueue

log = structlog.get_logger(__name__)

#: Longest ``error`` string a failed record carries.
_ERROR_CHARS = 500

#: The run-level record, written before dispatch, rewritten at each stage
#: transition and again at the end. Its presence is what turns an abandoned call
#: into an identified run.
RUN_RECORD_NAME = 'run.json'

#: Serialises every write of a run record in this process, so the stage loop's
#: writes and the progress writes never interleave their read-merge-replace.
_RECORD_LOCK = threading.Lock()

#: Stages driven by the machine's single authenticated ``claude`` CLI, and so by
#: the local seat this deployment is built around (ADR-0009, local-first). Any
#: tier containing one of these needs that seat before it is worth spending a
#: cent on research.
LOCAL_SEAT_STAGES = frozenset(
    {'claude', 'synthesis', 'journal-passes', 'falsification', 'evaluation', 'claude-prior'}
)


#: Observed wall-clock of the research stage, in minutes (low, high): the
#: substrates run concurrently, so it tracks the slowest. ``skills/research``
#: states these figures and a doc-consistency test holds the prose to them.
RESEARCH_STAGE_MINUTES = (5, 10)

#: Median length of one local-seat Claude turn, in minutes (observed range 131 s
#: to 2601 s). Cited by the skill's latency bullet and by the detach docs.
LOCAL_SEAT_TURN_MEDIAN_MINUTES = 7


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
    # Research only: the briefs and their cost, no local-seat stage at all.
    # `assurance` was naming two different things — how much checking the answer
    # gets, and which stages run — so "just the research" could not be asked
    # for, and every tier ended in a synthesis that cannot complete inside an
    # MCP client's idle window. This is the tier that runs where the others
    # cannot (MANT-B60).
    'research': ['openrouter'],
    'fast': ['openrouter', 'synthesis'],
    'standard': ['openrouter', 'synthesis', 'falsification'],
    'high': ['openrouter', 'synthesis', 'falsification', 'claude-prior', 'evaluation'],
}


#: A caller that prefixes its question with shared context can name the topic
#: explicitly. Four questions carrying the same CONTEXT paragraph slugged
#: identically off their first 48 characters, which is how they collided.
_QUESTION_KEY = re.compile(r'RESEARCH QUESTION \(([^)]{1,60})\)', re.IGNORECASE)


def _slugify(text: str) -> str:
    """Name a topic from its question, preferring an explicit key."""
    marked = _QUESTION_KEY.search(text)
    source = marked.group(1) if marked else text
    s = re.sub(r'[^a-z0-9]+', '-', source.lower()).strip('-')
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
        # Whether this run owed an epistemic sidecar at all. A research-only
        # tier does not, and the serving path's refusal needs to know.
        'produces_sidecar': produces_sidecar(list(results)),
        'stages': {stage: {'exit_code': rc} for stage, rc in results.items()},
        'outputs': outputs,
        'cost': _read_cost(dirs, stem),
        # Two outcomes, not one (ADR-0011). `ok` is the stages: did the run
        # produce the documents it was asked for. The sidecar reports itself —
        # a derived artifact's failure never retracts one that was produced,
        # and folding them together is what turned three complete, paid-for
        # syntheses into failed runs.
        'sidecar': _read_sidecar_outcome(dirs, list(results), dry_run=dry_run),
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


#: What `mantis research` exits when every stage passed and the run still has no
#: epistemic sidecar. Distinct from 1 on purpose: since ADR-0011 `ok` is true
#: about the *stages* in exactly that case, so folding it into the stage-failure
#: code would discard the distinction that ADR exists to draw — and moving a
#: failed stage off 1 would break a contract this change has no business
#: touching. 2 is already the invalid-argument code.
MISSING_PRODUCT_EXIT_CODE = 3


def missing_product(manifest: Mapping[str, Any]) -> str | None:
    """Why this run owes an epistemic sidecar it does not have, or None.

    The one place that judgement is made. The sidecar is the product (ADR-0003),
    so "did this run deliver an answer" is a question about the artifact, not
    about ``ok`` — which since ADR-0011 reports the stages. Both serving surfaces
    read this: the MCP tool builds its refusal from the returned reason, and
    ``mantis research`` derives its exit code from it.

    One function rather than a test at each surface, because the copy is what
    drifts: for one release candidate the MCP path refused a run whose sidecar
    had failed while the CLI exited 0 over the identical manifest, because only
    one of the two had been reconciled with ``ok``'s new meaning.

    A run that never owed a sidecar is not missing one — a research-only tier
    (MANT-B60) or a dry run legitimately has none, and refusing those would
    refuse the one tier that runs without a local seat.
    """
    if manifest.get('dry_run', False):
        return None
    # Absent, the flag reads as owed: every tier before it was.
    if not manifest.get('produces_sidecar', True):
        return None
    if Path(str(manifest['outputs']['sidecar'])).exists():
        return None
    stages: Mapping[str, Mapping[str, Any]] = manifest.get('stages') or {}
    failed = sorted(stage for stage, rc in stages.items() if rc.get('exit_code', 0) != 0)
    if failed:
        return f'{", ".join(failed)} exited non-zero'
    reason = (manifest.get('sidecar') or {}).get('error')
    if reason:
        # Since ADR-0011 a stage can exit 0 with its sidecar recorded as failed,
        # and that reason is more use than the exit codes it no longer shows up
        # in.
        return f'every stage exited 0 and the sidecar turn failed: {reason}'
    return 'every stage exited 0, so the artifact was lost rather than refused'


def produces_sidecar(stages: Sequence[str]) -> bool:
    """True when this stage sequence is expected to leave an epistemic sidecar.

    The sidecar is the product (ADR-0003), so a run that owes one and has none
    is a failure. A research-only run owes none — it is briefs and their cost by
    definition — and the refusal has to be able to tell the two apart, or it
    refuses the one tier that works from inside a Claude Code session.
    """
    return 'synthesis' in stages


def _mint_run_name(question: str) -> str:
    """A run name that is unique by construction, not by luck (MANT-B62).

    The old name was the question's first 48 characters plus a timestamp to the
    second — two facts that are not unique, at a granularity that is not
    unique. Four concurrent questions sharing a preamble collided on it. The
    random suffix is what makes a collision impossible rather than unlikely;
    the timestamp stays because a human reads these names in a directory
    listing and wants them ordered.
    """
    ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    return f'research-{_slugify(question)}-{ts}-{secrets.token_hex(2)}'


def _journal_request(
    question: str,
    assurance: str,
    *,
    outcome: str,
    detail: str = '',
) -> None:
    """Append one line about a request, before any run directory exists.

    A request that died before its directory was created left nothing at all —
    on 2026-08-23 a caller waited its full window for a run that has no trace
    anywhere on disk, and whether it was dropped, queued or never arrived is
    still undiagnosable. Best-effort by construction: a journal that can fail a
    run is worse than no journal.
    """
    try:
        root = paths.logs_root()
        root.mkdir(parents=True, exist_ok=True)
        entry = {
            'received_at': _now_iso(),
            'question_slug': _slugify(question),
            'assurance': assurance,
            'outcome': outcome,
            'detail': detail,
            'pid': os.getpid(),
        }
        with (root / 'requests.jsonl').open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry) + '\n')
    except OSError:
        return


class RunNameCollisionError(RuntimeError):
    """An explicit batch name already belongs to a different question.

    Two runs sharing one state tree is not a lost run, it is a misattributed
    one: whichever finishes last leaves briefs that read as the answer to the
    other's question. Refusing is the only outcome that cannot be misread.
    """


def _claim_run_root(dirs: RunDirs, question: str) -> None:
    """Take the run directory, or refuse it (MANT-B62).

    ``exist_ok=False`` makes the filesystem the arbiter for a *new* run, which
    is what the minted name — carrying a random suffix — expects to always
    succeed. An explicit ``--batch-name`` is the one case where a caller can
    legitimately land on an existing directory, and there the question decides:
    the same question is a re-run (invariant I5 calls that resume), a different
    one is a collision.
    """
    root = dirs.root()
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        prior = root / RUN_RECORD_NAME
        if prior.exists():
            try:
                asked = json.loads(prior.read_text(encoding='utf-8')).get('question')
            except (OSError, ValueError):
                asked = None
            if asked is not None and asked != question:
                msg = (
                    f'the run name {dirs.batch_name!r} already belongs to a different '
                    f'question. Two runs sharing one state tree produce briefs that '
                    f'read as the answer to the wrong question — choose another name, '
                    f'or pass resume={str(root)!r} to continue the existing run.'
                )
                raise RunNameCollisionError(msg) from None


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
    with _RECORD_LOCK:
        prior: list[Any] = []
        if path.exists():
            try:
                prior = json.loads(path.read_text(encoding='utf-8')).get('history') or []
            except (OSError, ValueError):
                prior = []
        merged = {**record, 'history': [*prior, *record.get('history', [])]}
        # A name per writer, not a fixed one: a second writer (a resume racing a
        # dying worker) would otherwise truncate the file the first is replacing.
        tmp = path.with_name(f'{RUN_RECORD_NAME}.{os.getpid()}.{secrets.token_hex(4)}.tmp')
        tmp.write_text(json.dumps(merged, indent=2), encoding='utf-8')
        try:
            _replace_with_retry(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    return path


class _StageRecorder:
    """Keep ``run.json`` in step with a run while it is in flight (T1e).

    The record used to be written before the first stage and after the last,
    so a poller saw ``stages={}`` for the whole life of a healthy run: on
    2026-09-27, 10 of 11 collectors gave up on runs whose briefs, syntheses
    and sidecars were already on disk. This wraps the caller's ``on_event`` and
    rewrites the record on each event that changes what a poller should see —
    a stage starting or finishing, a substrate brief landing, a wait starting
    or ending — before passing the event on.

    Each ``stages`` entry carries ``state`` (``running``, ``waiting`` or
    ``done``), ``started_at`` and ``exit_code`` (``None`` until the stage is
    done), plus ``finished_at`` once it is; the research stage also lists
    ``substrates_done``, and a stage that took the local seat records the first
    time it did as ``seat_acquired_at`` (T1f). The seat reports its wait every
    few seconds, so only the move into ``waiting`` is written, and the next sign
    of work (the seat taken, a child's output, a substrate starting) moves it
    back to ``running``.

    These writes are best-effort: on Windows ``replace`` fails while a poller
    holds the record open, and the next transition writes the whole state
    again. :meth:`close` stops them before the terminal write, so a late event
    cannot turn a finished record back into a running one.
    """

    def __init__(
        self,
        dirs: RunDirs,
        base: Mapping[str, Any],
        forward: ProgressCallback | None,
    ) -> None:
        self._dirs = dirs
        # `base` carries no `history`: `_write_run_record` carries the record's
        # history forward on every write, so passing it again would duplicate it.
        self._base = dict(base)
        self._forward = forward
        self._stages: dict[str, dict[str, Any]] = {}
        self._current: str | None = None
        self._closed = False
        self._lock = threading.Lock()

    def __call__(self, event: RunEvent) -> None:
        try:
            with self._lock:
                if not self._closed and self._apply(event):
                    self._write()
        finally:
            emit(self._forward, event)

    def close(self) -> None:
        """Stop writing; any write already under way finishes first."""
        with self._lock:
            self._closed = True

    def finished_stages(self, results: Mapping[str, int]) -> dict[str, dict[str, Any]]:
        """The terminal record's ``stages``: each exit code, with when the stage ran.

        The timings outlive the run so a later queued run can estimate how long
        a seat turn takes (:func:`seat_turn_durations`).
        """
        with self._lock:
            return {
                stage: {
                    'exit_code': rc,
                    **{
                        key: self._stages[stage][key]
                        for key in _STAGE_TIMINGS
                        if key in self._stages.get(stage, {})
                    },
                }
                for stage, rc in results.items()
            }

    def _apply(self, event: RunEvent) -> bool:
        """Fold one event into the stage map; True when the record should change."""
        if event.kind == 'stage_start':
            stage = str(event.data.get('stage'))
            self._stages[stage] = {'state': 'running', 'started_at': _now_iso(), 'exit_code': None}
            self._current = stage
            return True
        if event.kind == 'stage_done':
            entry = self._stages.get(str(event.data.get('stage')))
            if entry is None:
                return False
            entry.update(
                state='done', exit_code=event.data.get('exit_code'), finished_at=_now_iso()
            )
            return True
        entry = self._stages.get(self._current) if self._current is not None else None
        if entry is None or entry['state'] == 'done':
            return False
        if event.kind == 'waiting':
            if entry['state'] == 'waiting':
                return False
            entry['state'] = 'waiting'
            return True
        if event.kind == 'seat_acquired':
            # The first acquisition is the one kept: a journal turn takes the
            # seat again inside the same stage.
            changed = entry['state'] == 'waiting' or 'seat_acquired_at' not in entry
            entry.setdefault('seat_acquired_at', _now_iso())
            entry['state'] = 'running'
            return changed
        if event.kind not in ('substrate_start', 'substrate_done', 'thinking'):
            return False
        changed = entry['state'] == 'waiting'
        entry['state'] = 'running'
        if event.kind == 'substrate_done' and event.data.get('status', 'done') == 'done':
            done: list[Any] = entry.setdefault('substrates_done', [])
            substrate = event.data.get('substrate')
            if substrate not in done:
                done.append(substrate)
                changed = True
        return changed

    def _write(self) -> None:
        record = {**self._base, 'current_stage': self._current, 'stages': self._stages}
        try:
            _write_run_record(self._dirs, record)
        except OSError as exc:
            log.debug('run record progress write skipped', error=str(exc))


#: The timing fields a stage entry keeps in the terminal record.
_STAGE_TIMINGS = ('started_at', 'seat_acquired_at', 'finished_at')

#: How many recent seat turns the expected-start estimate takes its median over.
SEAT_SAMPLE_RUNS = 20


def seat_turn_durations(outputs_root: Path, *, limit: int = SEAT_SAMPLE_RUNS) -> list[float]:
    """Seconds from taking the seat to finishing synthesis, newest run first.

    Read from the finished run records under ``outputs_root``, up to ``limit``
    of them. Only a complete run whose synthesis exited 0 and took the seat
    counts: a dry run never takes it, a failed one stopped early, and a stage
    skipped on a resume finished in an instant without it. The span runs to the
    end of the stage, so it includes the sidecar turn, which runs after the
    seat is released; the estimate errs late by that much.
    """

    def modified(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    samples: list[float] = []
    for path in sorted(outputs_root.glob(f'*/{RUN_RECORD_NAME}'), key=modified, reverse=True):
        if len(samples) >= limit:
            break
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        seconds = _seat_turn_s(record)
        if seconds is not None:
            samples.append(seconds)
    return samples


def _seat_turn_s(record: Any) -> float | None:
    if not isinstance(record, dict) or record.get('status') != 'complete':
        return None
    stage = (record.get('stages') or {}).get('synthesis')
    if not isinstance(stage, dict) or stage.get('exit_code') != 0:
        return None
    try:
        took = datetime.fromisoformat(str(stage['seat_acquired_at']))
        done = datetime.fromisoformat(str(stage['finished_at']))
        seconds = (done - took).total_seconds()
    except (KeyError, TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def uses_local_seat(assurance: str, *, dry_run: bool) -> bool:
    """True when a run of this tier will queue for the local seat."""
    return not dry_run and any(s in LOCAL_SEAT_STAGES for s in _TIER_STAGES.get(assurance, ()))


def seat_report(batch_name: str) -> dict[str, Any]:
    """The seat as run ``batch_name`` sees it: the queue, and when it can expect a turn.

    ``waiting`` counts every run queued on the seat now, and ``holder`` names the
    one holding it. ``expected_start_s`` is ``[early, late]`` in seconds from
    now, for this run as one of the waiters (counted in if it is not queued
    yet): early if it is taken next, late if every other waiter goes first.
    There is no position, because the lock grants the seat to whichever waiter
    polls first. With no measured seat turn to go on, the range is ``None`` and
    ``reason`` says why.
    """
    return _seat_block(seat_queue(paths.seat_lock_path()), batch_name)


def seat_report_if_queued(batch_name: str) -> dict[str, Any] | None:
    """:func:`seat_report`, or None when run ``batch_name`` holds no waiter ticket.

    A stage's ``waiting`` also covers a rate-limit backoff, so the ticket is
    what says the run is queued for the seat.
    """
    queue = seat_queue(paths.seat_lock_path())
    if not _is_queued(queue, batch_name):
        return None
    return _seat_block(queue, batch_name)


def _is_queued(queue: SeatQueue, batch_name: str) -> bool:
    # Seat owners are named `<batch>/<stage>:<topic>` (StageContext.seat_owner).
    return any(owner.startswith(f'{batch_name}/') for owner in queue.owners)


def _seat_block(queue: SeatQueue, batch_name: str) -> dict[str, Any]:
    samples = seat_turn_durations(paths.outputs_root())
    median = statistics.median(samples) if samples else None
    elapsed = _seconds_since(queue.holder_since) if queue.holder is not None else None
    waiting = queue.waiting + (0 if _is_queued(queue, batch_name) else 1)
    span = seat_start_range(waiting, elapsed, median)
    reason = None if span else 'no finished run on record has a measured seat turn to go on'
    return {
        'waiting': queue.waiting,
        'holder': queue.holder,
        'expected_start_s': [round(span[0]), round(span[1])] if span else None,
        'reason': reason,
    }


def _seconds_since(iso: str | None) -> float:
    """Seconds since ``iso``; 0 when it cannot be read, which errs late."""
    try:
        since = datetime.fromisoformat(str(iso))
        return max(0.0, (datetime.now(UTC) - since).total_seconds())
    except (TypeError, ValueError):
        return 0.0


#: How many times a blocked ``replace`` is tried, and the pause between tries. On
#: Windows ``replace`` raises ``PermissionError`` while another process (the
#: status tool, a monitor) has the destination open for reading; the hold lasts
#: milliseconds, and the terminal record is the one write that must not be lost
#: to it.
_RECORD_REPLACE_ATTEMPTS = 5
_RECORD_RETRY_PAUSE_S = 0.1


def _replace_with_retry(tmp: Path, path: Path) -> None:
    for attempt in range(1, _RECORD_REPLACE_ATTEMPTS + 1):
        try:
            tmp.replace(path)
        except PermissionError:
            if attempt == _RECORD_REPLACE_ATTEMPTS:
                raise
            time.sleep(_RECORD_RETRY_PAUSE_S)
        else:
            return


def _plugin_cache_hint(run_dir: Path) -> str:
    """Say how to get back a run written inside a plugin version's cache directory.

    Up to 0.5.1 a plugin install kept its runs in its own versioned cache
    directory; they now live under the data root, so the containment check
    refuses the old ones. Both ways out work because a resume recomputes every
    path from the run's batch name: the absolute paths in its ``run.json`` are
    for display only.
    """
    batch = run_dir.name
    old_root = run_dir.parent.parent if run_dir.parent.name == 'outputs' else None
    if old_root is None:
        where, source = 'MANTIS_HOME=<that version directory>', ''
    else:
        where, source = f'MANTIS_HOME={old_root}', f' from {old_root}'
    return (
        f". It sits in a plugin version's cache directory, where runs were kept "
        f'before they moved to the data root ({paths.data_root().resolve()}). Either '
        f'set {where} and resume again to resume it in place, or move outputs/{batch}, '
        f'state/{batch} and transcripts/{batch}{source} under the data root and '
        f'resume it there. Copy them out before that cache directory is pruned.'
    )


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
        if paths.in_plugin_cache(resolved):
            msg += _plugin_cache_hint(resolved)
        raise ValueError(msg)
    if not resolved.is_dir():
        msg = f'no run directory at {resolved}'
        raise ValueError(msg)
    return resolved


def is_finished_record(record: Mapping[str, Any]) -> bool:
    """True when a run record is a successful, real run with nothing left to run.

    The one judgement behind "a resume collects": a ``complete`` record whose
    stages all exited 0 and whose sidecar did not fail. A ``failed`` record, a
    ``complete`` one with a stage that exited non-zero, a dry run's
    ``validated`` one and an abandoned ``dispatching`` one each still have
    stages to run, so resuming them is a resume and not a collect.

    So does a run whose sidecar failed, although its stages all exited 0
    (ADR-0011): its synthesis state is not settled, so a resume re-enters that
    stage for the sidecar alone. A sidecar removed after it was published does
    not make a run unfinished: its synthesis is recorded as done with the
    sidecar delivered, so a resume would re-run nothing and end at the same
    refusal, and reading it as a collect returns that refusal at once rather
    than a handle to a run that cannot change.
    """
    sidecar = record.get('sidecar')
    sidecar_failed = (
        isinstance(sidecar, dict) and sidecar.get('status') == SidecarOutcome.FAILED.value
    )
    return (
        record.get('status') == 'complete'
        and record.get('ok') is True
        and not record.get('dry_run', False)
        and not sidecar_failed
    )


def _collect_finished(
    record: Mapping[str, Any], on_event: ProgressCallback | None
) -> dict[str, Any] | None:
    """Rebuild the manifest of a finished run from its record, writing nothing.

    A resume of a finished run used to run every stage again, each skipping, and
    then rewrite ``run.json`` with only that call's timings. That dropped the
    seat turn the expected-start estimate reads, and the rewrite moved the run
    up the newest-first listing, so collecting a run erased it from the one and
    misplaced it in the other. The record already holds what the manifest needs
    and the artifacts are on disk, so collecting reads them and leaves the
    record as it is. ``None`` when the record lacks a field the manifest needs,
    and the caller then falls back to a full resume.
    """
    try:
        stages = {str(stage): int(entry['exit_code']) for stage, entry in record['stages'].items()}
        manifest = _manifest(
            question=str(record['question']),
            batch_name=str(record['batch_name']),
            assurance=str(record['assurance']),
            slug=str(record['question_slug']),
            substrates=_recorded_substrates(record),
            results=stages,
            dry_run=False,
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    emit(
        on_event,
        RunEvent(
            kind='run_done',
            message=f'run {manifest["batch_name"]} was already complete (ok=True)',
            step=len(stages),
            total=len(stages),
            data={
                'batch_name': manifest['batch_name'],
                'ok': True,
                'outputs_dir': manifest['outputs_dir'],
            },
        ),
    )
    return manifest


def _recorded_substrates(record: Mapping[str, Any]) -> list[str]:
    """The substrates a finished run asked for.

    A terminal record written before it carried ``substrates`` still names
    them, as the brief files the manifest lists, one ``<substrate>.md`` each.
    """
    recorded = record.get('substrates')
    if recorded:
        return [str(sub) for sub in recorded]
    return [Path(str(brief)).name.removesuffix('.md') for brief in record['outputs']['briefs']]


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

    if not dry_run and is_finished_record(record):
        collected = _collect_finished(record, on_event)
        if collected is not None:
            return collected

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


def _read_sidecar_outcome(dirs: RunDirs, stages: Sequence[str], *, dry_run: bool) -> dict[str, Any]:
    """The sidecar's own outcome for this run, read off the synthesis state.

    The synthesis stage records it (ADR-0011); this reads it back the way
    :func:`_read_cost` reads the OpenRouter state. Anything it cannot establish
    — no synthesis stage ran, a dry run, an unreadable or pre-field state file —
    is reported as what it is rather than guessed at.
    """
    absent = {'status': SidecarOutcome.NOT_RUN.value, 'error': None}
    if not produces_sidecar(stages):
        return {'status': SidecarOutcome.NOT_OWED.value, 'error': None}
    if dry_run:
        return absent
    state_path = dirs.state('synthesis') / '1.json'
    if not state_path.exists():
        return absent
    try:
        state = SynthesisState.model_validate_json(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return absent
    if state.sidecar_status is None:
        return absent
    return {'status': state.sidecar_status.value, 'error': state.sidecar_error}


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
    orphan directory it cannot match to a question. Each later transition is
    written into that record before ``on_event`` hears of it
    (:class:`_StageRecorder`).
    """
    # Lazy import: importing cli.dispatch runs cli/__init__, which imports
    # research_cmd -> cli.research -> back to this module. Deferring dispatch to
    # call time breaks that cycle (it is only needed once we run a stage).
    from mantis_research.interface.cli.dispatch import dispatch_stage_config

    if assurance not in _TIER_STAGES:
        _journal_request(question, assurance, outcome='rejected', detail='invalid assurance')
        msg = f'invalid assurance {assurance!r}; choose {"|".join(_TIER_STAGES)}'
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
    name = batch_name or _mint_run_name(question)

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
    _claim_run_root(dirs, question)
    _journal_request(question, assurance, outcome='accepted', detail=name)
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
    started_at = _now_iso()
    dispatching = {
        **identity,
        'status': 'dispatching',
        'started_at': started_at,
        # Written in so a later run can read it back and tell an owner that
        # is still working from one that is gone (MANT-B08).
        'owner_pid': os.getpid(),
    }
    # The resume history goes in once; later writes carry it forward.
    _write_run_record(dirs, {**dispatching, 'history': _resume_history or []})
    # From here every event goes through the recorder, which rewrites the
    # record at each transition before the caller hears of it (T1e).
    recorder = _StageRecorder(dirs, dispatching, on_event)
    emit(
        recorder,
        RunEvent(
            kind='run_named',
            message=f'run {name} dispatching {len(stages)} stage(s) into {dirs.root()}',
            step=0,
            total=len(stages),
            data=identity,
        ),
    )

    results: dict[str, int] = {}
    # Whatever ends this function other than a `return` — a stage that raises, a
    # manifest that cannot be built, an interrupt — must leave the record
    # terminal. Left at `dispatching`, a dead worker inside a live server reads
    # as `running` for as long as the server's pid lives (T1d).
    try:
        for index, stage in enumerate(stages, start=1):
            emit(
                recorder,
                RunEvent(
                    kind='stage_start',
                    message=f'{stage} starting',
                    step=index - 1,
                    total=len(stages),
                    data={'stage': stage, 'batch_name': name},
                ),
            )
            rc = dispatch_stage_config(
                stage, cfg, dry_run=dry_run, log_level=log_level, on_event=recorder
            )
            results[stage] = rc
            emit(
                recorder,
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
        # `complete` means the artifacts under `outputs` are on disk. A dry run
        # wrote none of them, so it says what it actually did: every path in the
        # record is a destination, and only a real run turns them into evidence.
        status = 'validated' if dry_run else 'complete'
        recorder.close()
        # The record keeps each stage's timings beside its exit code, and what
        # the run started with: `started_at` orders the run listing, and a
        # resume asks the research stage for `substrates` again. The manifest
        # returned to the caller keeps its shape.
        _write_run_record(
            dirs,
            {
                **manifest,
                'substrates': subs,
                'started_at': started_at,
                'stages': recorder.finished_stages(results),
                'status': status,
                'finished_at': _now_iso(),
            },
        )
    except BaseException as exc:
        recorder.close()
        _write_failed_record(
            dirs,
            identity,
            stages=recorder.finished_stages(results),
            started_at=started_at,
            error=exc,
        )
        raise

    emit(
        recorder,
        RunEvent(
            kind='run_done',
            message=f'run {name} complete (ok={manifest["ok"]})',
            step=len(stages),
            total=len(stages),
            data={'batch_name': name, 'ok': manifest['ok'], 'outputs_dir': str(dirs.root())},
        ),
    )
    return manifest


def _write_failed_record(
    dirs: RunDirs,
    identity: Mapping[str, Any],
    *,
    stages: Mapping[str, Mapping[str, Any]],
    started_at: str,
    error: BaseException,
) -> None:
    """Make an exception's end of the run a terminal record, never a new failure.

    The original exception is the one the caller must see, so a write that itself
    fails is logged and dropped rather than raised over it.
    """
    try:
        _write_run_record(
            dirs,
            {
                **identity,
                'status': 'failed',
                'ok': False,
                'stages': dict(stages),
                'error': repr(error)[:_ERROR_CHARS],
                'owner_pid': os.getpid(),
                'started_at': started_at,
                'finished_at': _now_iso(),
            },
        )
    except OSError:
        log.exception('could not write the failed run record')


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()

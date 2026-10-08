"""MCP stdio server exposing the ``research`` tool (spec 0002 §2/§3, ADR-0009).

Local-first: run co-located with an authenticated ``claude`` CLI so the
synthesis-family stages consume the host's Claude subscription seat (ADR-0009).
Start it with ``python -m mantis_research.interface.mcp``.

Pinned ``mcp`` SDK API — probed against the installed package (spec 0002 §2 / FM-2,
FM-B):

- ``from mcp.server.mcpserver import Context, MCPServer``; ``MCPServer(name)``. The
  2.x rename of the 1.x ``FastMCP``, whose module no longer exists.
- ``@server.tool()`` registers a tool; the function's type hints are the input
  schema, and a ``dict`` return annotation yields structured output (the Tool
  carries an ``output_schema``). A listed Tool's schema is ``Tool.input_schema``
  (1.x: ``inputSchema``).
- ``server.run(transport='stdio')`` serves over stdio.
- ``await server.list_tools()`` is the public tool-introspection API (used by the
  §2 registration test); a synchronous ``server._tool_manager.list_tools()`` also
  exists.
- Synchronous ``@tool``-decorated functions are dispatched off the event loop by
  the SDK; even so, the ``research`` handler is ``async`` and offloads the blocking
  ``run_research`` via ``asyncio.to_thread`` — safe regardless of the SDK's
  sync-threading behaviour (FM-1/FM-B).
- A parameter annotated ``Context`` is injected by the SDK and excluded from the
  tool's input schema (``Tool.context_kwarg``), so it never reaches the agent as
  an argument to supply.

Progress is reported over that context. A client gives up on a call that sends
no progress notification for its idle limit, and only progress resets that clock
(a log notification does not), so a blocking call sends every run event as
progress and adds a keepalive tick while the run is silent
(:class:`_ProgressChannel`). The SDK requires each value to be strictly greater
than the last one sent on the same token, while the run's steps repeat and most
events carry none; the channel sends those as fractions between two steps.
Before 0.2.0 the whole multi-stage run hid behind one ``to_thread`` await and the
client saw silence from call to return — which a client cannot distinguish from
a hang, and answers by giving up.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import structlog
from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from mantis_research.core import paths
from mantis_research.core.sidecar import ResearchSidecar, project_for_agent
from mantis_research.interface.research_service import (
    RUN_RECORD_NAME,
    is_finished_record,
    missing_product,
    resolve_resume_dir,
    resume_research,
    run_research,
    seat_report,
    seat_report_if_queued,
    uses_local_seat,
)
from mantis_research.interface.seat import process_is_alive

if TYPE_CHECKING:
    from mantis_research.core.progress import ProgressCallback, RunEvent

_SERVER_NAME = 'mantis-research'

#: What the sidecar's outcome reads as on a run record that predates the field.
_UNKNOWN_SIDECAR: dict[str, Any] = {'status': 'not_run', 'error': None}

#: How long a detached call waits for the run to name itself. The run emits
#: `run_named` after building its config and before dispatching any stage, so
#: this bounds config validation, not research.
_NAMING_TIMEOUT_S = 30.0

#: How often a blocking call sends a keepalive progress notification while the
#: run is silent. Claude Code aborts a tool call after 1800 s without a progress
#: notification (checked every 30 s); a log notification does not count.
_KEEPALIVE_S = 60.0

#: How many times a refused read of a run record is tried, and the pause between
#: tries. The record is rewritten while a run is polled, and on Windows a read
#: that lands while ``replace`` swaps the file in raises ``PermissionError``; the
#: swap takes milliseconds.
_RECORD_READ_ATTEMPTS = 5
_RECORD_READ_PAUSE_S = 0.05
# The most runs one listing returns; older ones are counted, not sent.
_LIST_LIMIT = 50

log = structlog.get_logger(__name__)


class IncompleteRunError(RuntimeError):
    """The run produced no epistemic sidecar, so it produced no answer.

    Raised instead of returning the partial result. The sidecar is the product
    (ADR-0003); a result carrying only research briefs is a run that failed, and
    handing it back as an ordinary tool result lets a caller read it as a
    delivered answer — which is precisely what happened in the field.
    """


def _incomplete(manifest: dict[str, Any], sidecar_path: Path, blame: str) -> IncompleteRunError:
    """Build the refusal around the blame line the judgement already produced.

    ``blame`` comes from :func:`missing_product`, which is also what the CLI's
    exit code reads — so the reason an agent is given and the reason an operator
    is given cannot drift apart.
    """
    outputs_dir = manifest.get('outputs_dir') or manifest.get('batch_name', '')
    return IncompleteRunError(
        f'the run produced no epistemic sidecar at {sidecar_path} — {blame}. '
        f'The sidecar is the product (ADR-0003): research briefs without a '
        f'synthesis and its sidecar are not an answer, so this is reported as a '
        f'failure rather than returned as a partial result. The briefs that were '
        f'paid for are on disk — re-enter the run with '
        f'resume="{outputs_dir}" once the cause is fixed, rather than asking '
        f'again and buying them twice.'
    )


def _agent_result(manifest: dict[str, Any]) -> dict[str, Any]:
    """Assemble the agent-facing result from a run manifest and its sidecar.

    Carries the manifest's output paths, per-stage exit codes and cost block,
    plus the sidecar's epistemic content (claims / divergences / verification
    queue, via :func:`project_for_agent`). The synthesis and briefs stay
    referenced by path in ``outputs`` — never inlined (§3). Synchronous file I/O,
    so it runs inside the worker thread the async tool offloads to (FM-1).

    A live run with no sidecar on disk raises :class:`IncompleteRunError` rather
    than returning. Every path in ``outputs`` is a destination, not evidence, so
    a briefs-only result is indistinguishable at a glance from a complete one —
    an agent that reads `outputs` and finds three real brief files has no reason
    to doubt the rest. A dry run is exempt on the manifest's own ``dry_run``
    flag: it legitimately writes nothing, and says so in the result.
    """
    result: dict[str, Any] = {
        'ok': manifest['ok'],
        'dry_run': manifest.get('dry_run', False),
        'question': manifest['question'],
        'assurance': manifest['assurance'],
        'cost': manifest['cost'],
        'stages': manifest['stages'],
        'outputs': manifest['outputs'],
        # Where the run lives and what it is called, so a caller that wants to
        # poll or resume has them from the result in hand (T9c). Both are on
        # every manifest `run_research` and `resume_research` return.
        'outputs_dir': manifest.get('outputs_dir'),
        'batch_name': manifest.get('batch_name'),
        # The run's second outcome (ADR-0011). Absent on run records written
        # before the field, which a resume still reads: unknown, not fine.
        'sidecar': manifest.get('sidecar') or _UNKNOWN_SIDECAR,
    }
    sidecar_path = Path(manifest['outputs']['sidecar'])
    # A live run that owed a sidecar and has none produced no answer. Which runs
    # those are, and why, is decided once in `missing_product` — the CLI's exit
    # code reads the same call, so the two surfaces cannot disagree about what a
    # run delivered.
    blame = missing_product(manifest)
    if blame is not None:
        raise _incomplete(manifest, sidecar_path, blame)
    if sidecar_path.exists():
        sc = ResearchSidecar.from_model_json(sidecar_path.read_text(encoding='utf-8'))
        result['sidecar_available'] = True
        result.update(project_for_agent(sc))
        return result
    result['sidecar_available'] = False
    return result


def _run_and_assemble(
    question: str,
    *,
    assurance: str,
    substrates: list[str] | None,
    primary: str,
    journal: bool,
    dry_run: bool,
    name: str = '',
    resume: str = '',
    on_event: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the pipeline and assemble the agent result (sync — runs off the loop)."""
    if resume:
        manifest = resume_research(Path(resume), dry_run=dry_run, on_event=on_event)
    else:
        manifest = run_research(
            question,
            assurance=assurance,
            substrates=substrates,
            primary=primary,
            journal=journal,
            dry_run=dry_run,
            batch_name=name,
            on_event=on_event,
        )
    return _agent_result(manifest)


class _ProgressChannel:
    """The progress one blocking call sends, owned by that call, on its loop.

    A client gives up on a tool call that sends no progress notification for its
    idle limit (1800 s in Claude Code), and only a progress notification resets
    that clock: a log notification does not. So every run event goes out as
    progress, and so does a keepalive tick while the run says nothing.

    The SDK requires each value to be strictly greater than the last one sent on
    the token, while the run's steps repeat (a stage's start and its
    predecessor's finish share one) and most events carry no step at all. A step
    that exceeds the last whole step sent is sent as itself, so the client's
    scale still reads ``step / total``. Anything else (a repeated step, an event
    without one, a keepalive tick) is sent as ``last + k / (k + 1)`` for the
    k-th such send since that step: strictly between the last whole step and the
    next, so the values keep increasing and the next real step still advances.

    No value exceeds ``total``, and ``total`` itself is sent once, by
    ``run_done``. The last stage's finish carries ``step == total`` too, and
    ticks arrive while that stage runs, so until ``run_done`` a step is held at
    ``total - 1`` and those sends fall in the band below ``total``. A run that
    raises never sends ``run_done`` and so never reaches ``total``: it did not
    finish. After ``total`` the call is ending, and the channel sends no more
    progress; an event's log line still goes out.

    Values are computed under a lock on the loop, in the order the sends take
    it, so what the client receives is in the order it was computed.
    """

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx
        self._lock = asyncio.Lock()
        self._step: int | None = None
        self._since_step = 0
        self._total: int | None = None
        self._last_message = ''
        self._finished = False

    def _next_value(self, step: int | None, *, final: bool = False) -> float | None:
        """The value for the next send, or ``None`` once ``total`` has been sent."""
        if self._finished:
            return None
        if final:
            self._finished = True
            if self._total is not None:
                return float(self._total)
        elif step is not None and self._total is not None:
            step = min(step, self._total - 1)
        if step is not None and (self._step is None or step > self._step):
            self._step = step
            self._since_step = 0
            return float(step)
        if self._step is None:
            # Nothing sent yet: the first send anchors the scale at zero.
            self._step = 0
            return 0.0
        self._since_step += 1
        k = self._since_step
        return self._step + k / (k + 1)

    async def _send(self, value: float | None, message: str) -> None:
        # `report_progress` no-ops when the client sent no progress token. A
        # client that is gone must not fail the call: the run is the job.
        if value is None:
            return
        try:
            await self._ctx.report_progress(progress=value, total=self._total, message=message)
        except Exception:
            log.debug('progress notification not delivered', exc_info=True)

    async def event(self, event: RunEvent) -> None:
        """Send one run event as progress, and as a log line as before."""
        async with self._lock:
            if event.total:
                self._total = event.total
            self._last_message = event.message
            value = self._next_value(event.step, final=event.kind == 'run_done')
            await self._send(value, event.message)
            # `ctx.info` is deprecated in mcp 2.x (the logging capability is going
            # away, SEP-2577) but is still delivered, and it is the only channel a
            # client with no progress token hears; drop it when the SDK does.
            try:
                await self._ctx.info(event.message)
            except Exception:
                log.debug('log notification not delivered', exc_info=True)

    async def keepalive(self, elapsed_s: float) -> None:
        """Send a tick that says the run is still going and what it last said."""
        async with self._lock:
            last = self._last_message or 'the run has not reported yet'
            message = f'still running: {last} ({elapsed_s:.0f} s)'
            await self._send(self._next_value(None), message)

    def callback(self, loop: asyncio.AbstractEventLoop) -> ProgressCallback:
        """Adapt the synchronous run-event callback onto the session's loop.

        ``run_research`` is synchronous and runs in a worker thread (FM-1), while
        the MCP session belongs to the event loop that spawned it, so an event is
        handed back across that boundary rather than awaited in place.
        ``run_coroutine_threadsafe`` is that hand-off; the future is deliberately
        not awaited, since the run must not block on its audience.
        """

        def deliver(event: RunEvent) -> None:
            asyncio.run_coroutine_threadsafe(self.event(event), loop)

        return deliver


async def _blocking_call(ctx: Any, question: str, **options: Any) -> dict[str, Any]:
    """Run the pipeline off the loop and keep the call alive until it returns.

    Every :data:`_KEEPALIVE_S` seconds without a result a keepalive tick goes
    out on the call's progress channel. Run events reach the client as they
    happen, but a phase can emit nothing at all (a sidecar turn, a hung child,
    an OpenRouter call waiting on its timeout), and the client counts that
    silence toward its idle limit. The interval is read on every tick, so a test
    can shorten it.

    A cancelled call leaves the run working, as a client that gave up does:
    the worker is not cancelled, and its outcome is retrieved when it ends, so
    a later failure is logged here rather than reported by asyncio as a task
    exception nobody retrieved.
    """
    loop = asyncio.get_running_loop()
    channel = _ProgressChannel(ctx) if ctx is not None else None
    on_event = channel.callback(loop) if channel is not None else None
    task = asyncio.create_task(
        asyncio.to_thread(_run_and_assemble, question, on_event=on_event, **options)
    )
    started = time.monotonic()
    try:
        while True:
            timeout = _KEEPALIVE_S if channel is not None else None
            done, _ = await asyncio.wait({task}, timeout=timeout)
            if done:
                return task.result()
            if channel is not None:
                await channel.keepalive(time.monotonic() - started)
    except asyncio.CancelledError:
        task.add_done_callback(_retrieve_outcome)
        raise


def _retrieve_outcome(task: asyncio.Task[Any]) -> None:
    """Read the outcome of a worker whose call was cancelled, and log a failure."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.debug('run of a cancelled call ended with an error', exc_info=exc)


def _artifacts_on_disk(run_dir: Path) -> dict[str, list[str]]:
    """What a run has already written, read off the disk rather than its record.

    The record is rewritten at each stage transition, but a write can be lost to
    a reader holding the file, and a run started by a version that wrote the
    record only at its start and end says nothing until it finishes. The files
    themselves are the evidence a poller needs either way (T1e).
    """
    synthesis = run_dir / 'synthesis'
    return {
        'briefs': sorted(str(p) for p in (run_dir / 'openrouter').glob('**/*.md')),
        'synthesis': sorted(str(p) for p in synthesis.glob('*.md')),
        'sidecar': sorted(str(p) for p in synthesis.glob('*.sidecar.json')),
    }


def _project(record: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Describe a run from its record, without judging it.

    Deliberately not :func:`_agent_result`: that raises when a live run owed a
    sidecar and has none, which is right for the call that was supposed to
    deliver one and wrong for a caller asking how a run went. Polling must
    answer the question, not hand back an exception to interpret.

    A run that has not finished also reports the ``artifacts`` already on disk
    under ``run_dir``, so a lagging record cannot hide them, and a run queued
    for the local seat reports the queue as ``seat`` (T1f).
    """
    status = str(record.get('status', ''))
    if status == 'dispatching':
        owner = record.get('owner_pid')
        alive = isinstance(owner, int) and process_is_alive(owner)
        state = 'running' if alive else 'abandoned'
    else:
        # `failed` — a run that ended on an exception — is a finished run that
        # did not succeed, not a fifth state: the vocabulary stays closed.
        state = 'finished'
    projection: dict[str, Any] = {
        'state': state,
        'batch_name': record.get('batch_name'),
        'outputs_dir': record.get('outputs_dir'),
        'question': record.get('question'),
        'question_slug': record.get('question_slug'),
        'started_at': record.get('started_at'),
        'assurance': record.get('assurance'),
        'ok': record.get('ok'),
        # Mid-run each entry carries `state`, and `exit_code` stays null until
        # the stage is done; a finished record carries `exit_code` alone.
        'stages': record.get('stages') or {},
        'current_stage': record.get('current_stage'),
        'sidecar': record.get('sidecar') or _UNKNOWN_SIDECAR,
        'cost': record.get('cost') or {},
        'outputs': record.get('outputs') or {},
    }
    if status == 'dispatching':
        projection['artifacts'] = _artifacts_on_disk(run_dir)
    if state == 'running':
        seat = seat_report_if_queued(str(record.get('batch_name') or run_dir.name))
        if seat is not None:
            projection['seat'] = seat
    if record.get('error'):
        projection['error'] = record['error']
    return projection


async def research_status(
    outputs_dir: Annotated[
        str,
        Field(
            description=(
                'The output directory of a run to report on — the "outputs_dir" '
                "a detached `research` call returned. Reads the run's own record "
                'and per-stage state; it never starts or changes anything. Leave it '
                "empty to list the runs under this server's data root instead, "
                'newest first.'
            )
        ),
    ] = '',
) -> dict[str, Any]:
    """Report how a run is going, without waiting for it.

    Returns its state (``running`` / ``finished`` / ``abandoned`` / ``unknown``;
    a run that ended on an exception is ``finished`` with ``ok`` false and an
    ``error`` string), per-stage exit codes, cost so far and output paths, plus ``data_root``: the
    directory this server writes runs under (``<data_root>/outputs/<run>``). While
    a run is in flight, each ``stages`` entry carries ``state`` (``running`` /
    ``waiting`` / ``done``) and its ``exit_code`` is null until the stage is done;
    ``current_stage`` names the stage most recently started, and ``artifacts``
    lists the briefs, syntheses and sidecars already on disk. A finished run's
    full epistemic result is fetched by calling ``research`` again with
    ``resume=<outputs_dir>``, which skips the stages already done.

    With no ``outputs_dir``, returns ``runs``: every run directory under the data
    root that holds a record, newest first, each described as above plus
    ``age_s`` (seconds since it started), ``question_slug`` and ``batch_name``.
    At most 50 are listed; ``truncated`` counts the older ones left out. A record
    that cannot be read is listed with state ``unknown`` and a ``detail``.
    """
    # Off the loop: the read can pause for a writer, and the artifact listing
    # walks the run directory.
    if not outputs_dir:
        listing = await asyncio.to_thread(_list_runs)
        return {**listing, 'data_root': str(paths.data_root())}
    status = await asyncio.to_thread(_status, outputs_dir)
    return {**status, 'data_root': str(paths.data_root())}


def _status(outputs_dir: str) -> dict[str, Any]:
    """Read one run's record into the status shape (``unknown`` when it cannot)."""
    record_path = Path(outputs_dir) / RUN_RECORD_NAME
    if not record_path.exists():
        return {
            'state': 'unknown',
            'outputs_dir': outputs_dir,
            'detail': (
                f'no run record at {record_path}. Either the run never started, '
                f'or this is not a run directory.'
            ),
        }
    try:
        record = _read_record(record_path)
    except (OSError, ValueError) as exc:
        return {'state': 'unknown', 'outputs_dir': outputs_dir, 'detail': str(exc)}
    return _project(record, record_path.parent)


def _list_runs() -> dict[str, Any]:
    """Describe the runs under the outputs root, newest first, capped at the limit.

    A run is a direct child directory holding a record. Each is read through
    :func:`_status`, so an unreadable record becomes an ``unknown`` entry rather
    than an exception: a listing that failed on one bad directory would hide
    every good one. Recency is the record's ``started_at``, falling back to the
    directory's modification time for a record that has none.
    """
    root = paths.outputs_root()
    try:
        candidates = [d for d in root.iterdir() if (d / RUN_RECORD_NAME).is_file()]
    except OSError:
        candidates = []
    now = time.time()
    entries: list[tuple[float, dict[str, Any]]] = []
    for run_dir in candidates:
        entry = _status(str(run_dir))
        started = _epoch(entry.get('started_at'))
        if started is None:
            try:
                started = run_dir.stat().st_mtime
            except OSError:
                started = now
        entry['age_s'] = max(0.0, round(now - started, 1))
        entry['batch_name'] = entry.get('batch_name') or run_dir.name
        entry['outputs_dir'] = entry.get('outputs_dir') or str(run_dir)
        entries.append((started, entry))
    entries.sort(key=lambda pair: pair[0], reverse=True)
    return {
        'runs': [entry for _, entry in entries[:_LIST_LIMIT]],
        'truncated': max(0, len(entries) - _LIST_LIMIT),
    }


def _epoch(stamp: object) -> float | None:
    """Parse an ISO-8601 timestamp to epoch seconds, or ``None`` when it is not one."""
    if not isinstance(stamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _read_record(record_path: Path) -> dict[str, Any]:
    """Read a run record, retrying a read refused while a writer swaps it in."""
    attempt = 1
    while True:
        try:
            record: dict[str, Any] = json.loads(record_path.read_text(encoding='utf-8'))
        except PermissionError:
            if attempt >= _RECORD_READ_ATTEMPTS:
                raise
            attempt += 1
            time.sleep(_RECORD_READ_PAUSE_S)
        else:
            return record


def _should_detach(detach: bool | None, *, assurance: str, dry_run: bool, resume: str) -> bool:
    """Whether this call returns a handle instead of the result (T20a).

    A resume of a run that finished is a collect, and a collect returns the
    result whatever ``detach`` says: answering it with another handle would
    leave the caller polling a run that is already finished. Only a run with
    nothing left to run is a collect (:func:`is_finished_record`); a ``failed``
    or abandoned one, or one with a stage that exited non-zero, re-runs its
    remaining stages on resume, and that is as long as a new run. So does one
    whose sidecar failed, which re-enters the synthesis stage. A record that
    cannot be read blocks, so the resume's own refusal reaches the caller.
    Otherwise an explicit ``detach`` is honoured, and unset it detaches exactly
    the runs that will queue for the local seat, judged on the tier the run will
    actually use: on a resume, the record's, not the call's.
    """
    if resume:
        try:
            record = _read_record(resolve_resume_dir(Path(resume)) / RUN_RECORD_NAME)
        except (OSError, ValueError):
            return False
        if not dry_run and is_finished_record(record):
            return False
        assurance = str(record.get('assurance') or 'fast')
    if detach is not None:
        return detach
    return uses_local_seat(assurance, dry_run=dry_run)


def _detach(
    question: str,
    *,
    assurance: str,
    substrates: list[str] | None,
    primary: str,
    journal: bool,
    dry_run: bool,
    name: str,
    resume: str,
) -> dict[str, Any]:
    """Start the run, hand back its identity, and let it work.

    A background thread rather than a detached process: ``dispatch_stage_config``
    nests ``asyncio.run`` per stage, so the work cannot sit on this loop, and a
    thread inherits the server's resolved paths without a new environment
    contract. The run is therefore bound to the server's lifetime — which is the
    session that will do the polling — and a run lost with its session is
    re-entered through ``resume``.

    The handle carries no epistemic payload. There is nothing to report yet, and
    a result shaped like an answer is exactly what let a briefs-only run read as
    one. When the run will need the local seat, it carries the queue it will
    join as ``seat`` (T1f).

    A resume can turn out to be a collect: the record the caller's check read
    was ``dispatching``, and its owner finished before this worker resumed it.
    A collect names no run, so the worker returns before any name arrives, and
    its result is returned as a blocking collect would return it.
    """
    started = threading.Event()
    identity: dict[str, Any] = {}
    refused: list[Exception] = []
    collected: list[dict[str, Any]] = []

    def note(event: RunEvent) -> None:
        if event.kind == 'run_named' and not identity:
            identity.update(event.data)
            started.set()

    def work() -> None:
        try:
            result = _run_and_assemble(
                question,
                assurance=assurance,
                substrates=substrates,
                primary=primary,
                journal=journal,
                dry_run=dry_run,
                name=name,
                resume=resume,
                on_event=note,
            )
            if not identity:
                collected.append(result)
        except Exception as exc:
            # Before the run names itself, a failure is the caller's answer:
            # the seat check and argument validation run there.
            if not identity:
                refused.append(exc)
            log.exception('detached run failed')
        except BaseException:  # the thread must never take the server down
            log.exception('detached run failed')
        finally:
            started.set()

    thread = threading.Thread(target=work, name='mantis-research-run', daemon=True)
    thread.start()
    # The run names itself before it dispatches anything, so this waits only for
    # the config to build — not for the research to happen.
    started.wait(timeout=_NAMING_TIMEOUT_S)
    if not identity:
        if refused:
            raise refused[0]
        if collected:
            return collected[0]
        msg = (
            'the detached run did not name itself within '
            f'{_NAMING_TIMEOUT_S:.0f}s — it failed before dispatch. Re-run '
            'with detach=false to see the error.'
        )
        raise RuntimeError(msg)
    handle: dict[str, Any] = {'state': 'running', **identity}
    if uses_local_seat(str(identity.get('assurance')), dry_run=bool(identity.get('dry_run'))):
        handle['seat'] = seat_report(str(identity.get('batch_name')))
    return handle


async def research(
    question: Annotated[str, Field(description='The research question to investigate.')],
    assurance: Annotated[
        str,
        Field(
            description=(
                'How far the pipeline runs. "fast" (the default) is research + '
                'synthesis. Escalate explicitly when the extra checking is worth '
                'the extra Claude-seat time: "standard" adds an adversarial '
                'falsification pass over the finished synthesis, "high" adds a '
                'Claude-prior baseline and a rubric evaluation on top. '
                '"research" stops after the cross-model briefs and returns their '
                'paths and cost with no synthesis and no sidecar — the tier to '
                'use when no local Claude seat is available, or when you want to '
                'read the substrates yourself.'
            )
        ),
    ] = 'fast',
    substrates: Annotated[
        list[str] | None,
        Field(
            description=(
                'OpenRouter research vendor slugs to fan the question across, each '
                'run as its newest frontier model. Accepted: openai, google, '
                'anthropic, deepseek, perplexity, qwen, x-ai, meta-llama, mistralai. '
                'None uses the default Path B set: openai, deepseek, google.'
            )
        ),
    ] = None,
    primary: Annotated[
        str,
        Field(
            description=(
                'Which research brief the synthesis anchors on: "claude" or '
                '"openrouter:<slug>" (e.g. "openrouter:openai"). Empty string '
                'anchors on the first substrate.'
            )
        ),
    ] = '',
    journal: Annotated[
        bool,
        Field(
            description=(
                'Also emit a mantis-ingestion journal via a second synthesis turn '
                '(slower). Off by default.'
            )
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        Field(description='Validate orchestration without spending any model calls.'),
    ] = False,
    detach: Annotated[
        bool | None,
        Field(
            description=(
                'Start the run and return its identity immediately ("state": '
                '"running", "outputs_dir", "batch_name") instead of waiting for '
                'it. A run with local-seat turns takes many minutes and outlasts '
                'the time a client will hold one tool call open; poll '
                '`research_status` with the returned "outputs_dir", then call '
                '`research` again with `resume=<outputs_dir>` to collect the '
                'finished result. Leave it unset to choose by tier: a run whose '
                'tier uses the local Claude seat ("fast", "standard", "high") '
                'detaches, and a "research"-tier run or a dry run blocks and '
                'returns the result. Pass false to block on any tier, or true to '
                'detach any run. A resume of a finished run is a collect: it '
                'blocks and returns the result whatever this says. A resume of '
                'a failed run re-runs it, and a resume of a run whose sidecar '
                'failed retries the sidecar; both follow this setting.'
            )
        ),
    ] = None,
    name: Annotated[
        str,
        Field(
            description=(
                'An optional name for the run, used for its output directory. '
                'Without one the name is derived from the question, so several '
                'questions sharing a long common preamble read alike; you can '
                'also mark the key inline as "RESEARCH QUESTION (<key>)".'
            )
        ),
    ] = '',
    resume: Annotated[
        str,
        Field(
            description=(
                'Re-enter an interrupted run instead of starting a new one: pass '
                'its output directory (the "outputs_dir" of the run you lost, e.g. '
                '"outputs/research-my-question-20260811T101500Z"). Stages that '
                'already finished are skipped, and the question and settings come '
                'from that run\'s own record, so "question" is ignored. Pass a '
                "finished run's directory to collect its result: that call "
                'blocks whatever "detach" says. A failed run, or one with a stage '
                'that exited non-zero, is re-run from that stage instead, and a '
                'run whose sidecar failed has its sidecar retried; "detach" '
                'applies to either as to a new run.'
            )
        ),
    ] = '',
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Research a question across multiple models and return a cross-checked result.

    Runs OpenRouter research substrates plus a Claude synthesis, returning the run
    manifest (output paths, per-stage exit codes, cost) together with the epistemic
    sidecar's claims, cross-model divergences, and verification queue. The
    synthesis / falsification / evaluation / journal stages drive a local
    authenticated ``claude`` CLI (ADR-0009); research-only runs need only an
    ``OPENROUTER_API_KEY``. A plain call to a tier that uses that seat returns a
    handle first and the result on the collect call (see ``detach``).

    Parameters:
      - ``assurance`` (``research`` | ``fast`` | ``standard`` | ``high``) chooses
        depth. ``fast`` — research + synthesis — is the default and what most
        calls want; ``standard`` adds a falsification pass and ``high`` adds a
        Claude-prior baseline and an evaluation pass, as explicit escalations.
        ``research`` stops after the cross-model briefs and returns their paths
        and cost, with no synthesis and no sidecar: the tier for a caller with no
        local Claude seat, or one that wants to read the briefs itself.
      - ``substrates`` overrides the OpenRouter research vendors (slugs such as
        ``openai``, ``deepseek``, ``google``, ``anthropic``, ``qwen``, ``x-ai``,
        ``meta-llama``, ``mistralai``, ``perplexity``); each runs as its newest
        frontier model. ``None`` uses the default Path B set: openai, deepseek,
        google.
      - ``primary`` selects which research brief the synthesis anchors on —
        ``claude`` or ``openrouter:<slug>`` (e.g. ``openrouter:openai``); the empty
        default anchors on the first substrate.
      - ``journal`` also emits a mantis-ingestion journal via a second synthesis
        turn (slower); off by default.
      - ``name`` optionally names the run's output directory; without one the
        name is derived from the question.
      - ``dry_run`` validates orchestration without spending model calls.
      - ``resume`` re-enters an interrupted run by its output directory instead
        of starting a new one; completed stages are skipped and the question and
        settings are read from that run's own record. On a finished run it is
        the collect call, and returns the result.
      - ``detach`` returns the run's identity at once (``state``,
        ``outputs_dir``, ``batch_name``) instead of the result. Unset, it is
        chosen by tier: a run that uses the local Claude seat detaches, and a
        ``research``-tier run or a dry run blocks; pass ``false`` to block or
        ``true`` to detach. Research takes 5 to 10 min. Each local-seat turn after
        it takes about 7 min (median), and every run on the machine queues those
        turns on one seat; the turns per tier are ``fast`` 2, ``standard`` 3,
        ``high`` 5, plus 1 with ``journal``. A subagent, or any caller whose
        tool call can be cut off, keeps the detached default: poll
        ``research_status``, then collect with ``resume=<outputs_dir>``. A
        resume of a finished run blocks and returns the result whatever
        ``detach`` says. A resume of a failed or abandoned run, or of one with a
        stage that exited non-zero, re-runs those stages and follows ``detach``
        like a new run, and so does a resume of a run whose sidecar failed, which
        retries the sidecar.
    """
    # dispatch_stage_config nests asyncio.run per stage, so the synchronous
    # pipeline must run OFF this event loop or it raises RuntimeError (FM-1).
    # The progress channel is built on the loop, in `_blocking_call`: the worker
    # thread hands events back rather than touching the session directly.
    # Off the loop: on a resume the decision reads the run's record.
    if await asyncio.to_thread(
        _should_detach, detach, assurance=assurance, dry_run=dry_run, resume=resume
    ):
        return _detach(
            question,
            assurance=assurance,
            substrates=substrates,
            primary=primary,
            journal=journal,
            dry_run=dry_run,
            name=name,
            resume=resume,
        )
    return await _blocking_call(
        ctx,
        question,
        assurance=assurance,
        substrates=substrates,
        primary=primary,
        journal=journal,
        dry_run=dry_run,
        name=name,
        resume=resume,
    )


def build_server() -> MCPServer:
    """Construct the MCP server with the ``research`` tool registered."""
    server = MCPServer(_SERVER_NAME)
    server.tool()(research)
    server.tool()(research_status)
    return server

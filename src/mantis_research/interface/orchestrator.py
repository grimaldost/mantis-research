"""Generic per-topic-with-retries batch runner.

This is the only orchestration code in the project — every stage uses it,
no copy-paste. Responsibilities:

- Spawn per-topic tasks under a concurrency semaphore (asyncio.TaskGroup).
- Per-topic retry loop with rate-limit-aware backoff.
- Persist per-topic state (``state/<stage>/<id>.json``) on every transition.
- Periodic progress.json snapshot (legacy shape, for monitor scripts).
- Graceful SIGINT handling — stop scheduling new work, finish in-flight,
  exit clean.

A topic task NEVER propagates an exception. Internal try/except converts
crashes into ``AttemptResult.fail(...)`` so TaskGroup doesn't cancel siblings.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from mantis_research.core.progress import RunEvent, emit, progress_payload
from mantis_research.core.retry import RetryPolicy, resolve_failure_kind
from mantis_research.core.stage import AttemptResult, RunContext, Stage
from mantis_research.core.state import TopicState, TopicStatus
from mantis_research.interface.seat import process_is_alive

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mantis_research.core.config import BatchConfig, TopicConfig
    from mantis_research.core.progress import ProgressCallback

log = structlog.get_logger(__name__)

#: How often a long wait says it is still a wait. Also the granularity at which
#: a backoff notices the stop signal.
HEARTBEAT_SECONDS = 10.0


class Orchestrator:
    """Generic batch runner — instantiate with a Stage, call ``run()``.

    The orchestrator is single-use. Construct one per ``mantis run <stage>``
    invocation; do not reuse across batches.
    """

    def __init__(
        self,
        *,
        stage: Stage,
        state_class: type[TopicState],
        config: BatchConfig,
        state_dir: Path,
        output_dir: Path,
        transcript_dir: Path,
        parallel: int | None = None,
        dry_run: bool = False,
        on_event: ProgressCallback | None = None,
    ) -> None:
        self.stage = stage
        self.state_class = state_class
        self.config = config
        self.state_dir = state_dir
        self.output_dir = output_dir
        self.transcript_dir = transcript_dir
        self.dry_run = dry_run
        self.on_event = on_event
        self.parallel = parallel or config.runner.max_parallel_topics
        self.retry_policy = RetryPolicy(
            max_retries_per_stage=config.runner.max_retries_per_stage,
            rate_limit_backoff_minutes=config.runner.rate_limit_backoff_minutes,
            generic_failure_backoff_minutes=config.runner.generic_failure_backoff_minutes,
            caller_idle_budget_seconds=config.runner.caller_idle_budget_seconds,
        )

    # ── public entry point ──────────────────────────────────────

    async def run(
        self,
        *,
        only: Sequence[str] | None = None,
        force: bool = False,
    ) -> int:
        """Execute the batch. Returns 0 on full success, 1 if any failures."""
        topics = self._select_topics(only)
        if force:
            self._clear_state(topics)

        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._reap_abandoned(topics)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_dir.mkdir(parents=True, exist_ok=True)

        pending = [t for t in topics if self._is_pending(t)]
        log.info(
            'batch starting',
            stage=self.stage.name,
            batch_name=self.config.batch_name,
            topics_total=len(topics),
            topics_pending=len(pending),
            parallel=self.parallel,
            dry_run=self.dry_run,
        )

        if not pending:
            log.info('nothing to do — all topics already DONE', stage=self.stage.name)
            return 0

        ctx = RunContext(
            batch=self.config,
            state_dir=self.state_dir,
            output_dir=self.output_dir,
            transcript_dir=self.transcript_dir,
            dry_run=self.dry_run,
            on_event=self.on_event,
        )

        stop = asyncio.Event()
        self._install_signal_handlers(stop)

        sem = asyncio.Semaphore(self.parallel)
        progress_stop = asyncio.Event()
        progress_task = asyncio.create_task(
            self._run_progress_reporter(topics, progress_stop),
        )

        try:
            async with asyncio.TaskGroup() as tg:
                for topic in pending:
                    tg.create_task(self._run_topic(topic, ctx, sem, stop))
        finally:
            progress_stop.set()
            await progress_task

        return self._final_summary(topics)

    # ── per-topic task ──────────────────────────────────────────

    async def _run_topic(
        self,
        topic: TopicConfig,
        ctx: RunContext,
        sem: asyncio.Semaphore,
        stop: asyncio.Event,
    ) -> None:
        """One topic's full lifecycle. NEVER raises (catches all exceptions)."""
        bound = log.bind(stage=self.stage.name, topic_id=topic.id, slug=topic.slug)
        try:
            state = self.state_class.load_or_create(self.state_dir, topic.id, topic.slug)
            if state.settled:
                bound.debug('already DONE — skipping')
                return
            # This run now owns the record, so the record says which kind of run
            # is writing it. A real run clears a marker it inherits from a dry
            # run, which is how the dry run's DONE stops being load-bearing.
            state.dry_run = True if self.dry_run else None

            if not self.stage.is_enabled(topic, self.config):
                bound.info('stage disabled for this topic — skipping')
                return

            ready, reason = self.stage.upstream_ready(topic.id, topic.slug, ctx)
            if not ready:
                bound.warning('upstream not ready', reason=reason)
                state.mark_blocked(reason or 'upstream not ready')
                state.save(self.state_dir)
                return

            async with sem:
                await self._retry_loop(topic, state, ctx, stop, bound)

        except Exception:
            bound.exception('topic task crashed unexpectedly')

    async def _retry_loop(
        self,
        topic: TopicConfig,
        state: TopicState,
        ctx: RunContext,
        stop: asyncio.Event,
        bound: structlog.stdlib.BoundLogger,
    ) -> None:
        """Run attempts under the retry policy. Updates state on every step."""
        for attempt in range(1, self.retry_policy.max_retries_per_stage + 2):
            if stop.is_set():
                bound.info('stop signal — exiting attempt loop')
                return
            state.mark_in_flight(owner_pid=os.getpid())
            state.save(self.state_dir)

            try:
                result = await self.stage.run_attempt(topic, state, ctx)
            except Exception as e:
                result = AttemptResult.fail(error=f'unexpected: {e}')
                bound.exception('attempt raised unexpectedly', attempt=attempt)

            if result.success:
                state.mark_done()
                state.save(self.state_dir)
                bound.info('attempt succeeded', attempt=attempt, output_bytes=result.output_bytes)
                return

            kind = resolve_failure_kind(
                declared=result.failure_kind, error_output=result.error_output
            )
            error_msg = result.error or 'unknown failure'
            bound.info(
                'attempt failed',
                attempt=attempt,
                kind=kind.value,
                error=error_msg,
            )

            if self.retry_policy.is_final_attempt(attempt, kind):
                if kind.value == 'rate_limit':
                    state.mark_rate_limited(error_msg)
                else:
                    state.mark_failed(error_msg)
                state.save(self.state_dir)
                bound.warning('giving up after final attempt', attempts=attempt)
                return

            # Set transient state for the wait window, then back off.
            if kind.value == 'rate_limit':
                state.mark_rate_limited(error_msg)
            else:
                state.reset_for_retry(error_msg)
            # The next attempt mints its own session (MANT-B59).
            state.clear_session()
            state.save(self.state_dir)
            await self._stop_aware_sleep(
                self.retry_policy.backoff_seconds(kind),
                stop,
                on_event=self.on_event,
                data={
                    'stage': self.stage.name,
                    'topic_id': topic.id,
                    'kind': kind.value,
                    'attempt': attempt,
                },
            )

    @staticmethod
    async def _stop_aware_sleep(
        seconds: float,
        stop: asyncio.Event,
        *,
        on_event: ProgressCallback | None = None,
        data: dict[str, object] | None = None,
        chunk: float = HEARTBEAT_SECONDS,
    ) -> None:
        """Sleep ``seconds`` total, checking ``stop`` each chunk for early exit.

        A heartbeat goes out per chunk. A backoff is the longest a run is silent,
        and silence is what a caller reads as a hang — so the wait has to keep
        saying it is a wait. Without this, MANT-B02's cap is load-bearing rather
        than belt-and-braces.
        """
        slept = 0.0
        while slept < seconds:
            if stop.is_set():
                return
            remaining = seconds - slept
            emit(
                on_event,
                RunEvent(
                    kind='waiting',
                    message=f'backing off, {remaining:.0f}s remaining before the next attempt',
                    data={**(data or {}), 'remaining_s': round(remaining, 1)},
                ),
            )
            await asyncio.sleep(min(chunk, remaining))
            slept += chunk

    # ── progress reporter ──────────────────────────────────────

    async def _run_progress_reporter(
        self,
        topics: Sequence[TopicConfig],
        stop: asyncio.Event,
    ) -> None:
        """Write progress.json every 60s until ``stop`` is set."""
        while not stop.is_set():
            self._write_progress_snapshot(topics)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=60)
        self._write_progress_snapshot(topics)

    def _write_progress_snapshot(self, topics: Sequence[TopicConfig]) -> None:
        states = [self.state_class.load_or_create(self.state_dir, t.id, t.slug) for t in topics]
        payload = progress_payload(
            batch_name=self.config.batch_name,
            updated_at_iso=datetime.now(UTC).isoformat(),
            states=states,
        )
        path = self.state_dir / 'progress.json'
        path.write_text(json.dumps(payload, indent=2), encoding='utf-8')

    # ── helpers ─────────────────────────────────────────────────

    def _select_topics(self, only: Sequence[str] | None) -> list[TopicConfig]:
        if not only:
            return list(self.config.topics)
        wanted = set(only)
        return [t for t in self.config.topics if t.id in wanted]

    def _reap_abandoned(self, topics: Sequence[TopicConfig]) -> None:
        """Mark DEAD every topic left IN_FLIGHT by a process that is now gone.

        The owner's PID was written in when the topic went in flight, so a
        stranded topic is *detectable* rather than merely old — no guess about
        how long is too long. It stays re-attemptable (DEAD is not DONE); what
        changes is that the record says nobody is coming back, instead of
        claiming work is still under way.
        """
        me = os.getpid()
        for topic in topics:
            state = self.state_class.load_or_create(self.state_dir, topic.id, topic.slug)
            if state.status is not TopicStatus.IN_FLIGHT:
                continue
            pid = state.owner_pid
            if pid == me or (pid is not None and process_is_alive(pid)):
                continue
            reason = (
                f'owner pid {pid} is gone'
                if pid is not None
                else 'left in flight by an unknown owner'
            )
            log.warning(
                'reaping an abandoned topic',
                stage=self.stage.name,
                topic_id=topic.id,
                owner_pid=pid,
            )
            state.mark_dead(reason)
            state.save(self.state_dir)

    def _clear_state(self, topics: Sequence[TopicConfig]) -> None:
        for t in topics:
            sp = self.state_dir / f'{t.id}.json'
            if sp.exists():
                sp.unlink()
                log.info('cleared state', topic_id=t.id)

    def _is_pending(self, topic: TopicConfig) -> bool:
        state = self.state_class.load_or_create(self.state_dir, topic.id, topic.slug)
        return not state.settled

    def _final_summary(self, topics: Sequence[TopicConfig]) -> int:
        states = [self.state_class.load_or_create(self.state_dir, t.id, t.slug) for t in topics]
        counts: dict[str, int] = {}
        for s in states:
            counts[s.status.value] = counts.get(s.status.value, 0) + 1
        log.info('batch summary', stage=self.stage.name, **counts)
        failed = [
            s
            for s in states
            if s.status in (TopicStatus.FAILED, TopicStatus.RATE_LIMITED, TopicStatus.DEAD)
        ]
        if failed:
            ids = ' '.join(s.id for s in failed)
            log.warning(
                'topics requiring follow-up',
                ids=ids,
                resume_command=f'mantis run {self.stage.name} <config> --only {ids}',
            )
        # A blocked-upstream topic produced no output. In a live run that is a
        # failure the exit code must report: a downstream consumer (the agent
        # contract, spec 0002) must never see ok:true then find no synthesis.
        # A dry run legitimately produces no upstream artifacts (adapters
        # short-circuit), so a downstream block is expected there, not a failure.
        blocked = [s for s in states if s.status is TopicStatus.BLOCKED_UPSTREAM]
        blocked_is_failure = bool(blocked) and not self.dry_run
        if blocked_is_failure:
            ids = ' '.join(s.id for s in blocked)
            log.warning('topics blocked upstream — run the upstream stage first', ids=ids)
        if failed or blocked_is_failure:
            return 1
        return 0

    @staticmethod
    def _install_signal_handlers(stop: asyncio.Event) -> None:
        """Wire SIGINT to set ``stop`` (graceful shutdown).

        Only the process's main thread receives signals, and both wiring
        mechanisms below refuse outside it — ``signal.signal`` with ValueError,
        ``loop.add_signal_handler`` via ``set_wakeup_fd``. The MCP server runs
        the orchestrator on worker threads (``asyncio.to_thread``, the detach
        thread), so off the main thread there is nothing to wire: skip, rather
        than die on the refusal. Ctrl-C then reaches the server's own loop,
        which owns shutdown for every run it hosts.
        """
        if threading.current_thread() is not threading.main_thread():
            return
        loop = asyncio.get_running_loop()

        def _handler() -> None:
            log.info('SIGINT received — finishing in-flight, no new tasks')
            stop.set()

        if sys.platform == 'win32':
            # Windows asyncio doesn't support add_signal_handler.
            # signal.signal works for SIGINT but the handler can't touch the
            # event loop directly — use call_soon_threadsafe.
            # signal.signal only works in main thread; suppress non-main errors.
            with contextlib.suppress(ValueError, OSError):
                signal.signal(
                    signal.SIGINT,
                    lambda *_: loop.call_soon_threadsafe(_handler),
                )
        else:
            loop.add_signal_handler(signal.SIGINT, _handler)

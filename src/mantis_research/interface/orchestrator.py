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
import signal
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from mantis_research.core.progress import progress_payload
from mantis_research.core.retry import RetryPolicy, classify_failure
from mantis_research.core.stage import AttemptResult, RunContext, Stage
from mantis_research.core.state import TopicState, TopicStatus

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mantis_research.core.config import BatchConfig, TopicConfig

log = structlog.get_logger(__name__)


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
    ) -> None:
        self.stage = stage
        self.state_class = state_class
        self.config = config
        self.state_dir = state_dir
        self.output_dir = output_dir
        self.transcript_dir = transcript_dir
        self.dry_run = dry_run
        self.parallel = parallel or config.runner.max_parallel_topics
        self.retry_policy = RetryPolicy(
            max_retries_per_stage=config.runner.max_retries_per_stage,
            rate_limit_backoff_minutes=config.runner.rate_limit_backoff_minutes,
            generic_failure_backoff_minutes=config.runner.generic_failure_backoff_minutes,
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
            if state.status is TopicStatus.DONE:
                bound.debug('already DONE — skipping')
                return

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
            state.mark_in_flight()
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

            kind = classify_failure(result.error_output)
            error_msg = result.error or 'unknown failure'
            bound.info(
                'attempt failed',
                attempt=attempt,
                kind=kind.value,
                error=error_msg,
            )

            if self.retry_policy.is_final_attempt(attempt):
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
            state.save(self.state_dir)
            await self._stop_aware_sleep(self.retry_policy.backoff_seconds(kind), stop)

    @staticmethod
    async def _stop_aware_sleep(seconds: float, stop: asyncio.Event) -> None:
        """Sleep ``seconds`` total; check ``stop`` every 10s for early exit."""
        slept = 0.0
        chunk = 10.0
        while slept < seconds:
            if stop.is_set():
                return
            await asyncio.sleep(min(chunk, seconds - slept))
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

    def _clear_state(self, topics: Sequence[TopicConfig]) -> None:
        for t in topics:
            sp = self.state_dir / f'{t.id}.json'
            if sp.exists():
                sp.unlink()
                log.info('cleared state', topic_id=t.id)

    def _is_pending(self, topic: TopicConfig) -> bool:
        state = self.state_class.load_or_create(self.state_dir, topic.id, topic.slug)
        return state.status is not TopicStatus.DONE

    def _final_summary(self, topics: Sequence[TopicConfig]) -> int:
        states = [self.state_class.load_or_create(self.state_dir, t.id, t.slug) for t in topics]
        counts: dict[str, int] = {}
        for s in states:
            counts[s.status.value] = counts.get(s.status.value, 0) + 1
        log.info('batch summary', stage=self.stage.name, **counts)
        failed = [s for s in states if s.status in (TopicStatus.FAILED, TopicStatus.RATE_LIMITED)]
        if failed:
            ids = ' '.join(s.id for s in failed)
            log.warning(
                'topics requiring follow-up',
                ids=ids,
                resume_command=f'mantis run {self.stage.name} <config> --only {ids}',
            )
            return 1
        return 0

    @staticmethod
    def _install_signal_handlers(stop: asyncio.Event) -> None:
        """Wire SIGINT to set ``stop`` (graceful shutdown)."""
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

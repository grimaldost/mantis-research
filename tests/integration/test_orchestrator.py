"""Orchestrator integration tests against a fake Stage.

These tests exercise the retry loop, rate-limit detection, semaphore-based
concurrency limit, and final-summary logic without actually invoking any
external CLI or HTTP — a fake Stage controls success/failure modes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from mantis_research.core.config import BatchConfig, load_batch_config
from mantis_research.core.paths import run_state_dir
from mantis_research.core.stage import AttemptResult
from mantis_research.core.state import ClaudeResearchState, TopicStatus
from mantis_research.interface.orchestrator import Orchestrator

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import TopicConfig
    from mantis_research.core.stage import RunContext


# ── fake stage and helpers ───────────────────────────────────────────


@dataclass
class FakeStage:
    """Minimal Stage Protocol implementation. Driven by per-topic-id scripts."""

    name: str = 'claude'
    state_subdir: str = 'claude'
    output_subdir: str = 'claude'
    # results[topic_id] = list of AttemptResults (one per attempt, in order)
    results: dict[str, list[AttemptResult]] = field(default_factory=dict)
    upstream: dict[str, tuple[bool, str | None]] = field(default_factory=dict)
    enabled: dict[str, bool] = field(default_factory=dict)
    # invocation log — one entry per run_attempt call
    calls: list[str] = field(default_factory=list)

    def is_enabled(self, topic: TopicConfig, config: BatchConfig) -> bool:
        return self.enabled.get(topic.id, True)

    def upstream_ready(
        self,
        topic_id: str,
        slug: str,
        ctx: RunContext,
    ) -> tuple[bool, str | None]:
        return self.upstream.get(topic_id, (True, None))

    async def run_attempt(
        self,
        topic: TopicConfig,
        state: ClaudeResearchState,
        ctx: RunContext,
    ) -> AttemptResult:
        topic_id = topic.id
        self.calls.append(topic_id)
        scripted = self.results.get(topic_id)
        if not scripted:
            return AttemptResult.fail('no scripted result')
        # Pop the next result from the front (per-attempt scripting).
        return scripted.pop(0) if len(scripted) > 1 else scripted[0]


def _config_with_topics(topic_count: int = 3, **runner_overrides: object) -> BatchConfig:
    runner = {
        'max_parallel_topics': 2,
        'max_retries_per_stage': 2,
        'rate_limit_backoff_minutes': 0,  # 0 minutes → backoff is 0 in tests
        'generic_failure_backoff_minutes': 0,
        **runner_overrides,
    }
    cfg_dict = {
        'schema_version': 2,
        'batch_name': 'test-batch',
        'models': {'claude': {'model': 'claude-opus-4-7', 'effort': 'max'}},
        'runner': runner,
        'default_prompts': {},
        'topics': [
            {
                'id': str(i + 1),
                'slug': f'topic-{i + 1}',
                'title': f'Topic {i + 1}',
                'stages': {'claude': {'prompt': 'do work'}},
            }
            for i in range(topic_count)
        ],
    }
    return load_batch_config(cfg_dict)


def _make_orchestrator(
    stage: FakeStage,
    config: BatchConfig,
    tmp_path: Path,
    parallel: int | None = None,
) -> Orchestrator:
    return Orchestrator(
        stage=stage,
        state_class=ClaudeResearchState,
        config=config,
        state_dir=tmp_path / 'state',
        output_dir=tmp_path / 'outputs',
        transcript_dir=tmp_path / 'transcripts',
        parallel=parallel,
        dry_run=False,
    )


# ── tests ────────────────────────────────────────────────────────────


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_all_topics_succeed_first_attempt(self, tmp_path: Path) -> None:
        stage = FakeStage(
            results={
                '1': [AttemptResult.ok(output_bytes=1000)],
                '2': [AttemptResult.ok(output_bytes=2000)],
                '3': [AttemptResult.ok(output_bytes=3000)],
            }
        )
        config = _config_with_topics(3)
        orch = _make_orchestrator(stage, config, tmp_path)
        rc = await orch.run()

        assert rc == 0
        assert len(stage.calls) == 3
        for tid in ['1', '2', '3']:
            state = ClaudeResearchState.load_or_create(orch.state_dir, tid, f'topic-{tid}')
            assert state.status is TopicStatus.DONE
            assert state.attempts == 1
            assert state.last_error is None


class TestRetries:
    @pytest.mark.asyncio
    async def test_retry_then_success(self, tmp_path: Path) -> None:
        stage = FakeStage(
            results={
                '1': [
                    AttemptResult.fail('transient 500', error_output='Internal error'),
                    AttemptResult.ok(output_bytes=500),
                ],
            }
        )
        config = _config_with_topics(1)
        orch = _make_orchestrator(stage, config, tmp_path)
        rc = await orch.run()

        assert rc == 0
        state = ClaudeResearchState.load_or_create(orch.state_dir, '1', 'topic-1')
        assert state.status is TopicStatus.DONE
        assert state.attempts == 2

    @pytest.mark.asyncio
    async def test_exhaust_retries_marks_failed(self, tmp_path: Path) -> None:
        stage = FakeStage(
            results={
                '1': [
                    AttemptResult.fail('err 1'),
                    AttemptResult.fail('err 2'),
                    AttemptResult.fail('err 3 — final'),
                ],
            }
        )
        config = _config_with_topics(1)  # max_retries = 2 → 3 total attempts
        orch = _make_orchestrator(stage, config, tmp_path)
        rc = await orch.run()

        assert rc == 1  # any failure → exit code 1
        state = ClaudeResearchState.load_or_create(orch.state_dir, '1', 'topic-1')
        assert state.status is TopicStatus.FAILED
        assert state.attempts == 3
        assert state.last_error == 'err 3 — final'


class TestRateLimitClassification:
    @pytest.mark.asyncio
    async def test_rate_limit_marks_state_correctly(self, tmp_path: Path) -> None:
        stage = FakeStage(
            results={
                '1': [
                    AttemptResult.fail(
                        'quota',
                        error_output='Error 429: rate limit exceeded',
                    ),
                ]
                * 3,
            }
        )
        config = _config_with_topics(1)
        orch = _make_orchestrator(stage, config, tmp_path)
        rc = await orch.run()

        assert rc == 1
        state = ClaudeResearchState.load_or_create(orch.state_dir, '1', 'topic-1')
        assert state.status is TopicStatus.RATE_LIMITED


class TestUpstreamGate:
    @pytest.mark.asyncio
    async def test_blocked_upstream_skips_attempts(self, tmp_path: Path) -> None:
        stage = FakeStage(upstream={'1': (False, 'missing claude brief')})
        config = _config_with_topics(1)
        orch = _make_orchestrator(stage, config, tmp_path)
        rc = await orch.run()

        assert rc == 0  # blocked is not a failure
        state = ClaudeResearchState.load_or_create(orch.state_dir, '1', 'topic-1')
        assert state.status is TopicStatus.BLOCKED_UPSTREAM
        assert state.last_error == 'missing claude brief'
        assert stage.calls == []  # never called run_attempt


class TestStageDisabled:
    @pytest.mark.asyncio
    async def test_disabled_stage_skips_topic(self, tmp_path: Path) -> None:
        stage = FakeStage(enabled={'2': False})
        # topic 2 disabled; topics 1 and 3 succeed
        stage.results = {
            '1': [AttemptResult.ok()],
            '3': [AttemptResult.ok()],
        }
        config = _config_with_topics(3)
        orch = _make_orchestrator(stage, config, tmp_path)
        rc = await orch.run()

        assert rc == 0
        # Topic 2 stays at PENDING (skip leaves state untouched in this design).
        # Topics 1 and 3 are DONE.
        state2 = ClaudeResearchState.load_or_create(orch.state_dir, '2', 'topic-2')
        assert state2.status is TopicStatus.PENDING
        assert '2' not in stage.calls


class TestForceFlag:
    @pytest.mark.asyncio
    async def test_force_clears_existing_state(self, tmp_path: Path) -> None:
        stage = FakeStage(
            results={
                '1': [AttemptResult.ok()],
                '2': [AttemptResult.ok()],
            }
        )
        config = _config_with_topics(2)
        orch = _make_orchestrator(stage, config, tmp_path)
        # Pre-create a DONE state for topic 1 — without --force, would be skipped.
        orch.state_dir.mkdir(parents=True, exist_ok=True)
        prior = ClaudeResearchState(id='1', slug='topic-1', status=TopicStatus.DONE)
        prior.save(orch.state_dir)

        # Without force: topic 1 skipped.
        await orch.run()
        assert '1' not in stage.calls

        # With force: topic 1 runs.
        stage.calls.clear()
        await orch.run(force=True)
        assert '1' in stage.calls


class TestCrossRunResume:
    """Cross-run selection rule (spec 0001 §3): only DONE is skipped; every
    other prior status is re-attempted on a fresh invocation. This is what
    makes a batch resumable and is the reason there is no cross-run 'terminal'
    state other than DONE (the deleted ``is_terminal`` claimed otherwise)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'prior_status',
        [
            TopicStatus.FAILED,
            TopicStatus.RATE_LIMITED,
            TopicStatus.IN_FLIGHT,
        ],
    )
    async def test_non_done_prior_status_is_reattempted(
        self, tmp_path: Path, prior_status: TopicStatus
    ) -> None:
        stage = FakeStage(results={'1': [AttemptResult.ok()]})
        config = _config_with_topics(1)
        orch = _make_orchestrator(stage, config, tmp_path)
        orch.state_dir.mkdir(parents=True, exist_ok=True)
        ClaudeResearchState(id='1', slug='topic-1', status=prior_status).save(orch.state_dir)

        await orch.run()

        # Re-attempted (not skipped) and now DONE.
        assert '1' in stage.calls
        final = ClaudeResearchState.load_or_create(orch.state_dir, '1', 'topic-1')
        assert final.status is TopicStatus.DONE

    @pytest.mark.asyncio
    async def test_done_prior_status_is_skipped(self, tmp_path: Path) -> None:
        stage = FakeStage(results={'1': [AttemptResult.ok()]})
        config = _config_with_topics(1)
        orch = _make_orchestrator(stage, config, tmp_path)
        orch.state_dir.mkdir(parents=True, exist_ok=True)
        ClaudeResearchState(id='1', slug='topic-1', status=TopicStatus.DONE).save(orch.state_dir)

        await orch.run()

        assert stage.calls == []  # DONE is the only cross-run skip


class TestBatchLayout:
    """Spec 0001 §11: a run under batch layout writes its state and progress.json
    beneath state/<batch>/<stage>/. The orchestrator honors the batch-scoped
    state dir it is handed (dispatch resolves it via run_state_dir in §18)."""

    @pytest.mark.asyncio
    async def test_state_and_progress_land_under_batch_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Redirect state_root so the batch resolver points into tmp, then use
        # the real resolver to build the state dir — proving the composition.
        monkeypatch.setattr('mantis_research.core.paths.state_root', lambda: tmp_path / 'state')
        state_dir = run_state_dir('batch', 'mybatch', 'claude')
        assert state_dir == tmp_path / 'state' / 'mybatch' / 'claude'

        stage = FakeStage(results={'1': [AttemptResult.ok()]})
        config = _config_with_topics(1)
        orch = Orchestrator(
            stage=stage,
            state_class=ClaudeResearchState,
            config=config,
            state_dir=state_dir,
            output_dir=tmp_path / 'outputs' / 'mybatch' / 'claude',
            transcript_dir=tmp_path / 'transcripts' / 'mybatch',
            dry_run=False,
        )
        await orch.run()

        assert (state_dir / '1.json').exists()
        assert (state_dir / 'progress.json').exists()


class TestOnlyFlag:
    @pytest.mark.asyncio
    async def test_only_filters_topics(self, tmp_path: Path) -> None:
        stage = FakeStage(
            results={
                '1': [AttemptResult.ok()],
                '2': [AttemptResult.ok()],
                '3': [AttemptResult.ok()],
            }
        )
        config = _config_with_topics(3)
        orch = _make_orchestrator(stage, config, tmp_path)
        await orch.run(only=['2'])

        assert stage.calls == ['2']


class TestProgressJson:
    @pytest.mark.asyncio
    async def test_progress_snapshot_written_at_end(self, tmp_path: Path) -> None:
        stage = FakeStage(results={'1': [AttemptResult.ok()]})
        config = _config_with_topics(1)
        orch = _make_orchestrator(stage, config, tmp_path)
        await orch.run()

        prog = orch.state_dir / 'progress.json'
        assert prog.exists()
        import json

        data = json.loads(prog.read_text(encoding='utf-8'))
        assert data['batch_name'] == 'test-batch'
        assert data['total_topics'] == 1
        assert data['counts'] == {'done': 1}


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_semaphore_caps_concurrent_attempts(self, tmp_path: Path) -> None:
        # Slow stage — block long enough that concurrency bound is observable.
        peak = 0

        class CountingStage(FakeStage):
            current_in_flight: int = 0

            async def run_attempt(  # type: ignore[override]
                self,
                topic: TopicConfig,
                state: ClaudeResearchState,
                ctx: RunContext,
            ) -> AttemptResult:
                nonlocal peak
                self.calls.append(topic.id)
                self.current_in_flight += 1
                peak = max(peak, self.current_in_flight)
                await asyncio.sleep(0.02)
                self.current_in_flight -= 1
                return AttemptResult.ok()

        stage = CountingStage()
        config = _config_with_topics(6)
        orch = _make_orchestrator(stage, config, tmp_path, parallel=3)
        await orch.run()

        # Peak concurrency must be ≤ parallel cap.
        assert peak <= 3

"""Unit tests for mantis_research.core.state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mantis_research.core.state import (
    ClaudeResearchState,
    EvaluationState,
    FalsificationState,
    GeminiResearchState,
    JournalPassesState,
    OpenRouterResearchState,
    SubsessionResult,
    SynthesisState,
    TopicState,
    TopicStatus,
)


class TestTopicStatus:
    def test_string_values_match_legacy(self) -> None:
        # These string values are written to disk; changing them breaks resume.
        assert TopicStatus.PENDING.value == 'pending'
        assert TopicStatus.IN_FLIGHT.value == 'in_flight'
        assert TopicStatus.DONE.value == 'done'
        assert TopicStatus.FAILED.value == 'failed'
        assert TopicStatus.RATE_LIMITED.value == 'rate_limited'
        assert TopicStatus.BLOCKED_UPSTREAM.value == 'blocked_upstream'


class TestTopicStateRoundTrip:
    def test_save_and_load_idempotent(self, tmp_state_dir: Path) -> None:
        s = ClaudeResearchState(
            id='1',
            slug='c4-structurizr-adrs',
            status=TopicStatus.DONE,
            attempts=1,
            session_id='abc-123',
            turn_1_duration_s=1093.0,
            research_file_bytes=85_504,
            started_at='2026-05-01T20:00:00+00:00',
            completed_at='2026-05-01T20:18:13+00:00',
        )
        s.save(tmp_state_dir)
        loaded = ClaudeResearchState.load_or_create(tmp_state_dir, '1', 'c4-structurizr-adrs')
        assert loaded == s

    def test_load_or_create_creates_when_missing(self, tmp_state_dir: Path) -> None:
        s = ClaudeResearchState.load_or_create(tmp_state_dir, '99', 'fresh-slug')
        assert s.id == '99'
        assert s.slug == 'fresh-slug'
        assert s.status is TopicStatus.PENDING
        assert s.attempts == 0
        assert s.session_id is None

    def test_status_serialized_as_string_value(self, tmp_state_dir: Path) -> None:
        # On-disk JSON must use the lowercase string values, not enum repr.
        s = SynthesisState(id='5', slug='iso-20022', status=TopicStatus.RATE_LIMITED)
        s.save(tmp_state_dir)
        raw = json.loads((tmp_state_dir / '5.json').read_text(encoding='utf-8'))
        assert raw['status'] == 'rate_limited'

    def test_legacy_claude_state_shape_loads(self, tmp_state_dir: Path) -> None:
        # Bit-equivalent shape from existing batch-10 state/1.json on disk.
        legacy = {
            'id': '1',
            'slug': 'c4-structurizr-adrs',
            'status': 'done',
            'attempts': 1,
            'session_id': '710aa78c-1234-4abc-9def-012345678901',
            'started_at': '2026-05-01T23:43:48.000000+00:00',
            'completed_at': '2026-05-02T00:01:21.000000+00:00',
            'last_error': None,
            'turn_1_duration_s': 1093.4,
            'research_file_bytes': 87_654,
        }
        (tmp_state_dir / '1.json').write_text(json.dumps(legacy), encoding='utf-8')
        loaded = ClaudeResearchState.load_or_create(tmp_state_dir, '1', 'c4-structurizr-adrs')
        assert loaded.status is TopicStatus.DONE
        assert loaded.research_file_bytes == 87_654
        assert loaded.turn_1_duration_s == pytest.approx(1093.4)

    def test_gemini_subsessions_round_trip(self, tmp_state_dir: Path) -> None:
        s = GeminiResearchState(
            id='3',
            slug='slo-burn-rate',
            status=TopicStatus.DONE,
            attempts=1,
            subsessions=[
                SubsessionResult(
                    subslug='single',
                    status='done',
                    duration_s=112.97,
                    output_bytes=2810,
                    output_path='C:/path/to/3-slo-burn-rate.md',
                ),
            ],
        )
        s.save(tmp_state_dir)
        loaded = GeminiResearchState.load_or_create(tmp_state_dir, '3', 'slo-burn-rate')
        assert len(loaded.subsessions) == 1
        assert loaded.subsessions[0].subslug == 'single'
        assert loaded.subsessions[0].output_bytes == 2810

    @pytest.mark.parametrize(
        'cls',
        [
            ClaudeResearchState,
            GeminiResearchState,
            OpenRouterResearchState,
            SynthesisState,
            JournalPassesState,
            FalsificationState,
            EvaluationState,
        ],
    )
    def test_every_stage_state_round_trips(
        self, tmp_state_dir: Path, cls: type[TopicState]
    ) -> None:
        s = cls(id='42', slug='fake-slug', status=TopicStatus.PENDING)
        s.save(tmp_state_dir)
        loaded = cls.load_or_create(tmp_state_dir, '42', 'fake-slug')
        assert loaded.id == '42'
        assert loaded.slug == 'fake-slug'
        assert loaded.status is TopicStatus.PENDING


class TestAtomicSave:
    """``save`` writes via a temp file + replace so a crash can't truncate an
    existing state file (resumability, I5)."""

    def test_save_leaves_no_temp_file(self, tmp_state_dir: Path) -> None:
        ClaudeResearchState(id='1', slug='t', status=TopicStatus.DONE).save(tmp_state_dir)
        assert (tmp_state_dir / '1.json').exists()
        assert not (tmp_state_dir / '1.json.tmp').exists()

    def test_failed_replace_preserves_existing_state(
        self, tmp_state_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_state_dir / '1.json'
        ClaudeResearchState(id='1', slug='t', status=TopicStatus.DONE).save(tmp_state_dir)
        good = path.read_text(encoding='utf-8')

        def boom(self: Path, target: Path) -> None:
            raise OSError('simulated crash during replace')

        monkeypatch.setattr(Path, 'replace', boom)
        with pytest.raises(OSError, match='simulated crash'):
            ClaudeResearchState(id='1', slug='t', status=TopicStatus.FAILED).save(tmp_state_dir)
        # The prior DONE file is intact and still parses — not truncated.
        assert path.read_text(encoding='utf-8') == good
        assert (
            ClaudeResearchState.load_or_create(tmp_state_dir, '1', 't').status is TopicStatus.DONE
        )


class TestTopicStateTransitions:
    def test_mark_in_flight_increments_attempts_and_sets_started_at(self) -> None:
        s = ClaudeResearchState(id='1', slug='x')
        s.mark_in_flight()
        assert s.status is TopicStatus.IN_FLIGHT
        assert s.attempts == 1
        assert s.started_at is not None

    def test_mark_done_clears_last_error(self) -> None:
        s = ClaudeResearchState(id='1', slug='x', last_error='prior failure')
        s.mark_done()
        assert s.status is TopicStatus.DONE
        assert s.last_error is None
        assert s.completed_at is not None

    def test_mark_failed_records_error(self) -> None:
        s = ClaudeResearchState(id='1', slug='x')
        s.mark_failed('exit code 1')
        assert s.status is TopicStatus.FAILED
        assert s.last_error == 'exit code 1'

    def test_reset_for_retry_returns_to_pending(self) -> None:
        s = ClaudeResearchState(id='1', slug='x', status=TopicStatus.IN_FLIGHT, attempts=1)
        s.reset_for_retry('transient 500')
        assert s.status is TopicStatus.PENDING
        assert s.last_error == 'transient 500'
        assert s.attempts == 1  # attempt count is preserved across the retry

    def test_consecutive_attempts_increment_correctly(self) -> None:
        s = ClaudeResearchState(id='1', slug='x')
        s.mark_in_flight()
        s.mark_in_flight()
        s.mark_in_flight()
        assert s.attempts == 3


class TestStateInvariantsHypothesis:
    """Property-based tests — hypothesis generates many (id, slug) pairs."""

    # NOTE: hypothesis @given does not interleave with pytest fixtures, so we
    # construct a temp directory inside the test using tempfile rather than
    # taking tmp_path as a fixture argument.

    @given(
        topic_id=st.text(alphabet='0123456789', min_size=1, max_size=3),
        slug=st.from_regex(r'[a-z][a-z0-9-]{1,30}', fullmatch=True),
    )
    def test_save_load_invariant(self, topic_id: str, slug: str) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            s = ClaudeResearchState(id=topic_id, slug=slug)
            s.save(state_dir)
            loaded = ClaudeResearchState.load_or_create(state_dir, topic_id, slug)
            assert loaded.id == topic_id
            assert loaded.slug == slug

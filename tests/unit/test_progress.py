"""Unit tests for mantis_research.core.progress."""

from __future__ import annotations

import pytest

from mantis_research.core.progress import count_by_status, progress_payload, seat_start_range
from mantis_research.core.state import (
    ClaudeResearchState,
    SynthesisState,
    TopicStatus,
)


class TestCountByStatus:
    def test_aggregates_counts(self) -> None:
        states = [
            ClaudeResearchState(id='1', slug='a', status=TopicStatus.DONE),
            ClaudeResearchState(id='2', slug='b', status=TopicStatus.DONE),
            ClaudeResearchState(id='3', slug='c', status=TopicStatus.PENDING),
            ClaudeResearchState(id='4', slug='d', status=TopicStatus.RATE_LIMITED),
        ]
        counts = count_by_status(states)
        assert counts == {'done': 2, 'pending': 1, 'rate_limited': 1}

    def test_empty(self) -> None:
        assert count_by_status([]) == {}

    def test_uses_string_values_for_keys(self) -> None:
        # Keys must be the lowercase legacy strings (not enum names).
        s = ClaudeResearchState(id='1', slug='a', status=TopicStatus.IN_FLIGHT)
        counts = count_by_status([s])
        assert 'in_flight' in counts
        assert 'IN_FLIGHT' not in counts


class TestProgressPayloadShape:
    def test_legacy_progress_json_shape(self) -> None:
        states = [
            ClaudeResearchState(id='1', slug='a', status=TopicStatus.DONE, attempts=1),
            SynthesisState(id='2', slug='b', status=TopicStatus.PENDING),
        ]
        payload = progress_payload(
            batch_name='batch-X',
            updated_at_iso='2026-05-03T00:00:00+00:00',
            states=states,
        )
        # All five keys per the legacy progress.json shape.
        assert set(payload.keys()) == {
            'batch_name',
            'updated_at',
            'total_topics',
            'counts',
            'topics',
        }
        assert payload['batch_name'] == 'batch-X'
        assert payload['total_topics'] == 2
        assert payload['counts'] == {'done': 1, 'pending': 1}
        assert len(payload['topics']) == 2
        # Each topic in the payload preserves its full state shape.
        ids = {t['id'] for t in payload['topics']}
        assert ids == {'1', '2'}

    def test_total_topics_matches_states_length(self) -> None:
        states = [ClaudeResearchState(id=str(i), slug=f's{i}') for i in range(5)]
        payload = progress_payload(batch_name='x', updated_at_iso='', states=states)
        assert payload['total_topics'] == 5


class TestSeatStartRange:
    """When a run queued for the local seat can expect to take it (T1f).

    The early bound assumes this run is taken next; the late bound assumes every
    other waiter goes first. Both lean on the median measured seat turn, and the
    lock has no order, so a range is all that can honestly be promised.
    """

    def test_known_numbers(self) -> None:
        # Two waiting (this run and one other), the holder 60 s into a 300 s turn.
        assert seat_start_range(2, 60.0, 300.0) == (240.0, 540.0)

    def test_alone_in_the_queue_the_bounds_meet(self) -> None:
        assert seat_start_range(1, 100.0, 300.0) == (200.0, 200.0)

    def test_a_holder_past_the_median_could_finish_now(self) -> None:
        assert seat_start_range(3, 400.0, 300.0) == (0.0, 600.0)

    def test_a_free_seat_starts_the_next_waiter_now(self) -> None:
        assert seat_start_range(2, None, 300.0) == (0.0, 300.0)

    def test_nobody_waiting_is_treated_as_this_run_alone(self) -> None:
        assert seat_start_range(0, 60.0, 300.0) == (240.0, 240.0)

    def test_no_measured_turn_means_no_range(self) -> None:
        assert seat_start_range(2, 60.0, None) is None

    @pytest.mark.parametrize('waiting', [1, 2, 5])
    def test_the_late_bound_never_precedes_the_early_one(self, waiting: int) -> None:
        span = seat_start_range(waiting, 10.0, 120.0)
        assert span is not None
        assert span[0] <= span[1]

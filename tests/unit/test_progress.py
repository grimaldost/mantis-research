"""Unit tests for mantis_research.core.progress."""

from __future__ import annotations

from mantis_research.core.progress import count_by_status, progress_payload
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

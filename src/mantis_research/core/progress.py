"""Pure progress aggregation — given a list of states, compute counts.

The orchestrator persists progress.json (legacy shape, for monitor scripts)
based on what these functions produce. The functions are pure: no I/O,
deterministic, easy to test.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mantis_research.core.state import TopicState


def count_by_status(states: list[TopicState]) -> dict[str, int]:
    """Aggregate ``state.status`` values to counts.

    Returns a dict like ``{'done': 3, 'pending': 7}`` (only non-zero entries).
    Status keys are the lowercase string values of ``TopicStatus``, matching
    the legacy on-disk progress.json shape.
    """
    return dict(Counter(s.status.value for s in states))


def progress_payload(
    *,
    batch_name: str,
    updated_at_iso: str,
    states: list[TopicState],
) -> dict[str, Any]:
    """Build the progress.json dict (legacy shape, matches all 5 runners)."""
    return {
        'batch_name': batch_name,
        'updated_at': updated_at_iso,
        'total_topics': len(states),
        'counts': count_by_status(states),
        'topics': [s.model_dump(mode='json') for s in states],
    }

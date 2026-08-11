"""Pure progress aggregation and the run-event vocabulary.

Two things live here, both pure:

- ``count_by_status`` / ``progress_payload`` — the aggregation the orchestrator
  persists as ``progress.json`` for monitor scripts.
- ``RunEvent`` and ``ProgressCallback`` — the vocabulary a run uses to tell a
  watching caller what it is doing right now. A long run that says nothing is
  indistinguishable from a hang, and the caller's response to a hang is to give
  up. The events are data; who delivers them (the MCP progress channel, stderr,
  nobody) is the caller's business.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

    from mantis_research.core.state import TopicState

#: What a run reports. ``run_named`` comes first and always, before anything is
#: dispatched, so an interrupted call still leaves an identified run behind.
RunEventKind = Literal[
    'run_named',
    'stage_start',
    'stage_done',
    'waiting',
    'run_done',
]


@dataclass(frozen=True, slots=True)
class RunEvent:
    """One legible moment in a run.

    ``message`` is the human-readable line; ``step`` / ``total`` place the run on
    a scale when there is one; ``data`` carries the machine-readable payload
    (run identity, stage name, exit code, seconds remaining in a backoff).
    """

    kind: RunEventKind
    message: str
    step: int | None = None
    total: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


#: A caller-supplied sink for :class:`RunEvent`. Synchronous and best-effort —
#: a run must never fail because its audience stopped listening. Declared with
#: ``type`` so the annotation stays lazy and ``Callable`` need not be imported
#: at runtime.
type ProgressCallback = Callable[[RunEvent], None]


def emit(callback: ProgressCallback | None, event: RunEvent) -> None:
    """Deliver ``event`` to ``callback`` if there is one. Never raises."""
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        # A broken listener must not fail the run: the events are courtesy, the
        # research is the job.
        return


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

"""Parse the Claude CLI's ``stream-json`` envelope — pure, no I/O (I1).

The CLI emits NDJSON under ``--output-format stream-json --verbose``: one JSON
object per line while the turn runs, and a final ``{"type": "result"}`` carrying
the answer text, an error flag, the session id and the turn's dollar cost. Lines
that are not JSON also occur — the CLI prints its stdin warning and hard
authentication failures as plain text.

Separating *what the CLI said* from *how the CLI said it* is the point of this
module, not a convenience. The rate-limit classifier matches the substring
``rate_limit``, and the envelope emits ``{"type": "rate_limit_event"}`` on
perfectly healthy runs to report remaining quota. Handing the raw stream to that
classifier would read every successful run as rate-limited and back off for it,
so :attr:`StreamSummary.prose` carries only the human-readable half.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

#: The envelope line that closes a turn.
_RESULT = 'result'


class OutputCadence(StrEnum):
    """When a spawned child produces output — the fact a watchdog depends on.

    A watchdog on silence can only tell a wedged child from a working one if a
    working child says something while it works. Under ``TERMINAL`` it cannot:
    the child is mute by design until the turn ends, so the "silence" clock is
    really a cap on total runtime, and it fires on healthy work.
    """

    #: The child emits lines as it goes; silence is evidence.
    STREAMING = 'streaming'
    #: The child emits only when finished; silence is the normal case.
    TERMINAL = 'terminal'

    def validate_watchdog(self, idle_timeout_s: float | None) -> None:
        """Refuse a silence watchdog over a child that is silent by design.

        This is the coupling MANT-B58 exists to make unrepresentable. The two
        settings lived on the same dataclass and nothing related them, so the
        format could be chosen for how the answer reads while the timeout was
        chosen for how long a turn may stall — and the pair silently became a
        runtime cap that killed 28% of historically successful stages.
        """
        if self is OutputCadence.TERMINAL and idle_timeout_s is not None:
            msg = (
                f'a {idle_timeout_s:.0f}s watchdog on silence is meaningless over a '
                f'{self.value}-cadence child: it emits nothing until the turn ends, so '
                f'the clock measures total runtime and kills work that is merely long. '
                f'Use a streaming output format, or set no idle timeout.'
            )
            raise ValueError(msg)


class ClaudeOutputFormat(StrEnum):
    """``claude -p --output-format`` values, and how each one behaves.

    The enum exists so the cadence travels *with* the format instead of being
    remembered separately. ``STREAM_JSON`` additionally requires ``--verbose``:
    the CLI refuses the combination without it.
    """

    TEXT = 'text'
    STREAM_JSON = 'stream-json'

    @property
    def cadence(self) -> OutputCadence:
        """Whether a child using this format speaks while it works."""
        return (
            OutputCadence.STREAMING
            if self is ClaudeOutputFormat.STREAM_JSON
            else OutputCadence.TERMINAL
        )

    @property
    def needs_verbose(self) -> bool:
        """True when the CLI refuses this format unless ``--verbose`` is passed."""
        return self is ClaudeOutputFormat.STREAM_JSON


@dataclass(frozen=True, slots=True)
class StreamSummary:
    """What one ``stream-json`` turn reported.

    ``prose`` is the text a human (or the failure classifier) should read: the
    CLI's own message plus any non-JSON lines. Every other field comes off the
    final result line, and is ``None`` when the child died before emitting one —
    which is exactly what a watchdog kill leaves behind.
    """

    prose: str
    result_text: str | None = None
    is_error: bool = False
    cost_usd: float | None = None
    session_id: str | None = None
    duration_ms: int | None = None


def parse_stream(output: str) -> StreamSummary:
    """Summarise a merged stdout+stderr ``stream-json`` stream.

    Never raises: a killed child leaves a truncated object on the pipe, and a
    parser that fails on it would convert a diagnosable stage failure into an
    exception from the reporting path.
    """
    prose_parts: list[str] = []
    result: dict[str, Any] | None = None

    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        obj = _as_envelope(line)
        if obj is None:
            # Not the envelope — the CLI talking to a human. Hard failures
            # ("API Error: 401 …") arrive this way and must reach the classifier.
            prose_parts.append(line)
            continue
        if obj.get('type') == _RESULT:
            result = obj

    if result is not None:
        text = result.get(_RESULT)
        if isinstance(text, str) and text:
            prose_parts.append(text)

    return StreamSummary(
        prose='\n'.join(prose_parts),
        result_text=_str_or_none(result, _RESULT),
        is_error=bool(result.get('is_error', False)) if result else False,
        cost_usd=_float_or_none(result, 'total_cost_usd'),
        session_id=_str_or_none(result, 'session_id'),
        duration_ms=_int_or_none(result, 'duration_ms'),
    )


def _as_envelope(line: str) -> dict[str, Any] | None:
    """Return the line's JSON object, or None if it is not one.

    A bare JSON scalar (``42``) parses but is not an envelope; it is something
    the CLI printed, so it belongs in the prose.
    """
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _str_or_none(obj: dict[str, Any] | None, key: str) -> str | None:
    value = obj.get(key) if obj else None
    return value if isinstance(value, str) else None


def _float_or_none(obj: dict[str, Any] | None, key: str) -> float | None:
    value = obj.get(key) if obj else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int_or_none(obj: dict[str, Any] | None, key: str) -> int | None:
    value = obj.get(key) if obj else None
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

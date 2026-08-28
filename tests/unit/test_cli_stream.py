"""Parsing the Claude CLI's stream-json envelope (MANT-B58).

The stream is NDJSON: one JSON object per line, a final ``{"type": "result"}``
carrying the answer, the error flag and the turn's cost. A line can also be
plain text — the CLI prints a stdin warning and hard failures that way.

The load-bearing case is :func:`prose`. The envelope's own vocabulary contains
``rate_limit_event`` on *successful* runs, and the rate-limit classifier matches
the substring ``rate_limit``. Feeding it the raw stream would classify every run
as rate-limited and back off for it, so the parser separates what the CLI said
from how the CLI said it.
"""

from __future__ import annotations

import json

import pytest

from mantis_research.core.cli_stream import (
    ClaudeOutputFormat,
    OutputCadence,
    parse_stream,
)

_SESSION = '94d4d6ef-6cd0-42be-b377-cb253601d3d8'


def _result_line(**over: object) -> str:
    payload: dict[str, object] = {
        'type': 'result',
        'subtype': 'success',
        'result': 'the synthesis is written',
        'is_error': False,
        'total_cost_usd': 0.0256435,
        'session_id': _SESSION,
        'duration_ms': 9440,
        'num_turns': 1,
    }
    payload.update(over)
    return json.dumps(payload)


def _healthy_stream() -> str:
    return '\n'.join(
        [
            json.dumps({'type': 'system', 'subtype': 'init', 'session_id': _SESSION}),
            json.dumps({'type': 'system', 'subtype': 'thinking_tokens', 'estimated_tokens': 43}),
            json.dumps({'type': 'assistant', 'message': {'role': 'assistant'}}),
            json.dumps({'type': 'rate_limit_event', 'rate_limit_info': {'status': 'allowed'}}),
            _result_line(),
        ]
    )


class TestTheResultLine:
    def test_the_answer_text_comes_off_the_result_line(self) -> None:
        assert parse_stream(_healthy_stream()).result_text == 'the synthesis is written'

    def test_the_cost_of_the_turn_is_recovered(self) -> None:
        # Local-seat spend was invisible to the manifest before this: the seat
        # is a subscription, so nothing metered it per run.
        assert parse_stream(_healthy_stream()).cost_usd == 0.0256435

    def test_the_session_id_is_recovered(self) -> None:
        assert parse_stream(_healthy_stream()).session_id == _SESSION

    def test_an_error_result_is_flagged(self) -> None:
        summary = parse_stream(_result_line(is_error=True, result='API Error: 401'))
        assert summary.is_error is True

    def test_a_stream_with_no_result_line_yields_no_answer(self) -> None:
        # What a watchdog kill leaves behind: the child died mid-stream.
        partial = json.dumps({'type': 'system', 'subtype': 'init'})
        summary = parse_stream(partial)
        assert summary.result_text is None
        assert summary.cost_usd is None


class TestProse:
    """What the classifier is allowed to see."""

    def test_the_envelopes_own_vocabulary_is_not_prose(self) -> None:
        # `rate_limit_event` rides along on healthy runs. If it reached
        # `classify_failure` every run would read as rate-limited and wait.
        assert 'rate_limit' not in parse_stream(_healthy_stream()).prose

    def test_what_the_cli_said_is_prose(self) -> None:
        summary = parse_stream(_result_line(is_error=True, result='you have hit your limit'))
        assert 'you have hit your limit' in summary.prose

    def test_a_non_json_line_is_prose(self) -> None:
        # Hard failures and the stdin warning arrive as plain text.
        stream = 'Failed to authenticate. API Error: 401 OAuth token expired\n' + _result_line()
        assert 'API Error: 401' in parse_stream(stream).prose

    def test_a_blank_stream_yields_blank_prose(self) -> None:
        assert parse_stream('').prose == ''


class TestTolerance:
    def test_a_truncated_final_line_does_not_raise(self) -> None:
        # A killed child can leave half a JSON object on the pipe.
        summary = parse_stream(_healthy_stream() + '\n{"type": "resu')
        assert summary.result_text == 'the synthesis is written'

    def test_a_bare_json_scalar_is_treated_as_prose_not_an_envelope(self) -> None:
        assert '42' in parse_stream('42').prose


class TestTheWatchdogCoupling:
    """A clock on silence is only a clock on silence if the child speaks.

    MANT-B58's actual defect: ``--output-format text`` emits nothing until the
    turn ends, so a 600 s "silence" watchdog was a 600 s cap on total runtime —
    below the real duration of 66 of the 237 local-seat stages this tool has
    completed. The two facts were configured independently and drifted; the
    coupling is now checked where the pair is constructed.
    """

    def test_a_silence_watchdog_over_a_mute_child_is_refused(self) -> None:
        with pytest.raises(ValueError, match='silence'):
            OutputCadence.TERMINAL.validate_watchdog(600.0)

    def test_a_mute_child_with_no_watchdog_is_allowed(self) -> None:
        # Legitimate: no watchdog means no false claim about what it measures.
        OutputCadence.TERMINAL.validate_watchdog(None)

    def test_a_streaming_child_may_carry_a_watchdog(self) -> None:
        OutputCadence.STREAMING.validate_watchdog(600.0)

    def test_stream_json_streams_and_text_does_not(self) -> None:
        assert ClaudeOutputFormat.STREAM_JSON.cadence is OutputCadence.STREAMING
        assert ClaudeOutputFormat.TEXT.cadence is OutputCadence.TERMINAL

"""The local-seat precondition, checked before anything is dispatched.

The synthesis family drives the machine's single authenticated ``claude`` CLI
(ADR-0009, local-first). Nothing checked that seat until the synthesis stage
reached its own preflight — which is *after* the OpenRouter research stage has
run and been paid for. A run whose seat was unusable therefore bought its briefs
and then had nowhere to take them, which is exactly the shape of the field
failure of 2026-08-11: three runs whose briefs are on disk and whose
``synth-turn1`` transcripts end ``Failed to authenticate. API Error: 401 OAuth
access token has expired`` at ``Exit code: 1``.

The precondition is checked once, up front, for the whole tier, and names itself
when it fails. The probe is a Protocol (``SeatProbe``, ``core/stage.py``) so the
check is testable without a Claude seat — invariant I3's seam, used for what it
is for.
"""

from __future__ import annotations

import pytest

from mantis_research.interface.research_service import (
    LocalSeatUnavailableError,
    require_local_claude_seat,
)


class _FakeSeat:
    """A Protocol-typed stand-in for ``ClaudeCliAdapter``'s seat probe."""

    def __init__(self, failure: str | None = None) -> None:
        self.failure = failure
        self.calls = 0

    def preflight(self) -> None:
        self.calls += 1
        if self.failure is not None:
            raise RuntimeError(self.failure)


class TestWhenTheSeatIsChecked:
    def test_a_tier_with_a_claude_cli_stage_probes_the_seat(self) -> None:
        probe = _FakeSeat()
        require_local_claude_seat(stages=['openrouter', 'synthesis'], probe=probe)
        assert probe.calls == 1

    def test_a_tier_with_no_claude_cli_stage_does_not_probe(self) -> None:
        # Research-only work needs an OpenRouter key and nothing else; making it
        # depend on a Claude seat would refuse runs that can genuinely proceed.
        probe = _FakeSeat()
        require_local_claude_seat(stages=['openrouter'], probe=probe)
        assert probe.calls == 0

    def test_every_claude_cli_stage_counts(self) -> None:
        for stage in ('synthesis', 'falsification', 'evaluation', 'claude-prior'):
            probe = _FakeSeat()
            require_local_claude_seat(stages=[stage], probe=probe)
            assert probe.calls == 1, f'{stage} drives the CLI but did not probe the seat'


class TestWhatTheRefusalSays:
    def test_an_unusable_seat_raises_a_named_error(self) -> None:
        probe = _FakeSeat(failure='claude auth status failed — run `claude auth login`')
        with pytest.raises(LocalSeatUnavailableError) as caught:
            require_local_claude_seat(stages=['openrouter', 'synthesis'], probe=probe)
        message = str(caught.value)
        # The precondition, by name — a caller must be able to act on this
        # without reading the source.
        assert 'claude' in message
        # The stages that need it, so the reader knows what will not happen.
        assert 'synthesis' in message
        # The probe's own diagnosis, not swallowed.
        assert 'claude auth login' in message

    def test_the_underlying_failure_is_chained(self) -> None:
        probe = _FakeSeat(failure='claude CLI not found')
        with pytest.raises(LocalSeatUnavailableError) as caught:
            require_local_claude_seat(stages=['synthesis'], probe=probe)
        assert isinstance(caught.value.__cause__, RuntimeError)

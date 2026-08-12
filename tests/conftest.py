"""Pytest fixtures shared across the test suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_structlog() -> None:
    """Send structlog nowhere unless a test says otherwise.

    ``configure_logging`` binds a ``PrintLogger`` to whatever stdout was current
    when it ran; pytest's capture replaces stdout per test, so a logger bound in
    one test writes to a closed file in the next. Resetting per test keeps that
    coupling out of unrelated tests.
    """
    structlog.reset_defaults()
    structlog.configure(logger_factory=structlog.ReturnLoggerFactory())


@pytest.fixture(autouse=True)
def _no_live_seat_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite off the machine's real Claude seat.

    ``run_research`` checks the local-seat precondition before it dispatches
    anything, which spawns ``claude --version`` and ``claude auth status``. That
    is the point in production and unacceptable in a test: it would make the
    result depend on whether this machine happens to hold an authenticated seat.
    Tests that are *about* the precondition patch it back, or call
    ``require_local_claude_seat`` directly with a fake probe (the ``SeatProbe``
    Protocol exists for that).
    """
    monkeypatch.setattr(
        'mantis_research.interface.research_service.require_local_claude_seat',
        lambda **_: None,
    )


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Path:
    """Return a temp directory suitable for state/<id>.json round-trip tests."""
    state = tmp_path / 'state'
    state.mkdir()
    return state

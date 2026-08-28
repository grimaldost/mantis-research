"""Pytest fixtures shared across the test suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog

from tests.hermetic import refuse_http, refuse_spawn, spawn_seams

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


@pytest.fixture(autouse=True)
def _no_live_provider(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse the seams where a test could spend real money (MANT-B65).

    Three rings, each at the point of spend rather than at its callers:

    1. No API key, so a path that slips the other two fails on preflight rather
       than authenticating.
    2. No HTTP send. ``httpx.Client.send`` is the single funnel every request
       method reaches, so patching it covers ``get``/``post``/streaming alike
       without the tests having to know which one a caller used.
    3. No child spawn — for the Claude runner and, separately, for the Gemini
       adapter's own inlined copy of the loop.

    A test that is *about* a seam requests ``allow_child_spawn``; the list of
    modules that legitimately do is pinned in :mod:`tests.hermetic`.
    """
    monkeypatch.setenv('OPENROUTER_API_KEY', '')
    monkeypatch.setattr('httpx.Client.send', refuse_http)
    monkeypatch.setattr('httpx.AsyncClient.send', refuse_http)
    if 'allow_child_spawn' in request.fixturenames:
        return
    for seam in spawn_seams():
        monkeypatch.setattr(seam, refuse_spawn)


@pytest.fixture
def allow_child_spawn() -> None:
    """Opt out of the spawn ring, for the tests that are about spawning.

    Requesting it is the whole mechanism — ``_no_live_provider`` checks for the
    name and leaves the seams alone. These tests still never reach the real
    binary: they pass an explicit fake argv.
    """
    return


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Path:
    """Return a temp directory suitable for state/<id>.json round-trip tests."""
    state = tmp_path / 'state'
    state.mkdir()
    return state

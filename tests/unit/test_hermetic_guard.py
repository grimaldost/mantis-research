"""The hermetic floor refuses live providers, and its holes are enumerated.

MANT-B65. A green suite that concealed a real, paid, eight-minute production
run is a gate that cannot fail; these tests are what make the gate able to.
"""

from __future__ import annotations

import httpx
import pytest

from tests.hermetic import SPAWN_OPT_IN, LiveProviderReachedError


def test_the_guard_refuses_a_live_http_send() -> None:
    with pytest.raises(LiveProviderReachedError):
        httpx.Client().get('https://openrouter.ai/api/v1/models')


@pytest.mark.asyncio
async def test_the_guard_refuses_a_child_spawn() -> None:
    from mantis_research.interface.adapters import claude_cli

    with pytest.raises(LiveProviderReachedError):
        await claude_cli.run_streaming(['claude', '-p', 'hello'], None)


def test_the_guard_is_not_catchable_by_the_orchestrators_handlers() -> None:
    """The orchestrator catches ``Exception`` twice on the attempt path.

    A guard it can catch does not fail the suite — it turns a hermeticity
    breach into three retries and a capped backoff, which reads as slowness.
    """
    assert not issubclass(LiveProviderReachedError, Exception)
    assert issubclass(LiveProviderReachedError, BaseException)


def test_the_spawn_opt_in_list_is_exactly_the_tests_about_spawning() -> None:
    """Every opt-in is a hole. Pin the list so a fourth is a deliberate act."""
    expected = {
        'tests/unit/test_child_watchdog.py',
        'tests/unit/test_claude_cli_adapter.py',
        'tests/unit/test_local_seat_precondition.py',
    }
    assert expected == SPAWN_OPT_IN

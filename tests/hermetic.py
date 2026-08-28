"""The hermetic floor: no test may reach a live provider (MANT-B65).

A test that reaches OpenRouter or the machine's Claude seat spends real money
and makes the suite's verdict depend on the machine it ran on. One did: a test
called ``run_research(dry_run=False)`` with the dispatch seam unpatched, fanned
out to three substrates plus a real synthesis turn, and the suite stayed green
because nothing in the harness could tell a hermetic test from a paid one.

The guard refuses at the two seams where money is actually spent — the HTTP
send and the child spawn — rather than at the callers, so a new caller is
covered the day it is written instead of the day someone remembers to list it.

``LiveProviderReachedError`` derives from :class:`BaseException` on purpose.
``Orchestrator._run_topic`` and its attempt loop both catch ``Exception``; an
``Exception``-derived guard would be swallowed into a failed attempt and three
capped backoffs, so the suite would go slow rather than loud.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Test modules allowed to drive a real spawn seam, and why. These pass an
#: explicit fake binary (``/fake/claude``) or ``sys.executable``; they are the
#: tests *about* the spawn, so the guard is the thing they are testing around.
#: Keep this list short — every entry is a hole, and an entry that stops being
#: needed should be removed rather than left as cover.
SPAWN_OPT_IN: Final[frozenset[str]] = frozenset(
    {
        'tests/unit/test_child_watchdog.py',
        'tests/unit/test_claude_cli_adapter.py',
        'tests/unit/test_local_seat_precondition.py',
    }
)


class LiveProviderReachedError(BaseException):
    """A test reached a live provider. Never raised in production.

    BaseException, not Exception: the orchestrator catches ``Exception`` twice
    on the attempt path, and a guard it can catch is a guard that turns a
    hermeticity breach into a retry loop.
    """


def refuse_http(*_args: Any, **_kwargs: Any) -> Any:
    """Stand in for an httpx send. Accepts any signature and always refuses."""
    msg = (
        'a test reached the network. Patch the seam under test, or pass a '
        'transport the test owns — the suite must not depend on a live provider.'
    )
    raise LiveProviderReachedError(msg)


async def refuse_spawn(*args: Any, **_kwargs: Any) -> Any:
    """Stand in for a child spawn. Accepts any signature and always refuses.

    Deliberately ``*args, **kwargs``: the streaming runner's signature is
    changing across this wave, and a guard that has to be kept in step with it
    is a guard that fails open on the day it is not.
    """
    cmd = args[0] if args else '<unknown>'
    msg = (
        f'a test spawned a child process ({cmd!r}). Drive the adapter through '
        f'its Protocol seam with a fake, or request the `allow_child_spawn` '
        f'fixture if this test is about the spawn itself.'
    )
    raise LiveProviderReachedError(msg)


def spawn_seams() -> Iterator[str]:
    """The attributes through which a child process is actually spawned.

    Patched by name where each module *looks the function up*, not where it is
    defined — rebinding the definition would leave every ``from … import``
    reference pointing at the original.

    There are two, not one: the Gemini adapter carries its own inlined copy of
    the streaming loop (``_run_streaming_with_env``, for the OAuth path's env
    and cwd quirks) which never passes through the shared runner. That copy is
    also the one with no watchdog — the same drift this wave is closing, in the
    adapter nobody looked at.
    """
    yield 'mantis_research.interface.adapters.claude_cli.run_streaming'
    yield ('mantis_research.interface.adapters.gemini_cli.GeminiCliAdapter._run_streaming_with_env')

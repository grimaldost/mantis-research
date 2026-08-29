"""Signal wiring must be a no-op off the main thread (the MCP path).

unix accepts ``loop.add_signal_handler`` only on the process's main thread,
and the MCP server runs every research call on a worker thread — the exact
combination the first ubuntu CI leg caught dying at dispatch. Windows refuses
the same wiring through ``signal.signal``'s own main-thread check. Both arms
must skip, because there is nothing to wire where signals never arrive.
"""

from __future__ import annotations

import asyncio
import signal
import threading

from mantis_research.interface.orchestrator import Orchestrator


def test_install_signal_handlers_off_main_thread_is_a_no_op() -> None:
    errors: list[Exception] = []
    before = signal.getsignal(signal.SIGINT)

    def work() -> None:
        async def go() -> None:
            Orchestrator._install_signal_handlers(asyncio.Event())

        try:
            asyncio.run(go())
        except Exception as exc:  # the assertion is that nothing escapes
            errors.append(exc)

    thread = threading.Thread(target=work, name='signal-probe')
    thread.start()
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert errors == []
    # The early return leaves the process's SIGINT disposition untouched.
    assert signal.getsignal(signal.SIGINT) is before

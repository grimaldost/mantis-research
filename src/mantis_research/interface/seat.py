"""Liveness for the single local Claude seat (backlog MANT-B08).

Three things live here, all I/O and therefore all outside ``core/`` (I1):

- :func:`process_is_alive` — is the process that claimed something still there?
- :func:`seat_lock` / :func:`async_seat_lock` — an explicit, PID-stamped lock
  on the one local Claude CLI seat, so concurrent runs serialise visibly
  instead of interleaving invisibly.
- :func:`seat_queue` — who holds the seat and how many runs wait for it, read
  from the tickets waiters leave beside the lock.

The shape is deliberately the one the sibling series engine already uses rather
than a second design: the owner's PID goes **into** the lock file and is read
back, so a lock left behind by a dead owner is *detectable* rather than merely
old. A lock whose only evidence is its age can only be resolved by guessing how
long is too long, and every such guess is wrong for someone.

``os.kill(pid, 0)`` is not the liveness test on Windows — any signal other than
``CTRL_C_EVENT`` / ``CTRL_BREAK_EVENT`` there calls ``TerminateProcess``, so the
POSIX idiom would kill the process it was asked about. The Windows branch asks
the kernel instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from mantis_research.core.progress import RunEvent, emit

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from mantis_research.core.progress import ProgressCallback

log = structlog.get_logger(__name__)

#: Windows: STILL_ACTIVE, the exit code a running process reports.
_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def process_is_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` is currently running.

    Never signals the process. An invalid pid (``<= 0``) is not alive.
    """
    if pid <= 0:
        return False
    if sys.platform == 'win32':
        return _win32_process_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists; we are simply not allowed to signal it.
        return True
    return True


def _win32_process_is_alive(pid: int) -> bool:
    if sys.platform != 'win32':
        # The one call site guards on platform already; this narrows the type
        # checker's view too, so `ctypes.windll` (Windows-only in typeshed)
        # resolves on every checking platform, not just Windows.
        raise RuntimeError('Windows-only helper called off-Windows')
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            # The handle opened, so the object exists; treat an unreadable exit
            # code as alive rather than reclaiming a seat we cannot vouch for.
            return True
        return exit_code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


@dataclass(frozen=True, slots=True)
class SeatHolder:
    """Who a lock file says holds the seat."""

    pid: int
    owner: str
    acquired_at: str

    @classmethod
    def read(cls, path: Path) -> SeatHolder | None:
        """Read the holder record, or None if it is absent or unreadable.

        An unreadable record is treated as no record: a half-written lock file
        is a crash artifact, and refusing to proceed on one would strand the
        seat exactly when a crash already cost a run.
        """
        try:
            raw: dict[str, Any] = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        try:
            return cls(pid=int(raw['pid']), owner=str(raw['owner']), acquired_at=str(raw['at']))
        except (KeyError, TypeError, ValueError):
            return None

    def is_alive(self) -> bool:
        return process_is_alive(self.pid)


def _try_acquire(
    path: Path,
    owner: str,
    *,
    on_event: ProgressCallback | None,
) -> SeatHolder | None:
    """One non-blocking attempt at the seat. None means a live owner holds it.

    Reclaims the lock in place when its recorded PID is gone or its record is
    unreadable, so the next attempt succeeds.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder = SeatHolder.read(path)
        if holder is None or not holder.is_alive():
            log.warning(
                'reclaiming the local seat from a dead owner',
                lock=str(path),
                dead_owner=holder.owner if holder else None,
                dead_pid=holder.pid if holder else None,
            )
            with contextlib.suppress(OSError):
                path.unlink()
            return None
        # Say it on both channels: structlog reaches the stderr an operator or a
        # detached caller reads, the run event reaches an MCP client. Queueing
        # for the seat is fine; queueing silently is what made concurrent
        # sibling runs look like hangs.
        log.info('waiting for the local Claude seat', held_by=holder.owner, holder_pid=holder.pid)
        emit(
            on_event,
            RunEvent(
                kind='waiting',
                message=f'waiting for the local Claude seat, held by {holder.owner}',
                data={'seat_owner': holder.owner, 'seat_pid': holder.pid},
            ),
        )
        return None
    mine = SeatHolder(pid=os.getpid(), owner=owner, acquired_at=_now_iso())
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump({'pid': mine.pid, 'owner': mine.owner, 'at': mine.acquired_at}, fh)
    return mine


def _waiters_dir(path: Path) -> Path:
    """Where the runs queued on the lock at ``path`` leave their tickets."""
    return path.with_name(f'{path.name}.waiters')


def _tickets(path: Path) -> list[tuple[Path, int]]:
    """Each ticket beside the lock at ``path`` with the pid its name carries."""
    found: list[tuple[Path, int]] = []
    for ticket in sorted(_waiters_dir(path).glob('*.json')):
        pid_text, _, _ = ticket.stem.partition('-')
        try:
            found.append((ticket, int(pid_text)))
        except ValueError:
            continue
    return found


def _clear_dead_tickets(path: Path) -> None:
    """Remove the tickets of waiters that died without dropping theirs, best-effort."""
    for ticket, pid in _tickets(path):
        if not process_is_alive(pid):
            with contextlib.suppress(OSError):
                ticket.unlink()


def _take_ticket(path: Path, owner: str) -> Path | None:
    """Say on disk that ``owner`` is waiting for the seat; None if that failed.

    The file name carries the pid, so a reader can tell a live waiter from one
    that died without reading the body, which may still be half written. The
    token keeps two waiters in one process apart. Best-effort: a ticket feeds
    an estimate, and failing to write one must not stop the wait.
    Joining also clears the tickets of waiters that have died.
    """
    _clear_dead_tickets(path)
    waiters = _waiters_dir(path)
    ticket = waiters / f'{os.getpid()}-{secrets.token_hex(4)}.json'
    try:
        waiters.mkdir(parents=True, exist_ok=True)
        ticket.write_text(
            json.dumps({'pid': os.getpid(), 'owner': owner, 'since': _now_iso()}),
            encoding='utf-8',
        )
    except OSError as exc:
        log.debug('could not write a seat waiter ticket', ticket=str(ticket), error=str(exc))
        return None
    return ticket


def _drop_ticket(ticket: Path | None) -> None:
    if ticket is not None:
        with contextlib.suppress(OSError):
            ticket.unlink()


def _acquired(on_event: ProgressCallback | None, mine: SeatHolder) -> None:
    emit(
        on_event,
        RunEvent(
            kind='seat_acquired',
            message=f'took the local Claude seat as {mine.owner}',
            data={'seat_owner': mine.owner, 'seat_pid': mine.pid},
        ),
    )


@dataclass(frozen=True, slots=True)
class SeatQueue:
    """The seat as a waiter sees it: who holds it and who else is waiting.

    There is no position. The lock is an ``O_EXCL`` file that every waiter
    polls, so whichever polls first after a release takes it.
    """

    waiting: int
    holder: str | None
    holder_since: str | None
    owners: tuple[str, ...]


def seat_queue(path: Path) -> SeatQueue:
    """Read the seat at ``path``: its live holder and its live waiters.

    A ticket counts only while the pid in its name is a live process. A ticket
    whose pid is gone was left by a waiter that died without its ``finally``
    running; it is skipped here and left on disk, because this is what a status
    poll reads and a poll must not change what it reads. A waiter clears those
    tickets when it joins the queue (:func:`_take_ticket`). A pid the operating
    system has since handed to another process reads as live, so such a ticket
    stays counted until that process ends.
    """
    holder = SeatHolder.read(path)
    if holder is not None and not holder.is_alive():
        holder = None
    owners: list[str] = []
    for ticket, pid in _tickets(path):
        if not process_is_alive(pid):
            continue
        try:
            owner = str(json.loads(ticket.read_text(encoding='utf-8')).get('owner', ''))
        except (OSError, ValueError, AttributeError):
            # Mid-write, or unreadable: the waiter is alive all the same.
            owner = ''
        owners.append(owner)
    return SeatQueue(
        waiting=len(owners),
        holder=holder.owner if holder else None,
        holder_since=holder.acquired_at if holder else None,
        owners=tuple(owners),
    )


def _held_by_a_live_owner(path: Path) -> bool:
    holder = SeatHolder.read(path)
    return holder is not None and holder.is_alive()


def _release(path: Path, mine: SeatHolder) -> None:
    # Only drop the lock if it is still ours — a reclaim by another run means we
    # already lost it, and deleting it then would strand theirs.
    current = SeatHolder.read(path)
    if current is not None and current.pid == mine.pid and current.owner == mine.owner:
        with contextlib.suppress(OSError):
            path.unlink()


@contextlib.contextmanager
def seat_lock(
    path: Path,
    owner: str,
    *,
    poll_seconds: float = 5.0,
    on_event: ProgressCallback | None = None,
) -> Iterator[SeatHolder]:
    """Hold the local Claude seat for the duration of the block (synchronous).

    Blocks while a *live* owner holds it, saying so on every poll — waiting for
    a seat is legitimate, waiting silently is the thing this whole area is about.
    A lock whose recorded PID is gone is reclaimed immediately and loudly.

    While it waits, the caller holds a ticket beside the lock
    (:func:`seat_queue` counts them). The ticket goes when the wait ends,
    whether the seat was taken or the wait was given up.
    """
    ticket: Path | None = None
    try:
        while True:
            mine = _try_acquire(path, owner, on_event=on_event)
            if mine is not None:
                break
            if _held_by_a_live_owner(path):
                ticket = ticket or _take_ticket(path, owner)
                time.sleep(poll_seconds)
    finally:
        _drop_ticket(ticket)
    _acquired(on_event, mine)
    try:
        yield mine
    finally:
        _release(path, mine)


@contextlib.asynccontextmanager
async def async_seat_lock(
    path: Path,
    owner: str,
    *,
    poll_seconds: float = 5.0,
    on_event: ProgressCallback | None = None,
) -> AsyncIterator[SeatHolder]:
    """:func:`seat_lock` for an adapter running on the event loop.

    Same contract, ticket included; the wait yields to the loop instead of
    blocking it, so the progress reporter and sibling topics keep running while
    this call queues.
    """
    ticket: Path | None = None
    try:
        while True:
            mine = _try_acquire(path, owner, on_event=on_event)
            if mine is not None:
                break
            if _held_by_a_live_owner(path):
                ticket = ticket or _take_ticket(path, owner)
                await asyncio.sleep(poll_seconds)
    finally:
        _drop_ticket(ticket)
    _acquired(on_event, mine)
    try:
        yield mine
    finally:
        _release(path, mine)


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()

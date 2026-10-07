"""The local-seat liveness contract (backlog MANT-B08).

No timeout, kill or wait-for existed on the main CLI spawn, so a child
producing zero output left the run `in_flight` with `last_error: null`
indefinitely: three synthesis children produced nothing for 75+ minutes,
falsification children then spawned against a synthesis artifact that was never
written and hung identically, and all six were killed by hand. Separately, the
single local seat had no lock, so concurrent sibling agents serialised
invisibly.

The lock's shape is the sibling engine's — the owner's PID is written in and
read back — so a lock left by a dead owner is detectable rather than merely old.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from mantis_research.core.state import SynthesisState, TopicStatus
from mantis_research.interface.seat import (
    SeatHolder,
    async_seat_lock,
    process_is_alive,
    seat_lock,
    seat_queue,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.progress import RunEvent


def _exited_pid() -> int:
    """A pid we know is dead, because we watched the process exit."""
    proc = subprocess.Popen([sys.executable, '-c', ''])
    proc.wait()
    return proc.pid


class TestProcessLiveness:
    def test_this_process_is_alive(self) -> None:
        assert process_is_alive(os.getpid()) is True

    def test_an_exited_process_is_not_alive(self) -> None:
        assert process_is_alive(_exited_pid()) is False

    @pytest.mark.parametrize('pid', [0, -1])
    def test_invalid_pids_are_not_alive(self, pid: int) -> None:
        assert process_is_alive(pid) is False

    def test_liveness_never_signals_the_process(self) -> None:
        # os.kill(pid, 0) on Windows calls TerminateProcess: the POSIX idiom
        # would kill the process it was asked about. Ask, then check it lived.
        proc = subprocess.Popen(
            [sys.executable, '-c', 'import sys; sys.stdin.read()'],
            stdin=subprocess.PIPE,
        )
        try:
            assert process_is_alive(proc.pid) is True
            assert proc.poll() is None, 'the liveness check killed the process'
        finally:
            proc.kill()
            proc.wait()


class TestDeadIsNotFailed:
    """The status vocabulary has to distinguish the two.

    A watchdog kill and an abandoned run are different facts: one means an
    attempt ran and lost, the other means nobody is coming back. Collapsing
    them sends you to debug a prompt when you should just re-run.
    """

    def test_dead_is_its_own_status(self) -> None:
        state = SynthesisState(id='1', slug='t')
        state.mark_in_flight(owner_pid=4242)
        assert state.owner_pid == 4242
        state.mark_dead('owner pid 4242 is gone')
        assert state.status is TopicStatus.DEAD
        assert state.status is not TopicStatus.FAILED
        assert state.last_error == 'owner pid 4242 is gone'
        assert state.owner_pid is None

    def test_dead_is_not_done_so_it_is_re_attempted(self) -> None:
        # Resumability (I5): DEAD is terminal for the *attempt*, not for the run.
        state = SynthesisState(id='1', slug='t')
        state.mark_dead('owner gone')
        assert state.status is not TopicStatus.DONE

    def test_owner_pid_survives_a_state_round_trip(self, tmp_path: Path) -> None:
        state = SynthesisState(id='1', slug='t')
        state.mark_in_flight(owner_pid=os.getpid())
        state.save(tmp_path)
        assert SynthesisState.load_or_create(tmp_path, '1', 't').owner_pid == os.getpid()

    def test_a_historical_state_file_without_owner_pid_still_loads(self, tmp_path: Path) -> None:
        # I4/I6: every state file written before this field existed.
        (tmp_path / '1.json').write_text(
            json.dumps({'id': '1', 'slug': 't', 'status': 'in_flight'}), encoding='utf-8'
        )
        assert SynthesisState.load_or_create(tmp_path, '1', 't').owner_pid is None


class TestSeatLock:
    def test_lock_records_the_owner_pid(self, tmp_path: Path) -> None:
        lock = tmp_path / 'seat.lock'
        with seat_lock(lock, owner='b/synthesis') as held:
            record = json.loads(lock.read_text(encoding='utf-8'))
            assert record['pid'] == os.getpid() == held.pid
            assert record['owner'] == 'b/synthesis'
            assert record['at']

    def test_lock_is_released_on_exit(self, tmp_path: Path) -> None:
        lock = tmp_path / 'seat.lock'
        with seat_lock(lock, owner='b/synthesis'):
            pass
        assert not lock.exists()

    def test_lock_is_released_when_the_body_raises(self, tmp_path: Path) -> None:
        lock = tmp_path / 'seat.lock'
        with pytest.raises(RuntimeError), seat_lock(lock, owner='b/synthesis'):
            raise RuntimeError('boom')
        assert not lock.exists()

    def test_a_lock_left_by_a_dead_owner_is_reclaimed(self, tmp_path: Path) -> None:
        # This is the whole point of writing the pid in: the lock is stale
        # because its owner is gone, not because it is old.
        lock = tmp_path / 'seat.lock'
        lock.write_text(
            json.dumps({'pid': _exited_pid(), 'owner': 'crashed-run/synthesis', 'at': 'earlier'}),
            encoding='utf-8',
        )
        with seat_lock(lock, owner='b/synthesis') as held:
            assert held.pid == os.getpid()
            assert json.loads(lock.read_text(encoding='utf-8'))['owner'] == 'b/synthesis'

    def test_an_unreadable_lock_is_reclaimed(self, tmp_path: Path) -> None:
        # A half-written lock file is a crash artifact; refusing to proceed on
        # one would strand the seat exactly when a crash already cost a run.
        lock = tmp_path / 'seat.lock'
        lock.write_text('{not json', encoding='utf-8')
        with seat_lock(lock, owner='b/synthesis') as held:
            assert held.owner == 'b/synthesis'

    def test_a_live_owner_makes_the_waiter_wait_and_say_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock = tmp_path / 'seat.lock'
        lock.write_text(
            json.dumps({'pid': os.getpid(), 'owner': 'sibling-run/synthesis', 'at': 'now'}),
            encoding='utf-8',
        )
        events: list[str] = []
        polls = {'n': 0}

        def fake_sleep(_: float) -> None:
            polls['n'] += 1
            if polls['n'] >= 2:  # the live holder finally finishes
                lock.unlink()

        monkeypatch.setattr('mantis_research.interface.seat.time.sleep', fake_sleep)
        with seat_lock(
            lock,
            owner='b/synthesis',
            poll_seconds=0.0,
            on_event=lambda e: events.append(e.message),
        ):
            pass
        assert polls['n'] == 2
        assert any('sibling-run/synthesis' in m for m in events)

    def test_release_does_not_steal_a_lock_someone_else_now_holds(self, tmp_path: Path) -> None:
        lock = tmp_path / 'seat.lock'
        with seat_lock(lock, owner='b/synthesis'):
            lock.write_text(
                json.dumps({'pid': os.getpid(), 'owner': 'other-run/synthesis', 'at': 'now'}),
                encoding='utf-8',
            )
        assert lock.exists()
        assert SeatHolder.read(lock).owner == 'other-run/synthesis'  # type: ignore[union-attr]


def _waiters(lock: Path) -> Path:
    """Where the tickets of the runs queued on ``lock`` live."""
    return lock.with_name(f'{lock.name}.waiters')


def _tickets(lock: Path) -> list[dict[str, object]]:
    return [
        json.loads(p.read_text(encoding='utf-8')) for p in sorted(_waiters(lock).glob('*.json'))
    ]


def _hold(lock: Path, owner: str = 'holder-run/synthesis:1', at: str = 'now') -> None:
    """Stamp ``lock`` as held by this test's own, live process."""
    lock.write_text(json.dumps({'pid': os.getpid(), 'owner': owner, 'at': at}), encoding='utf-8')


def _ticket(lock: Path, *, pid: int, owner: str, token: str) -> Path:
    waiters = _waiters(lock)
    waiters.mkdir(parents=True, exist_ok=True)
    path = waiters / f'{pid}-{token}.json'
    path.write_text(json.dumps({'pid': pid, 'owner': owner, 'since': 'earlier'}), encoding='utf-8')
    return path


class TestSeatQueue:
    """How many runs wait on the seat, and who holds it (T1f).

    The lock is an O_EXCL file polled every 5 s, so any waiter can win the next
    acquisition: there is no order to report, only a count.
    """

    def test_live_tickets_are_counted_beside_the_holder(self, tmp_path: Path) -> None:
        lock = tmp_path / 'seat.lock'
        _hold(lock, at='2026-10-06T10:00:00+00:00')
        _ticket(lock, pid=os.getpid(), owner='first-run/synthesis:1', token='aaaa')
        _ticket(lock, pid=os.getpid(), owner='second-run/synthesis:1', token='bbbb')

        queue = seat_queue(lock)

        assert queue.waiting == 2
        assert queue.holder == 'holder-run/synthesis:1'
        assert queue.holder_since == '2026-10-06T10:00:00+00:00'
        assert sorted(queue.owners) == ['first-run/synthesis:1', 'second-run/synthesis:1']

    def test_a_ticket_left_by_a_dead_waiter_is_ignored_and_removed(self, tmp_path: Path) -> None:
        lock = tmp_path / 'seat.lock'
        _hold(lock)
        live = _ticket(lock, pid=os.getpid(), owner='live-run/synthesis:1', token='aaaa')
        dead = _ticket(lock, pid=_exited_pid(), owner='crashed-run/synthesis:1', token='bbbb')

        queue = seat_queue(lock)

        assert queue.waiting == 1
        assert queue.owners == ('live-run/synthesis:1',)
        assert live.exists()
        assert not dead.exists()

    def test_a_free_seat_with_nobody_queued(self, tmp_path: Path) -> None:
        queue = seat_queue(tmp_path / 'seat.lock')
        assert queue.waiting == 0
        assert queue.holder is None
        assert queue.holder_since is None

    def test_a_lock_left_by_a_dead_owner_names_no_holder(self, tmp_path: Path) -> None:
        lock = tmp_path / 'seat.lock'
        lock.write_text(
            json.dumps({'pid': _exited_pid(), 'owner': 'crashed-run/synthesis:1', 'at': 'x'}),
            encoding='utf-8',
        )
        assert seat_queue(lock).holder is None


class TestWaiterTickets:
    """A waiter says it is waiting on disk, and stops saying so when it leaves."""

    def test_a_waiter_holds_a_ticket_until_it_acquires(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock = tmp_path / 'seat.lock'
        _hold(lock)
        seen: list[list[dict[str, object]]] = []

        def fake_sleep(_: float) -> None:
            seen.append(_tickets(lock))
            lock.unlink()  # the holder finishes

        monkeypatch.setattr('mantis_research.interface.seat.time.sleep', fake_sleep)
        with seat_lock(lock, owner='b/synthesis:1', poll_seconds=0.0):
            assert _tickets(lock) == []

        assert len(seen) == 1
        [ticket] = seen[0]
        assert ticket['pid'] == os.getpid()
        assert ticket['owner'] == 'b/synthesis:1'
        assert ticket['since']

    def test_the_ticket_is_gone_when_the_body_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock = tmp_path / 'seat.lock'
        _hold(lock)
        monkeypatch.setattr('mantis_research.interface.seat.time.sleep', lambda _: lock.unlink())
        with pytest.raises(RuntimeError), seat_lock(lock, owner='b/synthesis:1', poll_seconds=0.0):
            raise RuntimeError('boom')
        assert _tickets(lock) == []
        assert not lock.exists()

    def test_a_waiter_that_gives_up_leaves_no_ticket(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock = tmp_path / 'seat.lock'
        _hold(lock)

        def interrupted(_: float) -> None:
            assert len(_tickets(lock)) == 1
            msg = 'the caller went away'
            raise RuntimeError(msg)

        monkeypatch.setattr('mantis_research.interface.seat.time.sleep', interrupted)
        with pytest.raises(RuntimeError), seat_lock(lock, owner='b/synthesis:1'):
            pass
        assert _tickets(lock) == []
        assert lock.exists(), 'giving up must not touch the holder'

    def test_an_uncontended_acquire_writes_no_ticket(self, tmp_path: Path) -> None:
        lock = tmp_path / 'seat.lock'
        with seat_lock(lock, owner='b/synthesis:1'):
            assert _tickets(lock) == []

    async def test_an_async_waiter_holds_a_ticket_until_it_acquires(self, tmp_path: Path) -> None:
        lock = tmp_path / 'seat.lock'
        _hold(lock)
        seen: list[list[dict[str, object]]] = []

        async def holder_finishes_once_queued() -> None:
            for _ in range(10_000):
                if _tickets(lock):
                    break
                await asyncio.sleep(0)
            seen.append(_tickets(lock))
            lock.unlink()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(holder_finishes_once_queued())
            async with async_seat_lock(lock, owner='b/synthesis:1', poll_seconds=0.0):
                assert _tickets(lock) == []

        assert [t['owner'] for t in seen[0]] == ['b/synthesis:1']

    def test_taking_the_seat_is_announced(self, tmp_path: Path) -> None:
        # The run record stores when a stage took the seat, which is where the
        # expected-start estimate's durations come from.
        events: list[RunEvent] = []
        with seat_lock(tmp_path / 'seat.lock', owner='b/synthesis:1', on_event=events.append):
            pass
        acquired = [e for e in events if e.kind == 'seat_acquired']
        assert len(acquired) == 1
        assert acquired[0].data['seat_owner'] == 'b/synthesis:1'

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

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from mantis_research.core.state import SynthesisState, TopicStatus
from mantis_research.interface.seat import SeatHolder, process_is_alive, seat_lock

if TYPE_CHECKING:
    from pathlib import Path


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

"""Per-session transcript writer.

Each subprocess attempt (Claude/Gemini CLI) gets its own transcript file
under ``transcripts/`` containing the full command, start/finish timestamps,
streamed stdout+stderr, and the final exit code. Shape matches the legacy
runners' output so ``transcripts/`` greps still work.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import IO, TYPE_CHECKING, Self

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType


class TranscriptWriter(AbstractAsyncContextManager['TranscriptWriter']):
    """Async context manager that owns one transcript file.

    Usage::

        async with TranscriptWriter(path, cmd) as tx:
            tx.append_line(line)
            ...
            tx.finalize(exit_code=0)

    Headers are written on enter; footer (Finished + Exit code) is written
    when ``finalize()`` is called or on context exit.
    """

    def __init__(self, path: Path, command: list[str]) -> None:
        self.path = path
        self.command = command
        self._fh: IO[str] | None = None
        self._exit_code: int | None = None

    async def __aenter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open('w', encoding='utf-8')
        self._fh.write(f'# Command: {" ".join(self.command)}\n')
        self._fh.write(f'# Started: {_iso_now()}\n')
        self._fh.write('-' * 80 + '\n')
        self._fh.flush()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fh is None:
            return
        self._fh.write('-' * 80 + '\n')
        self._fh.write(f'# Finished: {_iso_now()}\n')
        if self._exit_code is not None:
            self._fh.write(f'# Exit code: {self._exit_code}\n')
        elif exc is not None:
            self._fh.write(f'# Exception: {exc!r}\n')
        self._fh.close()
        self._fh = None

    def append_line(self, line: str) -> None:
        """Append one streamed line. Does NOT add a trailing newline (caller controls)."""
        if self._fh is None:
            msg = 'TranscriptWriter not entered — use as async context manager'
            raise RuntimeError(msg)
        self._fh.write(line)
        self._fh.flush()

    def finalize(self, *, exit_code: int) -> None:
        """Record the subprocess exit code; final flush happens on __aexit__."""
        self._exit_code = exit_code

    def write_dry_run_marker(self) -> None:
        """For ``--dry-run``: write a single marker instead of streaming output."""
        if self._fh is None:
            msg = 'TranscriptWriter not entered'
            raise RuntimeError(msg)
        self._fh.write(f'# DRY RUN — command: {" ".join(self.command)}\n')
        self._fh.flush()
        self._exit_code = 0


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()

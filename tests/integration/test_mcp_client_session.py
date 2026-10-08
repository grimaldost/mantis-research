"""The server over a real MCP client session, in process.

Calling the handlers directly (as the unit tests do) proves the pipeline, not the
protocol: it never exercises tool listing, argument validation against the
published schema, or the progress notifications a client actually receives. This
drives the built server through `mcp.client.Client` on an in-memory transport, so
an SDK major bump that changes any of that fails here rather than in the field.
"""

from __future__ import annotations

import json
import os
import threading
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client

from mantis_research.core.progress import RunEvent
from mantis_research.interface.mcp import server
from mantis_research.interface.mcp.server import build_server

SCHEMA_SNAPSHOT = Path(__file__).resolve().parents[1] / 'data' / 'mcp_tool_schemas.json'


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


async def test_the_session_lists_both_tools_with_the_published_schemas() -> None:
    async with Client(build_server(), log_level='info') as client:
        listed = await client.list_tools()
    tools = {t.name: t.input_schema for t in listed.tools}
    assert set(tools) == {'research', 'research_status'}
    assert tools == json.loads(SCHEMA_SNAPSHOT.read_text(encoding='utf-8'))


async def test_a_dry_run_call_completes_and_progress_reaches_the_client(rooted: Path) -> None:
    updates: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        updates.append((progress, total, message))

    arguments: dict[str, Any] = {
        'question': 'q',
        'assurance': 'fast',
        'substrates': ['openai'],
        'dry_run': True,
    }
    async with Client(build_server(), log_level='info') as client:
        result = await client.call_tool('research', arguments, progress_callback=on_progress)

    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content['ok'] is True
    assert updates, 'no progress notification reached the client'
    # The protocol requires progress to increase; the run emits repeated steps.
    values = [u[0] for u in updates]
    assert values == sorted(set(values))


async def test_a_silent_blocking_call_keeps_sending_progress(
    monkeypatch: pytest.MonkeyPatch, rooted: Path
) -> None:
    # Field window 2026-07-26..09-26: 14 of 15 tool errors were the client
    # giving up after 1800 s with no progress notification. Only progress resets
    # that clock, so a phase that emits nothing, and events with no step, must
    # still reach the client as progress.
    monkeypatch.setattr(server, '_KEEPALIVE_S', 0.05)

    def silent(question: str, *, on_event: Any = None, **_: Any) -> dict[str, Any]:
        on_event(RunEvent(kind='run_named', message='run named', step=0, total=1, data={}))
        on_event(RunEvent(kind='stage_start', message='openrouter starting', step=0, total=1))
        time.sleep(0.6)
        for i in range(3):
            on_event(RunEvent(kind='thinking', message=f'thinking {i}'))
        time.sleep(0.2)
        return {'ok': True}

    monkeypatch.setattr(server, '_run_and_assemble', silent)
    stamps: list[tuple[float, float, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        stamps.append((time.monotonic(), progress, message))

    arguments = {'question': 'q', 'assurance': 'research', 'detach': False}
    async with Client(build_server(), log_level='info') as client:
        started = time.monotonic()
        result = await client.call_tool('research', arguments, progress_callback=on_progress)
        ended = time.monotonic()

    assert not result.is_error
    values = [value for _, value, _ in stamps]
    assert all(b > a for a, b in pairwise(values))
    moments = [started, *(at for at, _, _ in stamps), ended]
    # The run is silent for 0.6 s; without the keepalive the longest gap exceeds it.
    assert max(b - a for a, b in pairwise(moments)) < 0.45
    messages = [message or '' for _, _, message in stamps]
    assert [m for m in messages if m.startswith('thinking')] == [f'thinking {i}' for i in range(3)]
    assert any(m.startswith('still running: openrouter starting') for m in messages)


async def test_a_resume_of_a_run_this_server_holds_answers_with_its_handle(
    monkeypatch: pytest.MonkeyPatch, rooted: Path
) -> None:
    # In the field (0.4.0) a resume of a run the same server was still running
    # came back as "still owned by a live process", with no next step. The
    # owner is this server, so the answer is the run's handle.
    run_dir = rooted / 'outputs_root' / 'held-run'
    run_dir.mkdir(parents=True)
    identity = {
        'question': 'q',
        'question_slug': 'q',
        'batch_name': 'held-run',
        'assurance': 'fast',
        'substrates': ['openai'],
        'layout': 'batch',
        'outputs_dir': str(run_dir),
        'dry_run': False,
    }
    release = threading.Event()

    def held(question: str, *, resume: str = '', on_event: Any = None, **_: Any) -> dict[str, Any]:
        if resume:
            msg = f'run held-run is still owned by a live process (pid {os.getpid()})'
            raise ValueError(msg)
        record = {
            **identity,
            'status': 'dispatching',
            'owner_pid': os.getpid(),
            'current_stage': 'synthesis',
            'stages': {'openrouter': {'state': 'done', 'exit_code': 0}},
        }
        (run_dir / 'run.json').write_text(json.dumps(record), encoding='utf-8')
        on_event(RunEvent(kind='run_named', message='named', step=0, total=2, data=identity))
        release.wait(timeout=20)
        return {'ok': True}

    monkeypatch.setattr(server, '_run_and_assemble', held)
    try:
        async with Client(build_server(), log_level='info') as client:
            handle = await client.call_tool('research', {'question': 'q', 'detach': True})
            assert not handle.is_error
            again = await client.call_tool('research', {'question': 'q', 'resume': str(run_dir)})
    finally:
        release.set()

    assert not again.is_error, again.content
    answer = again.structured_content or {}
    assert answer['state'] == 'running'
    assert Path(answer['outputs_dir']) == run_dir
    assert answer['batch_name'] == 'held-run'
    assert answer['current_stage'] == 'synthesis'
    assert 'research_status' in answer['note']
    # Once the worker returns, the run is no longer held.
    for thread in threading.enumerate():
        if thread.name == 'mantis-research-run':
            thread.join(timeout=10)
    assert not server._HELD_RUNS

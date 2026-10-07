"""The server over a real MCP client session, in process.

Calling the handlers directly (as the unit tests do) proves the pipeline, not the
protocol: it never exercises tool listing, argument validation against the
published schema, or the progress notifications a client actually receives. This
drives the built server through `mcp.client.Client` on an in-memory transport, so
an SDK major bump that changes any of that fails here rather than in the field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client

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

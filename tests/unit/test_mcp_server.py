"""MCP server tests (spec 0002 §2/§3)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mantis_research.interface.mcp.server import build_server, research

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


async def test_build_server_registers_research_tool() -> None:
    # Introspect via the SDK's own list_tools API (spec 0002 §2 acceptance).
    server = build_server()
    tools = await server.list_tools()
    assert 'research' in [t.name for t in tools]


async def test_research_tool_schema_documents_every_parameter() -> None:
    # Agent-discoverability guard: every parameter must carry a description in the
    # tool inputSchema — the agent's first-glance surface. Bare typed slots (no
    # description) are what left `primary` / `journal` / the substrate vocabulary
    # undiscoverable to a fresh agent before 0.1.1.
    server = build_server()
    tools = await server.list_tools()
    tool = next(t for t in tools if t.name == 'research')
    props = tool.inputSchema['properties']
    expected = {'question', 'assurance', 'substrates', 'primary', 'journal', 'dry_run'}
    assert set(props) == expected
    for name in expected:
        assert props[name].get('description', '').strip(), f'{name} has no description'
    # The substrate vocabulary + default set must actually reach the agent.
    assert 'deepseek' in props['substrates']['description']


async def test_research_tool_projects_sidecar_and_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # §3: run_research monkeypatched to write a fake sidecar and return a manifest;
    # the tool result carries the manifest, the sidecar's structured content, the
    # cost block, and the brief by PATH (not inlined).
    sidecar_path = tmp_path / '01-q.sidecar.json'
    brief_path = tmp_path / 'openai.md'

    def fake_run_research(question: str, **_: Any) -> dict[str, Any]:
        sidecar_path.write_text(
            json.dumps(
                {
                    'sidecar_version': 1,
                    'claims': [{'id': 'c1', 'text': 'a claim', 'support': 'direct'}],
                    'divergences': [{'id': 'd1', 'description': 'x'}],
                    'verification_queue': [{'id': 'v1', 'claim': 'y', 'reason': 'single-source'}],
                    'agreements_worth_verifying': [],
                    'coverage_notes': [],
                }
            ),
            encoding='utf-8',
        )
        return {
            'ok': True,
            'question': question,
            'assurance': 'standard',
            'cost': {'available': True, 'cost_usd': 0.05, 'tokens_prompt': 1000},
            'stages': {'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 0}},
            'outputs': {
                'synthesis': str(tmp_path / '01-q.md'),
                'sidecar': str(sidecar_path),
                'briefs': [str(brief_path)],
            },
        }

    monkeypatch.setattr('mantis_research.interface.mcp.server.run_research', fake_run_research)
    result = await research('q', substrates=['openai'], dry_run=True)

    assert result['ok'] is True
    assert result['cost']['cost_usd'] == 0.05
    assert [c['id'] for c in result['claims']] == ['c1']
    assert result['divergences'][0]['id'] == 'd1'
    assert result['verification_queue'][0]['id'] == 'v1'
    # Brief + synthesis referenced by path, never inlined.
    assert result['outputs']['briefs'] == [str(brief_path)]
    assert result['outputs']['synthesis'] == str(tmp_path / '01-q.md')


async def test_research_tool_runs_in_live_loop_without_asyncio_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # §3 / FM-1: the real handler runs inside THIS live event loop in dry-run,
    # exercising dispatch_stage_config's asyncio.run per stage offloaded via
    # asyncio.to_thread. A regression (calling run_research on the loop) would
    # raise RuntimeError('asyncio.run() cannot be called from a running event loop').
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)

    result = await research('test q', assurance='fast', substrates=['openai'], dry_run=True)

    assert isinstance(result, dict)
    assert result['ok'] is True
    assert result['cost']['available'] is True
    # Protocol safety: the tool must write NOTHING to stdout — the stdio MCP
    # server owns stdout for JSON-RPC, and pipeline logs go to stderr.
    assert capsys.readouterr().out == ''

"""MCP server tests (spec 0002 §2/§3)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mantis_research.core.progress import RunEvent
from mantis_research.interface.mcp.server import _progress_bridge, build_server, research

if TYPE_CHECKING:
    import pytest

#: The input schemas both tools published before the SDK major port. The port is
#: meant to change how the server is built, not what an agent is shown.
SCHEMA_SNAPSHOT = Path(__file__).resolve().parents[1] / 'data' / 'mcp_tool_schemas.json'
_ROOT = Path(__file__).resolve().parents[2]


async def test_build_server_registers_research_tool() -> None:
    # Introspect via the SDK's own list_tools API (spec 0002 §2 acceptance).
    server = build_server()
    tools = await server.list_tools()
    assert 'research' in [t.name for t in tools]


async def test_tool_input_schemas_match_the_snapshot() -> None:
    # Compatibility oracle for SDK major upgrades: an agent's first-glance surface
    # (parameter names, types, defaults, descriptions) must not move unnoticed.
    # Regenerate the snapshot deliberately when a schema is meant to change.
    tools = await build_server().list_tools()
    live = {t.name: t.input_schema for t in tools}
    assert live == json.loads(SCHEMA_SNAPSHOT.read_text(encoding='utf-8'))


async def test_research_tool_schema_documents_every_parameter() -> None:
    # Agent-discoverability guard: every parameter must carry a description in the
    # tool input_schema — the agent's first-glance surface. Bare typed slots (no
    # description) are what left `primary` / `journal` / the substrate vocabulary
    # undiscoverable to a fresh agent before 0.1.1.
    server = build_server()
    tools = await server.list_tools()
    tool = next(t for t in tools if t.name == 'research')
    props = tool.input_schema['properties']
    expected = {
        'question',
        'assurance',
        'substrates',
        'primary',
        'journal',
        'dry_run',
        'resume',
        'name',
        'detach',
    }
    assert set(props) == expected
    for name in expected:
        assert props[name].get('description', '').strip(), f'{name} has no description'
    # The substrate vocabulary + default set must actually reach the agent.
    assert 'deepseek' in props['substrates']['description']


async def test_request_context_is_injected_and_not_an_agent_parameter() -> None:
    # MANT-B01: the handler takes the MCPServer Context so it can report progress.
    # The SDK must recognise it as the injected context — if it ever leaked into
    # the input schema instead, agents would be asked to supply it.
    server = build_server()
    tool = server._tool_manager.get_tool('research')
    assert tool.context_kwarg == 'ctx'
    assert 'ctx' not in tool.parameters['properties']


async def test_research_tool_defaults_to_fast_assurance() -> None:
    # MANT-B04: the default tier is the one most calls want and the one that
    # actually completes over this tool's own transport. standard/high stay as
    # explicit escalations.
    server = build_server()
    tools = await server.list_tools()
    tool = next(t for t in tools if t.name == 'research')
    assert tool.input_schema['properties']['assurance']['default'] == 'fast'


async def test_research_tool_assurance_description_names_the_escalations() -> None:
    server = build_server()
    tools = await server.list_tools()
    tool = next(t for t in tools if t.name == 'research')
    description = tool.input_schema['properties']['assurance']['description']
    assert 'default' in description.lower()
    for tier in ('fast', 'standard', 'high'):
        assert tier in description


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


async def test_research_tool_offers_a_research_only_tier() -> None:
    """MANT-B60 — the tier that works from inside a Claude Code session."""
    tool = next(t for t in await build_server().list_tools() if t.name == 'research')
    description = tool.input_schema['properties']['assurance']['description']
    assert 'research' in description


async def test_research_tool_accepts_a_name() -> None:
    """MANT-B62 — a caller that prefixes shared context can name its run."""
    tool = next(t for t in await build_server().list_tools() if t.name == 'research')
    assert 'name' in tool.input_schema['properties']
    assert tool.input_schema['properties']['name']['description']


async def test_the_tool_description_gives_the_durations_the_skill_cites() -> None:
    """T20b — the description an agent reads first says how long a run takes.

    The figures come from the constants the skill's latency bullet is held to, so
    the two surfaces cannot quote different durations.
    """
    from mantis_research.interface.research_service import (
        LOCAL_SEAT_TURN_MEDIAN_MINUTES,
        RESEARCH_STAGE_MINUTES,
    )
    from tests.unit.test_agent_serving_docs import _turns_per_tier

    tool = next(t for t in await build_server().list_tools() if t.name == 'research')
    description = ' '.join((tool.description or '').split())
    skill = ' '.join((_ROOT / 'skills' / 'research' / 'SKILL.md').read_text('utf-8').split())
    lo, hi = RESEARCH_STAGE_MINUTES
    # The skill writes the range with an en dash; ruff keeps one out of a docstring.
    assert f'{lo} to {hi} min' in description
    assert f'{lo}{chr(0x2013)}{hi} min' in skill
    median = f'about {LOCAL_SEAT_TURN_MEDIAN_MINUTES} min'
    assert median in description
    assert median in skill

    # The Parameters entry for detach, up to the next entry or the end.
    start = description.index('- ``detach``')
    end = description.find(' - ``', start + 1)
    entry = description[start : end if end != -1 else None]
    turns = ', '.join(
        f'``{tier}`` {n}' for tier, n in _turns_per_tier().items() if tier != 'research'
    )
    assert turns in entry
    assert 'one seat' in entry
    assert 'subagent' in entry
    assert 'resume=<outputs_dir>' in entry


class _RecordingContext:
    """Records what the bridge sends, in place of the SDK's request context."""

    def __init__(self) -> None:
        self.progress: list[float] = []
        self.logged: list[str] = []

    async def report_progress(
        self, progress: float, total: float | None = None, message: str | None = None
    ) -> None:
        self.progress.append(progress)

    async def info(self, message: str, **_: Any) -> None:
        self.logged.append(message)


async def test_progress_bridge_only_reports_steps_that_advance() -> None:
    # The run emits steps 0,0,1,1,2,2 (a stage start and the previous stage's
    # finish share a step) and the SDK requires progress to strictly increase, so
    # the repeats must be logged but not sent as progress.
    ctx = _RecordingContext()
    bridge = _progress_bridge(ctx, asyncio.get_running_loop())
    for step in (0, 0, 1, 1, 2, 2):
        bridge(RunEvent(kind='stage_start', message=f'step {step}', step=step, total=3))
    bridge(RunEvent(kind='waiting', message='no scale'))
    await asyncio.sleep(0.05)
    assert ctx.progress == [0, 1, 2]
    assert len(ctx.logged) == 7

"""Starting a run and collecting it are separate acts (MANT-B61).

The `research` tool was one blocking call, and a real run legitimately takes
longer than an MCP client will hold one open. Across every recorded transcript,
18 of 18 non-dry-run calls hit the client's ceiling and none returned; the five
that did return in two seconds were dry runs. Progress notifications helped —
measured on 2026-08-23 they bought each caller 216-460 s — but they cannot
extend a call past a ceiling on its total duration.

`detach=True` is additive: the blocking default is unchanged, so no existing
caller is affected. A detached run is bound to the server's lifetime, which is
the session doing the polling; a run lost with the session is re-entered with
``resume``, which is what invariant I5 already provides.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mantis_research.interface.mcp.server import build_server, research, research_status

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


class TestTheToolSurface:
    async def test_the_server_exposes_a_status_tool(self) -> None:
        names = {t.name for t in await build_server().list_tools()}
        assert names == {'research', 'research_status'}

    async def test_detach_is_off_by_default(self) -> None:
        tool = next(t for t in await build_server().list_tools() if t.name == 'research')
        assert tool.inputSchema['properties']['detach']['default'] is False

    async def test_the_status_tool_documents_its_argument(self) -> None:
        tool = next(t for t in await build_server().list_tools() if t.name == 'research_status')
        assert tool.inputSchema['properties']['outputs_dir']['description']


class TestADetachedCallReturnsAHandle:
    async def test_it_returns_before_the_run_finishes(self, rooted: Path) -> None:
        result = await research('a detached question', assurance='research', detach=True)
        assert result['state'] == 'running'
        assert result['outputs_dir']
        assert result['batch_name']

    async def test_the_handle_names_a_run_that_exists_on_disk(self, rooted: Path) -> None:
        result = await research('a detached question', assurance='research', detach=True)
        record = json.loads(
            (rooted / 'outputs_root' / result['batch_name'] / 'run.json').read_text(
                encoding='utf-8'
            )
        )
        assert record['question'] == 'a detached question'

    async def test_the_handle_carries_no_epistemic_payload(self, rooted: Path) -> None:
        # There is nothing to report yet; saying otherwise is the shape that
        # let a briefs-only run read as an answer.
        result = await research('q', assurance='research', detach=True)
        assert 'claims' not in result
        assert result.get('sidecar_available') is not True


class TestStatusReadsWhatIsOnDisk:
    async def test_an_unknown_directory_is_reported_not_raised(self, rooted: Path) -> None:
        status = await research_status(str(rooted / 'outputs_root' / 'no-such-run'))
        assert status['state'] == 'unknown'

    async def test_a_finished_run_reports_its_outcome(self, rooted: Path) -> None:
        blocking = await research('q', assurance='research', dry_run=True)
        status = await research_status(blocking['outputs'].get('run_dir') or _dir(rooted))
        assert status['state'] in {'finished', 'running'}

    async def test_a_failed_run_is_reported_rather_than_raised(self, rooted: Path) -> None:
        # `_agent_result` raises when a live run owed a sidecar and has none.
        # Polling must not: a caller asking "how did it go" needs the answer,
        # not an exception it has to interpret.
        run_dir = rooted / 'outputs_root' / 'failed-run'
        run_dir.mkdir(parents=True)
        (run_dir / 'run.json').write_text(
            json.dumps(
                {
                    'question': 'q',
                    'batch_name': 'failed-run',
                    'status': 'complete',
                    'ok': False,
                    'dry_run': False,
                    'produces_sidecar': True,
                    'assurance': 'fast',
                    'stages': {'synthesis': {'exit_code': 1}},
                    'outputs': {'sidecar': str(run_dir / 'nothing.json')},
                }
            ),
            encoding='utf-8',
        )
        status = await research_status(str(run_dir))
        assert status['state'] == 'finished'
        assert status['ok'] is False


def _dir(rooted: Path) -> str:
    return str(next((rooted / 'outputs_root').iterdir()))


class TestTheBlockingDefaultIsUnchanged:
    async def test_a_plain_call_still_returns_the_result(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def fake(question: str, **kw: Any) -> dict[str, Any]:
            seen['blocked'] = True
            return {
                'ok': True,
                'dry_run': True,
                'question': question,
                'assurance': 'fast',
                'produces_sidecar': False,
                'cost': {},
                'stages': {},
                'outputs': {'sidecar': str(rooted / 'none.json')},
            }

        monkeypatch.setattr('mantis_research.interface.mcp.server.run_research', fake)
        result = await research('q', dry_run=True)
        assert seen.get('blocked') is True
        assert result['question'] == 'q'

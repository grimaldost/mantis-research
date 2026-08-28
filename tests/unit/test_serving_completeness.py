"""The MCP serving path must never present a briefs-only run as a result.

Field failure, 2026-08-11: an agent called the ``research`` tool from inside a
Claude Code session — the headline use case in ADR-0009 — and got back research
briefs with no synthesis, no sidecar and no falsification. The run's own record
(``outputs/vf-selfverif-live/run.json``) shows ``synthesis`` at ``exit_code: 1``
beside three brief paths that do exist, and the transcripts show the ``claude``
child exiting 1 at dispatch. What the caller received was a structured result it
could read as a delivered product: the paths were all there, and the one field
that said otherwise was an ``ok`` flag next to a ``sidecar_available: false``.

The epistemic sidecar **is** the product (ADR-0003). A run that did not produce
one did not produce an answer, and the tool now says so by raising rather than
by returning a shape that reads as success. A dry run is the one exception, and
it is exempted on the manifest's own ``dry_run`` flag rather than on a guess.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mantis_research.interface.mcp.server import (
    IncompleteRunError,
    _agent_result,
    research,
)

if TYPE_CHECKING:
    from pathlib import Path


def _manifest(
    tmp_path: Path,
    *,
    ok: bool,
    dry_run: bool,
    stages: dict[str, dict[str, int]],
) -> dict[str, Any]:
    return {
        'ok': ok,
        'dry_run': dry_run,
        'question': 'where does agent self-verification pay off?',
        'assurance': 'standard',
        'batch_name': 'vf',
        'outputs_dir': str(tmp_path / 'vf'),
        'cost': {'available': True, 'cost_usd': 0.21, 'tokens_prompt': 1000},
        'stages': stages,
        'outputs': {
            'synthesis': str(tmp_path / 'vf' / '01-q.md'),
            'sidecar': str(tmp_path / 'vf' / '01-q.sidecar.json'),
            'briefs': [str(tmp_path / 'vf' / 'openai.md')],
        },
    }


def _write_sidecar(tmp_path: Path) -> None:
    (tmp_path / 'vf').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'vf' / '01-q.sidecar.json').write_text(
        json.dumps(
            {
                'sidecar_version': 2,
                'claims': [{'id': 'c1', 'text': 'a claim', 'support': 'direct'}],
                'divergences': [],
                'verification_queue': [],
                'agreements_worth_verifying': [],
                'coverage_notes': [],
            }
        ),
        encoding='utf-8',
    )


def _patch_run(monkeypatch: pytest.MonkeyPatch, manifest: dict[str, Any]) -> None:
    monkeypatch.setattr(
        'mantis_research.interface.mcp.server.run_research',
        lambda question, **_: manifest,
    )


class TestABriefsOnlyRunIsRefused:
    async def test_a_live_run_with_no_sidecar_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # The exact field shape: briefs on disk, synthesis exit 1, no sidecar.
        _patch_run(
            monkeypatch,
            _manifest(
                tmp_path,
                ok=False,
                dry_run=False,
                stages={'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 1}},
            ),
        )
        with pytest.raises(IncompleteRunError):
            await research('q')

    async def test_the_refusal_names_the_product_the_stage_and_the_way_back(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_run(
            monkeypatch,
            _manifest(
                tmp_path,
                ok=False,
                dry_run=False,
                stages={'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 1}},
            ),
        )
        with pytest.raises(IncompleteRunError) as caught:
            await research('q')
        message = str(caught.value)
        assert 'sidecar' in message  # what is missing
        assert 'synthesis' in message  # which stage did not deliver it
        assert 'resume' in message  # how to recover without re-buying the briefs
        assert str(tmp_path / 'vf') in message  # the run to resume

    async def test_a_run_that_reports_ok_but_wrote_no_sidecar_is_still_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # `ok` is assembled from stage exit codes, so it can be True over a tree
        # with no product in it. The guard is the artifact, not the flag.
        _patch_run(
            monkeypatch,
            _manifest(
                tmp_path,
                ok=True,
                dry_run=False,
                stages={'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 0}},
            ),
        )
        with pytest.raises(IncompleteRunError):
            await research('q')


class TestWhatIsStillReturned:
    async def test_a_live_run_with_a_sidecar_returns_normally(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_sidecar(tmp_path)
        _patch_run(
            monkeypatch,
            _manifest(
                tmp_path,
                ok=True,
                dry_run=False,
                stages={'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 0}},
            ),
        )
        result = await research('q')
        assert result['sidecar_available'] is True
        assert [c['id'] for c in result['claims']] == ['c1']

    async def test_a_failing_later_stage_still_returns_when_the_product_exists(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Falsification is a check on top of the product, not the product. Its
        # failure is reported through `ok` and `stages`, which are faithful; the
        # sidecar is there, so the caller has an answer to act on.
        _write_sidecar(tmp_path)
        _patch_run(
            monkeypatch,
            _manifest(
                tmp_path,
                ok=False,
                dry_run=False,
                stages={
                    'openrouter': {'exit_code': 0},
                    'synthesis': {'exit_code': 0},
                    'falsification': {'exit_code': 1},
                },
            ),
        )
        result = await research('q')
        assert result['ok'] is False
        assert result['stages']['falsification']['exit_code'] == 1

    async def test_a_dry_run_returns_and_says_it_was_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # A dry run legitimately has no sidecar. It is exempted on the
        # manifest's own flag, and the flag travels to the caller — the result
        # has to be unmistakable, because every path in it points at nothing.
        _patch_run(
            monkeypatch,
            _manifest(
                tmp_path,
                ok=True,
                dry_run=True,
                stages={'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 0}},
            ),
        )
        result = await research('q', dry_run=True)
        assert result['dry_run'] is True
        assert result['sidecar_available'] is False


class TestAResearchOnlyRunIsNotIncomplete:
    """MANT-B60 — the refusal must learn which runs owe a sidecar.

    0.3.0 made a live run with no sidecar raise, because the sidecar is the
    product and a briefs-only result read as an answer. A research-only run
    produces no sidecar *by design*, so the same guard would refuse the one
    tier that works from inside a Claude Code session.
    """

    def test_a_research_tier_manifest_says_it_owes_no_sidecar(self) -> None:
        from mantis_research.interface.research_service import _TIER_STAGES, produces_sidecar

        assert produces_sidecar(_TIER_STAGES['research']) is False
        assert produces_sidecar(_TIER_STAGES['fast']) is True

    def test_a_research_only_result_is_returned_not_refused(self, tmp_path: Path) -> None:
        manifest = {
            'ok': True,
            'dry_run': False,
            'question': 'q',
            'assurance': 'research',
            'produces_sidecar': False,
            'cost': {'available': True, 'cost_usd': 0.42},
            'stages': {'openrouter': {'exit_code': 0}},
            'outputs': {'sidecar': str(tmp_path / 'nothing.json'), 'briefs': ['a.md']},
        }
        result = _agent_result(manifest)
        assert result['sidecar_available'] is False
        assert result['cost']['cost_usd'] == 0.42

    def test_a_synthesis_tier_with_no_sidecar_still_raises(self, tmp_path: Path) -> None:
        manifest = {
            'ok': True,
            'dry_run': False,
            'question': 'q',
            'assurance': 'fast',
            'produces_sidecar': True,
            'cost': {},
            'stages': {'synthesis': {'exit_code': 1}},
            'outputs': {'sidecar': str(tmp_path / 'nothing.json')},
        }
        with pytest.raises(IncompleteRunError):
            _agent_result(manifest)

    def test_a_manifest_without_the_flag_still_demands_a_sidecar(self, tmp_path: Path) -> None:
        # Older run records predate the field; absence must read as "owed",
        # which is what every tier before this one meant.
        manifest = {
            'ok': True,
            'dry_run': False,
            'question': 'q',
            'assurance': 'fast',
            'cost': {},
            'stages': {'synthesis': {'exit_code': 1}},
            'outputs': {'sidecar': str(tmp_path / 'nothing.json')},
        }
        with pytest.raises(IncompleteRunError):
            _agent_result(manifest)

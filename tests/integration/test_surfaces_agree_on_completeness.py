"""Both serving surfaces read one judgement about what a run delivered.

ADR-0011 made `ok` mean "the stages did what they were asked" rather than "the
product exists". The MCP path was reconciled with that in the same change; the
CLI's `exit 0 if manifest['ok']` was not, so for one release candidate a run
whose sidecar failed exited **0** from `mantis research` while the MCP tool
refused the identical manifest with `IncompleteRunError`. Two surfaces, one run,
opposite verdicts — the same class of defect that release claims to have fixed.

The repair is one producer: `research_service.missing_product` answers "does
this run owe a sidecar it does not have, and why", and both surfaces consume it
— the MCP refusal for its blame line, the CLI for its exit code. A second copy
of the judgement, however small, is what drifts; this module is the mechanism
that stops it.

Every case below is asserted against **both** surfaces from the same manifest,
so a change to one that is not a change to the other fails here.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
import typer

from mantis_research.interface.cli.research import research_cmd
from mantis_research.interface.mcp.server import IncompleteRunError, _agent_result
from mantis_research.interface.research_service import MISSING_PRODUCT_EXIT_CODE, missing_product

if TYPE_CHECKING:
    from pathlib import Path

_SIDECAR = json.dumps(
    {
        'sidecar_version': 2,
        'claims': [{'id': 'c1', 'text': 'a claim', 'support': 'direct'}],
        'divergences': [],
        'verification_queue': [],
        'agreements_worth_verifying': [],
        'coverage_notes': [],
    }
)


def _manifest(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        'ok': True,
        'dry_run': False,
        'question': 'q',
        'assurance': 'fast',
        'produces_sidecar': True,
        'batch_name': 'b',
        'outputs_dir': str(tmp_path / 'b'),
        'cost': {'available': True, 'cost_usd': 0.21},
        'stages': {'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 0}},
        'sidecar': {'status': 'ok', 'error': None},
        'outputs': {
            'synthesis': str(tmp_path / 'b' / '01-q.md'),
            'sidecar': str(tmp_path / 'b' / '01-q.sidecar.json'),
            'briefs': [str(tmp_path / 'b' / 'openai.md')],
        },
    }
    return {**base, **overrides}


def _publish_sidecar(tmp_path: Path) -> None:
    (tmp_path / 'b').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'b' / '01-q.sidecar.json').write_text(_SIDECAR, encoding='utf-8')


def _cli_exit(monkeypatch: pytest.MonkeyPatch, manifest: dict[str, Any]) -> int:
    """Run `mantis research` over this manifest and return its exit code."""
    monkeypatch.setattr(
        'mantis_research.interface.cli.research.run_research', lambda question, **_: manifest
    )
    with pytest.raises(typer.Exit) as exc:
        research_cmd('q', assurance='fast', log_level='CRITICAL')
    return int(exc.value.exit_code)


def _mcp_refused(manifest: dict[str, Any]) -> bool:
    try:
        _agent_result(manifest)
    except IncompleteRunError:
        return True
    return False


_FAILED_SIDECAR = {'status': 'failed', 'error': 'schema drift on every re-ask'}

#: (name, manifest overrides, publish the sidecar file?, product missing?, CLI exit)
_CASES: list[tuple[str, dict[str, Any], bool, bool, int]] = [
    ('a delivered run', {}, True, False, 0),
    (
        'a complete synthesis whose sidecar turn failed',
        {'sidecar': _FAILED_SIDECAR},
        False,
        True,
        MISSING_PRODUCT_EXIT_CODE,
    ),
    (
        'a run whose synthesis stage exited non-zero',
        {'ok': False, 'stages': {'openrouter': {'exit_code': 0}, 'synthesis': {'exit_code': 1}}},
        False,
        True,
        1,
    ),
    (
        'a run reporting ok over a tree with no product in it',
        {'sidecar': {'status': 'not_run', 'error': None}},
        False,
        True,
        MISSING_PRODUCT_EXIT_CODE,
    ),
    ('a dry run', {'dry_run': True}, False, False, 0),
    (
        'a research-only tier',
        {
            'assurance': 'research',
            'produces_sidecar': False,
            'stages': {'openrouter': {'exit_code': 0}},
            'sidecar': {'status': 'not_owed', 'error': None},
        },
        False,
        False,
        0,
    ),
    (
        'a later check failing over a delivered product',
        {
            'ok': False,
            'stages': {'synthesis': {'exit_code': 0}, 'falsification': {'exit_code': 1}},
        },
        True,
        False,
        1,
    ),
]

_PARAMS = [pytest.param(o, p, m, c, id=name) for name, o, p, m, c in _CASES]


@pytest.mark.parametrize(('overrides', 'publish', 'is_missing', 'cli_code'), _PARAMS)
class TestBothSurfacesReadTheSameJudgement:
    @staticmethod
    def _built(tmp_path: Path, overrides: dict[str, Any], publish: bool) -> dict[str, Any]:
        if publish:
            _publish_sidecar(tmp_path)
        return _manifest(tmp_path, **overrides)

    def test_the_judgement_says_what_the_case_says(
        self,
        tmp_path: Path,
        overrides: dict[str, Any],
        publish: bool,
        is_missing: bool,
        cli_code: int,
    ) -> None:
        manifest = self._built(tmp_path, overrides, publish)
        assert (missing_product(manifest) is not None) is is_missing

    def test_the_mcp_surface_refuses_exactly_when_the_product_is_missing(
        self,
        tmp_path: Path,
        overrides: dict[str, Any],
        publish: bool,
        is_missing: bool,
        cli_code: int,
    ) -> None:
        assert _mcp_refused(self._built(tmp_path, overrides, publish)) is is_missing

    def test_the_cli_exit_code_is_the_documented_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        overrides: dict[str, Any],
        publish: bool,
        is_missing: bool,
        cli_code: int,
    ) -> None:
        assert _cli_exit(monkeypatch, self._built(tmp_path, overrides, publish)) == cli_code

    def test_the_cli_never_exits_zero_on_a_manifest_the_mcp_path_refuses(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        overrides: dict[str, Any],
        publish: bool,
        is_missing: bool,
        cli_code: int,
    ) -> None:
        # The invariant the defect broke, stated as one sentence. `ok` is about
        # the stages; neither surface may read it as "the product exists".
        manifest = self._built(tmp_path, overrides, publish)
        code = _cli_exit(monkeypatch, manifest)
        assert not (code == 0 and _mcp_refused(manifest))


class TestTheExitCodeSeparatesTheTwoOutcomes:
    """A missing product is not a failed stage, and the code says which.

    `ok` is genuinely true about the stages when only the sidecar failed, so
    folding that into exit 1 would throw away the distinction ADR-0011 exists to
    create — and moving a failed *stage* off 1 would break a documented contract
    this change has no business touching. So 1 keeps its meaning and the new
    case gets its own code. What it must never be is 0.
    """

    def test_a_missing_product_over_green_stages_is_neither_success_nor_stage_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manifest = _manifest(tmp_path, sidecar=_FAILED_SIDECAR)
        assert manifest['ok'] is True  # the stages really did succeed
        assert _cli_exit(monkeypatch, manifest) == MISSING_PRODUCT_EXIT_CODE
        assert MISSING_PRODUCT_EXIT_CODE not in (0, 1, 2)

    def test_the_refusal_reason_is_the_one_the_judgement_gave(self, tmp_path: Path) -> None:
        # The MCP message and the CLI's verdict come from one call, so an agent's
        # reason and an operator's reason cannot diverge either.
        manifest = _manifest(tmp_path, sidecar=_FAILED_SIDECAR)
        reason = missing_product(manifest)
        assert reason is not None
        assert 'schema drift' in reason
        with pytest.raises(IncompleteRunError, match='schema drift'):
            _agent_result(manifest)

    def test_the_operator_is_told_why_not_only_by_a_number(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _cli_exit(monkeypatch, _manifest(tmp_path, sidecar=_FAILED_SIDECAR))
        assert 'schema drift' in capsys.readouterr().err

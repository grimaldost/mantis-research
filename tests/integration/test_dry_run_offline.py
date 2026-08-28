"""A dry run validates orchestration — it must not reach a provider, or lie.

MANT-B64/B65. ``--dry-run`` is documented as validating the pipeline "for free"
and is what the skill tells an agent to do first. Two ways it fell short of
that promise: it fetched the OpenRouter model catalog over the network on every
subsession, and it recorded ``status: "complete"`` beside output paths that no
run had written.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mantis_research.interface.research_service import run_research

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


def test_a_dry_run_reaches_no_provider(rooted: Path) -> None:
    """The hermetic guard is the assertion: it raises if anything went out.

    The model resolver asked the live catalog for every subsession, inside the
    loop, with no dry-run guard — so the free validation pass was a paid path's
    network call away from the machine being offline.
    """
    manifest = run_research(
        'does a dry run stay offline?',
        assurance='fast',
        batch_name='offline',
        dry_run=True,
        log_level='CRITICAL',
    )
    assert manifest['dry_run'] is True


def test_a_dry_run_is_recorded_as_validated_not_complete(rooted: Path) -> None:
    """``complete`` means an artifact is on disk. A dry run wrote none."""
    run_research(
        'what does a dry run record?',
        assurance='fast',
        batch_name='validated',
        dry_run=True,
        log_level='CRITICAL',
    )
    run_json = rooted / 'outputs_root' / 'validated' / 'run.json'
    record = json.loads(run_json.read_text(encoding='utf-8'))
    assert record['status'] == 'validated'
    assert record['dry_run'] is True


def test_a_real_run_is_still_recorded_as_complete(
    rooted: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rename must not leak into the path that did produce artifacts."""
    monkeypatch.setattr(
        'mantis_research.interface.cli.dispatch.dispatch_stage_config',
        lambda *_a, **_k: 0,
    )
    run_research(
        'what does a real run record?',
        assurance='fast',
        batch_name='real',
        dry_run=False,
        log_level='CRITICAL',
    )
    record = json.loads((rooted / 'outputs_root' / 'real' / 'run.json').read_text(encoding='utf-8'))
    assert record['status'] == 'complete'

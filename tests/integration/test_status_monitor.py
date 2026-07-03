"""Layout-aware status + monitor (spec 0001 §19)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import typer

from mantis_research.core.state import ClaudeResearchState, TopicStatus
from mantis_research.interface.cli.monitor import monitor_cmd
from mantis_research.interface.cli.status import status_cmd

if TYPE_CHECKING:
    from pathlib import Path

_BATCH_CFG = {
    'schema_version': 2,
    'batch_name': 'b',
    'runner': {'layout': 'batch'},
    'models': {'claude': {'model': 'claude-opus-4-7'}},
    'topics': [{'id': '1', 'slug': 't', 'title': 'T', 'stages': {'claude': {'prompt': 'p'}}}],
}


def test_status_batch_layout_shows_markers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr('mantis_research.core.paths.state_root', lambda: tmp_path / 'state')
    cfg_path = tmp_path / 'cfg.json'
    cfg_path.write_text(json.dumps(_BATCH_CFG), encoding='utf-8')
    # A DONE claude state under the batch-scoped dir.
    sd = tmp_path / 'state' / 'b' / 'claude'
    sd.mkdir(parents=True, exist_ok=True)
    ClaudeResearchState(id='1', slug='t', status=TopicStatus.DONE).save(sd)

    status_cmd(cfg_path)

    out = capsys.readouterr().out
    assert 'OK' in out  # the DONE marker — proves it read the batch-scoped dir


def test_monitor_batch_finds_scoped_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr('mantis_research.core.paths.state_root', lambda: tmp_path / 'state')
    sd = tmp_path / 'state' / 'b' / 'claude'
    sd.mkdir(parents=True, exist_ok=True)
    (sd / 'progress.json').write_text(
        json.dumps(
            {
                'batch_name': 'b',
                'updated_at': 'x',
                'total_topics': 1,
                'counts': {'done': 1},
                'topics': [{'id': '1', 'status': 'done'}],
            }
        ),
        encoding='utf-8',
    )
    # All-terminal → monitor prints and returns (no infinite loop).
    monitor_cmd('claude', poll_seconds=0, batch_name='b', layout='batch')
    assert 'ALL_TERMINAL' in capsys.readouterr().out


def test_bare_monitor_missing_progress_exits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Legacy invocation with no progress file → clean exit 1 (unchanged behavior).
    monkeypatch.setattr('mantis_research.core.paths.project_root', lambda: tmp_path)
    with pytest.raises(typer.Exit) as exc:
        monitor_cmd('claude', poll_seconds=0)
    assert exc.value.exit_code == 1

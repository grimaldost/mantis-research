"""Re-entering an interrupted run (backlog MANT-B13).

Invariant I5 already promised per-stage resumability and the state files already
delivered it — both runs that died at the client timeout had written their
per-model briefs, and those briefs were harvested by hand into two finished
documents. What was missing was an entry point that consumes that state, so
recovery was manual every time.

The containment rule is the sibling series engine's: the directory offered for
resume must be *strictly* contained by the root it claims, which is what stops a
resume from reaching across runs or up into a parent tree.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from mantis_research.interface.research_service import (
    resolve_resume_dir,
    resume_research,
    run_research,
)

if TYPE_CHECKING:
    from pathlib import Path


def _exited_pid() -> int:
    proc = subprocess.Popen([sys.executable, '-c', ''])
    proc.wait()
    return proc.pid


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


def _abandoned_run(rooted: Path, *, owner_pid: int, batch: str = 'b') -> Path:
    run_dir = rooted / 'outputs_root' / batch
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'run.json').write_text(
        json.dumps(
            {
                'question': 'what changed in X?',
                'question_slug': 'what-changed-in-x',
                'batch_name': batch,
                'assurance': 'fast',
                'substrates': ['openai', 'deepseek'],
                'layout': 'batch',
                'outputs_dir': str(run_dir),
                'status': 'dispatching',
                'started_at': 'earlier',
                'owner_pid': owner_pid,
            }
        ),
        encoding='utf-8',
    )
    return run_dir


class TestContainment:
    def test_the_outputs_root_itself_is_not_a_run(self, rooted: Path) -> None:
        # Strict containment: resuming "the outputs tree" would let one resume
        # reach across every run on the machine.
        with pytest.raises(ValueError, match='not inside the outputs root'):
            resolve_resume_dir(rooted / 'outputs_root')

    def test_a_directory_outside_the_outputs_root_is_refused(self, rooted: Path) -> None:
        with pytest.raises(ValueError, match='not inside the outputs root'):
            resolve_resume_dir(rooted / 'somewhere-else')

    def test_a_traversal_out_of_the_root_is_refused(self, rooted: Path) -> None:
        # Resolution happens before the check, so `..` cannot walk past it — the
        # failure mode a plain prefix-string comparison would miss.
        with pytest.raises(ValueError, match='not inside the outputs root'):
            resolve_resume_dir(rooted / 'outputs_root' / '..' / 'elsewhere')

    def test_a_real_run_directory_resolves(self, rooted: Path) -> None:
        run_dir = _abandoned_run(rooted, owner_pid=_exited_pid())
        assert resolve_resume_dir(run_dir) == run_dir.resolve()

    def test_a_contained_path_that_does_not_exist_is_refused(self, rooted: Path) -> None:
        (rooted / 'outputs_root').mkdir(parents=True)
        with pytest.raises(ValueError, match='no run directory'):
            resolve_resume_dir(rooted / 'outputs_root' / 'never-ran')


class TestResume:
    def test_resume_recovers_the_question_and_settings_from_the_record(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_dir = _abandoned_run(rooted, owner_pid=_exited_pid())
        seen: list[str] = []

        def fake_dispatch(stage: str, cfg: object, **_: object) -> int:
            seen.append(stage)
            return 0

        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', fake_dispatch
        )
        manifest = resume_research(run_dir, log_level='CRITICAL')
        assert manifest['question'] == 'what changed in X?'
        assert manifest['batch_name'] == 'b'
        assert manifest['assurance'] == 'fast'
        assert seen == ['openrouter', 'synthesis']
        assert len(manifest['outputs']['briefs']) == 2  # both substrates recovered

    def test_resume_appends_a_terminal_record_for_the_abandoned_owner(self, rooted: Path) -> None:
        # The abandoned attempt gets a record appended, rather than the run
        # being left at its last live state as though work were still under way.
        run_dir = _abandoned_run(rooted, owner_pid=_exited_pid())
        resume_research(run_dir, dry_run=True, log_level='CRITICAL')
        record = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        # `validated` rather than `complete`: this resume is a dry run, so it
        # settled the record without writing any of the artifacts it names.
        assert record['status'] == 'validated'
        assert [h['status'] for h in record['history']] == ['dead']
        assert 'was gone at resume' in record['history'][0]['note']

    def test_a_run_with_a_live_owner_is_refused(self, rooted: Path) -> None:
        # Two owners over one state tree is worse than a lost run.
        run_dir = _abandoned_run(rooted, owner_pid=os.getpid())
        with pytest.raises(ValueError, match='still owned by a live process'):
            resume_research(run_dir, dry_run=True, log_level='CRITICAL')

    def test_a_completed_run_resumes_without_a_dead_record(self, rooted: Path) -> None:
        run_research(
            'what changed in X?',
            assurance='fast',
            batch_name='b',
            dry_run=True,
            log_level='CRITICAL',
        )
        run_dir = rooted / 'outputs_root' / 'b'
        resume_research(run_dir, dry_run=True, log_level='CRITICAL')
        record = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        assert record['history'] == []

    def test_a_directory_with_no_record_is_refused(self, rooted: Path) -> None:
        empty = rooted / 'outputs_root' / 'not-a-run'
        empty.mkdir(parents=True)
        with pytest.raises(ValueError, match='not a mantis run'):
            resume_research(empty, log_level='CRITICAL')

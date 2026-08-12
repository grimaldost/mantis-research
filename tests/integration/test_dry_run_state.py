"""A dry run must not be mistaken for a completed run (field defect, 2026-08-11).

A dry run wrote terminal ``status: done`` into the batch state directory, so the
next real run under the same batch name skipped every topic: the stage reported
``exit_code: 0`` and the manifest listed brief paths that did not exist. The only
visible symptom was a downstream synthesis failure pointing at the wrong stage.
Recovered from disk afterwards, ``state/research-test-20260811T175640Z/
openrouter/1.json`` reads ``status: "done"``, ``attempts: 1``,
``output_bytes: 0`` beside an ``outputs/`` tree holding nothing but ``run.json``.

That is invariant I5 read backwards. Resume is "re-run the same command", and it
works because ``done`` means the artifact is on disk — a dry run that writes
``done`` without writing the artifact makes the whole state directory lie.

The marker is additive and Optional (I4): ``dry_run`` is absent from every
historical state file, which reads as "a real run wrote this".
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mantis_research.core.config import load_batch_config
from mantis_research.core.stage import AttemptResult
from mantis_research.core.state import OpenRouterResearchState, TopicStatus
from mantis_research.interface.cli import dispatch as dispatch_mod
from mantis_research.interface.cli.dispatch import StageEntry, dispatch_stage_config
from mantis_research.interface.research_service import run_research

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import BatchConfig, TopicConfig
    from mantis_research.core.stage import RunContext
    from mantis_research.core.state import TopicState


class _CountingStage:
    """A stage that records every attempt and writes its artifact on a real run."""

    name = 'openrouter'
    state_subdir = 'openrouter'
    output_subdir = 'openrouter'
    attempts: list[str] = []  # noqa: RUF012 — class-level recorder, reset per test

    async def preflight(self) -> None:
        return

    def is_enabled(self, topic: TopicConfig, config: BatchConfig) -> bool:
        return True

    def upstream_ready(self, topic_id: str, slug: str, ctx: RunContext) -> tuple[bool, str | None]:
        return (True, None)

    async def run_attempt(
        self, topic: TopicConfig, state: TopicState, ctx: RunContext
    ) -> AttemptResult:
        type(self).attempts.append(topic.id)
        if not ctx.dry_run:
            ctx.output_dir.mkdir(parents=True, exist_ok=True)
            (ctx.output_dir / f'{topic.id}.md').write_text('a real brief', encoding='utf-8')
        return AttemptResult.ok(output_bytes=12)


def _config(batch: str = 'poisoned') -> BatchConfig:
    return load_batch_config(
        {
            'schema_version': 2,
            'batch_name': batch,
            'runner': {'layout': 'batch'},
            'models': {'claude': {}},
            'topics': [
                {
                    'id': '1',
                    'slug': 'q',
                    'title': 'a question',
                    'research_prompt': 'research this',
                    'stages': {'claude': {'prompt': ''}, 'openrouter': [{'subslug': 'openai'}]},
                }
            ],
        }
    )


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


@pytest.fixture
def counting(monkeypatch: pytest.MonkeyPatch) -> type[_CountingStage]:
    _CountingStage.attempts = []
    monkeypatch.setitem(
        dispatch_mod.STAGE_REGISTRY,
        'openrouter',
        StageEntry(
            stage_factory=_CountingStage,  # type: ignore[arg-type]
            state_class=OpenRouterResearchState,
            legacy_state_name='openrouter',
            legacy_output_name='openrouter',
        ),
    )
    return _CountingStage


class TestARealRunAfterADryRun:
    def test_the_real_run_actually_executes_the_stage(
        self, rooted: Path, counting: type[_CountingStage]
    ) -> None:
        # The regression: dry run first, then the same batch name for real. The
        # real run must attempt the topic rather than read the dry run's `done`
        # and report success over an output tree it never wrote.
        cfg = _config()
        assert dispatch_stage_config('openrouter', cfg, dry_run=True, log_level='CRITICAL') == 0
        assert counting.attempts == ['1']

        assert dispatch_stage_config('openrouter', cfg, dry_run=False, log_level='CRITICAL') == 0
        assert counting.attempts == ['1', '1'], 'the real run skipped the stage'

    def test_the_real_run_produces_the_artifact_the_state_claims(
        self, rooted: Path, counting: type[_CountingStage]
    ) -> None:
        # `done` is only meaningful because it means the artifact is on disk.
        cfg = _config()
        dispatch_stage_config('openrouter', cfg, dry_run=True, log_level='CRITICAL')
        dispatch_stage_config('openrouter', cfg, dry_run=False, log_level='CRITICAL')

        brief = rooted / 'outputs_root' / 'poisoned' / 'openrouter' / '1.md'
        state = json.loads(
            (rooted / 'state_root' / 'poisoned' / 'openrouter' / '1.json').read_text(
                encoding='utf-8'
            )
        )
        assert state['status'] == TopicStatus.DONE.value
        assert brief.exists(), 'state says done but the artifact was never written'

    def test_a_second_real_run_still_skips_a_really_done_topic(
        self, rooted: Path, counting: type[_CountingStage]
    ) -> None:
        # Resumability (I5) is unchanged for records a real run wrote: only the
        # dry run's `done` is disregarded, not every `done`.
        cfg = _config()
        dispatch_stage_config('openrouter', cfg, dry_run=False, log_level='CRITICAL')
        dispatch_stage_config('openrouter', cfg, dry_run=False, log_level='CRITICAL')
        assert counting.attempts == ['1']


class TestTheStateSaysWhichKindOfRunWroteIt:
    def test_a_dry_run_marks_its_own_records(
        self, rooted: Path, counting: type[_CountingStage]
    ) -> None:
        dispatch_stage_config('openrouter', _config(), dry_run=True, log_level='CRITICAL')
        state = json.loads(
            (rooted / 'state_root' / 'poisoned' / 'openrouter' / '1.json').read_text(
                encoding='utf-8'
            )
        )
        assert state['dry_run'] is True

    def test_a_real_run_clears_the_marker_it_inherits(
        self, rooted: Path, counting: type[_CountingStage]
    ) -> None:
        cfg = _config()
        dispatch_stage_config('openrouter', cfg, dry_run=True, log_level='CRITICAL')
        dispatch_stage_config('openrouter', cfg, dry_run=False, log_level='CRITICAL')
        state = json.loads(
            (rooted / 'state_root' / 'poisoned' / 'openrouter' / '1.json').read_text(
                encoding='utf-8'
            )
        )
        assert state['dry_run'] is None

    def test_a_historical_state_file_without_the_field_reads_as_a_real_run(self) -> None:
        # I4: the field is absent from every state file written before this
        # change, and absence must not turn a finished topic back into work.
        legacy = OpenRouterResearchState.model_validate_json(
            json.dumps({'id': '1', 'slug': 'q', 'status': 'done', 'attempts': 1})
        )
        assert legacy.dry_run is None
        assert legacy.settled is True


class TestTheRunRecordSaysItWasADryRun:
    def test_the_manifest_and_run_record_carry_the_dry_run_flag(
        self, rooted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The field artifact that started this: a run.json with `ok: true` and a
        # briefs list pointing at files that were never written. Whatever else it
        # says, it has to say it was a dry run.
        def fake_dispatch(stage: str, cfg: object, **_: object) -> int:
            return 0

        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', fake_dispatch
        )
        manifest = run_research(
            'test', assurance='fast', batch_name='dr', dry_run=True, log_level='CRITICAL'
        )
        record: dict[str, Any] = json.loads(
            (rooted / 'outputs_root' / 'dr' / 'run.json').read_text(encoding='utf-8')
        )
        assert manifest['dry_run'] is True
        assert record['dry_run'] is True

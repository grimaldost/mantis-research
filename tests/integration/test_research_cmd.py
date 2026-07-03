"""The `mantis research` one-shot command (spec 0001 §16 / ADR-0004)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import typer

from mantis_research.core.config import load_batch_config
from mantis_research.interface.cli.research import (
    _DEFAULT_SUBSTRATES,
    _TIER_STAGES,
    build_config,
    research_cmd,
    run_research,
)


def test_default_substrates_exclude_dead_perplexity() -> None:
    # perplexity's auto pick (sonar-pro-search) 404s, and one dead substrate nukes
    # the whole paid topic — it must not be a default (fresh-test finding).
    assert 'perplexity' not in _DEFAULT_SUBSTRATES
    assert _DEFAULT_SUBSTRATES == ('openai', 'deepseek', 'google')


if TYPE_CHECKING:
    from pathlib import Path


class TestTierMapping:
    def test_fast_runs_research_and_synthesis_only(self) -> None:
        assert _TIER_STAGES['fast'] == ['openrouter', 'synthesis']

    def test_standard_adds_falsification(self) -> None:
        assert _TIER_STAGES['standard'] == ['openrouter', 'synthesis', 'falsification']

    def test_high_adds_claude_prior_and_evaluation(self) -> None:
        assert _TIER_STAGES['high'] == [
            'openrouter',
            'synthesis',
            'falsification',
            'claude-prior',
            'evaluation',
        ]


class TestBuildConfig:
    def test_builds_valid_batch_config(self) -> None:
        cfg_dict = build_config(
            'How does ISO 20022 migration work?',
            substrates=['openai', 'deepseek'],
            primary='openrouter:openai',
            journal=False,
            batch_name='b',
            assurance='standard',
        )
        cfg = load_batch_config(cfg_dict)  # validates
        assert cfg.runner.layout == 'batch'
        assert cfg.models.primary == 'openrouter:openai'
        topic = cfg.topics[0]
        # research_prompt filled every openrouter substrate's omitted prompt.
        assert [e.subslug for e in topic.stages.openrouter] == ['openai', 'deepseek']
        assert topic.stages.openrouter[0].prompt  # resolved from research_prompt
        assert 'ISO 20022' in topic.stages.openrouter[0].prompt

    def test_enabled_flags_track_assurance(self) -> None:
        fast = load_batch_config(
            build_config(
                'q',
                substrates=['openai'],
                primary='openrouter:openai',
                journal=False,
                batch_name='b',
                assurance='fast',
            )
        ).topics[0]
        assert fast.stages.falsification.enabled is False
        assert fast.stages.evaluation.enabled is False

        high = load_batch_config(
            build_config(
                'q',
                substrates=['openai'],
                primary='openrouter:openai',
                journal=False,
                batch_name='b',
                assurance='high',
            )
        ).topics[0]
        assert high.stages.falsification.enabled is True
        assert high.stages.evaluation.enabled is True


class TestDryRunManifest:
    def test_dry_run_prints_batch_layout_manifest(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
            monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)

        with pytest.raises(typer.Exit) as exc:
            research_cmd(
                'test question',
                assurance='fast',
                substrates='openai,deepseek',
                batch_name='b',
                dry_run=True,
                log_level='CRITICAL',  # suppress structlog so stdout is just the manifest
            )
        assert exc.value.exit_code == 0

        manifest = json.loads(capsys.readouterr().out)
        assert manifest['layout'] == 'batch'
        assert manifest['batch_name'] == 'b'
        assert set(manifest['stages']) == {'openrouter', 'synthesis'}  # fast tier
        # Every output path is under the batch-scoped outputs tree.
        assert '/b/synthesis/' in manifest['outputs']['synthesis'].replace('\\', '/')
        assert manifest['outputs']['sidecar'].endswith('.sidecar.json')
        assert len(manifest['outputs']['briefs']) == 2
        # The batch-scoped state tree was created.
        assert (tmp_path / 'state_root' / 'b' / 'openrouter').exists()


class TestRunResearch:
    """The extracted ``run_research`` orchestrator (spec 0002 §1)."""

    def test_dry_run_returns_manifest(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
            monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
        manifest = run_research(
            'test question',
            assurance='fast',
            substrates=['openai', 'deepseek'],
            batch_name='b',
            dry_run=True,
            log_level='CRITICAL',
        )
        assert set(manifest) >= {'outputs', 'stages', 'cost', 'ok'}
        assert manifest['ok'] is True
        assert set(manifest['stages']) == {'openrouter', 'synthesis'}
        # A dry run still writes the OpenRouter state via the orchestrator's
        # unconditional save, so _read_cost finds it: available with zero
        # recorded cost (spec 0002 round-2 FM-A).
        assert manifest['cost']['available'] is True
        assert manifest['cost']['cost_usd'] == 0.0

    def test_invalid_assurance_raises_valueerror_not_typer_exit(self) -> None:
        # run_research raises no typer.Exit — the CLI wrapper maps it (FM-4).
        with pytest.raises(ValueError, match='invalid assurance'):
            run_research('q', assurance='bogus')

    def test_live_run_reports_failure_when_synthesis_blocks(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # BUG-1 regression: a live run where research succeeds but synthesis
        # blocks (e.g. a single substrate → no secondary brief) must break after
        # synthesis and report ok:False — never ok:true with no synthesis written.
        for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
            monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
        calls: list[str] = []

        def fake_dispatch(stage: str, cfg: object, *, dry_run: bool, log_level: str) -> int:
            calls.append(stage)
            return 0 if stage == 'openrouter' else 1  # synthesis blocks → exit 1

        monkeypatch.setattr(
            'mantis_research.interface.cli.dispatch.dispatch_stage_config', fake_dispatch
        )
        manifest = run_research(
            'q', assurance='standard', substrates=['openai'], batch_name='b', log_level='CRITICAL'
        )
        assert manifest['ok'] is False
        assert manifest['stages']['synthesis']['exit_code'] == 1
        assert 'falsification' not in manifest['stages']  # broke after synthesis
        assert calls == ['openrouter', 'synthesis']

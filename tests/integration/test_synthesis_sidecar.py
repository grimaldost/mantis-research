"""Sidecar emission in the synthesis stage (spec 0001 §14 / ADR-0003).

A scripted fake adapter distinguishes turns by ``options.name`` (the brief turn
is ``synthesis-topic-*``, the sidecar turn ``sidecar-topic-*``, the journal turn
carries no name) and writes the files each turn is expected to produce. Runs
non-dry-run so the sidecar sub-loop actually fires; briefs live under a batch
layout with ``outputs_root`` redirected to tmp.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from mantis_research.core import prompts as default_prompts
from mantis_research.core.config import load_batch_config
from mantis_research.core.sidecar import ResearchSidecar
from mantis_research.core.stage import RunContext
from mantis_research.core.state import SynthesisState
from mantis_research.interface.adapters.claude_cli import ClaudeCliOptions, ClaudeCliResult
from mantis_research.interface.stages.synthesis import SynthesisStage

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import BatchConfig

_VALID = json.dumps(
    {
        'sidecar_version': 1,
        'claims': [{'id': 'c1', 'text': 'a claim', 'support': 'direct'}],
        'divergences': [],
        'verification_queue': [],
        'agreements_worth_verifying': [],
        'coverage_notes': [],
    }
)
_INVALID = json.dumps({'sidecar_version': 2})  # wrong version → ValidationError


@dataclass
class ScriptedAdapter:
    """Writes the file each turn produces; sidecar content is scripted per call."""

    synthesis_path: Path
    sidecar_path: Path
    journal_path: Path
    sidecar_contents: list[str | None] = field(default_factory=lambda: [_VALID])
    brief_calls: int = 0
    sidecar_calls: int = 0
    journal_calls: int = 0

    def preflight(self) -> None:
        return None

    async def run(
        self,
        prompt: str,
        options: ClaudeCliOptions,
        transcript_path: Path,
        *,
        dry_run: bool = False,
    ) -> ClaudeCliResult:
        name = options.name or ''
        if 'sidecar-topic' in name:
            i = self.sidecar_calls
            self.sidecar_calls += 1
            content = self.sidecar_contents[i] if i < len(self.sidecar_contents) else None
            if content is not None:
                self.sidecar_path.parent.mkdir(parents=True, exist_ok=True)
                self.sidecar_path.write_text(content, encoding='utf-8')
        elif 'synthesis-topic' in name:
            self.brief_calls += 1
            self.synthesis_path.parent.mkdir(parents=True, exist_ok=True)
            self.synthesis_path.write_text('# synthesis brief', encoding='utf-8')
        else:  # journal turn (no name)
            self.journal_calls += 1
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            self.journal_path.write_text('journal', encoding='utf-8')
        return ClaudeCliResult(success=True, exit_code=0, duration_s=1.0, session_id='s')


def _config() -> BatchConfig:
    return load_batch_config(
        {
            'schema_version': 2,
            'batch_name': 'sc',
            'runner': {'layout': 'batch'},
            'models': {'claude': {'model': 'claude-opus-4-7', 'effort': 'max'}},
            'topics': [
                {'id': '1', 'slug': 't', 'title': 'T', 'stages': {'claude': {'prompt': 'p'}}}
            ],
        }
    )


@pytest.fixture
def paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    monkeypatch.setattr('mantis_research.core.paths.outputs_root', lambda: tmp_path)
    for stage in ('claude', 'gemini'):
        d = tmp_path / 'sc' / stage
        d.mkdir(parents=True, exist_ok=True)
        (d / '01-t.md').write_text(f'{stage} brief', encoding='utf-8')
    return {
        'synthesis': tmp_path / 'sc' / 'synthesis' / '01-t.md',
        'sidecar': tmp_path / 'sc' / 'synthesis' / '01-t.sidecar.json',
        'journal': tmp_path / 'sc' / 'journals' / '01-t-journal.md',
    }


async def _run(adapter: ScriptedAdapter, cfg: BatchConfig, tmp_path: Path, state: SynthesisState):
    stage = SynthesisStage(adapter=adapter)  # type: ignore[arg-type]
    ctx = RunContext(
        batch=cfg,
        state_dir=tmp_path / 'state',
        output_dir=tmp_path / 'out',
        transcript_dir=tmp_path / 'tx',
        dry_run=False,
    )
    return await stage.run_attempt(cfg.topics[0], state, ctx)


class TestSidecarEmission:
    async def test_valid_sidecar_merges_both_zones(self, paths, tmp_path: Path) -> None:
        adapter = ScriptedAdapter(paths['synthesis'], paths['sidecar'], paths['journal'], [_VALID])
        state = SynthesisState(id='1', slug='t')
        result = await _run(adapter, _config(), tmp_path, state)
        assert result.success
        assert adapter.brief_calls == 1
        assert adapter.sidecar_calls == 1
        # Merged file has both the model zone (claims) and the runner zone (identity).
        merged = ResearchSidecar.from_model_json(paths['sidecar'].read_text(encoding='utf-8'))
        assert merged.claims[0].id == 'c1'
        assert merged.topic_id == '1'
        assert merged.batch_name == 'sc'
        assert merged.sources  # runner filled source refs
        assert state.sidecar_bytes is not None

    async def test_provenance_filled_from_openrouter_state(
        self, paths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The synthesis stage reads the OpenRouter state's per-subsession costs and
        # aggregates them into the sidecar's provenance (A1).
        monkeypatch.setattr('mantis_research.core.paths.state_root', lambda: tmp_path / 'state')
        or_dir = tmp_path / 'state' / 'sc' / 'openrouter'
        or_dir.mkdir(parents=True, exist_ok=True)
        (or_dir / '1.json').write_text(
            json.dumps(
                {
                    'id': '1',
                    'slug': 't',
                    'status': 'done',
                    'subsessions': [
                        {
                            'subslug': 'gpt-5-exa',
                            'status': 'done',
                            'cost_usd': 0.02,
                            'tokens_prompt': 1000,
                            'tokens_completion': 500,
                        },
                        {
                            'subslug': 'gemini-3-pro',
                            'status': 'done',
                            'cost_usd': 0.03,
                            'tokens_prompt': 2000,
                            'tokens_completion': 800,
                        },
                    ],
                }
            ),
            encoding='utf-8',
        )
        adapter = ScriptedAdapter(paths['synthesis'], paths['sidecar'], paths['journal'], [_VALID])
        result = await _run(adapter, _config(), tmp_path, SynthesisState(id='1', slug='t'))
        assert result.success
        prov = ResearchSidecar.from_model_json(
            paths['sidecar'].read_text(encoding='utf-8')
        ).provenance
        assert prov.total_cost_usd == pytest.approx(0.05)
        assert prov.total_tokens_prompt == 3000
        assert prov.total_tokens_completion == 1300
        assert prov.per_source_cost_usd == {'gpt-5-exa': 0.02, 'gemini-3-pro': 0.03}
        assert prov.synthesis_duration_s is not None  # runner still fills timing

    async def test_invalid_then_valid_reasks_without_second_brief(
        self, paths, tmp_path: Path
    ) -> None:
        adapter = ScriptedAdapter(
            paths['synthesis'], paths['sidecar'], paths['journal'], [_INVALID, _VALID]
        )
        result = await _run(adapter, _config(), tmp_path, SynthesisState(id='1', slug='t'))
        assert result.success
        assert adapter.brief_calls == 1  # brief generated exactly once
        assert adapter.sidecar_calls == 2  # one re-ask

    async def test_all_invalid_fails_with_brief_intact(self, paths, tmp_path: Path) -> None:
        adapter = ScriptedAdapter(
            paths['synthesis'], paths['sidecar'], paths['journal'], [_INVALID, _INVALID, _INVALID]
        )
        result = await _run(adapter, _config(), tmp_path, SynthesisState(id='1', slug='t'))
        assert not result.success
        assert adapter.sidecar_calls == 3  # exhausted the budget
        assert paths['synthesis'].exists()  # brief left intact for the next attempt
        assert adapter.journal_calls == 0  # never reached the journal

    async def test_retry_after_failure_does_not_recall_turn1(self, paths, tmp_path: Path) -> None:
        state = SynthesisState(id='1', slug='t')
        cfg = _config()
        # First attempt: sidecar exhausts → fail, but the brief is written and sized.
        first = ScriptedAdapter(
            paths['synthesis'], paths['sidecar'], paths['journal'], [_INVALID, _INVALID, _INVALID]
        )
        r1 = await _run(first, cfg, tmp_path, state)
        assert not r1.success
        assert first.brief_calls == 1
        assert state.synthesis_bytes  # recorded → re-entry will skip Turn 1

        # Orchestrator retry with the SAME state: brief exists, so Turn 1 is skipped.
        second = ScriptedAdapter(paths['synthesis'], paths['sidecar'], paths['journal'], [_VALID])
        r2 = await _run(second, cfg, tmp_path, state)
        assert r2.success
        assert second.brief_calls == 0  # Turn 1 NOT re-called on re-entry
        assert second.sidecar_calls == 1


def test_sidecar_prompt_formats_without_brace_error() -> None:
    # FM-6: the JSON example must be brace-escaped so str.format only binds the
    # two real keys. A bare brace would raise here (and break every synthesis).
    out = default_prompts.SYNTHESIS_SIDECAR.format(
        synthesis_path='/x/01-t.md', sidecar_path='/x/01-t.sidecar.json'
    )
    assert '/x/01-t.sidecar.json' in out
    assert '"sidecar_version": 1' in out  # the literal JSON survived intact

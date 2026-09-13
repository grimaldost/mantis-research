"""The sidecar's outcome is its own, and its published path is written once.

Three reports, one shape: a synthesis document complete on disk — 45 to 63 KB,
ending in a proper conclusion — and the run reporting `ok: false` with
`synthesis.exit_code: 1`, because `run_attempt` returned a single
`AttemptResult` for Turn 1 and the sidecar loop together. The topic was marked
FAILED, the pipeline stopped before falsification, and the paid work read as a
failed run. ADR-0011 splits the two outcomes.

A fourth finding in the same wave: a sidecar could be observed on disk with
`sources: []` and `provenance: {}` — the model's own draft, written straight to
the path that means "finished", before the runner had merged anything into it.
The model now writes a draft and the runner renames the merged document into
place, so the published path only ever holds a whole one.

The scripted adapter here writes wherever the prompt tells it to, rather than to
a path the test hard-codes — that is the contract under test.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mantis_research.core.config import load_batch_config
from mantis_research.core.sidecar import ResearchSidecar, SidecarOutcome
from mantis_research.core.stage import RunContext
from mantis_research.core.state import SynthesisState
from mantis_research.interface.adapters.claude_cli import ClaudeCliOptions, ClaudeCliResult
from mantis_research.interface.stages.synthesis import SynthesisStage

if TYPE_CHECKING:
    from mantis_research.core.config import BatchConfig

_VALID = json.dumps(
    {
        'sidecar_version': 2,
        'claims': [{'id': 'c1', 'text': 'a claim', 'support': 'direct'}],
        'divergences': [],
        'verification_queue': [],
        'agreements_worth_verifying': [],
        'coverage_notes': [],
    }
)
_INVALID = json.dumps({'sidecar_version': 99})  # unknown version → ValidationError

_TARGET = re.compile(r'(\S+\.sidecar(?:\.draft)?\.json)')


def _write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')


@dataclass
class ScriptedAdapter:
    """Writes each turn's artifact, and the sidecar wherever the prompt says."""

    synthesis_path: Path
    published_sidecar: Path
    journal_path: Path
    sidecar_contents: list[str | None] = field(default_factory=lambda: [_VALID])
    sidecar_calls: int = 0
    brief_calls: int = 0
    journal_calls: int = 0
    #: Where the sidecar turn was told to write — the contract T16b changes.
    wrote_sidecar_to: Path | None = None
    #: Whether the published path already existed when the model wrote its own
    #: document. True means a watcher could read a half-made sidecar as done.
    published_existed_when_model_wrote: bool | None = None

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
            index = self.sidecar_calls
            self.sidecar_calls += 1
            content = self.sidecar_contents[index] if index < len(self.sidecar_contents) else None
            match = _TARGET.search(prompt)
            assert match is not None, 'the sidecar prompt must name a path to write'
            target = Path(match.group(1))
            self.wrote_sidecar_to = target
            if content is not None:
                self.published_existed_when_model_wrote = self.published_sidecar.exists()
                _write(target, content)
        elif 'synthesis-topic' in name:
            self.brief_calls += 1
            _write(self.synthesis_path, '# synthesis brief')
        else:
            self.journal_calls += 1
            _write(self.journal_path, 'journal')
        return ClaudeCliResult(success=True, exit_code=0, duration_s=1.0, session_id='s')


def _config(*, journal: bool = False) -> BatchConfig:
    return load_batch_config(
        {
            'schema_version': 2,
            'batch_name': 'sc',
            'runner': {'layout': 'batch'},
            'models': {'claude': {'model': 'claude-opus-4-7', 'effort': 'max'}},
            'topics': [
                {
                    'id': '1',
                    'slug': 't',
                    'title': 'T',
                    'stages': {'claude': {'prompt': 'p'}, 'journal': {'enabled': journal}},
                }
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


def _adapter(paths: dict[str, Path], contents: list[str | None]) -> ScriptedAdapter:
    return ScriptedAdapter(paths['synthesis'], paths['sidecar'], paths['journal'], contents)


async def _attempt(
    adapter: ScriptedAdapter,
    state: SynthesisState,
    tmp_path: Path,
    cfg: BatchConfig | None = None,
):
    config = cfg or _config()
    stage = SynthesisStage(adapter=adapter)  # type: ignore[arg-type]
    ctx = RunContext(
        batch=config,
        state_dir=tmp_path / 'state',
        output_dir=tmp_path / 'out',
        transcript_dir=tmp_path / 'tx',
        dry_run=False,
    )
    return await stage.run_attempt(config.topics[0], state, ctx)


class TestAFailedSidecarDoesNotRetractTheSynthesis:
    async def test_the_attempt_succeeds_when_only_the_sidecar_failed(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        adapter = _adapter(paths, [_INVALID, _INVALID, _INVALID])
        result = await _attempt(adapter, SynthesisState(id='1', slug='t'), tmp_path)
        assert result.success is True
        assert adapter.sidecar_calls == 3  # the re-ask budget was still spent
        assert paths['synthesis'].exists()

    async def test_the_failure_is_named_rather_than_swallowed(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        # Succeeding quietly would be the opposite error: the caller has to be
        # able to tell a run with an epistemic contract from one without.
        state = SynthesisState(id='1', slug='t')
        result = await _attempt(_adapter(paths, [_INVALID, _INVALID, _INVALID]), state, tmp_path)
        assert state.sidecar_status is SidecarOutcome.FAILED
        assert state.sidecar_error
        assert result.extras['sidecar'] == SidecarOutcome.FAILED.value

    async def test_a_good_sidecar_is_recorded_as_such(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        state = SynthesisState(id='1', slug='t')
        result = await _attempt(_adapter(paths, [_VALID]), state, tmp_path)
        assert result.success is True
        assert state.sidecar_status is SidecarOutcome.OK
        assert state.sidecar_error is None
        assert result.extras['sidecar'] == SidecarOutcome.OK.value

    async def test_the_journal_turn_still_runs_after_a_failed_sidecar(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        # The journal is a third artifact, not a consequence of the second.
        adapter = _adapter(paths, [_INVALID, _INVALID, _INVALID])
        await _attempt(adapter, SynthesisState(id='1', slug='t'), tmp_path, _config(journal=True))
        assert adapter.journal_calls == 1

    async def test_a_runner_side_contract_gap_is_also_a_sidecar_outcome(
        self, paths: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `require_complete()` guards the runner-authored zone, so re-asking the
        # model cannot fix it — but neither can regenerating the synthesis, which
        # is what failing the attempt bought. It is reported, loudly, on the
        # sidecar's own axis, and no hollow document is published.
        monkeypatch.setattr(
            'mantis_research.interface.stages.synthesis.SynthesisStage._fill_runner_fields',
            staticmethod(lambda sc, *a, **k: sc.model_copy(update={'question': None})),
        )
        adapter = _adapter(paths, [_VALID])
        state = SynthesisState(id='1', slug='t')
        result = await _attempt(adapter, state, tmp_path)
        assert result.success is True
        assert state.sidecar_status is SidecarOutcome.FAILED
        assert 'question' in (state.sidecar_error or '')
        assert not paths['sidecar'].exists()
        assert adapter.sidecar_calls == 1  # no re-ask burned on a runner-side gap


class TestThePublishedSidecarIsWrittenOnce:
    async def test_the_model_writes_a_draft_not_the_published_path(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        adapter = _adapter(paths, [_VALID])
        await _attempt(adapter, SynthesisState(id='1', slug='t'), tmp_path)
        assert adapter.wrote_sidecar_to is not None
        assert adapter.wrote_sidecar_to != paths['sidecar']
        assert adapter.wrote_sidecar_to.name.endswith('.sidecar.draft.json')

    async def test_nothing_appears_at_the_published_path_before_the_merge(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        # The reported hazard, directly: a watcher keyed on the sidecar's
        # presence used to read the model's own document — `sources: []`,
        # `provenance: {}` — as a finished one.
        adapter = _adapter(paths, [_VALID])
        await _attempt(adapter, SynthesisState(id='1', slug='t'), tmp_path)
        assert adapter.published_existed_when_model_wrote is False

    async def test_the_published_document_carries_the_runner_zone(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        await _attempt(_adapter(paths, [_VALID]), SynthesisState(id='1', slug='t'), tmp_path)
        merged = ResearchSidecar.from_model_json(paths['sidecar'].read_text(encoding='utf-8'))
        assert merged.question == 'T'
        assert merged.sources

    async def test_no_draft_or_temp_file_is_left_behind(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        await _attempt(_adapter(paths, [_VALID]), SynthesisState(id='1', slug='t'), tmp_path)
        leftovers = sorted(
            p.name
            for p in paths['sidecar'].parent.iterdir()
            if p.name.endswith(('.draft.json', '.tmp'))
        )
        assert leftovers == []

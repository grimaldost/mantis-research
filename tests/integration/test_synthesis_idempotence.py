"""Turn 1's product is recorded from disk, not from a variable after the call.

Field evidence, three reports: a retry re-ran the whole synthesis turn and
overwrote a finished document with a differently-structured one before failing
again — 60,542 B → 57,271 B, 11 sections → 14, on a run whose briefs and
synthesis were already paid for. The triage could not explain it, because
`run_attempt`'s guard (``need_brief = not (synthesis_path.exists() and
state.synthesis_bytes)``) reads correct for a same-process retry.

The reproduction is here. `state.synthesis_bytes` was assigned *after* the
adapter call, so an adapter that raises — which is exactly what the stream-limit
overrun does, and the model has usually written the document by then — unwinds
straight past the assignment. The guard then sees a file on disk with no
recorded size, calls that "no brief yet", and buys the expensive turn again.

The fix records what is on disk in a ``finally``, against a fingerprint taken
before the turn, so the record cannot be skipped and a stale document from an
earlier run cannot be adopted as this turn's work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from mantis_research.core.config import load_batch_config
from mantis_research.core.stage import RunContext
from mantis_research.core.state import SynthesisState
from mantis_research.interface.adapters.claude_cli import ClaudeCliOptions, ClaudeCliResult
from mantis_research.interface.stages.synthesis import SynthesisStage

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import BatchConfig

#: asyncio's own text, verbatim — the exception the local-seat reader raised on
#: a long synthesis line before the ceiling was declared.
_OVERRUN = 'Separator is found, but chunk is longer than limit'


@dataclass
class ScriptedTurns:
    """A synthesis adapter whose Turn 1 can write, raise, or both."""

    synthesis_path: Path
    journal_path: Path
    #: Written by Turn 1 before it decides whether to raise. None writes nothing.
    turn_1_text: str | None = '# synthesis\n' + 'body\n' * 200
    #: Raised by Turn 1 after the write, standing in for the stream overrun.
    turn_1_raises: Exception | None = None
    brief_calls: int = 0
    journal_calls: int = 0
    sidecar_calls: list[str] = field(default_factory=list)

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
            self.sidecar_calls.append(name)
            return ClaudeCliResult(success=False, exit_code=1, duration_s=0.1, error='no sidecar')
        if 'synthesis-topic' in name:
            self.brief_calls += 1
            if self.turn_1_text is not None:
                self.synthesis_path.parent.mkdir(parents=True, exist_ok=True)
                self.synthesis_path.write_text(self.turn_1_text, encoding='utf-8')
            if self.turn_1_raises is not None:
                raise self.turn_1_raises
        else:
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
                {
                    'id': '1',
                    'slug': 't',
                    'title': 'T',
                    'stages': {'claude': {'prompt': 'p'}, 'journal': {'enabled': False}},
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
        'journal': tmp_path / 'sc' / 'journals' / '01-t-journal.md',
    }


async def _attempt(adapter: ScriptedTurns, state: SynthesisState, tmp_path: Path):
    cfg = _config()
    stage = SynthesisStage(adapter=adapter)  # type: ignore[arg-type]
    ctx = RunContext(
        batch=cfg,
        state_dir=tmp_path / 'state',
        output_dir=tmp_path / 'out',
        transcript_dir=tmp_path / 'tx',
        dry_run=False,
    )
    return await stage.run_attempt(cfg.topics[0], state, ctx)


class TestATurnThatRaisesStillRecordsWhatItWrote:
    async def test_the_product_is_recorded_when_the_turn_ends_by_raising(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        state = SynthesisState(id='1', slug='t')
        crashing = ScriptedTurns(
            paths['synthesis'], paths['journal'], turn_1_raises=ValueError(_OVERRUN)
        )
        with pytest.raises(ValueError, match='chunk is longer than limit'):
            await _attempt(crashing, state, tmp_path)
        assert paths['synthesis'].exists()
        assert state.synthesis_bytes == paths['synthesis'].stat().st_size

    async def test_the_next_attempt_does_not_re_buy_the_synthesis(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        state = SynthesisState(id='1', slug='t')
        crashing = ScriptedTurns(
            paths['synthesis'], paths['journal'], turn_1_raises=ValueError(_OVERRUN)
        )
        with pytest.raises(ValueError, match='chunk is longer than limit'):
            await _attempt(crashing, state, tmp_path)
        first = paths['synthesis'].read_text(encoding='utf-8')

        # The orchestrator retries with the SAME state object it passed in.
        second = ScriptedTurns(
            paths['synthesis'], paths['journal'], turn_1_text='# a different synthesis\n'
        )
        await _attempt(second, state, tmp_path)
        assert second.brief_calls == 0
        assert paths['synthesis'].read_text(encoding='utf-8') == first

    async def test_a_turn_that_wrote_nothing_records_nothing(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        # The mirror case: if the turn died before writing, the next attempt
        # must still buy Turn 1.
        state = SynthesisState(id='1', slug='t')
        crashing = ScriptedTurns(
            paths['synthesis'],
            paths['journal'],
            turn_1_text=None,
            turn_1_raises=ValueError(_OVERRUN),
        )
        with pytest.raises(ValueError, match='chunk is longer than limit'):
            await _attempt(crashing, state, tmp_path)
        assert not state.synthesis_bytes

        second = ScriptedTurns(paths['synthesis'], paths['journal'])
        await _attempt(second, state, tmp_path)
        assert second.brief_calls == 1

    async def test_a_stale_document_is_not_adopted_as_this_turn_s_work(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        # `--force` clears state but not outputs (invariant I5), so a synthesis
        # from an earlier run can already be on disk when Turn 1 is asked to
        # regenerate it. A turn that raises without writing must leave that
        # document unclaimed, or the retry would ship the stale one.
        paths['synthesis'].parent.mkdir(parents=True, exist_ok=True)
        paths['synthesis'].write_text('# a synthesis from an earlier run\n', encoding='utf-8')
        state = SynthesisState(id='1', slug='t')
        crashing = ScriptedTurns(
            paths['synthesis'],
            paths['journal'],
            turn_1_text=None,
            turn_1_raises=ValueError(_OVERRUN),
        )
        with pytest.raises(ValueError, match='chunk is longer than limit'):
            await _attempt(crashing, state, tmp_path)
        assert not state.synthesis_bytes

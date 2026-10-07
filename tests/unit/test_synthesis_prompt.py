"""The synthesis prompt describes the run it is actually in (backlog MANT-B05).

The Path-B pivot reached the code and the docs but never the prompt bodies.
`SYNTHESIS` still opened "merge two LLM-produced briefs", asked for the most
divergent passages "between the Claude and Gemini briefs", asserted that "the
structure follows Claude's brief", explained a Gemini router quirk, and closed
with an independence paragraph describing the run as one model integrating its
own brief plus a cross-check. None of that was true on a default
three-substrate run: the model was told a false story about its own inputs on
every run, and all six syntheses in one batch independently detected and
corrected the label mismatch.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from mantis_research.core.paths import RunDirs
from mantis_research.core.prompts import SYNTHESIS
from mantis_research.interface.stages import synthesis as syn

if TYPE_CHECKING:
    from pathlib import Path

_PLACEHOLDERS = frozenset(re.findall(r'{(\w+)[^}]*}', SYNTHESIS))
_DIRS = RunDirs(layout='batch', batch_name='b')


class TestSubstrateNeutral:
    def test_no_vendor_is_named_in_the_template_body(self) -> None:
        # Vendor names reach the prompt only through the run's own labels.
        body = SYNTHESIS.lower()
        for vendor in ('claude', 'gemini', 'openai', 'deepseek'):
            assert vendor not in body, f'{vendor!r} is hard-coded in the synthesis template'

    def test_the_brief_count_comes_from_the_run(self) -> None:
        assert 'source_count' in _PLACEHOLDERS
        assert 'two LLM-produced briefs' not in SYNTHESIS

    def test_the_independence_note_names_the_substrates_actually_used(self) -> None:
        assert 'substrate_list' in _PLACEHOLDERS

    def test_the_independence_note_carries_the_measured_retrieval_overlap(self) -> None:
        # T5e: two briefs citing the same URLs share retrieval, which the note
        # spoke of only as shared training substrate.
        assert 'retrieval_overlap' in _PLACEHOLDERS
        note = SYNTHESIS.split('**Independence note.**', 1)[1].split('\n', 1)[0]
        assert '{retrieval_overlap}' in note
        assert 'shared retrieval, not independent confirmation' in note

    def test_the_primary_slot_uses_the_primary_vocabulary(self) -> None:
        # The template read the legacy {claude_path} / {gemini_block} aliases, so
        # a three-substrate run rendered the right paths underneath prose that
        # named the wrong models.
        assert {'primary_path', 'primary_label', 'secondary_block', 'secondary_count'} <= (
            _PLACEHOLDERS
        )

    def test_the_retired_pre_pivot_clauses_are_gone(self) -> None:
        for clause in (
            'router',  # the gemini-3-flash router note
            'structure follows',  # "the structure follows Claude's brief"
            'integrating its own brief',  # the two-model independence paragraph
        ):
            assert clause not in SYNTHESIS


class TestCoHallucinationRule:
    def test_agreement_without_a_primary_source_is_a_flag(self) -> None:
        # Two substrates co-hallucinated the same fake source and the synthesis
        # promoted it to a recommendation on the strength of their agreement;
        # the same class recurred as a whole invented repository.
        assert 'CO-HALLUCINATION FLAG' in SYNTHESIS
        assert 'never promote one to a recommendation' in SYNTHESIS

    def test_the_rule_covers_named_artifacts_not_only_citations(self) -> None:
        for artifact in ('repository slugs', 'package names', 'URLs'):
            assert artifact in SYNTHESIS


class TestRenderedLabels:
    """The rendered prompt names each brief by the label the sidecar records (T30a)."""

    @pytest.fixture
    def path_b(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> syn._Briefs:
        monkeypatch.setattr('mantis_research.core.paths.outputs_root', lambda: tmp_path)
        for subslug in ('openai', 'deepseek', 'google'):
            brief = tmp_path / 'b' / 'openrouter' / '01-t' / f'{subslug}.md'
            brief.parent.mkdir(parents=True, exist_ok=True)
            brief.write_text(f'{subslug} brief', encoding='utf-8')
        return syn._resolve_briefs(_DIRS, '1', 't', 'openrouter:openai')

    def _render(self, briefs: syn._Briefs, tmp_path: Path) -> str:
        assert briefs.primary_path is not None
        return syn._synthesis_prompt(
            SYNTHESIS, briefs, briefs.primary_path, tmp_path / 'synthesis.md'
        )

    def test_the_secondary_block_names_each_subslug(
        self, path_b: syn._Briefs, tmp_path: Path
    ) -> None:
        rendered = self._render(path_b, tmp_path)
        secondary = rendered.split('<source role="secondary"', 1)[1].split('</source>', 1)[0]
        labels = re.findall(r'^- \[([^\]]+)\]', secondary, flags=re.MULTILINE)
        assert sorted(labels) == ['openrouter:deepseek', 'openrouter:google']

    def test_the_independence_note_names_each_subslug(
        self, path_b: syn._Briefs, tmp_path: Path
    ) -> None:
        rendered = self._render(path_b, tmp_path)
        note = rendered.split('**Independence note.**', 1)[1].split('\n', 1)[0]
        merged_from = note.split('merges briefs from: ', 1)[1].split('. ', 1)[0]
        assert merged_from.split(', ') == [
            'openrouter:openai',
            'openrouter:deepseek',
            'openrouter:google',
        ]


class TestRenderedRetrievalOverlap:
    """The rendered independence note shows each pair's cited-URL overlap (T5e)."""

    _POOL = '\n'.join(f'- claim [src](https://pool.example/{i}?utm_source=x)' for i in range(5))
    _OTHER = '\n'.join(f'- claim [src](https://elsewhere.example/{i})' for i in range(10))

    @pytest.fixture
    def briefs(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> syn._Briefs:
        monkeypatch.setattr('mantis_research.core.paths.outputs_root', lambda: tmp_path)
        # The 2026-09-27 shape: two briefs share one 5-URL set, the third is disjoint.
        texts = {'openai': self._OTHER, 'deepseek': self._POOL, 'google': self._POOL}
        for subslug, text in texts.items():
            brief = tmp_path / 'b' / 'openrouter' / '01-t' / f'{subslug}.md'
            brief.parent.mkdir(parents=True, exist_ok=True)
            brief.write_text(text, encoding='utf-8')
        return syn._resolve_briefs(_DIRS, '1', 't', 'openrouter:openai')

    def test_the_note_shows_the_overlap_line(self, briefs: syn._Briefs, tmp_path: Path) -> None:
        assert briefs.primary_path is not None
        rendered = syn._synthesis_prompt(
            SYNTHESIS, briefs, briefs.primary_path, tmp_path / 'synthesis.md'
        )
        note = rendered.split('**Independence note.**', 1)[1].split('\n', 1)[0]
        assert (
            'openrouter:openai / openrouter:deepseek 0.00; '
            'openrouter:openai / openrouter:google 0.00; '
            'openrouter:deepseek / openrouter:google 1.00'
        ) in note

    def test_a_custom_template_without_the_placeholder_still_renders(
        self, briefs: syn._Briefs, tmp_path: Path
    ) -> None:
        assert briefs.primary_path is not None
        synthesis_path = tmp_path / 'synthesis.md'
        rendered = syn._synthesis_prompt(
            'Merge {source_count} briefs into {synthesis_path}.',
            briefs,
            briefs.primary_path,
            synthesis_path,
        )
        assert rendered == f'Merge 3 briefs into {synthesis_path.as_posix()}.'


class TestPreserved:
    def test_the_steelmanned_divergence_block_survives(self) -> None:
        assert '**Divergence:**' in SYNTHESIS
        assert 'Steelmanning required' in SYNTHESIS
        assert "Don't quietly average" in SYNTHESIS

    def test_shared_substrate_weakens_agreement_survives(self) -> None:
        assert 'WEAKER signal than intuition suggests' in SYNTHESIS
        assert 'share substrate' in SYNTHESIS

    def test_do_not_manufacture_divergences_survives(self) -> None:
        assert 'do NOT manufacture divergences' in SYNTHESIS

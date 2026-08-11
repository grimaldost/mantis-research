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

from mantis_research.core.prompts import SYNTHESIS

_PLACEHOLDERS = frozenset(re.findall(r'{(\w+)[^}]*}', SYNTHESIS))


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

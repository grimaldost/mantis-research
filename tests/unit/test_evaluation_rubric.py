"""The evaluation rubric scores what a Path-B run produces (backlog MANT-B14).

The stage has run once in 19 runs and that record is a vacuous-gate signature:
verdict PASS, Q = 0.944, all three gates untriggered, five of six criteria at
3/3 — including C5, which scored the presence of a section only the retired
Path-A scaffold ever produced. Scoring 3/3 for a section the input cannot
contain is direct evidence the rubric was not discriminating.

Fixed here by inspection: the two named source blocks become the N-peer-brief
shape, C5 scores actionable content rather than a section, and the hardcoded
evaluator-model literal (which the model overrode in the one real record
anyway) is gone. Whether the gates can reject a deliberately degraded synthesis
is a separate measurement (MANT-B14's replay), and MANT-B50's retirement waits
on it.
"""

from __future__ import annotations

import re

from mantis_research.core.prompts import EVALUATION

_PLACEHOLDERS = frozenset(re.findall(r'{(\w+)[^}]*}', EVALUATION))


def test_the_source_blocks_take_the_peer_brief_shape() -> None:
    assert '<source role="peer-briefs"' in EVALUATION
    assert 'claude-original' not in EVALUATION
    assert 'gemini-originals' not in EVALUATION
    assert {'secondary_count', 'secondary_block'} <= _PLACEHOLDERS


def test_c5_scores_content_not_the_presence_of_a_section() -> None:
    # The retired Path-A scaffold's §7 is what C5 used to look for.
    assert '§7' not in EVALUATION
    assert 'Score what the synthesis says, not whether it has a particular section' in EVALUATION


def test_no_evaluator_model_is_hardcoded() -> None:
    # The one real evaluation record overrode the literal; a pinned id in a
    # template is a fact that rots without anything noticing.
    assert 'claude-opus-4-7' not in EVALUATION
    assert '"evaluator_model": "<the model id you are actually running as>"' in EVALUATION


def test_the_gates_and_the_verdict_logic_are_untouched() -> None:
    # This change fixes what the rubric reads; whether the gates can reject is
    # the open measurement, and nothing here should pre-empt it.
    for gate in ('gate_1_confabulation', 'gate_2_vacuity', 'gate_3_parroting'):
        assert gate in EVALUATION
    for verdict in ('REJECT_GATE_1', 'REJECT_GATE_2', 'PASS_WITH_PARROTING_PENALTY'):
        assert verdict in EVALUATION

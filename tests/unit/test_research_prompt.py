"""research_prompt templating + presence-not-truthiness resolution (spec §10).

The load-bearing case is the empty string: 163 committed Path-B topics carry
``claude.prompt == ""``, so resolution must key on ``is not None``, never
truthiness (which would drop ``""`` to the fallback and reject those configs).

The default template a ``mantis research`` question is formatted into,
``RESEARCH_REQUEST``, is pinned at the end: its provenance rule (T25a).
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from mantis_research.core.config import load_batch_config
from mantis_research.core.prompts import RESEARCH_REQUEST


def _cfg(topic: dict[str, object]) -> dict[str, object]:
    return {
        'schema_version': 2,
        'batch_name': 'rp',
        'models': {'claude': {'model': 'claude-opus-4-7'}},
        'topics': [{'id': '1', 'slug': 't', 'title': 'T', **topic}],
    }


def _load_topic(topic: dict[str, object]):
    return load_batch_config(_cfg(topic)).topics[0]


class TestResolution:
    def test_own_non_empty_prompt_wins(self) -> None:
        t = _load_topic(
            {
                'research_prompt': 'FALLBACK',
                'stages': {'claude': {'prompt': 'OWN'}},
            }
        )
        assert t.stages.claude.prompt == 'OWN'

    def test_own_empty_string_prompt_wins_no_fallback(self) -> None:
        # The FM-1 case: '' is explicitly set (present), so it must be kept,
        # not replaced by research_prompt.
        t = _load_topic(
            {
                'research_prompt': 'FALLBACK',
                'stages': {'claude': {'prompt': ''}},
            }
        )
        assert t.stages.claude.prompt == ''

    def test_omitted_prompt_falls_back_to_research_prompt(self) -> None:
        t = _load_topic(
            {
                'research_prompt': 'FALLBACK',
                'stages': {'claude': {}},
            }
        )
        assert t.stages.claude.prompt == 'FALLBACK'

    def test_openrouter_subsession_falls_back(self) -> None:
        t = _load_topic(
            {
                'research_prompt': 'FALLBACK',
                'stages': {
                    'claude': {'prompt': 'c'},
                    'openrouter': [{'subslug': 'gpt', 'model': 'openai/gpt-5'}],
                },
            }
        )
        assert t.stages.openrouter[0].prompt == 'FALLBACK'


class TestFailFast:
    def test_no_prompt_and_no_fallback_raises_naming_topic_and_subslug(self) -> None:
        with pytest.raises(ValidationError) as exc:
            _load_topic({'stages': {'claude': {}}})
        msg = str(exc.value)
        assert "'1'" in msg  # topic id
        assert 'claude' in msg  # subsession

    def test_openrouter_missing_prompt_no_fallback_raises(self) -> None:
        with pytest.raises(ValidationError) as exc:
            _load_topic(
                {
                    'stages': {
                        'claude': {'prompt': 'c'},
                        'openrouter': [{'subslug': 'gpt', 'model': 'openai/gpt-5'}],
                    }
                }
            )
        assert 'gpt' in str(exc.value)


# The one provenance rule of RESEARCH_REQUEST (T25a). Briefs attached confident
# numbers (stars, versions, benchmark scores) to repositories and papers the model
# only remembered; the rule makes each named artifact say where it came from.
_PROVENANCE_RULE = (
    'For every named repository, paper, product or benchmark, state whether you'
    ' retrieved it this turn or recall it from training, and attach no specific'
    ' numbers (stars, versions, scores, latencies) to one you only recall; mark'
    ' anything you cannot verify either way "Not found" instead of inventing it.'
)
_OLD_NOT_FOUND = 'Mark anything you cannot verify "Not found" instead of inventing it.'


class TestResearchRequestProvenance:
    def test_the_provenance_rule_is_in_the_method(self) -> None:
        method = re.search(r'<method>\n(.*?)\n</method>', RESEARCH_REQUEST, re.DOTALL)
        assert method is not None
        # Rewritten in place: the method stays one paragraph, no line is added.
        assert '\n' not in method.group(1)
        assert _PROVENANCE_RULE in method.group(1)

    def test_the_old_not_found_sentence_is_gone(self) -> None:
        assert _OLD_NOT_FOUND not in RESEARCH_REQUEST
        # "Not found" is asked for in one place, the provenance rule.
        assert RESEARCH_REQUEST.count('"Not found"') == 1

    def test_the_template_still_formats(self) -> None:
        rendered = RESEARCH_REQUEST.format(question='q')
        assert '<question>\nq\n</question>' in rendered
        assert _PROVENANCE_RULE in rendered

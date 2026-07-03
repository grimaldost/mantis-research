"""research_prompt templating + presence-not-truthiness resolution (spec §10).

The load-bearing case is the empty string: 163 committed Path-B topics carry
``claude.prompt == ""``, so resolution must key on ``is not None``, never
truthiness (which would drop ``""`` to the fallback and reject those configs).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mantis_research.core.config import load_batch_config


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

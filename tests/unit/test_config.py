"""Unit tests for mantis_research.core.config."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from mantis_research.core.config import (
    BatchConfig,
    ClaudeStageConfig,
    GeminiSubsessionConfig,
    OpenRouterSubsessionConfig,
    TopicStages,
    load_batch_config,
)

if TYPE_CHECKING:
    from pathlib import Path

# ── canonical-ish minimum config fixture ─────────────────────────────


def _minimal_config_dict() -> dict[str, object]:
    return {
        'schema_version': 2,
        'batch_name': 'test-batch',
        'description': 'fixture',
        'models': {'claude': {'model': 'claude-opus-4-7', 'effort': 'max'}},
        'runner': {
            'max_parallel_topics': 4,
            'max_retries_per_stage': 2,
            'rate_limit_backoff_minutes': 30,
            'generic_failure_backoff_minutes': 5,
        },
        'default_prompts': {},
        'topics': [
            {
                'id': '1',
                'slug': 'topic-one',
                'tier': 'engineering',
                'title': 'Topic one',
                'stages': {
                    'claude': {'prompt': 'do thing A'},
                    'gemini': [{'subslug': 'single', 'prompt': 'do thing B'}],
                },
            },
        ],
    }


# ── tests ────────────────────────────────────────────────────────────


class TestBatchConfigBasics:
    def test_minimal_valid_config(self) -> None:
        cfg = BatchConfig.model_validate(_minimal_config_dict())
        assert cfg.schema_version == 2
        assert cfg.batch_name == 'test-batch'
        assert len(cfg.topics) == 1
        assert cfg.topics[0].id == '1'
        assert cfg.topics[0].stages.claude.prompt == 'do thing A'

    def test_int_topic_id_normalizes_to_string(self) -> None:
        d = _minimal_config_dict()
        d['topics'][0]['id'] = 1  # numeric in raw JSON  # type: ignore[index]
        cfg = BatchConfig.model_validate(d)
        assert cfg.topics[0].id == '1'

    def test_duplicate_topic_ids_raise(self) -> None:
        d = _minimal_config_dict()
        d['topics'].append(  # type: ignore[attr-defined]
            {
                'id': '1',  # duplicate!
                'slug': 'dup',
                'title': 'Duplicate',
                'stages': {'claude': {'prompt': 'x'}},
            }
        )
        with pytest.raises(ValidationError, match='duplicate topic ids'):
            BatchConfig.model_validate(d)

    def test_wrong_schema_version_rejected(self) -> None:
        d = _minimal_config_dict()
        d['schema_version'] = 1
        with pytest.raises(ValidationError):
            BatchConfig.model_validate(d)

    def test_missing_required_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BatchConfig.model_validate({'schema_version': 2})


class TestTopicByIdLookup:
    def test_finds_topic(self) -> None:
        cfg = BatchConfig.model_validate(_minimal_config_dict())
        assert cfg.topic_by_id('1') is not None
        assert cfg.topic_by_id('1').slug == 'topic-one'  # type: ignore[union-attr]

    def test_returns_none_when_missing(self) -> None:
        cfg = BatchConfig.model_validate(_minimal_config_dict())
        assert cfg.topic_by_id('999') is None


class TestStageConfigs:
    def test_claude_stage_prompt_is_optional_at_field_level(self) -> None:
        # Since spec 0001 §10 the prompt is Optional at the ClaudeStageConfig
        # level (an omitted prompt is resolved from the topic's research_prompt
        # by the TopicConfig validator); the "must have a prompt" requirement
        # moved to topic-level resolution, tested in test_research_prompt.py.
        cfg = ClaudeStageConfig.model_validate({})
        assert cfg.prompt is None

    def test_gemini_subsession_defaults(self) -> None:
        ss = GeminiSubsessionConfig(prompt='x')
        assert ss.subslug == 'single'
        assert ss.prompt == 'x'

    def test_openrouter_subsession_requires_model_and_prompt(self) -> None:
        ss = OpenRouterSubsessionConfig(model='openai/gpt-5.5', prompt='x')
        assert ss.model == 'openai/gpt-5.5'
        assert ss.web_search is False
        assert ss.reasoning_effort is None

    def test_openrouter_validates_reasoning_effort(self) -> None:
        with pytest.raises(ValidationError):
            OpenRouterSubsessionConfig(
                model='openai/gpt-5.5',
                prompt='x',
                reasoning_effort='very-high',  # type: ignore[arg-type]
            )

    def test_topic_stages_with_only_claude(self) -> None:
        ts = TopicStages.model_validate({'claude': {'prompt': 'p'}})
        assert ts.claude.prompt == 'p'
        assert ts.gemini == []
        assert ts.openrouter == []

    def test_topic_with_extra_stage_fields_allowed(self) -> None:
        # extra='allow' on topic.stages — future-proof for new optional fields.
        d = _minimal_config_dict()
        d['topics'][0]['stages']['custom_future_stage'] = {'enabled': True}  # type: ignore[index]
        cfg = BatchConfig.model_validate(d)
        assert cfg is not None  # validated without error


class TestLoaderHelper:
    def test_load_from_path(self, tmp_path: Path) -> None:
        path = tmp_path / 'cfg.json'
        path.write_text(json.dumps(_minimal_config_dict()), encoding='utf-8')
        cfg = load_batch_config(path)
        assert cfg.batch_name == 'test-batch'

    def test_load_from_string_path(self, tmp_path: Path) -> None:
        path = tmp_path / 'cfg.json'
        path.write_text(json.dumps(_minimal_config_dict()), encoding='utf-8')
        cfg = load_batch_config(str(path))
        assert cfg.batch_name == 'test-batch'

    def test_load_from_dict(self) -> None:
        cfg = load_batch_config(_minimal_config_dict())
        assert cfg.schema_version == 2

    def test_load_raw_json_string(self) -> None:
        raw = json.dumps(_minimal_config_dict())
        cfg = load_batch_config(raw)
        assert cfg.schema_version == 2


class TestRealConfigsRoundTrip:
    """Validate the real batch-10 and batch-11 configs round-trip cleanly."""

    def test_example_config_loads(self) -> None:
        from mantis_research.core.paths import project_root

        path = project_root() / 'config' / 'example-batch.json'
        cfg = load_batch_config(path)
        assert cfg.schema_version == 2
        assert len(cfg.topics) == 2  # the shipped example ships two topics
        # Path B: each topic fans out to OpenRouter research substrates.
        for t in cfg.topics:
            assert t.stages.openrouter

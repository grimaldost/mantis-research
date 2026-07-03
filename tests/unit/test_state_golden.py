"""Golden-file state compatibility (spec 0001 §12, invariant I4).

Real pre-series state files (captured verbatim under
``tests/data/golden_state/``) must keep loading across releases. This pins I4:
a state-schema change that would fail to parse an existing on-disk file — for
example the token/cost fields §12 adds to ``SubsessionResult`` — is caught here.
The fixtures predate those fields, so loading them proves the additive change
stayed backward-compatible.

(The fixture directory is ``golden_state`` rather than the spec's
``state-golden`` because the ``state-*/`` gitignore pattern would otherwise
exclude it from version control.)
"""

from __future__ import annotations

import pytest

from mantis_research.core.paths import project_root
from mantis_research.core.state import (
    ClaudeResearchState,
    FalsificationState,
    GeminiResearchState,
    JournalPassesState,
    OpenRouterResearchState,
    SynthesisState,
    TopicState,
)

_GOLDEN = project_root() / 'tests' / 'data' / 'golden_state'

_CASES: list[tuple[str, type[TopicState]]] = [
    ('claude.json', ClaudeResearchState),
    ('openrouter.json', OpenRouterResearchState),
    ('synthesis.json', SynthesisState),
    ('falsification.json', FalsificationState),
    ('journal_passes.json', JournalPassesState),
    ('gemini.json', GeminiResearchState),
]


@pytest.mark.parametrize(('filename', 'state_cls'), _CASES, ids=[f for f, _ in _CASES])
def test_pre_series_state_files_still_load(filename: str, state_cls: type[TopicState]) -> None:
    path = _GOLDEN / filename
    text = path.read_text(encoding='utf-8')
    state = state_cls.model_validate_json(text)
    assert state.id  # loaded and the common contract survives
    assert state.status  # status enum still parses the on-disk string value


def test_openrouter_subsessions_without_usage_fields_load() -> None:
    # The golden openrouter file predates the §12 token/cost fields; its
    # subsessions must still parse with those fields defaulting to None (I4).
    text = (_GOLDEN / 'openrouter.json').read_text(encoding='utf-8')
    state = OpenRouterResearchState.model_validate_json(text)
    assert state.subsessions
    first = state.subsessions[0]
    assert first.tokens_prompt is None
    assert first.cost_usd is None


def test_golden_dir_is_populated() -> None:
    assert len(list(_GOLDEN.glob('*.json'))) == len(_CASES)

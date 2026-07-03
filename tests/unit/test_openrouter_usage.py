"""OpenRouter usage/cost persistence (spec 0001 §12).

A successful subsession persists token/cost fields when the response carries a
usage block, and leaves them None when it does not.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from mantis_research.interface.stages.openrouter_research import OpenRouterResearchStage

if TYPE_CHECKING:
    from pathlib import Path


def _result(usage: object) -> SimpleNamespace:
    return SimpleNamespace(
        success=True,
        output='a brief',
        raw_output='',
        duration_s=1.5,
        status_code=200,
        error=None,
        usage=usage,
    )


class TestUsagePersistence:
    def test_usage_fields_persisted_when_present(self, tmp_path: Path) -> None:
        usage = {
            'prompt_tokens': 1200,
            'completion_tokens': 3400,
            'completion_tokens_details': {'reasoning_tokens': 800},
            'cost': 0.0123,
        }
        rec = OpenRouterResearchStage._build_subsession_result(
            subslug='gpt', result=_result(usage), out_path=tmp_path / 'o.md', dry_run=True
        )
        assert rec.status == 'done'
        assert rec.tokens_prompt == 1200
        assert rec.tokens_completion == 3400
        assert rec.tokens_reasoning == 800
        assert rec.cost_usd == 0.0123

    def test_usage_absent_leaves_fields_none(self, tmp_path: Path) -> None:
        rec = OpenRouterResearchStage._build_subsession_result(
            subslug='gpt', result=_result(None), out_path=tmp_path / 'o.md', dry_run=True
        )
        assert rec.status == 'done'
        assert rec.tokens_prompt is None
        assert rec.tokens_completion is None
        assert rec.tokens_reasoning is None
        assert rec.cost_usd is None

    def test_reasoning_tokens_optional_within_usage(self, tmp_path: Path) -> None:
        # A usage block without completion_tokens_details still persists the
        # top-level counts and cost; reasoning stays None.
        usage = {'prompt_tokens': 10, 'completion_tokens': 20, 'cost': 0.001}
        rec = OpenRouterResearchStage._build_subsession_result(
            subslug='gpt', result=_result(usage), out_path=tmp_path / 'o.md', dry_run=True
        )
        assert rec.tokens_prompt == 10
        assert rec.tokens_reasoning is None
        assert rec.cost_usd == 0.001

"""The research stage runs a topic's substrates one after another.

This pins the behaviour the skill's latency bullet describes: the stage awaits
each substrate in turn, so it takes about the sum of their durations and each
added substrate adds its own. If the stage is made concurrent, change the
bullet in ``skills/research/SKILL.md`` (and the comment on
``RESEARCH_STAGE_MINUTES``) with it.

The test passes on code that is already correct; it pins the code side of the
claim that ``test_agent_serving_docs`` holds the prose to.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from mantis_research.core.config import load_batch_config
from mantis_research.interface.cli.dispatch import dispatch_stage_config
from mantis_research.interface.research_service import build_config
from tests.pipeline_fakes import FakeOpenRouter, FakePipeline, install_fake_pipeline

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.interface.adapters.openrouter_http import (
        OpenRouterHttpOptions,
        OpenRouterHttpResult,
    )


@dataclass
class _CountingOpenRouter(FakeOpenRouter):
    """A fake adapter that counts how many calls are in flight at once."""

    in_flight: int = 0
    max_in_flight: int = 0

    async def run(
        self,
        prompt: str,
        options: OpenRouterHttpOptions,
        transcript_path: Path,
        *,
        dry_run: bool = False,
    ) -> OpenRouterHttpResult:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            return await super().run(prompt, options, transcript_path, dry_run=dry_run)
        finally:
            self.in_flight -= 1


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


def test_a_topics_substrates_are_awaited_one_after_another(
    rooted: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline: FakePipeline = install_fake_pipeline(monkeypatch)
    counting = _CountingOpenRouter()
    pipeline.openrouter = counting
    raw: dict[str, Any] = build_config(
        'Which retry policy fits a flaky upstream?',
        substrates=['openai', 'deepseek', 'google'],
        primary='openrouter:openai',
        journal=False,
        batch_name='in-turn',
        assurance='research',
    )
    cfg = load_batch_config(raw)

    assert dispatch_stage_config('openrouter', cfg, log_level='CRITICAL') == 0

    assert counting.live_calls == 3
    assert counting.max_in_flight == 1, 'the substrates overlapped; update the skill latency bullet'

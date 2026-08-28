"""A run's identity is unique by construction (MANT-B62).

The name was ``research-{first 48 chars of the question}-{timestamp to the
second}``, and the directory was created with ``exist_ok=True``. On 2026-08-23
four of five questions carried a shared CONTEXT preamble, slugified to the same
string, and were dispatched within ten seconds — five requests, three
directories. The report filed it as a dropped request. It is worse than that: a
silent merge lets one run's briefs be read as the answer to another's question,
which is the correctness class MANT-B06 was built to close.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mantis_research.interface.research_service import (
    _TIER_STAGES,
    LocalSeatUnavailableError,
    RunNameCollisionError,
    _slugify,
    require_local_claude_seat,
    run_research,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for fn in ('state_root', 'outputs_root', 'transcripts_root', 'logs_root'):
        monkeypatch.setattr(f'mantis_research.core.paths.{fn}', lambda fn=fn: tmp_path / fn)
    return tmp_path


_PREAMBLE = (
    'CONTEXT: the client is a mid-sized asset manager migrating its books. '
    'RESEARCH QUESTION ({key}): {tail}'
)


def _ask(rooted: Path, key: str, tail: str) -> dict:
    return run_research(
        _PREAMBLE.format(key=key, tail=tail),
        assurance='research',
        dry_run=True,
        log_level='CRITICAL',
    )


class TestFourQuestionsFourRuns:
    def test_questions_sharing_a_preamble_get_distinct_directories(self, rooted: Path) -> None:
        runs = [
            _ask(rooted, 'ibor-quantity-ledger', 'how are IBOR quantities held?'),
            _ask(rooted, 'two-party-view', 'how is the two-party view modelled?'),
            _ask(rooted, 'undated-cashflows', 'how are undated cashflows scheduled?'),
            _ask(rooted, 'fund-share-events', 'how are fund quota events recorded?'),
        ]
        dirs = {m['outputs_dir'] for m in runs}
        assert len(dirs) == 4

    def test_each_run_records_its_own_question(self, rooted: Path) -> None:
        # The collision's actual cost: not a lost run, a misattributed one.
        _ask(rooted, 'ibor-quantity-ledger', 'how are IBOR quantities held?')
        _ask(rooted, 'two-party-view', 'how is the two-party view modelled?')
        records = [
            json.loads(p.read_text(encoding='utf-8'))
            for p in (rooted / 'outputs_root').glob('*/run.json')
        ]
        questions = {r['question'] for r in records}
        assert len(questions) == 2

    def test_the_same_question_twice_gets_two_runs(self, rooted: Path) -> None:
        first = _ask(rooted, 'k', 'the very same words')
        second = _ask(rooted, 'k', 'the very same words')
        assert first['outputs_dir'] != second['outputs_dir']


class TestTheSlugPrefersTheKey:
    def test_a_marked_question_slugs_on_its_key(self) -> None:
        text = _PREAMBLE.format(key='ibor-quantity-ledger', tail='how are quantities held?')
        assert _slugify(text) == 'ibor-quantity-ledger'

    def test_an_unmarked_question_still_slugs_on_its_words(self) -> None:
        assert _slugify('How does ISO 20022 migration work?') == 'how-does-iso-20022-migration-work'

    def test_an_empty_question_still_yields_a_slug(self) -> None:
        assert _slugify('') == 'question'


class TestAnExplicitNameIsNotAMerge:
    def test_reusing_a_name_for_a_different_question_is_refused(self, rooted: Path) -> None:
        run_research(
            'the first question',
            assurance='research',
            batch_name='shared',
            dry_run=True,
            log_level='CRITICAL',
        )
        with pytest.raises(RunNameCollisionError, match='shared'):
            run_research(
                'a different question',
                assurance='research',
                batch_name='shared',
                dry_run=True,
                log_level='CRITICAL',
            )

    def test_reusing_a_name_for_the_same_question_is_allowed(self, rooted: Path) -> None:
        # Re-running the same command is what invariant I5 calls resume.
        run_research(
            'the same question',
            assurance='research',
            batch_name='shared',
            dry_run=True,
            log_level='CRITICAL',
        )
        again = run_research(
            'the same question',
            assurance='research',
            batch_name='shared',
            dry_run=True,
            log_level='CRITICAL',
        )
        assert again['batch_name'] == 'shared'


class TestTheRequestIsRecordedBeforeTheRunExists:
    """A request that dies before its directory exists left no trace at all."""

    def test_an_accepted_request_is_journalled(self, rooted: Path) -> None:
        _ask(rooted, 'k', 'a question that will be accepted')
        entries = _acceptance_entries(rooted)
        assert entries
        assert entries[-1]['outcome'] == 'accepted'
        assert entries[-1]['question_slug'] == 'k'

    def test_a_refused_request_is_journalled(self, rooted: Path) -> None:
        with pytest.raises(ValueError, match='invalid assurance'):
            run_research('q', assurance='bogus', dry_run=True, log_level='CRITICAL')
        entries = _acceptance_entries(rooted)
        assert entries[-1]['outcome'] == 'rejected'


def _acceptance_entries(rooted: Path) -> list[dict]:
    path = rooted / 'logs_root' / 'requests.jsonl'
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]


class TestTheStageSequenceIsFirstClass:
    """MANT-B60 — `assurance` was doing two jobs.

    It named how much checking the answer gets AND which stages run, so
    "research only" had no way to be asked for. Every tier ended in a synthesis
    that could not complete inside an MCP client's window, which left the tool
    with no mode an agent could actually use.
    """

    def test_research_is_a_tier(self, rooted: Path) -> None:
        manifest = _ask(rooted, 'k', 'just the briefs please')
        assert list(manifest['stages']) == ['openrouter']

    def test_the_full_tiers_are_unchanged(self, rooted: Path) -> None:
        fast = run_research('q', assurance='fast', dry_run=True, log_level='CRITICAL')
        assert list(fast['stages']) == ['openrouter', 'synthesis']

    def test_an_unknown_tier_still_raises_the_pinned_message(self, rooted: Path) -> None:
        with pytest.raises(ValueError, match='invalid assurance'):
            run_research('q', assurance='bogus', dry_run=True, log_level='CRITICAL')

    def test_the_message_offers_the_new_tier(self, rooted: Path) -> None:
        with pytest.raises(ValueError, match='research'):
            run_research('q', assurance='bogus', dry_run=True, log_level='CRITICAL')

    def test_a_research_only_tier_never_probes_the_seat(self) -> None:
        # The whole point of the tier: it runs where no seat is usable. Driven
        # through the real precondition with a probe that fails if touched.
        class Exploding:
            def preflight(self) -> None:
                raise AssertionError('the seat was probed for a research-only run')

        require_local_claude_seat(stages=_TIER_STAGES['research'], probe=Exploding())

    def test_a_synthesis_tier_still_probes_the_seat(self) -> None:
        class Refusing:
            def preflight(self) -> None:
                msg = 'no seat here'
                raise RuntimeError(msg)

        with pytest.raises(LocalSeatUnavailableError):
            require_local_claude_seat(stages=_TIER_STAGES['fast'], probe=Refusing())


class TestTheNameStillFitsAPath:
    def test_the_deepest_generated_path_has_headroom(self) -> None:
        # The uniqueness suffix costs characters, and these paths are already
        # nested four deep under a checkout root on a platform with a 260-char
        # limit. Measured rather than asserted in prose.
        from mantis_research.interface.research_service import _mint_run_name

        name = _mint_run_name('a very long question ' * 20)
        root = 'C:/Users/grima/Documents/mantis-research-runner'
        deepest = f'{root}/outputs/{name}/openrouter/01-some-topic-slug/deepseek.md'
        assert len(deepest) < 260

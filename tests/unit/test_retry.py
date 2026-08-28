"""Unit tests for mantis_research.core.retry."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mantis_research.core.retry import (
    RATE_LIMIT_PATTERNS,
    FailureKind,
    RetryPolicy,
    classify_failure,
    detect_rate_limit,
    resolve_failure_kind,
)


class TestDetectRateLimit:
    @pytest.mark.parametrize(
        'output',
        [
            'Error: rate limit exceeded',
            'You have exhausted your capacity on this model',
            "You've hit your limit · resets 12:50am",
            'HTTP 429 Too Many Requests',
            'RESOURCE_EXHAUSTED',
            'Quota exceeded for this model',
            'rate-limit hit on cloudcode-pa',
            'no capacity available',
        ],
    )
    def test_detects_known_patterns(self, output: str) -> None:
        assert detect_rate_limit(output) is True

    @pytest.mark.parametrize(
        'output',
        [
            '',
            'normal output without errors',
            'Internal error: 500 backend failure',  # 500, not 429
            'AttachConsole failed',  # ConPTY error, not rate limit
            'The user aborted a request',
            # Regression (spec 0001 §2): bare 'resets' used to match network
            # errors and force a 30-min rate-limit backoff. It must not.
            'error: connection resets by peer',
            'the socket resets unexpectedly mid-stream',
        ],
    )
    def test_does_not_detect_non_rate_limit(self, output: str) -> None:
        assert detect_rate_limit(output) is False

    @pytest.mark.parametrize(
        'output',
        [
            "You've hit your limit · resets 12:50am",  # interpunct banner
            '5-hour limit resets at 3pm',  # plain form
            'You have hit your limit, please wait',
        ],
    )
    def test_still_detects_claude_usage_limit_banners(self, output: str) -> None:
        # The anchored 'limit resets' / 'limit · resets' patterns must keep
        # catching the real Claude Code usage-limit phrasings.
        assert detect_rate_limit(output) is True

    def test_case_insensitive(self) -> None:
        assert detect_rate_limit('RATE LIMIT EXCEEDED') is True
        assert detect_rate_limit('Rate Limit Exceeded') is True

    def test_empty_string(self) -> None:
        assert detect_rate_limit('') is False


class TestClassifyFailure:
    def test_rate_limit_text_classifies_as_rate_limit(self) -> None:
        assert classify_failure('Error 429: too many requests') is FailureKind.RATE_LIMIT

    def test_other_errors_classify_as_generic(self) -> None:
        assert classify_failure('exit code 1') is FailureKind.GENERIC
        assert classify_failure('') is FailureKind.GENERIC


class TestRetryPolicy:
    def test_defaults_match_legacy(self) -> None:
        # These defaults match the values previously hard-coded across all 5 runners.
        p = RetryPolicy()
        assert p.max_retries_per_stage == 2
        assert p.rate_limit_backoff_minutes == 30
        assert p.generic_failure_backoff_minutes == 5

    def test_rate_limit_backoff_in_seconds(self) -> None:
        # The configured 30 minutes is the wait the policy would take; what it
        # actually waits is capped to the caller's idle budget (MANT-B02, see
        # TestIdleBudgetCap). Uncapped, the arithmetic is unchanged.
        p = RetryPolicy(rate_limit_backoff_minutes=30, caller_idle_budget_seconds=None)
        assert p.backoff_seconds(FailureKind.RATE_LIMIT) == 1800.0

    def test_generic_backoff_in_seconds(self) -> None:
        p = RetryPolicy(generic_failure_backoff_minutes=5)
        assert p.backoff_seconds(FailureKind.GENERIC) == 300.0

    @pytest.mark.parametrize(
        ('attempt_number', 'is_final'),
        [
            (1, False),  # first attempt — retries available
            (2, False),  # one retry done — one more left
            (3, True),  # two retries done — final
            (4, True),  # well past
        ],
    )
    def test_is_final_attempt_with_default_max_retries(
        self, attempt_number: int, is_final: bool
    ) -> None:
        p = RetryPolicy(max_retries_per_stage=2)
        assert p.is_final_attempt(attempt_number, FailureKind.GENERIC) is is_final


class TestIdleBudgetCap:
    """MANT-B02 — a backoff must fit inside the caller's idle window.

    The 30-minute rate-limit backoff is exactly the MCP client's 1800 s idle
    default, so any rate-limited substrate guaranteed the abort at every
    assurance tier. The policy now caps a wait at half the budget.
    """

    def test_default_budget_is_comfortably_under_the_1800s_client_window(self) -> None:
        p = RetryPolicy()
        assert p.caller_idle_budget_seconds is not None
        assert p.caller_idle_budget_seconds < 1800.0

    def test_rate_limit_backoff_is_capped_at_half_the_budget(self) -> None:
        p = RetryPolicy(rate_limit_backoff_minutes=30, caller_idle_budget_seconds=1500.0)
        assert p.backoff_seconds(FailureKind.RATE_LIMIT) == 750.0

    def test_uncapped_when_the_budget_is_disabled(self) -> None:
        p = RetryPolicy(rate_limit_backoff_minutes=30, caller_idle_budget_seconds=None)
        assert p.backoff_seconds(FailureKind.RATE_LIMIT) == 1800.0

    def test_generic_five_minute_default_is_untouched_by_the_cap(self) -> None:
        # The generic backoff already sits inside the cap; MANT-B02 does not
        # move it.
        p = RetryPolicy()
        assert p.generic_failure_backoff_minutes == 5
        assert p.backoff_seconds(FailureKind.GENERIC) == 300.0

    def test_a_shorter_configured_backoff_is_not_lengthened(self) -> None:
        p = RetryPolicy(rate_limit_backoff_minutes=2, caller_idle_budget_seconds=1500.0)
        assert p.backoff_seconds(FailureKind.RATE_LIMIT) == 120.0

    @given(
        rl_min=st.integers(min_value=1, max_value=600),
        budget=st.floats(min_value=10.0, max_value=7200.0),
    )
    def test_no_wait_ever_exceeds_half_the_budget(self, rl_min: int, budget: float) -> None:
        p = RetryPolicy(rate_limit_backoff_minutes=rl_min, caller_idle_budget_seconds=budget)
        for kind in FailureKind:
            assert p.backoff_seconds(kind) <= budget / 2


class TestPatternsCoverage:
    def test_pattern_set_covers_all_observed_failures(self) -> None:
        # These are the actual rate-limit/quota strings observed in batch-10 and
        # batch-11 transcripts. Adding new ones requires adding to the canonical
        # frozenset in retry.py — this test documents what's covered.
        observed = [
            'You have exhausted your capacity on this model. Your quota will reset',
            'rate limit exceeded',
            "You've hit your limit · resets",
            '429 Too Many Requests',
            'RESOURCE_EXHAUSTED',
        ]
        for line in observed:
            assert detect_rate_limit(line), f'pattern set missing coverage for: {line!r}'

    def test_frozen_set_is_immutable(self) -> None:
        # We expose RATE_LIMIT_PATTERNS as a public constant; it must not be
        # accidentally mutable.
        with pytest.raises(AttributeError):
            RATE_LIMIT_PATTERNS.add('newpattern')  # type: ignore[attr-defined]


class TestRetryPolicyHypothesis:
    @given(
        rl_min=st.integers(min_value=1, max_value=120),
        gen_min=st.integers(min_value=1, max_value=120),
    )
    def test_rate_limit_backoff_always_at_least_generic(self, rl_min: int, gen_min: int) -> None:
        # Property: in any sane configuration, rate-limit backoff is configured
        # to be at-least-as-long as generic backoff. This isn't strictly
        # required by the policy, but documents the operator intent.
        if rl_min < gen_min:
            pytest.skip('inverted config — operator-error case, not a property to enforce')
        p = RetryPolicy(
            rate_limit_backoff_minutes=rl_min,
            generic_failure_backoff_minutes=gen_min,
        )
        assert p.backoff_seconds(FailureKind.RATE_LIMIT) >= p.backoff_seconds(FailureKind.GENERIC)

    @given(
        max_retries=st.integers(min_value=0, max_value=10),
        attempt=st.integers(min_value=1, max_value=20),
    )
    def test_is_final_attempt_monotonic(self, max_retries: int, attempt: int) -> None:
        p = RetryPolicy(max_retries_per_stage=max_retries)
        # Property: once is_final returns True, every higher attempt is also final.
        if p.is_final_attempt(attempt, FailureKind.GENERIC):
            assert p.is_final_attempt(attempt + 1, FailureKind.GENERIC)


class TestAPreconditionFailureIsNotRetried:
    """MANT-B59 — retry budget is a function of the failure's class.

    A rate limit is transient: the environment changes while you wait, so
    waiting is the fix. A watchdog kill is not: the same command goes back into
    the same environment and produces the same silence. On 2026-08-23 that was
    three strikes of 600 s per run, four runs deep, serialised on one seat —
    2.5 hours to learn what the first attempt already knew.
    """

    def test_a_precondition_failure_gets_no_second_attempt(self) -> None:
        policy = RetryPolicy()
        assert policy.attempts_for(FailureKind.PRECONDITION) == 1

    def test_a_rate_limit_still_gets_the_full_budget(self) -> None:
        policy = RetryPolicy(max_retries_per_stage=2)
        assert policy.attempts_for(FailureKind.RATE_LIMIT) == 3

    def test_a_generic_failure_still_gets_the_full_budget(self) -> None:
        policy = RetryPolicy(max_retries_per_stage=2)
        assert policy.attempts_for(FailureKind.GENERIC) == 3

    def test_a_precondition_failure_never_waits(self) -> None:
        # There is nothing to wait for; the backoff would only hold the seat.
        assert RetryPolicy().backoff_seconds(FailureKind.PRECONDITION) == 0.0

    def test_the_final_attempt_depends_on_the_kind(self) -> None:
        policy = RetryPolicy(max_retries_per_stage=2)
        assert policy.is_final_attempt(1, FailureKind.PRECONDITION) is True
        assert policy.is_final_attempt(1, FailureKind.GENERIC) is False


class TestWhoDecidesTheFailureKind:
    """The producer knows; the classifier was guessing from text.

    `classify_failure` regexes the child's output, so a watchdog kill — which
    by definition produced no output — read as GENERIC and got the transient
    budget. The signal existed on the result the whole time and died at the
    `AttemptResult` boundary.
    """

    def test_a_declared_kind_wins_over_the_text(self) -> None:
        assert (
            resolve_failure_kind(declared=FailureKind.PRECONDITION, error_output='rate limit')
            is FailureKind.PRECONDITION
        )

    def test_the_text_is_used_when_nothing_was_declared(self) -> None:
        assert (
            resolve_failure_kind(declared=None, error_output='429 too many requests')
            is FailureKind.RATE_LIMIT
        )

    def test_an_empty_output_with_no_declaration_is_generic(self) -> None:
        assert resolve_failure_kind(declared=None, error_output='') is FailureKind.GENERIC

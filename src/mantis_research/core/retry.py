"""Rate-limit detection and backoff math — pure functions.

The orchestrator calls these to decide whether a stage attempt's failure
counts as a rate-limit (long backoff) vs a generic failure (short backoff),
and how long to wait before the next attempt.

The pattern set here matches the union of patterns historically duplicated
across all 5 stage runners. Adding a new pattern means adding it here once.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# All rate-limit indicator strings, lowercased. Match against subprocess
# output (stdout+stderr merged) case-insensitively.
RATE_LIMIT_PATTERNS: frozenset[str] = frozenset(
    {
        'rate limit',
        'rate-limit',
        'rate_limit',
        'quota exceeded',
        'usage limit',
        'too many requests',
        '429',
        'retry-after',
        'resource_exhausted',
        'no capacity available',
        'exhausted your capacity',
        # Anthropic's user-facing message variants (Claude Code CLI):
        "you've hit your limit",
        'you have hit your limit',
        'hit your limit',
        # The usage-limit reset banner, anchored to 'limit … resets' so it
        # cannot match unrelated network text like 'connection resets by peer'.
        # 'limit · resets' is the interpunct form the CLI prints; 'limit resets'
        # the plain form.
        'limit · resets',
        'limit resets',
    }
)


def detect_rate_limit(output: str) -> bool:
    """True if output contains any known rate-limit indicator (case-insensitive)."""
    if not output:
        return False
    lower = output.lower()
    return any(pat in lower for pat in RATE_LIMIT_PATTERNS)


class FailureKind(StrEnum):
    """Classification of an attempt failure, for backoff and budget selection.

    The distinction that matters is whether waiting can help. A rate limit is
    transient — the environment changes on its own, so the retry is the fix. A
    precondition failure is not: the same command goes back into the same
    environment and fails the same way, so retrying only spends the seat.
    """

    RATE_LIMIT = 'rate_limit'
    GENERIC = 'generic'
    #: Something about the environment made the attempt impossible, and nothing
    #: about waiting changes it — a child that produced no output at all, or one
    #: that could not be reaped. Retrying is a loop that can only cost time.
    PRECONDITION = 'precondition'


# The tool has to fit inside an idle window it does not control: the MCP
# client's default is 1800 s and a running agent cannot change it. Default the
# budget comfortably under that, so the worst wait (half the budget) leaves the
# rest of the window for the work itself.
DEFAULT_CALLER_IDLE_BUDGET_SECONDS = 1500.0


@dataclass(frozen=True)
class RetryPolicy:
    """Backoff configuration. Loaded from config; never hard-coded in stages.

    ``caller_idle_budget_seconds`` is the window the *caller* will wait without
    hearing anything before it abandons the call. Any single wait is capped at
    half of it: a 30-minute rate-limit backoff is exactly the MCP client's
    1800 s idle default, so before this cap a rate-limited substrate guaranteed
    the abort at every assurance tier — which is why the documented "drop to
    `fast`" remedy failed. ``None`` disables the cap for a caller with no idle
    window. The generic backoff default is unchanged at 5 minutes and already
    sits inside the cap.
    """

    max_retries_per_stage: int = 2
    rate_limit_backoff_minutes: int = 30
    generic_failure_backoff_minutes: int = 5
    caller_idle_budget_seconds: float | None = DEFAULT_CALLER_IDLE_BUDGET_SECONDS

    def attempts_for(self, kind: FailureKind) -> int:
        """How many attempts this failure class is worth in total.

        One, for a precondition failure. Three strikes of an identical command
        into an unchanged environment is a loop that can only spend seat time —
        and it did: twelve attempts, zero bytes, serialised across 2.5 hours.
        """
        if kind is FailureKind.PRECONDITION:
            return 1
        return self.max_retries_per_stage + 1

    def backoff_seconds(self, kind: FailureKind) -> float:
        """Return the seconds to wait before the next retry, capped to the budget."""
        if kind is FailureKind.PRECONDITION:
            # Nothing to wait for. A backoff here would hold the seat while the
            # answer stayed the same.
            return 0.0
        minutes = (
            self.rate_limit_backoff_minutes
            if kind is FailureKind.RATE_LIMIT
            else self.generic_failure_backoff_minutes
        )
        wait = float(minutes * 60)
        if self.caller_idle_budget_seconds is None:
            return wait
        return min(wait, self.caller_idle_budget_seconds / 2)

    def is_final_attempt(self, attempt_number: int, kind: FailureKind) -> bool:
        """True when ``attempt_number`` (1-indexed) exhausts this kind's budget."""
        return attempt_number >= self.attempts_for(kind)


def classify_failure(error_text: str) -> FailureKind:
    """Bucket an error text/output into RATE_LIMIT vs GENERIC."""
    return FailureKind.RATE_LIMIT if detect_rate_limit(error_text) else FailureKind.GENERIC


def resolve_failure_kind(*, declared: FailureKind | None, error_output: str) -> FailureKind:
    """Prefer the kind the producer declared over one guessed from its text.

    Scanning the output was the only classifier, which meant the one failure
    that produces *no* output — a watchdog kill — could never be recognised: it
    read as GENERIC and drew the transient budget. The adapter knew, and the
    knowledge died at the ``AttemptResult`` boundary. Text remains the fallback
    for producers that only have text.
    """
    if declared is not None:
        return declared
    return classify_failure(error_output)

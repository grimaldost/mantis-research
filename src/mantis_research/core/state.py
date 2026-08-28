"""Per-topic state machines — pure data structures.

Each pipeline stage persists per-topic state as JSON under
`state/<stage>/<topic_id>.json`. The on-disk JSON shape is part of the
public contract: existing batches' state files must remain readable across
releases.

State models:
- ``TopicState`` — the common base (id, slug, status, attempts, timestamps,
  last_error).
- ``ClaudeResearchState``, ``GeminiResearchState``, ``SynthesisState``,
  ``JournalPassesState``, ``FalsificationState``, ``EvaluationState`` —
  per-stage subclasses with stage-specific fields.

Status transitions (TopicStatus values, matching legacy on-disk values).

Within a single run (the orchestrator's retry loop):
    PENDING ─▶ IN_FLIGHT ─▶ DONE
                  ├──────▶ FAILED         (retries exhausted)
                  └──────▶ RATE_LIMITED ─▶ (after backoff) PENDING
    PENDING ─▶ BLOCKED_UPSTREAM (upstream gate failed)

Across runs, an IN_FLIGHT topic whose recorded ``owner_pid`` is no longer a live
process is marked DEAD before anything is re-attempted — a terminal record for
the abandoned attempt, and a different fact from FAILED (an attempt that ran and
lost).

Across runs (re-invoking ``mantis run <stage>`` on the same batch): only a DONE
a real run wrote is skipped. Every other status — FAILED, RATE_LIMITED,
BLOCKED_UPSTREAM, DEAD, and an interrupted IN_FLIGHT — is selected as pending
and re-attempted (``Orchestrator._is_pending`` returns ``not state.settled``);
BLOCKED_UPSTREAM re-runs its upstream gate. So there is no cross-run "terminal"
state other than DONE — a failed or rate-limited topic is retried on the next
invocation, which is what makes a batch resumable (I5).

A DONE a **dry run** wrote is not one of them: ``dry_run`` records which kind of
run wrote the record, and ``settled`` disregards a dry run's. A dry run
short-circuits every adapter, so it can report the orchestration is wired up
without any artifact reaching disk; left indistinguishable from a real DONE it
made the next real run under the same batch name skip every topic and report
success over an output tree nothing had written.

These are mutable models — the orchestrator updates and re-saves between
attempts. We use pydantic v2 for round-trip JSON validation against the
existing on-disk shape.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from pathlib import Path


class TopicStatus(StrEnum):
    """Topic lifecycle states. String-valued for stable JSON serialization."""

    PENDING = 'pending'
    IN_FLIGHT = 'in_flight'
    DONE = 'done'
    FAILED = 'failed'
    RATE_LIMITED = 'rate_limited'
    BLOCKED_UPSTREAM = 'blocked_upstream'
    # The process that claimed this topic is gone. Distinct from FAILED, which
    # means an attempt ran and lost: DEAD means nobody is coming back. Without
    # the distinction an abandoned run reads as a stage defect, and the
    # difference decides whether you debug the prompt or just re-run.
    DEAD = 'dead'


class TopicState(BaseModel):
    """Common fields persisted for every topic across every stage.

    Concrete stage state classes subclass this and add stage-specific fields.
    pydantic v2 model_dump produces stable JSON; field defaults match the
    legacy hand-written to_dict shape.
    """

    model_config = ConfigDict(use_enum_values=False, validate_assignment=True)

    id: str
    slug: str
    status: TopicStatus = TopicStatus.PENDING
    #: The CLI session this topic's last attempt used, where the stage drives a
    #: session-based child. Declared once here rather than six times over,
    #: because the retry contract above has to be able to clear it.
    session_id: str | None = None
    attempts: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    last_error: str | None = None
    # PID of the process that put this topic IN_FLIGHT, written in so a later
    # run can read it back and tell an owner that is still working from one that
    # is gone. Additive optional field (I4); absent on every historical state
    # file, which reads as "unknown owner".
    owner_pid: int | None = None
    # True when a **dry run** wrote this record. A dry run short-circuits every
    # adapter, so its DONE means "the orchestration is wired up", not "the
    # artifact is on disk" — and DONE is only skippable because it means the
    # latter (I5). Recording which kind of run wrote the record is what lets a
    # later real run tell the two apart. Additive optional field (I4); absent on
    # every historical state file, which reads as "a real run wrote this".
    dry_run: bool | None = None

    # ── queries ──

    @property
    def settled(self) -> bool:
        """True when this topic is finished for good and can be skipped.

        Only a DONE a **real** run wrote settles anything. A dry run's DONE is
        disregarded by every run, dry or real, so re-running the same command —
        which is the whole of resume (I5) — always re-executes work a dry run
        only pretended to do.
        """
        return self.status is TopicStatus.DONE and not self.dry_run

    # ── persistence helpers ──

    @classmethod
    def load_or_create(cls, state_dir: Path, topic_id: str, slug: str) -> Self:
        """Load existing state file, or create a fresh state for this topic."""
        path = state_dir / f'{topic_id}.json'
        if path.exists():
            return cls.model_validate_json(path.read_text(encoding='utf-8'))
        return cls(id=topic_id, slug=slug)

    def save(self, state_dir: Path) -> None:
        """Persist this state to ``state_dir/<id>.json`` atomically.

        Write a sibling temp file then ``replace`` it into place, so a crash
        mid-write leaves the previous state file intact rather than a truncated
        one an interrupted run could no longer parse (resumability, I5).
        ``Path.replace`` is atomic on the same filesystem on POSIX and Windows.
        """
        state_dir.mkdir(parents=True, exist_ok=True)
        path = state_dir / f'{self.id}.json'
        # use mode='json' so enums serialize as their values
        payload = self.model_dump(mode='json')
        tmp = path.with_name(f'{self.id}.json.tmp')
        tmp.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        tmp.replace(path)

    # ── transition helpers (immutable updates by reassignment) ──

    def mark_in_flight(self, owner_pid: int | None = None) -> None:
        self.status = TopicStatus.IN_FLIGHT
        self.attempts += 1
        self.started_at = _iso_now()
        self.owner_pid = owner_pid

    def mark_done(self) -> None:
        self.status = TopicStatus.DONE
        self.completed_at = _iso_now()
        self.last_error = None

    def mark_failed(self, error: str) -> None:
        self.status = TopicStatus.FAILED
        self.last_error = error

    def mark_rate_limited(self, error: str = 'rate_limit') -> None:
        self.status = TopicStatus.RATE_LIMITED
        self.last_error = error

    def mark_dead(self, reason: str) -> None:
        """Record that the process which claimed this topic is gone.

        A terminal record for the abandoned attempt, rather than leaving the
        topic at its last live state where it reads as still working. DEAD is
        not DONE, so the next invocation re-attempts it (I5).
        """
        self.status = TopicStatus.DEAD
        self.last_error = reason
        self.owner_pid = None

    def mark_blocked(self, reason: str) -> None:
        self.status = TopicStatus.BLOCKED_UPSTREAM
        self.last_error = reason

    def reset_for_retry(self, error: str) -> None:
        """Move back to PENDING after a non-rate-limit failure (for retry)."""
        self.status = TopicStatus.PENDING
        self.last_error = error

    def clear_session(self) -> None:
        """Drop the session identity so the next attempt mints its own.

        Reusing it made two of three retries in the original field incident die
        on ``Session ID ... is already in use`` rather than on the cause they
        were retrying — so the retry destroyed the evidence of the failure
        (MANT-B59).
        """
        self.session_id = None


# ── stage-specific state classes ─────────────────────────────────────


class ClaudeResearchState(TopicState):
    """Stage 1 (Claude research) per-topic state.

    Fields match the legacy flat ``state/<id>.json`` shape for resume
    compatibility (I6).
    """

    turn_1_duration_s: float | None = None
    research_file_bytes: int | None = None


class SubsessionResult(BaseModel):
    """One subsession result (Gemini or OpenRouter, for multi-session topics)."""

    subslug: str
    status: str = 'pending'  # plain string for legacy shape compatibility
    duration_s: float | None = None
    output_bytes: int | None = None
    output_path: str | None = None
    error: str | None = None
    # Resolved/served model id for this subsession (OpenRouter routes by model
    # id). Additive optional field (I4); None for the Gemini CLI path and for a
    # subsession that never reached a provider. The synthesis stage threads this
    # into the sidecar's ``sources[].model_id`` so an agent can attribute each
    # brief to the substrate that produced it.
    model: str | None = None
    # Usage/cost (OpenRouter) — additive optional fields (I4); None when the
    # provider returned no usage block or for the Gemini CLI path.
    tokens_prompt: int | None = None
    tokens_completion: int | None = None
    tokens_reasoning: int | None = None
    cost_usd: float | None = None


class GeminiResearchState(TopicState):
    """Stage 2 legacy (Gemini OAuth CLI) per-topic state."""

    subsessions: list[SubsessionResult] = Field(default_factory=list)


class OpenRouterResearchState(TopicState):
    """Stage 2 new (OpenRouter HTTP) per-topic state.

    Mirrors the Gemini multi-session shape but adds ``model`` per subsession
    (since OpenRouter routes by model id).
    """

    subsessions: list[SubsessionResult] = Field(default_factory=list)


class SynthesisState(TopicState):
    """Stage 3 (synthesis + journal) per-topic state."""

    turn_1_duration_s: float | None = None
    turn_2_duration_s: float | None = None
    synthesis_bytes: int | None = None
    journal_bytes: int | None = None
    sidecar_bytes: int | None = None  # additive (I4); the epistemic sidecar (§14)


class JournalPassesState(TopicState):
    """Stage 3.5 (journal augmentation) per-topic state."""

    duration_s: float | None = None
    augmentation_bytes: int | None = None


class FalsificationState(TopicState):
    """Stage 4 (falsification) per-topic state."""

    duration_s: float | None = None
    falsification_bytes: int | None = None


class EvaluationState(TopicState):
    """Stage 5 (evaluation) per-topic state."""

    duration_s: float | None = None
    eval_bytes: int | None = None
    verdict: str | None = None
    quality_score: float | None = None


class ClaudePriorState(TopicState):
    """Stage 5-input (claude-prior baseline) per-topic state."""

    duration_s: float | None = None
    baseline_bytes: int | None = None


# ── helpers ──────────────────────────────────────────────────────────


def _iso_now() -> str:
    """Return UTC ISO 8601 timestamp string (matches legacy format)."""
    return datetime.now(UTC).isoformat()

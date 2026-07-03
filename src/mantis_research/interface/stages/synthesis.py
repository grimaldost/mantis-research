"""Stage 3 — synthesis + journal (2-turn Claude session).

Reads Claude + Gemini briefs, produces the merged synthesis at
``outputs/synthesis/NN-slug.md`` (Turn 1), then runs the journal skill via
``--resume`` on the same session to produce ``outputs/journals/NN-slug-journal.md``
(Turn 2).

Upstream gate: requires Claude brief AND at least one Gemini brief on disk.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from mantis_research.core import prompts as default_prompts
from mantis_research.core.model_policy import resolve_claude_model
from mantis_research.core.paths import RunDirs, topic_stem
from mantis_research.core.sidecar import Provenance, ResearchSidecar, SourceRef
from mantis_research.core.stage import AttemptResult
from mantis_research.core.state import OpenRouterResearchState
from mantis_research.interface.adapters.claude_cli import (
    ClaudeCliAdapter,
    ClaudeCliOptions,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import BatchConfig, TopicConfig
    from mantis_research.core.stage import RunContext
    from mantis_research.core.state import SynthesisState

log = structlog.get_logger(__name__)

# Sidecar validate-and-re-ask budget: one initial write + this many re-asks
# on the same session before the attempt fails (§14).
_SIDECAR_MAX_ATTEMPTS = 3


def _stem_for(topic_id: str, slug: str) -> str:
    return topic_stem(topic_id, slug)


def _claude_path(dirs: RunDirs, topic_id: str, slug: str) -> Path:
    return dirs.output('claude') / f'{_stem_for(topic_id, slug)}.md'


def _gemini_paths(dirs: RunDirs, topic_id: str, slug: str) -> list[Path]:
    """Return all gemini brief paths for a topic. Multi-part dir wins."""
    return _briefs_in_stage_dir(dirs, 'gemini', topic_id, slug)


def _openrouter_paths(dirs: RunDirs, topic_id: str, slug: str) -> list[Path]:
    """Return all openrouter brief paths for a topic. Multi-part dir wins."""
    return _briefs_in_stage_dir(dirs, 'openrouter', topic_id, slug)


def _briefs_in_stage_dir(dirs: RunDirs, stage_name: str, topic_id: str, slug: str) -> list[Path]:
    """Discover brief files for a topic under a given stage's output dir."""
    base = dirs.output(stage_name)
    s = _stem_for(topic_id, slug)
    multi = base / s
    if multi.is_dir():
        return sorted(p for p in multi.glob('*.md') if p.is_file())
    single = base / f'{s}.md'
    return [single] if single.exists() else []


def _secondary_briefs(dirs: RunDirs, topic_id: str, slug: str) -> list[tuple[str, Path]]:
    """Return (model_label, path) for every non-Claude brief on disk.

    Order: gemini first, then openrouter. The model_label is the source
    stage name; downstream prompts can use it to attribute claims back
    to the right substrate.
    """
    out: list[tuple[str, Path]] = [('gemini', p) for p in _gemini_paths(dirs, topic_id, slug)]
    out.extend(('openrouter', p) for p in _openrouter_paths(dirs, topic_id, slug))
    return out


def _openrouter_brief(dirs: RunDirs, topic_id: str, slug: str, subslug: str) -> Path | None:
    """Return the brief path for one OpenRouter subsession, or None.

    Multi-part layout is ``outputs/openrouter/NN-slug/<subslug>.md``; a single
    ``subslug='single'`` subsession is ``outputs/openrouter/NN-slug.md``.
    """
    base = dirs.output('openrouter')
    s = _stem_for(topic_id, slug)
    multi = base / s / f'{subslug}.md'
    if multi.exists():
        return multi
    single = base / f'{s}.md'
    if subslug == 'single' and single.exists():
        return single
    return None


def _openrouter_subslug(path: Path, or_dir: Path, stem: str) -> str | None:
    """Return the subslug of an OpenRouter brief path, or None if it isn't one.

    Multi-part layout ``outputs/openrouter/<stem>/<subslug>.md`` → ``<subslug>``;
    single layout ``outputs/openrouter/<stem>.md`` → ``'single'``. A path outside
    the openrouter output dir (a Claude/Gemini brief) → ``None``.
    """
    if or_dir == path.parent or or_dir in path.parents:
        return path.stem if path.parent.name == stem else 'single'
    return None


@dataclass(frozen=True, slots=True)
class _Briefs:
    """Resolved primary + secondary briefs for a synthesis run (ADR-0005)."""

    primary_label: str
    primary_path: Path | None
    secondaries: list[tuple[str, Path]]


def _resolve_briefs(dirs: RunDirs, topic_id: str, slug: str, primary_spec: str | None) -> _Briefs:
    """Resolve which brief is primary and which are secondaries.

    ``None``/``'claude'`` → the Claude brief is primary (default). An
    ``'openrouter:<subslug>'`` spec promotes that subsession's brief to primary
    and demotes every other brief (Claude included, when present) to secondary.
    ``primary_path`` is ``None`` when the requested primary is not on disk, so
    ``upstream_ready`` can report it.
    """
    spec = (primary_spec or 'claude').strip()
    all_secondary = _secondary_briefs(dirs, topic_id, slug)
    if spec == 'claude':
        return _Briefs('claude', _claude_path(dirs, topic_id, slug), all_secondary)
    if spec.startswith('openrouter:'):
        subslug = spec.split(':', 1)[1]
        primary_path = _openrouter_brief(dirs, topic_id, slug, subslug)
        secondaries: list[tuple[str, Path]] = []
        claude_path = _claude_path(dirs, topic_id, slug)
        if claude_path.exists():
            secondaries.append(('claude', claude_path))
        secondaries.extend((label, p) for label, p in all_secondary if p != primary_path)
        return _Briefs(spec, primary_path, secondaries)
    # Unknown spec — no resolvable primary; upstream_ready will block clearly.
    return _Briefs(spec, None, all_secondary)


class SynthesisStage:
    """Stage 3 — Claude synthesis + journal (2 turns on one session)."""

    name: str = 'synthesis'
    state_subdir: str = 'synthesis'
    output_subdir: str = 'synthesis'

    def __init__(self, adapter: ClaudeCliAdapter | None = None) -> None:
        self._adapter = adapter or ClaudeCliAdapter()

    # ── Stage Protocol ────────────────────────────────────────────

    async def preflight(self) -> None:
        # ClaudeCliAdapter.preflight is synchronous.
        self._adapter.preflight()

    def is_enabled(self, topic: TopicConfig, config: BatchConfig) -> bool:
        return True

    def upstream_ready(
        self,
        topic_id: str,
        slug: str,
        ctx: RunContext,
    ) -> tuple[bool, str | None]:
        dirs = RunDirs(ctx.batch.runner.layout, ctx.batch.batch_name)
        briefs = _resolve_briefs(dirs, topic_id, slug, ctx.batch.models.primary)
        if briefs.primary_path is None or not briefs.primary_path.exists():
            return (False, f'missing primary brief ({briefs.primary_label})')
        if not briefs.secondaries:
            return (False, 'no secondary brief found')
        return (True, None)

    async def run_attempt(
        self,
        topic: TopicConfig,
        state: SynthesisState,
        ctx: RunContext,
    ) -> AttemptResult:
        topic_id = topic.id
        slug = topic.slug
        stem = _stem_for(topic_id, slug)
        # Resolve every directory this run touches through one layout (ADR-0006).
        dirs = RunDirs(ctx.batch.runner.layout, ctx.batch.batch_name)
        synthesis_dir = dirs.output('synthesis')
        journal_dir = dirs.output('journals')
        synthesis_dir.mkdir(parents=True, exist_ok=True)
        journal_dir.mkdir(parents=True, exist_ok=True)
        synthesis_path = synthesis_dir / f'{stem}.md'
        sidecar_path = synthesis_dir / f'{stem}.sidecar.json'
        journal_path = journal_dir / f'{stem}-journal.md'

        # Resolve primary + secondaries from config (ADR-0005). Default is the
        # Claude brief; an 'openrouter:<subslug>' primary promotes that brief
        # and demotes the rest (Path B, no promote script needed).
        briefs = _resolve_briefs(dirs, topic_id, slug, ctx.batch.models.primary)
        primary_path = briefs.primary_path
        if primary_path is None:
            return AttemptResult.fail(
                error=f'primary brief unresolved ({briefs.primary_label})',
            )
        secondaries = briefs.secondaries
        secondary_block = '\n'.join(
            f'- [{label}] {p.as_posix()} ({p.stat().st_size / 1024:.1f} KB)'
            for label, p in secondaries
        )
        primary_size_kb = primary_path.stat().st_size / 1024
        # Prompt-variable aliases: new prompts use {primary_*} / {secondary_*};
        # legacy prompts use {claude_*} / {gemini_*}, bound here to the resolved
        # primary and the secondary block so every existing template keeps working.
        claude_path = primary_path
        gemini_block = secondary_block
        gemini_count = len(secondaries)

        # Build Turn-1 (synthesis) prompt
        synth_template = (
            topic.stages.synthesis.prompt
            or ctx.batch.default_prompts.synthesis
            or default_prompts.SYNTHESIS
        )
        synth_prompt = synth_template.format(
            # New primary/secondary vocabulary (ADR-0005).
            primary_path=primary_path.as_posix(),
            primary_size_kb=primary_size_kb,
            primary_label=briefs.primary_label,
            secondary_count=gemini_count,
            secondary_block=secondary_block,
            # Legacy aliases bound to the resolved primary — old templates work.
            claude_path=claude_path.as_posix(),
            claude_size_kb=primary_size_kb,
            gemini_count=gemini_count,
            gemini_block=gemini_block,
            synthesis_path=synthesis_path.as_posix(),
        )

        synth_model_cfg = ctx.batch.models.synthesis or ctx.batch.models.claude
        # Synthesis/journal run on the Claude CLI → resolve the auto sentinel to
        # the latest-resolving alias; explicit pins pass through unchanged.
        model = resolve_claude_model(synth_model_cfg.model)
        effort = synth_model_cfg.effort or 'max'
        session_id = state.session_id or str(uuid.uuid4())
        ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')

        # ── Turn 1 — synthesis (skipped on idempotent re-entry) ────
        # A sidecar/journal failure re-runs the attempt, but the expensive brief
        # must not be regenerated: if it already exists and its size was
        # recorded, skip Turn 1 and resume at the sidecar/journal steps (§14).
        need_brief = not (synthesis_path.exists() and state.synthesis_bytes)
        if need_brief:
            t1_transcript = dirs.transcripts() / f'{stem}-{ts}-synth-turn1.log'
            t1_options = ClaudeCliOptions(
                model=model,
                effort=effort,
                session_id=session_id,
                name=f'synthesis-topic-{topic_id}',
                add_dirs=(
                    dirs.output('claude'),
                    dirs.output('gemini'),
                    dirs.output('openrouter'),
                    synthesis_dir,
                    journal_dir,
                ),
                allowed_tools=('Read', 'Write'),
            )
            t1 = await self._adapter.run(
                prompt=synth_prompt,
                options=t1_options,
                transcript_path=t1_transcript,
                dry_run=ctx.dry_run,
            )
            state.session_id = t1.session_id
            state.turn_1_duration_s = t1.duration_s
            if not t1.success:
                return AttemptResult.fail(
                    error=t1.error or 'synthesis turn 1 failed',
                    error_output=t1.raw_output,
                )
            if not ctx.dry_run and not synthesis_path.exists():
                return AttemptResult.fail(
                    error=f'synthesis file not produced at {synthesis_path.name}',
                    error_output=t1.raw_output,
                )
            state.synthesis_bytes = synthesis_path.stat().st_size if synthesis_path.exists() else 0

        # ── Sidecar — epistemic JSON (bounded validate-and-re-ask) ──
        # A malformed sidecar must not fail the whole 2-turn attempt; the loop
        # re-asks on the same session up to twice before giving up (ADR-0003 §14).
        if not ctx.dry_run:
            sidecar_ok = await self._emit_sidecar(
                topic=topic,
                dirs=dirs,
                stem=stem,
                synthesis_path=synthesis_path,
                sidecar_path=sidecar_path,
                briefs=briefs,
                model=model,
                effort=effort,
                ts=ts,
                state=state,
            )
            if not sidecar_ok:
                return AttemptResult.fail(
                    error=f'sidecar not valid after retries at {sidecar_path.name}',
                )
            state.sidecar_bytes = sidecar_path.stat().st_size if sidecar_path.exists() else None

        # Journal (Turn 2) is optional: stages.journal.enabled=False skips it and
        # the attempt succeeds on synthesis alone. None/True keep it on — the
        # batch default stays journal-on (ADR-0002).
        if topic.stages.journal.enabled is False:
            state.journal_bytes = None
            return AttemptResult.ok(output_bytes=state.synthesis_bytes)

        # Build Turn-2 (journal) prompt
        journal_template = (
            topic.stages.journal.prompt
            or ctx.batch.default_prompts.journal
            or default_prompts.JOURNAL
        )
        journal_prompt = journal_template.format(
            synthesis_path=synthesis_path.as_posix(),
            journal_path=journal_path.as_posix(),
        )

        # ── Turn 2 — journal ───────────────────────────────────────
        # Resume the synthesis session when Turn 1 ran this attempt; on
        # idempotent re-entry that session is stale, so start a fresh one (the
        # journal prompt reads the synthesis from disk either way).
        t2_transcript = dirs.transcripts() / f'{stem}-{ts}-synth-turn2.log'
        t2_options = ClaudeCliOptions(
            model=model,
            session_id=str(uuid.uuid4()) if not need_brief else None,
            resume_session_id=session_id if need_brief else None,
            allowed_tools=('Read', 'Write'),
            add_dirs=(synthesis_dir, journal_dir),
        )
        t2 = await self._adapter.run(
            prompt=journal_prompt,
            options=t2_options,
            transcript_path=t2_transcript,
            dry_run=ctx.dry_run,
        )
        state.turn_2_duration_s = t2.duration_s
        if not t2.success:
            return AttemptResult.fail(
                error=t2.error or 'journal turn 2 failed',
                error_output=t2.raw_output,
            )
        if not ctx.dry_run and not journal_path.exists():
            return AttemptResult.fail(
                error=f'journal file not produced at {journal_path.name}',
                error_output=t2.raw_output,
            )
        state.journal_bytes = journal_path.stat().st_size if journal_path.exists() else 0

        return AttemptResult.ok(output_bytes=state.synthesis_bytes)

    # ── sidecar emission ──────────────────────────────────────────

    async def _emit_sidecar(
        self,
        *,
        topic: TopicConfig,
        dirs: RunDirs,
        stem: str,
        synthesis_path: Path,
        sidecar_path: Path,
        briefs: _Briefs,
        model: str,
        effort: str,
        ts: str,
        state: SynthesisState,
    ) -> bool:
        """Emit + validate the epistemic sidecar with bounded re-asks (§14).

        The model reads the brief and writes the JSON sidecar (its own turn, so a
        malformed sidecar never re-runs the synthesis). On schema-validation
        failure the loop re-asks on the same session, feeding back the error, up
        to ``_SIDECAR_MAX_ATTEMPTS`` total. On success the runner-authored
        identity/provenance fields are merged in and the file rewritten. Returns
        True on a valid, merged sidecar; False when the budget is exhausted
        (the brief is left intact for the next attempt).
        """
        sidecar_session = str(uuid.uuid4())
        base_prompt = default_prompts.SYNTHESIS_SIDECAR.format(
            synthesis_path=synthesis_path.as_posix(),
            sidecar_path=sidecar_path.as_posix(),
        )
        last_error = 'sidecar not written'
        for attempt in range(_SIDECAR_MAX_ATTEMPTS):
            first = attempt == 0
            prompt = (
                base_prompt
                if first
                else (
                    f'Your previous sidecar at {sidecar_path.as_posix()} failed schema '
                    f'validation:\n{last_error}\n\nRewrite {sidecar_path.as_posix()} as '
                    f'valid JSON matching the required shape. Emit ONLY the JSON object.'
                )
            )
            options = ClaudeCliOptions(
                model=model,
                effort=effort,
                session_id=sidecar_session if first else None,
                resume_session_id=None if first else sidecar_session,
                name=f'sidecar-topic-{topic.id}',
                add_dirs=(dirs.output('synthesis'),),
                allowed_tools=('Read', 'Write'),
            )
            transcript = dirs.transcripts() / f'{stem}-{ts}-sidecar-{attempt + 1}.log'
            result = await self._adapter.run(
                prompt=prompt, options=options, transcript_path=transcript
            )
            if not result.success:
                last_error = result.error or 'sidecar turn failed'
                continue
            # File read / validate / merge / rewrite is synchronous, kept out of
            # this async method (blocking Path I/O belongs in a sync helper).
            err = self._validate_and_merge(sidecar_path, topic, dirs, synthesis_path, briefs, state)
            if err is None:
                return True
            last_error = err
            log.info('sidecar invalid, re-asking', topic_id=topic.id, attempt=attempt + 1)
        log.warning('sidecar failed after retries', topic_id=topic.id, error=last_error)
        return False

    @classmethod
    def _validate_and_merge(
        cls,
        sidecar_path: Path,
        topic: TopicConfig,
        dirs: RunDirs,
        synthesis_path: Path,
        briefs: _Briefs,
        state: SynthesisState,
    ) -> str | None:
        """Validate the model-written sidecar and, on success, rewrite it with
        the runner-authored fields merged in. Returns None on success, or an
        error string to feed back to the next re-ask. Synchronous (Path I/O)."""
        if not sidecar_path.exists():
            return 'sidecar file not written'
        try:
            sc = ResearchSidecar.from_model_json(sidecar_path.read_text(encoding='utf-8'))
        except ValidationError as exc:
            return str(exc)
        merged = cls._fill_runner_fields(sc, topic, dirs, synthesis_path, briefs, state)
        sidecar_path.write_text(merged.to_json(), encoding='utf-8')
        return None

    @staticmethod
    def _fill_runner_fields(
        sc: ResearchSidecar,
        topic: TopicConfig,
        dirs: RunDirs,
        synthesis_path: Path,
        briefs: _Briefs,
        state: SynthesisState,
    ) -> ResearchSidecar:
        """Merge runner-authored identity + provenance onto the model's sidecar."""
        # Load the OpenRouter state once: it feeds both the per-source model ids
        # (empty subsessions when absent → Claude/Gemini-only run) and the cost
        # aggregation below.
        or_state = OpenRouterResearchState.load_or_create(
            dirs.state('openrouter'), topic.id, topic.slug
        )
        or_dir = dirs.output('openrouter')
        stem = topic_stem(topic.id, topic.slug)
        model_by_subslug = {s.subslug: s.model for s in or_state.subsessions}

        def _source_ref(label: str, path: Path) -> SourceRef:
            # An OpenRouter brief carries an `openrouter:<subslug>` label and the
            # resolved model id, so an agent can attribute the brief to the model
            # that produced it (was: label collapsed to a bare 'openrouter',
            # model_id null). Claude/Gemini briefs keep their stage label; their
            # model is not tracked in state, so model_id stays None.
            subslug = _openrouter_subslug(path, or_dir, stem)
            if subslug is not None:
                return SourceRef(
                    label=f'openrouter:{subslug}',
                    path=path.as_posix(),
                    model_id=model_by_subslug.get(subslug),
                    bytes=path.stat().st_size,
                )
            return SourceRef(label=label, path=path.as_posix(), bytes=path.stat().st_size)

        sources: list[SourceRef] = []
        if briefs.primary_path is not None:
            sources.append(_source_ref(briefs.primary_label, briefs.primary_path))
        sources.extend(_source_ref(label, p) for label, p in briefs.secondaries)

        provenance = Provenance.from_subsessions(
            or_state.subsessions, synthesis_duration_s=state.turn_1_duration_s
        )
        return sc.model_copy(
            update={
                'topic_id': topic.id,
                'slug': topic.slug,
                'batch_name': dirs.batch_name,
                'synthesis_path': synthesis_path.as_posix(),
                'generated_at': datetime.now(UTC).isoformat(),
                'sources': sources,
                'provenance': provenance,
            }
        )

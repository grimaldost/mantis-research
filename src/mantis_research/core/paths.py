"""Project path layout — single source of truth for where things live.

The project root is the directory containing ``pyproject.toml``. All
runtime directories (state, outputs, logs, transcripts) sit at the project
root. This module returns ``Path`` objects only — it does NOT create
directories. Callers create what they need (directories are created at
write time inside the relevant adapter or stage).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _find_project_root(start: Path) -> Path:
    """Walk up from ``start`` to the directory containing pyproject.toml.

    Falls back to the current working directory when no such directory exists —
    the case for an **installed** wheel (``uv tool install``), whose package lives
    in an isolated venv with no project tree. Runtime data dirs then live under
    the caller's CWD, the intuitive location for an installed CLI (git/npm do the
    same). A source checkout still resolves to the repo root, so dev behaviour is
    unchanged.
    """
    for parent in start.parents:
        if (parent / 'pyproject.toml').exists():
            return parent
    return Path.cwd()


def project_root() -> Path:
    """Return the project root (the dir containing pyproject.toml), or CWD.

    In a source checkout this is the repo root; for an installed package there is
    no project tree, so it falls back to the current working directory rather than
    raising (which would make the installed CLI / MCP server unable to run — the
    ``project root not found`` failure the isolated-tool install used to hit).
    """
    return _find_project_root(Path(__file__).resolve())


def outputs_root() -> Path:
    """Return the ``outputs/`` directory under the project root."""
    return project_root() / 'outputs'


def state_root() -> Path:
    """Return the ``state/`` directory under the project root."""
    return project_root() / 'state'


def logs_root() -> Path:
    """Return the ``logs/`` directory under the project root."""
    return project_root() / 'logs'


def transcripts_root() -> Path:
    """Return the ``transcripts/`` directory under the project root."""
    return project_root() / 'transcripts'


# ── topic filename stems ──────────────────────────────────────────────


def topic_nn(topic_id: str) -> str:
    """Return the filename id-prefix for a topic.

    Numeric ids zero-pad to two digits (``'7'`` → ``'07'``, ``'901'`` →
    ``'901'``), preserving every existing ``NN-slug`` path. Non-numeric ids —
    which ``TopicConfig`` permits — pass through verbatim (``'a5'`` → ``'a5'``)
    instead of raising, which the old ``int(topic_id)`` formatting did.
    """
    try:
        return f'{int(topic_id):02d}'
    except ValueError:
        return topic_id


def topic_stem(topic_id: str, slug: str) -> str:
    """Return the ``NN-slug`` file stem for a topic (see :func:`topic_nn`)."""
    return f'{topic_nn(topic_id)}-{slug}'


# ── legacy flat directories (the default 'legacy' layout) ─────────────
# These are the flat directories every committed batch uses. They are NOT
# being migrated away: the batch-scoped layout (ADR-0006, ``run_*`` resolvers
# above) is opt-in via ``runner.layout: 'batch'``, and legacy stays the default
# so existing batches keep resuming from their on-disk state unchanged (I6).


def legacy_state_dir(stage_name: str) -> Path:
    """Return the pre-refactor flat state directory for a stage."""
    if stage_name == 'claude':
        return project_root() / 'state'
    return project_root() / f'state-{stage_name}'


LEGACY_OUTPUT_DIRS: dict[str, str] = {
    'claude': 'research-outputs',
    'gemini': 'research-outputs-gemini',
    'openrouter': 'research-outputs-openrouter',
    'synthesis': 'research-outputs-synthesis',
    'journals': 'journals',
    'falsification': 'research-outputs-falsification',
    'evaluation': 'evaluations',
    'claude-prior': 'claude-prior-baselines',
}


def legacy_output_dir(stage_name: str) -> Path:
    """Return the pre-refactor flat output directory for a stage."""
    return project_root() / LEGACY_OUTPUT_DIRS.get(stage_name, stage_name)


# ── layout-aware run directories (ADR-0006) ──────────────────────────
# Two layouts, selected per config (``runner.layout``). ``'legacy'`` reproduces
# the flat directories above exactly (byte-identical paths — the 44 committed
# configs stay here by default). ``'batch'`` scopes every run under its own
# ``<batch_name>`` subtree so request-level runs (``mantis research``) and
# reruns never collide. A run resolves ALL its directories through one layout —
# there is no cross-layout fallback.

Layout = str  # 'legacy' | 'batch' (validated as a Literal on RunnerBlock)


def run_state_dir(layout: Layout, batch_name: str, stage_name: str) -> Path:
    """Return the per-stage state directory for a run under ``layout``."""
    if layout == 'batch':
        return state_root() / batch_name / stage_name
    return legacy_state_dir(stage_name)


def run_output_dir(layout: Layout, batch_name: str, stage_name: str) -> Path:
    """Return the per-stage output directory for a run under ``layout``."""
    if layout == 'batch':
        return outputs_root() / batch_name / stage_name
    return legacy_output_dir(stage_name)


def run_transcript_dir(layout: Layout, batch_name: str) -> Path:
    """Return the transcript directory for a run under ``layout``."""
    if layout == 'batch':
        return transcripts_root() / batch_name
    return transcripts_root()


@dataclass(frozen=True, slots=True)
class RunDirs:
    """Resolves one run's directories under its layout (ADR-0006).

    A stage constructs this once from ``ctx.batch`` and resolves every
    directory it touches — its own output and other stages' outputs it
    discovers — through it, so a run never mixes layouts. Pure: returns
    ``Path`` objects, creates nothing.
    """

    layout: Layout
    batch_name: str

    def output(self, stage_name: str) -> Path:
        return run_output_dir(self.layout, self.batch_name, stage_name)

    def state(self, stage_name: str) -> Path:
        return run_state_dir(self.layout, self.batch_name, stage_name)

    def transcripts(self) -> Path:
        return run_transcript_dir(self.layout, self.batch_name)

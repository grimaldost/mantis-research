"""Project path layout — single source of truth for where things live.

The project root is the directory containing ``pyproject.toml``; config lookup
resolves against it. All runtime directories (state, outputs, logs,
transcripts) sit at the **data root** (:func:`data_root`), which is the project
root in a checkout and a stable per-user directory when the package runs from
Claude Code's versioned plugin cache. This module returns ``Path`` objects only
— it does NOT create directories. Callers create what they need (directories
are created at write time inside the relevant adapter or stage).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mantis_research.core.settings import settings


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


#: The path segments Claude Code installs plugins under. A plugin's files sit
#: below them in one directory per marketplace, plugin and version.
_PLUGIN_CACHE_PARTS = ('.claude', 'plugins', 'cache')

#: The per-user data root a plugin-cache install falls back to, under the home
#: directory.
_USER_DATA_DIR = '.mantis'


def in_plugin_cache(path: Path) -> bool:
    """True when ``path`` lies inside Claude Code's plugin cache."""
    parts = path.parts
    width = len(_PLUGIN_CACHE_PARTS)
    return any(parts[i : i + width] == _PLUGIN_CACHE_PARTS for i in range(len(parts) - width + 1))


def _resolve_data_root(
    package_file: Path,
    *,
    override: str | None,
    home: Path,
    project_root: Path,
) -> Path:
    """Decide where runtime data lives, from the facts passed in (pure).

    An explicit ``override`` (``MANTIS_HOME``) wins; an empty one counts as
    unset, which is what a bare ``MANTIS_HOME=`` line in a ``.env`` reads as.
    Otherwise a package running from the plugin cache writes under
    ``<home>/.mantis``: the cache keeps one directory per plugin version, so
    data kept there is left behind by every upgrade and deleted with the old
    version, and two versions would each hold their own seat lock. Anything
    else — a checkout, or an installed wheel's working-directory fallback —
    keeps the project root, so existing trees stay where they are.
    """
    if override:
        return Path(override).expanduser()
    if in_plugin_cache(package_file):
        return home / _USER_DATA_DIR
    return project_root


def data_root() -> Path:
    """Return the directory every runtime tree (outputs, state, logs, transcripts) sits in.

    Distinct from :func:`project_root`, which config lookup keeps using: a
    plugin's configs ship with its version, its runs must not.
    """
    return _resolve_data_root(
        Path(__file__).resolve(),
        override=settings.MANTIS_HOME,
        home=Path.home(),
        project_root=project_root(),
    )


def outputs_root() -> Path:
    """Return the ``outputs/`` directory under the data root."""
    return data_root() / 'outputs'


def state_root() -> Path:
    """Return the ``state/`` directory under the data root."""
    return data_root() / 'state'


def logs_root() -> Path:
    """Return the ``logs/`` directory under the data root."""
    return data_root() / 'logs'


def transcripts_root() -> Path:
    """Return the ``transcripts/`` directory under the data root."""
    return data_root() / 'transcripts'


def seat_lock_path() -> Path:
    """Return the lock file for the machine's single local Claude seat.

    Machine-scoped, not run-scoped: the seat is one authenticated CLI, so every
    run queues on the same file (MANT-B08). It sits under the data root, which
    for a plugin install is the same directory whichever version is running.
    """
    return state_root() / 'claude-seat.lock'


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
        return data_root() / 'state'
    return data_root() / f'state-{stage_name}'


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
    return data_root() / LEGACY_OUTPUT_DIRS.get(stage_name, stage_name)


# ── layout-aware run directories (ADR-0006) ──────────────────────────
# Two layouts, selected per config (``runner.layout``). ``'legacy'`` reproduces
# the flat directories above exactly (byte-identical paths — historical
# batches resume there by default). ``'batch'`` scopes every run under its own
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


def run_root_dir(layout: Layout, batch_name: str) -> Path:
    """Return the directory that *is* the run, under ``layout``.

    Under ``'batch'`` this is the run's own subtree, which is where run-level
    records (the run manifest) belong. The flat ``'legacy'`` layout has no such
    thing — every batch shares the output root — so it resolves there, and a
    run-level record under legacy is shared, not per-run.
    """
    if layout == 'batch':
        return outputs_root() / batch_name
    return outputs_root()


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

    def root(self) -> Path:
        return run_root_dir(self.layout, self.batch_name)

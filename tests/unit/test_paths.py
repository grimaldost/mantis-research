"""Unit tests for mantis_research.core.paths."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mantis_research.core import paths
from mantis_research.core.paths import (
    LEGACY_OUTPUT_DIRS,
    RunDirs,
    _find_project_root,
    _resolve_data_root,
    data_root,
    legacy_output_dir,
    legacy_state_dir,
    logs_root,
    outputs_root,
    project_root,
    run_output_dir,
    run_state_dir,
    run_transcript_dir,
    seat_lock_path,
    state_root,
    topic_nn,
    topic_stem,
    transcripts_root,
)
from mantis_research.core.settings import settings

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class TestRunLayoutResolvers:
    def test_legacy_layout_reproduces_flat_dirs(self) -> None:
        # Byte-identical to the pre-existing helpers — every committed config
        # stays here (batch_name is ignored under legacy).
        assert run_state_dir('legacy', 'anybatch', 'claude') == legacy_state_dir('claude')
        assert run_state_dir('legacy', 'anybatch', 'synthesis') == legacy_state_dir('synthesis')
        assert run_output_dir('legacy', 'anybatch', 'claude') == legacy_output_dir('claude')
        assert run_output_dir('legacy', 'anybatch', 'synthesis') == legacy_output_dir('synthesis')
        assert run_transcript_dir('legacy', 'anybatch') == transcripts_root()

    def test_batch_layout_scopes_under_batch_name(self) -> None:
        assert run_state_dir('batch', 'b7', 'claude') == state_root() / 'b7' / 'claude'
        assert run_output_dir('batch', 'b7', 'synthesis') == outputs_root() / 'b7' / 'synthesis'
        assert run_transcript_dir('batch', 'b7') == transcripts_root() / 'b7'

    def test_rundirs_delegates(self) -> None:
        d = RunDirs('batch', 'b7')
        assert d.output('claude') == run_output_dir('batch', 'b7', 'claude')
        assert d.state('synthesis') == run_state_dir('batch', 'b7', 'synthesis')
        assert d.transcripts() == run_transcript_dir('batch', 'b7')


class TestTopicStem:
    @pytest.mark.parametrize(
        ('topic_id', 'expected_nn'),
        [
            ('7', '07'),  # single digit zero-pads (legacy behavior preserved)
            ('07', '07'),  # already two digits
            ('42', '42'),
            ('901', '901'),  # three digits pass through, no truncation
            ('a5', 'a5'),  # non-numeric id passes through verbatim (was a crash)
            ('501', '501'),
        ],
    )
    def test_topic_nn(self, topic_id: str, expected_nn: str) -> None:
        assert topic_nn(topic_id) == expected_nn

    @pytest.mark.parametrize(
        ('topic_id', 'expected_stem'),
        [
            ('7', '07-semiconductor'),
            ('901', '901-semiconductor'),
            ('a5', 'a5-semiconductor'),
        ],
    )
    def test_topic_stem(self, topic_id: str, expected_stem: str) -> None:
        assert topic_stem(topic_id, 'semiconductor') == expected_stem

    def test_non_numeric_id_does_not_raise(self) -> None:
        # The old `int(topic_id)` formatting raised ValueError here; TopicConfig
        # permits non-numeric ids, so the helper must not crash.
        assert topic_stem('agent-x', 'slug') == 'agent-x-slug'


class TestProjectRoot:
    def test_finds_root_with_pyproject(self) -> None:
        root = project_root()
        assert (root / 'pyproject.toml').exists()
        assert (root / 'src' / 'mantis_research').is_dir()


class TestLayout:
    def test_outputs_root_under_data_root(self) -> None:
        assert outputs_root() == data_root() / 'outputs'

    def test_state_root_under_data_root(self) -> None:
        assert state_root() == data_root() / 'state'

    def test_a_checkout_keeps_its_data_at_the_repo_root(self) -> None:
        # Byte-identical to before the data root existed: every committed batch
        # and every legacy flat directory stays where it was.
        assert data_root() == project_root()


def _cached_package(base: Path, version: str) -> Path:
    """Where the package file sits when Claude Code runs the plugin from its cache."""
    install = base / '.claude' / 'plugins' / 'cache' / 'x' / 'mantis-research' / version
    return install / 'src' / 'mantis_research' / 'core' / 'paths.py'


class TestDataRootResolution:
    """`_resolve_data_root`: runtime data leaves the versioned plugin cache (T4e)."""

    def test_a_plugin_cache_install_resolves_to_the_per_user_root(self, tmp_path: Path) -> None:
        # The cache directory is per version, so data kept there is orphaned by
        # every upgrade and deleted when the old version is pruned.
        home = tmp_path / 'home'
        pkg = _cached_package(home, '0.6.0')
        install = pkg.parents[3]
        resolved = _resolve_data_root(pkg, override=None, home=home, project_root=install)
        assert resolved == home / '.mantis'

    def test_a_checkout_resolves_to_the_repo_root(self, tmp_path: Path) -> None:
        repo = tmp_path / 'repo'
        pkg = repo / 'src' / 'mantis_research' / 'core' / 'paths.py'
        assert _resolve_data_root(pkg, override=None, home=tmp_path, project_root=repo) == repo

    def test_an_installed_wheel_keeps_the_cwd_fallback(self, tmp_path: Path) -> None:
        pkg = tmp_path / 'venv' / 'site-packages' / 'mantis_research' / 'core' / 'paths.py'
        cwd = tmp_path / 'workdir'
        assert _resolve_data_root(pkg, override=None, home=tmp_path, project_root=cwd) == cwd

    @pytest.mark.parametrize('where', ['cache', 'checkout'])
    def test_an_override_wins_over_both(self, tmp_path: Path, where: str) -> None:
        if where == 'cache':
            pkg = _cached_package(tmp_path / 'home', '0.6.0')
        else:
            pkg = tmp_path / 'repo' / 'src' / 'mantis_research' / 'core' / 'paths.py'
        chosen = tmp_path / 'chosen'
        resolved = _resolve_data_root(
            pkg, override=str(chosen), home=tmp_path / 'home', project_root=tmp_path / 'repo'
        )
        assert resolved == chosen

    def test_an_override_expands_the_home_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setenv('USERPROFILE', str(tmp_path))
        pkg = tmp_path / 'repo' / 'src' / 'mantis_research' / 'core' / 'paths.py'
        resolved = _resolve_data_root(
            pkg, override='~/mantis-data', home=tmp_path, project_root=tmp_path / 'repo'
        )
        assert resolved == tmp_path / 'mantis-data'

    def test_an_empty_override_counts_as_unset(self, tmp_path: Path) -> None:
        # `MANTIS_HOME=` in a .env reads as an empty string, not as None.
        repo = tmp_path / 'repo'
        pkg = repo / 'src' / 'mantis_research' / 'core' / 'paths.py'
        assert _resolve_data_root(pkg, override='', home=tmp_path, project_root=repo) == repo


@pytest.fixture
def run_from_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[[str], Path]:
    """Make the live resolvers see a package file inside a plugin cache.

    Returns a function that installs a given version and gives back the
    per-user data root that version should resolve to.
    """
    home = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    monkeypatch.setattr(settings, 'MANTIS_HOME', None)

    def install(version: str) -> Path:
        monkeypatch.setattr(paths, '__file__', str(_cached_package(home, version)))
        return home / '.mantis'

    return install


class TestDataRootFromAPluginCache:
    def test_every_runtime_dir_and_the_seat_lock_leave_the_cache(
        self, run_from_cache: Callable[[str], Path]
    ) -> None:
        root = run_from_cache('0.6.0')
        assert data_root() == root
        assert outputs_root() == root / 'outputs'
        assert state_root() == root / 'state'
        assert logs_root() == root / 'logs'
        assert transcripts_root() == root / 'transcripts'
        assert seat_lock_path() == root / 'state' / 'claude-seat.lock'

    def test_the_legacy_flat_dirs_follow_the_data_root(
        self, run_from_cache: Callable[[str], Path]
    ) -> None:
        root = run_from_cache('0.6.0')
        assert legacy_state_dir('claude') == root / 'state'
        assert legacy_state_dir('synthesis') == root / 'state-synthesis'
        assert legacy_output_dir('synthesis') == root / 'research-outputs-synthesis'

    def test_two_plugin_versions_queue_on_one_seat_lock(
        self, run_from_cache: Callable[[str], Path]
    ) -> None:
        # The seat is one authenticated CLI per machine. A lock inside each
        # version's own directory let an old and a new version hold the seat at
        # the same time.
        run_from_cache('0.5.1')
        old = seat_lock_path()
        run_from_cache('0.6.0')
        assert seat_lock_path() == old

    def test_mantis_home_overrides_the_cache_default(
        self,
        run_from_cache: Callable[[str], Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        run_from_cache('0.6.0')
        monkeypatch.setattr(settings, 'MANTIS_HOME', str(tmp_path / 'elsewhere'))
        assert outputs_root() == tmp_path / 'elsewhere' / 'outputs'


class TestProjectRootResolution:
    """`_find_project_root` (the installed-vs-clone fix)."""

    def test_finds_pyproject_walking_up(self, tmp_path: Path) -> None:
        (tmp_path / 'pyproject.toml').write_text('', encoding='utf-8')
        pkg = tmp_path / 'src' / 'mantis_research' / 'core'
        pkg.mkdir(parents=True)
        assert _find_project_root(pkg / 'paths.py') == tmp_path

    def test_falls_back_to_cwd_when_no_project_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Installed wheel: __file__ lives in an isolated venv with no pyproject
        # anywhere above it → resolve to CWD (never raise). This is the bug the
        # fresh-install acceptance test caught.
        cwd = tmp_path / 'workdir'
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        installed = tmp_path / 'venv' / 'site-packages' / 'mantis_research' / 'core'
        installed.mkdir(parents=True)
        assert _find_project_root(installed / 'paths.py') == cwd


class TestLegacyPaths:
    def test_legacy_state_claude_is_flat(self) -> None:
        assert legacy_state_dir('claude') == project_root() / 'state'

    def test_legacy_state_other_stages_are_dashed(self) -> None:
        assert legacy_state_dir('gemini') == project_root() / 'state-gemini'
        assert legacy_state_dir('synthesis') == project_root() / 'state-synthesis'

    def test_legacy_output_dirs_match_existing_layout(self) -> None:
        # These names match what's actually on disk from batch-10 / batch-11.
        assert legacy_output_dir('claude') == project_root() / 'research-outputs'
        assert legacy_output_dir('gemini') == project_root() / 'research-outputs-gemini'
        assert legacy_output_dir('synthesis') == project_root() / 'research-outputs-synthesis'
        assert legacy_output_dir('journals') == project_root() / 'journals'
        assert legacy_output_dir('evaluation') == project_root() / 'evaluations'
        assert legacy_output_dir('claude-prior') == project_root() / 'claude-prior-baselines'

    def test_legacy_dirs_dict_has_all_known_stages(self) -> None:
        expected = {
            'claude',
            'gemini',
            'openrouter',
            'synthesis',
            'journals',
            'falsification',
            'evaluation',
            'claude-prior',
        }
        assert expected == set(LEGACY_OUTPUT_DIRS.keys())

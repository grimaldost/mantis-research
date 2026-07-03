"""Unit tests for mantis_research.core.paths."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mantis_research.core.paths import (
    LEGACY_OUTPUT_DIRS,
    RunDirs,
    _find_project_root,
    legacy_output_dir,
    legacy_state_dir,
    outputs_root,
    project_root,
    run_output_dir,
    run_state_dir,
    run_transcript_dir,
    state_root,
    topic_nn,
    topic_stem,
    transcripts_root,
)

if TYPE_CHECKING:
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
    def test_outputs_root_under_project(self) -> None:
        assert outputs_root() == project_root() / 'outputs'

    def test_state_root_under_project(self) -> None:
        assert state_root() == project_root() / 'state'


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

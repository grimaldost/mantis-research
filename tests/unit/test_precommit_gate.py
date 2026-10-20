"""The pre-commit gate has to exist as an installable hook, not as prose.

The git hooks are railform's wrappers, tracked in ``.githooks/`` and checked by
``railform hooks-check`` (CI's ``hooks`` job and the ``railform-hooks-check`` hook), so this file
does not re-read their text. What stays here is what only this repository can know: the
documents teach the arming step, the old hooks directory is a stub that fails a clone still
armed to it, and the hooks the repository keeps beside railform's carry an explicit stage.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_OLD_HOOKS = _ROOT / 'scripts' / 'git-hooks'
_HOOK_NAMES = ('pre-commit', 'commit-msg', 'pre-push')


def test_contributing_documents_arming_the_hooks_directory() -> None:
    contributing = (_ROOT / 'CONTRIBUTING.md').read_text(encoding='utf-8')
    assert 'railform arm' in contributing
    assert '.githooks' in contributing


def test_readme_points_at_the_arming_step_rather_than_assuming_it() -> None:
    readme = (_ROOT / 'README.md').read_text(encoding='utf-8')
    assert 'railform arm' in readme


def test_old_hooks_directory_holds_only_stubs_that_fail() -> None:
    # A clone still armed to scripts/git-hooks must fail loudly: a missing hook there would let
    # a commit through unchecked, which is how a gate quietly becomes advisory.
    for name in _HOOK_NAMES:
        body = (_OLD_HOOKS / name).read_text(encoding='utf-8')
        assert 'railform arm' in body
        assert body.rstrip().endswith('exit 1')


def _repository_hooks(config: str) -> str:
    """The config without the region `railform adopt` owns."""
    return re.sub(
        r'^ *# >>> railform:.*?^ *# <<< railform\n', '', config, flags=re.DOTALL | re.MULTILINE
    )


def test_config_gives_every_repository_hook_an_explicit_stage() -> None:
    # The tree lane (`--hook-stage pre-commit`) and the message lane
    # (`--hook-stage commit-msg`) share one config; a hook without an explicit
    # `stages:` runs in every lane, which is how a check would end up running twice.
    config = _repository_hooks((_ROOT / '.pre-commit-config.yaml').read_text(encoding='utf-8'))
    hook_ids = [line.split('- id:')[1].strip() for line in config.splitlines() if '- id:' in line]
    stage_lines = [line for line in config.splitlines() if line.strip().startswith('stages:')]
    assert hook_ids, 'the repository keeps hooks beside railform'
    assert len(stage_lines) == len(hook_ids), (
        f'every hook needs an explicit stages: line — {len(hook_ids)} hooks, '
        f'{len(stage_lines)} stages lines'
    )

"""The pre-commit gate has to exist as an installable hook, not as prose.

`.git/hooks/` held only the stock samples, so the README sentence "the
pre-commit hooks and the commands above are the gate" was half untrue on the
machine this project is developed on. The hook is checked in under
`scripts/git-hooks/` and wired with `core.hooksPath`, because bare `.exe`
shims (what `pre-commit install` writes) are blocked here — the hook must go
through `uv run python -m pre_commit` (backlog MANT-B11).
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _ROOT / 'scripts' / 'git-hooks' / 'pre-commit'


def test_pre_commit_hook_script_is_checked_in() -> None:
    assert _HOOK.exists(), 'the pre-commit hook must be a checked-in file, not a local convention'


def test_hook_invokes_pre_commit_through_uv_run_python_m() -> None:
    body = _HOOK.read_text(encoding='utf-8')
    assert 'uv run python -m pre_commit' in body


def test_hook_does_not_call_the_blocked_bare_shim() -> None:
    # A line whose command word is the bare `pre-commit` shim is what
    # Application Control blocks on this machine.
    body = _HOOK.read_text(encoding='utf-8')
    commands = [line.strip() for line in body.splitlines() if not line.lstrip().startswith('#')]
    assert not any(cmd.startswith(('pre-commit ', 'exec pre-commit ')) for cmd in commands)


def test_contributing_documents_the_hooks_path_install() -> None:
    contributing = (_ROOT / 'CONTRIBUTING.md').read_text(encoding='utf-8')
    assert 'core.hooksPath' in contributing
    assert 'scripts/git-hooks' in contributing


def test_readme_points_at_the_install_step_rather_than_assuming_it() -> None:
    readme = (_ROOT / 'README.md').read_text(encoding='utf-8')
    assert 'core.hooksPath' in readme


_COMMIT_MSG_HOOK = _ROOT / 'scripts' / 'git-hooks' / 'commit-msg'


def test_commit_msg_hook_script_is_checked_in() -> None:
    assert _COMMIT_MSG_HOOK.exists(), (
        'the commit-msg hook must be a checked-in file, not a local convention'
    )


def test_commit_msg_hook_invokes_pre_commit_through_uv_run_python_m() -> None:
    body = _COMMIT_MSG_HOOK.read_text(encoding='utf-8')
    assert 'uv run python -m pre_commit' in body
    assert '--hook-stage commit-msg' in body
    assert '--commit-msg-filename' in body


def test_commit_msg_hook_does_not_call_the_blocked_bare_shim() -> None:
    body = _COMMIT_MSG_HOOK.read_text(encoding='utf-8')
    commands = [line.strip() for line in body.splitlines() if not line.lstrip().startswith('#')]
    assert not any(cmd.startswith(('pre-commit ', 'exec pre-commit ')) for cmd in commands)


def test_config_gives_every_hook_an_explicit_stage() -> None:
    # The tree lane (`--hook-stage pre-commit`) and the message lane
    # (`--hook-stage commit-msg`) share one config; a hook without an explicit
    # `stages:` runs in BOTH lanes, which is how the suite would end up
    # running twice per commit.
    config = (_ROOT / '.pre-commit-config.yaml').read_text(encoding='utf-8')
    hook_ids = [line.split('- id:')[1].strip() for line in config.splitlines() if '- id:' in line]
    stage_lines = [line for line in config.splitlines() if line.strip().startswith('stages:')]
    assert len(stage_lines) == len(hook_ids), (
        f'every hook needs an explicit stages: line — {len(hook_ids)} hooks, '
        f'{len(stage_lines)} stages lines'
    )

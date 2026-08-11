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

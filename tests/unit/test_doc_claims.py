"""Claims the docs make about the code, held by test.

Six releases (0.2.0 to 0.6.0) shipped a README that taught ``mantis status``,
which ADR-0010 folded into ``mantis monitor --snapshot`` in 0.2.0, and two
entry-point lists still named it (review, 2026-10-07). Every command a doc names
is now looked up in the typer app itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer.main

from mantis_research.interface.cli import app

_ROOT = Path(__file__).resolve().parents[2]
_README = _ROOT / 'README.md'


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


# ── commands a doc names ──────────────────────────────────────────────


def _commands(command: object) -> dict[str, object]:
    """A group's subcommands by name (typer now vendors click, so no isinstance)."""
    commands = getattr(command, 'commands', None)
    assert isinstance(commands, dict)
    return commands


def _cli() -> dict[str, object]:
    return _commands(typer.main.get_command(app))


def _code_spans(markdown: str) -> list[str]:
    """Fenced blocks and inline code spans: where a doc tells you what to type."""
    fenced = re.findall(r'```[^\n]*\n(.*?)```', markdown, flags=re.DOTALL)
    prose = re.sub(r'```.*?```', '', markdown, flags=re.DOTALL)
    return fenced + re.findall(r'`([^`\n]+)`', prose)


#: ``mantis <cmd> [<sub>]`` or ``python -m mantis_research <cmd> [<sub>]``. The
#: lookbehind keeps ``mantis-research`` / ``grimaldost/mantis-research`` out.
_INVOCATION = re.compile(
    r'(?:(?<![\w/.-])mantis|python -m mantis_research)[ \t]+([a-z][a-z-]*)(?:[ \t]+([a-z][a-z-]*))?'
)


def _invocations(markdown: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for span in _code_spans(markdown):
        found.extend(_INVOCATION.findall(span))
        # The README's stage table names run subcommands bare, as `run <stage>`.
        bare = re.fullmatch(r'run ([a-z][a-z-]*)', span.strip())
        if bare:
            found.append(('run', bare.group(1)))
    return found


def _entry_point_list(markdown: str) -> list[str]:
    """The ``cli/`` line of a layout tree: ``typer ... (run / research / ...)``."""
    match = re.search(r'cli/ +# +typer [a-z ]+?[:(] *([a-z-]+(?: / [a-z-]+)+)', markdown)
    assert match, 'no typer entry-point list found'
    return [name.strip() for name in match.group(1).split('/')]


class TestTheCommandsTheDocsNameExist:
    def test_the_readme_names_commands(self) -> None:
        # Guard against a vacuous pass: the parser must see the README's commands.
        commands = {cmd for cmd, _ in _invocations(_read(_README))}
        assert {'research', 'run', 'monitor', 'version'} <= commands

    def test_every_command_the_readme_names_is_in_the_typer_app(self) -> None:
        cli = _cli()
        missing = [cmd for cmd, _ in _invocations(_read(_README)) if cmd not in cli]
        assert missing == []

    def test_every_run_stage_the_readme_names_is_a_run_subcommand(self) -> None:
        stages = _commands(_cli()['run'])
        named = [sub for cmd, sub in _invocations(_read(_README)) if cmd == 'run' and sub]
        assert named
        assert [sub for sub in named if sub not in stages] == []

    def test_the_entry_point_lists_name_only_real_commands(self) -> None:
        cli = _cli()
        for doc in (_README, _ROOT / 'docs' / 'architecture.md'):
            listed = _entry_point_list(_read(doc))
            assert [name for name in listed if name not in cli] == [], doc.name

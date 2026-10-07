"""Claims the docs make about the code and the release record, held by test.

Two drifts a review found on 2026-10-07, one test class each:

- Six releases (0.2.0 to 0.6.0) shipped a README that taught ``mantis status``,
  which ADR-0010 folded into ``mantis monitor --snapshot`` in 0.2.0, and two
  entry-point lists still named it. Every command a doc names is now looked up
  in the typer app itself.
- 0.6.0 shipped MANT-B16 and MANT-B19 and cited both in ``CHANGELOG.md``, while
  ``docs/backlog.md`` still listed them as open. Every item a released section
  names now needs a **Landed** row, an item landed in full leaves the open
  sections, and every row names the release that carries it.
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


# ── the backlog's Landed table against the CHANGELOG ──────────────────

_BACKLOG = _ROOT / 'docs' / 'backlog.md'


def _released_sections(changelog: str) -> dict[str, str]:
    """``{version: body}`` for every ``## [X.Y.Z]`` section, Unreleased excluded."""
    sections: dict[str, str] = {}
    for match in re.finditer(
        r'^## \[(\d+\.\d+\.\d+)\][^\n]*\n(.*?)(?=^## |\Z)', changelog, flags=re.M | re.S
    ):
        sections[match.group(1)] = match.group(2)
    return sections


def _landed_rows(backlog: str) -> list[list[str]]:
    landed = backlog.split('\n# Landed\n', 1)[1]
    lines = [line for line in landed.splitlines() if line.startswith('|')]
    # The first line is the header; the separator is all dashes and pipes.
    rows = [line for line in lines[1:] if not re.fullmatch(r'\|[-| ]+\|', line)]
    return [[cell.strip() for cell in row.strip('|').split(' | ')] for row in rows]


def _closed(backlog: str) -> dict[str, bool]:
    """``{item id: closed in full}`` for every row whose Closes cell leads with an id."""
    closed: dict[str, bool] = {}
    for row in _landed_rows(backlog):
        match = re.match(r'\*\*(MANT-B\d+)(, partially)?', row[-1])
        if match:
            closed[match.group(1)] = closed.get(match.group(1), False) or not match.group(2)
    return closed


def _open_items(backlog: str) -> set[str]:
    before_landed = backlog.split('\n# Landed\n', 1)[0]
    return set(re.findall(r'^### (MANT-B\d+) ', before_landed, flags=re.M))


class TestTheBacklogMatchesTheReleases:
    def test_the_parsers_see_the_record(self) -> None:
        backlog = _read(_BACKLOG)
        assert '0.6.0' in _released_sections(_read(_ROOT / 'CHANGELOG.md'))
        rows = _landed_rows(backlog)
        assert [row[0][:40] for row in rows if len(row) != 3] == []
        assert 'MANT-B43' in [item for row in rows for item in re.findall(r'MANT-B\d+', row[2])]
        assert _closed(backlog)['MANT-B01'] is True
        assert _closed(backlog)['MANT-B14'] is False
        assert 'MANT-B09' in _open_items(backlog)

    def test_every_item_a_release_names_has_a_landed_row(self) -> None:
        closed = _closed(_read(_BACKLOG))
        sections = _released_sections(_read(_ROOT / 'CHANGELOG.md'))
        unrecorded = sorted(
            f'{item} ({version})'
            for version, body in sections.items()
            for item in set(re.findall(r'MANT-B\d+', body))
            if item not in closed
        )
        assert unrecorded == []

    def test_an_item_landed_in_full_is_no_longer_open(self) -> None:
        backlog = _read(_BACKLOG)
        landed = {item for item, full in _closed(backlog).items() if full}
        assert sorted(landed & _open_items(backlog)) == []

    def test_every_landed_row_names_a_release(self) -> None:
        # Two rows labelled "Unreleased (2026-07-31)" shipped that label in six
        # releases, 0.2.0 (the one that carried them) to 0.6.0. A row names the
        # release that carries it.
        released = set(_released_sections(_read(_ROOT / 'CHANGELOG.md')))
        unnamed = [
            row[1]
            for row in _landed_rows(_read(_BACKLOG))
            if row[1].split(' ', 1)[0] not in released
        ]
        assert unnamed == []

"""``mantis run <stage> <config>`` typer subcommands.

One subcommand per pipeline stage. All subcommands share the same set of
flags (``--parallel``, ``--dry-run``, ``--force``, ``--only``) and route
through ``dispatch_stage()``.

Note: this module deliberately does NOT use ``from __future__ import
annotations`` — typer evaluates annotations at runtime to build option
metadata, and that requires real types (``Path``, ``list``, ...) in the
function signature, not strings.
"""

from pathlib import Path
from typing import Annotated

import typer

from mantis_research.interface.cli.dispatch import dispatch_stage

app = typer.Typer(
    name='run',
    no_args_is_help=True,
    help='Run a pipeline stage on a batch config.',
)


def _exit_with(rc: int) -> None:
    raise typer.Exit(code=rc)


@app.command(name='claude')
def claude(
    config: Annotated[Path, typer.Argument(help='Path to v2 batch config JSON')],
    parallel: Annotated[int | None, typer.Option('--parallel', '-p')] = None,
    dry_run: Annotated[bool, typer.Option('--dry-run')] = False,
    force: Annotated[bool, typer.Option('--force')] = False,
    only: Annotated[list[str] | None, typer.Option('--only')] = None,
) -> None:
    """Stage 1 — Claude research substrate."""
    _exit_with(
        dispatch_stage('claude', config, parallel=parallel, dry_run=dry_run, force=force, only=only)
    )


@app.command(name='gemini')
def gemini(
    config: Annotated[Path, typer.Argument(help='Path to v2 batch config JSON')],
    parallel: Annotated[int | None, typer.Option('--parallel', '-p')] = None,
    dry_run: Annotated[bool, typer.Option('--dry-run')] = False,
    force: Annotated[bool, typer.Option('--force')] = False,
    only: Annotated[list[str] | None, typer.Option('--only')] = None,
) -> None:
    """Stage 2 (legacy) — Gemini research via OAuth CLI."""
    _exit_with(
        dispatch_stage('gemini', config, parallel=parallel, dry_run=dry_run, force=force, only=only)
    )


@app.command(name='openrouter')
def openrouter(
    config: Annotated[Path, typer.Argument(help='Path to v2 batch config JSON')],
    parallel: Annotated[int | None, typer.Option('--parallel', '-p')] = None,
    dry_run: Annotated[bool, typer.Option('--dry-run')] = False,
    force: Annotated[bool, typer.Option('--force')] = False,
    only: Annotated[list[str] | None, typer.Option('--only')] = None,
) -> None:
    """Stage 2 (new) — research via OpenRouter HTTP. Requires OPENROUTER_API_KEY in .env."""
    _exit_with(
        dispatch_stage(
            'openrouter', config, parallel=parallel, dry_run=dry_run, force=force, only=only
        )
    )


@app.command(name='synthesis')
def synthesis(
    config: Annotated[Path, typer.Argument(help='Path to v2 batch config JSON')],
    parallel: Annotated[int | None, typer.Option('--parallel', '-p')] = None,
    dry_run: Annotated[bool, typer.Option('--dry-run')] = False,
    force: Annotated[bool, typer.Option('--force')] = False,
    only: Annotated[list[str] | None, typer.Option('--only')] = None,
) -> None:
    """Stage 3 — synthesis + journal (2-turn Claude session)."""
    _exit_with(
        dispatch_stage(
            'synthesis', config, parallel=parallel, dry_run=dry_run, force=force, only=only
        )
    )


@app.command(name='journal-passes')
def journal_passes(
    config: Annotated[Path, typer.Argument(help='Path to v2 batch config JSON')],
    parallel: Annotated[int | None, typer.Option('--parallel', '-p')] = None,
    dry_run: Annotated[bool, typer.Option('--dry-run')] = False,
    force: Annotated[bool, typer.Option('--force')] = False,
    only: Annotated[list[str] | None, typer.Option('--only')] = None,
) -> None:
    """Stage 3.5 — journal augmentation with focused depth-passes."""
    _exit_with(
        dispatch_stage(
            'journal-passes', config, parallel=parallel, dry_run=dry_run, force=force, only=only
        )
    )


@app.command(name='falsification')
def falsification(
    config: Annotated[Path, typer.Argument(help='Path to v2 batch config JSON')],
    parallel: Annotated[int | None, typer.Option('--parallel', '-p')] = None,
    dry_run: Annotated[bool, typer.Option('--dry-run')] = False,
    force: Annotated[bool, typer.Option('--force')] = False,
    only: Annotated[list[str] | None, typer.Option('--only')] = None,
) -> None:
    """Stage 4 (optional) — adversarial counter-evidence pass."""
    _exit_with(
        dispatch_stage(
            'falsification', config, parallel=parallel, dry_run=dry_run, force=force, only=only
        )
    )


@app.command(name='claude-prior')
def claude_prior(
    config: Annotated[Path, typer.Argument(help='Path to v2 batch config JSON')],
    parallel: Annotated[int | None, typer.Option('--parallel', '-p')] = None,
    dry_run: Annotated[bool, typer.Option('--dry-run')] = False,
    force: Annotated[bool, typer.Option('--force')] = False,
    only: Annotated[list[str] | None, typer.Option('--only')] = None,
) -> None:
    """Stage 5-input — topic-title-only Claude baseline (for evaluation Gate 3)."""
    _exit_with(
        dispatch_stage(
            'claude-prior', config, parallel=parallel, dry_run=dry_run, force=force, only=only
        )
    )


@app.command(name='evaluation')
def evaluation(
    config: Annotated[Path, typer.Argument(help='Path to v2 batch config JSON')],
    parallel: Annotated[int | None, typer.Option('--parallel', '-p')] = None,
    dry_run: Annotated[bool, typer.Option('--dry-run')] = False,
    force: Annotated[bool, typer.Option('--force')] = False,
    only: Annotated[list[str] | None, typer.Option('--only')] = None,
) -> None:
    """Stage 5 (optional) — score the synthesis against the rubric."""
    _exit_with(
        dispatch_stage(
            'evaluation', config, parallel=parallel, dry_run=dry_run, force=force, only=only
        )
    )

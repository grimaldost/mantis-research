"""The `mantis research` one-shot command (spec 0001 §16 / ADR-0004).

A thin typer wrapper over ``run_research`` (``interface/research_service.py``):
it parses CLI options, maps a bad argument to a non-zero exit, calls the shared
orchestrator, prints the result manifest JSON, and exits with the manifest's
status. The orchestration lives in the service module so the MCP ``research``
tool can call the same tested path (spec 0002 §1).

This module deliberately does NOT use ``from __future__ import annotations`` —
typer evaluates annotations at runtime to build option metadata.
"""

import json
from typing import Annotated

import typer

from mantis_research.interface.research_service import (
    _DEFAULT_SUBSTRATES,
    _TIER_STAGES,
    build_config,
    run_research,
)

# ``build_config`` and ``_TIER_STAGES`` are re-exported here for existing
# importers (tests/integration/test_research_cmd.py, spec 0002 §1 / FM-3).
__all__ = ('_DEFAULT_SUBSTRATES', '_TIER_STAGES', 'build_config', 'research_cmd', 'run_research')


def research_cmd(
    question: Annotated[str, typer.Argument(help='The research question')],
    assurance: Annotated[
        str, typer.Option('--assurance', help='fast | standard | high')
    ] = 'standard',
    substrates: Annotated[
        str,
        typer.Option('--substrates', help='Comma-separated vendors (default Path B set)'),
    ] = ','.join(_DEFAULT_SUBSTRATES),
    primary: Annotated[
        str,
        typer.Option('--primary', help="Primary brief, e.g. 'openrouter:openai' or 'claude'"),
    ] = '',
    journal: Annotated[bool, typer.Option('--journal/--no-journal')] = False,
    batch_name: Annotated[str, typer.Option('--batch-name')] = '',
    dry_run: Annotated[bool, typer.Option('--dry-run')] = False,
    log_level: Annotated[str, typer.Option('--log-level')] = 'INFO',
) -> None:
    """Run one research question end-to-end and print a result manifest."""
    subs = [s.strip() for s in substrates.split(',') if s.strip()]
    try:
        manifest = run_research(
            question,
            assurance=assurance,
            substrates=subs,
            primary=primary,
            journal=journal,
            batch_name=batch_name,
            dry_run=dry_run,
            log_level=log_level,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(manifest, indent=2))
    raise typer.Exit(code=0 if manifest['ok'] else 1)

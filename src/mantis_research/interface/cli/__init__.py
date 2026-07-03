"""``mantis`` CLI entry point — typer-based subcommand dispatcher.

Subcommands::

    mantis run claude          <config>  [--force --only IDS --parallel N --dry-run]
    mantis run gemini          <config>  [...]
    mantis run openrouter      <config>  [...]
    mantis run synthesis       <config>  [...]
    mantis run journal-passes  <config>  [...]
    mantis run falsification   <config>  [...]
    mantis status              <config>
    mantis monitor             <stage>   [--poll-seconds N]
    mantis version

The legacy ``scripts/run_*_batch.py`` shims continue to work and dispatch
through the same code paths. They will be removed in Phase 6 cleanup.
"""

from __future__ import annotations

import typer

from mantis_research.interface.cli.monitor import monitor_cmd
from mantis_research.interface.cli.research import research_cmd
from mantis_research.interface.cli.run import app as run_app
from mantis_research.interface.cli.status import status_cmd

app = typer.Typer(
    name='mantis',
    no_args_is_help=True,
    help=(
        'Multi-model research pipeline harness - Claude + Gemini + OpenRouter, '
        'with synthesis, journal-augmentation, falsification, and evaluation stages.'
    ),
)

app.add_typer(run_app, name='run')
app.command(name='research')(research_cmd)
app.command(name='status')(status_cmd)
app.command(name='monitor')(monitor_cmd)


@app.command(name='version')
def version() -> None:
    """Print the package version."""
    from mantis_research import __version__

    typer.echo(f'mantis-research {__version__}')


if __name__ == '__main__':
    app()

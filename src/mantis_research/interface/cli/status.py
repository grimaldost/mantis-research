"""``mantis status <config>`` — cross-stage progress snapshot.

Walks every state directory and reports the topic-by-topic status for each
stage. Replaces the ad-hoc bash one-liners we used during batch runs.

Note: this module deliberately does NOT use ``from __future__ import
annotations`` — typer evaluates annotations at runtime to build option
metadata (``Path``, ``int``, etc.), and that requires real types in the
function signature, not strings.
"""

from pathlib import Path
from typing import Annotated

import typer

from mantis_research.core.config import load_batch_config
from mantis_research.core.paths import project_root, run_state_dir
from mantis_research.core.state import (
    ClaudePriorState,
    ClaudeResearchState,
    EvaluationState,
    FalsificationState,
    GeminiResearchState,
    JournalPassesState,
    OpenRouterResearchState,
    SynthesisState,
    TopicState,
    TopicStatus,
)

# Map stage display name → (state-dir name, state class)

STAGES: list[tuple[str, str, type[TopicState]]] = [
    ('claude', 'claude', ClaudeResearchState),
    ('gemini', 'gemini', GeminiResearchState),
    ('openrouter', 'openrouter', OpenRouterResearchState),
    ('synthesis', 'synthesis', SynthesisState),
    ('journal-passes', 'journal-passes', JournalPassesState),
    ('falsification', 'falsification', FalsificationState),
    ('claude-prior', 'claude-prior', ClaudePriorState),
    ('evaluation', 'evaluation', EvaluationState),
]


def _status_marker(status: TopicStatus | None) -> str:
    """ASCII-only markers — Windows cp1252 console can't encode unicode glyphs."""
    if status is None:
        return '.'
    return {
        TopicStatus.DONE: 'OK',
        TopicStatus.IN_FLIGHT: '..',
        TopicStatus.PENDING: '..',
        TopicStatus.FAILED: 'XX',
        TopicStatus.RATE_LIMITED: 'RL',
        TopicStatus.BLOCKED_UPSTREAM: 'BL',
    }.get(status, '?')


def status_cmd(
    config: Annotated[Path, typer.Argument(help='Path to v2 batch config JSON')],
) -> None:
    """Print cross-stage status for every topic in the batch config."""
    cfg_path = config if config.exists() else project_root() / config
    cfg = load_batch_config(cfg_path)
    layout = cfg.runner.layout
    batch = cfg.batch_name

    # Header
    stage_names = [name for name, _, _ in STAGES]
    typer.echo(f'\nbatch: {cfg.batch_name}  ({len(cfg.topics)} topics)\n')
    header = f'  {"id":>4}  {"slug":<35}'
    for name in stage_names:
        header += f'  {name[:8]:>8}'
    typer.echo(header)
    typer.echo('  ' + '-' * (len(header) - 2))

    # Per-topic row
    counts: dict[str, dict[str, int]] = {name: {} for name in stage_names}
    for t in cfg.topics:
        row = f'  {t.id:>4}  {t.slug[:35]:<35}'
        for stage_name, dir_name, state_cls in STAGES:
            sd = run_state_dir(layout, batch, dir_name)
            sf = sd / f'{t.id}.json'
            if sf.exists():
                state = state_cls.load_or_create(sd, t.id, t.slug)
                marker = _status_marker(state.status)
                counts[stage_name][state.status.value] = (
                    counts[stage_name].get(state.status.value, 0) + 1
                )
            else:
                marker = _status_marker(None)
                counts[stage_name]['(none)'] = counts[stage_name].get('(none)', 0) + 1
            row += f'  {marker:>8}'
        typer.echo(row)

    # Summary
    typer.echo()
    typer.echo('  Per-stage counts:')
    for name in stage_names:
        items = ' '.join(f'{k}={v}' for k, v in sorted(counts[name].items()))
        typer.echo(f'    {name:<16} {items}')
    typer.echo()

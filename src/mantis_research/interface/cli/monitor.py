"""``mantis monitor <stage>`` — batch progress monitor.

Polls a stage's ``progress.json`` every 30s and emits one line per topic
state transition (or any counts change). Designed to be driven by the
Claude Code Monitor tool (each stdout line becomes a notification).

Note: this module does NOT use ``from __future__ import annotations`` for
the same reason as ``run.py`` — typer needs real types at decoration time.
"""

import json
import time
from typing import Annotated

import typer

from mantis_research.core.paths import project_root, run_state_dir


def monitor_cmd(
    stage: Annotated[
        str,
        typer.Argument(help="Stage name (e.g. 'claude', 'gemini', 'synthesis')"),
    ],
    poll_seconds: Annotated[int, typer.Option(help='Polling interval')] = 30,
    batch_name: Annotated[
        str,
        typer.Option('--batch-name', help='Batch name (required for batch layout)'),
    ] = '',
    layout: Annotated[
        str,
        typer.Option('--layout', help="Run layout: 'legacy' (default) or 'batch'"),
    ] = 'legacy',
) -> None:
    """Watch a stage's progress.json. One stdout line per state change.

    Bare ``mantis monitor <stage>`` keeps the legacy behavior; add
    ``--batch-name <b> --layout batch`` to watch a batch-scoped run.
    """
    progress_path = run_state_dir(layout, batch_name, stage) / 'progress.json'
    if not progress_path.exists() and layout == 'legacy':
        # Legacy fallback: the canonical nested state/<stage>/progress.json.
        alt = project_root() / 'state' / stage / 'progress.json'
        if alt.exists():
            progress_path = alt
    if not progress_path.exists():
        typer.echo(f'progress file not found at {progress_path}', err=True)
        raise typer.Exit(code=1)

    last_counts_line: str | None = None
    last_topic_status: dict[str, str] = {}

    while True:
        try:
            d = json.loads(progress_path.read_text(encoding='utf-8'))
            c = d.get('counts', {})
        except (OSError, ValueError) as e:
            typer.echo(f'err: progress unreadable: {e}', err=True)
            time.sleep(poll_seconds)
            continue

        counts_line = (
            f'done={c.get("done", 0)} in_flight={c.get("in_flight", 0)} '
            f'pend={c.get("pending", 0)} fail={c.get("failed", 0)} '
            f'rl={c.get("rate_limited", 0)}'
        )
        if counts_line != last_counts_line:
            typer.echo(counts_line)
            last_counts_line = counts_line

        for t in d.get('topics', []):
            tid = t['id']
            st = t['status']
            if last_topic_status.get(tid) != st and st in (
                'done',
                'failed',
                'rate_limited',
            ):
                ext = f' bytes={_total_bytes(t)}' if st == 'done' else f' err={t.get("last_error")}'
                typer.echo(f'  [{tid}] {st}{ext}')
            last_topic_status[tid] = st

        terminal = c.get('done', 0) + c.get('failed', 0) + c.get('rate_limited', 0)
        if terminal == d.get('total_topics', 0):
            typer.echo('ALL_TERMINAL')
            return

        time.sleep(poll_seconds)


def _total_bytes(t: dict[str, object]) -> int:
    """Best-effort byte count across stage-state schemas."""
    subsessions = t.get('subsessions')
    if isinstance(subsessions, list):
        total = 0
        for s in subsessions:
            if isinstance(s, dict):
                ob = s.get('output_bytes')  # ty: ignore[invalid-argument-type]
                total += int(ob or 0)
        return total
    for key in (
        'research_file_bytes',
        'synthesis_bytes',
        'journal_bytes',
        'augmentation_bytes',
        'falsification_bytes',
    ):
        v = t.get(key)
        if isinstance(v, (int, float)) and v:
            return int(v)
    return 0

"""MCP stdio server exposing the ``research`` tool (spec 0002 §2/§3, ADR-0009).

Local-first: run co-located with an authenticated ``claude`` CLI so the
synthesis-family stages consume the host's Claude subscription seat (ADR-0009).
Start it with ``python -m mantis_research.interface.mcp``.

Pinned ``mcp`` SDK API — probed against the installed package (spec 0002 §2 / FM-2,
FM-B):

- ``from mcp.server.fastmcp import FastMCP``; ``FastMCP(name)``.
- ``@server.tool()`` registers a tool; the function's type hints are the input
  schema, and a ``dict`` return annotation yields structured output (the Tool
  carries an ``outputSchema``).
- ``server.run(transport='stdio')`` serves over stdio.
- ``await server.list_tools()`` is the public tool-introspection API (used by the
  §2 registration test); a synchronous ``server._tool_manager.list_tools()`` also
  exists.
- Synchronous ``@tool``-decorated functions are dispatched off the event loop by
  the SDK; even so, the ``research`` handler is ``async`` and offloads the blocking
  ``run_research`` via ``asyncio.to_thread`` — safe regardless of the SDK's
  sync-threading behaviour (FM-1/FM-B).
- A parameter annotated ``Context`` is injected by the SDK and excluded from the
  tool's input schema (``Tool.context_kwarg``), so it never reaches the agent as
  an argument to supply.

Progress is reported over that context. Before it, the whole multi-stage run hid
behind one ``to_thread`` await and the client saw silence from call to return —
which a client cannot distinguish from a hang, and answers by giving up.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from mantis_research.core.sidecar import ResearchSidecar, project_for_agent
from mantis_research.interface.research_service import resume_research, run_research

if TYPE_CHECKING:
    from mantis_research.core.progress import ProgressCallback, RunEvent

_SERVER_NAME = 'mantis-research'


class IncompleteRunError(RuntimeError):
    """The run produced no epistemic sidecar, so it produced no answer.

    Raised instead of returning the partial result. The sidecar is the product
    (ADR-0003); a result carrying only research briefs is a run that failed, and
    handing it back as an ordinary tool result lets a caller read it as a
    delivered answer — which is precisely what happened in the field.
    """


def _incomplete(manifest: dict[str, Any], sidecar_path: Path) -> IncompleteRunError:
    """Build the refusal, naming what is missing, what failed, and the way back."""
    failed = sorted(
        stage for stage, rc in manifest['stages'].items() if rc.get('exit_code', 0) != 0
    )
    blame = (
        f'{", ".join(failed)} exited non-zero'
        if failed
        else 'every stage exited 0, so the artifact was lost rather than refused'
    )
    outputs_dir = manifest.get('outputs_dir') or manifest.get('batch_name', '')
    return IncompleteRunError(
        f'the run produced no epistemic sidecar at {sidecar_path} — {blame}. '
        f'The sidecar is the product (ADR-0003): research briefs without a '
        f'synthesis and its sidecar are not an answer, so this is reported as a '
        f'failure rather than returned as a partial result. The briefs that were '
        f'paid for are on disk — re-enter the run with '
        f'resume="{outputs_dir}" once the cause is fixed, rather than asking '
        f'again and buying them twice.'
    )


def _agent_result(manifest: dict[str, Any]) -> dict[str, Any]:
    """Assemble the agent-facing result from a run manifest and its sidecar.

    Carries the manifest's output paths, per-stage exit codes and cost block,
    plus the sidecar's epistemic content (claims / divergences / verification
    queue, via :func:`project_for_agent`). The synthesis and briefs stay
    referenced by path in ``outputs`` — never inlined (§3). Synchronous file I/O,
    so it runs inside the worker thread the async tool offloads to (FM-1).

    A live run with no sidecar on disk raises :class:`IncompleteRunError` rather
    than returning. Every path in ``outputs`` is a destination, not evidence, so
    a briefs-only result is indistinguishable at a glance from a complete one —
    an agent that reads `outputs` and finds three real brief files has no reason
    to doubt the rest. A dry run is exempt on the manifest's own ``dry_run``
    flag: it legitimately writes nothing, and says so in the result.
    """
    result: dict[str, Any] = {
        'ok': manifest['ok'],
        'dry_run': manifest.get('dry_run', False),
        'question': manifest['question'],
        'assurance': manifest['assurance'],
        'cost': manifest['cost'],
        'stages': manifest['stages'],
        'outputs': manifest['outputs'],
    }
    sidecar_path = Path(manifest['outputs']['sidecar'])
    if sidecar_path.exists():
        sc = ResearchSidecar.from_model_json(sidecar_path.read_text(encoding='utf-8'))
        result['sidecar_available'] = True
        result.update(project_for_agent(sc))
        return result
    # A live run that owed a sidecar and has none produced no answer. A run
    # that never owed one — a research-only tier, or a dry run — legitimately
    # has none, and refusing those would refuse the tier that exists precisely
    # because the synthesis stage could not run (MANT-B60). Absent, the flag
    # reads as owed: every tier before this one was.
    owed = manifest.get('produces_sidecar', True)
    if owed and not result['dry_run']:
        raise _incomplete(manifest, sidecar_path)
    result['sidecar_available'] = False
    return result


def _run_and_assemble(
    question: str,
    *,
    assurance: str,
    substrates: list[str] | None,
    primary: str,
    journal: bool,
    dry_run: bool,
    name: str = '',
    resume: str = '',
    on_event: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the pipeline and assemble the agent result (sync — runs off the loop)."""
    if resume:
        manifest = resume_research(Path(resume), dry_run=dry_run, on_event=on_event)
    else:
        manifest = run_research(
            question,
            assurance=assurance,
            substrates=substrates,
            primary=primary,
            journal=journal,
            dry_run=dry_run,
            batch_name=name,
            on_event=on_event,
        )
    return _agent_result(manifest)


async def _deliver(ctx: Any, event: RunEvent) -> None:
    """Push one run event down the MCP channel (progress + log)."""
    # Both are sent: `report_progress` is the mechanism defined for this, but it
    # no-ops when the client sent no progress token, and a log notification
    # reaches that client anyway. Between them the caller always hears something.
    if event.step is not None and event.total:
        await ctx.report_progress(progress=event.step, total=event.total, message=event.message)
    await ctx.info(event.message)


def _progress_bridge(ctx: Any, loop: asyncio.AbstractEventLoop) -> ProgressCallback:
    """Adapt the synchronous run-event callback onto the MCP session's loop.

    ``run_research`` is synchronous and runs in a worker thread (FM-1), while the
    MCP session belongs to the event loop that spawned it — so an event has to
    be handed back across that boundary rather than awaited in place.
    ``run_coroutine_threadsafe`` is that hand-off; the future is deliberately not
    awaited, since the run must not block on its audience.
    """

    def deliver(event: RunEvent) -> None:
        asyncio.run_coroutine_threadsafe(_deliver(ctx, event), loop)

    return deliver


async def research(
    question: Annotated[str, Field(description='The research question to investigate.')],
    assurance: Annotated[
        str,
        Field(
            description=(
                'How far the pipeline runs. "fast" (the default) is research + '
                'synthesis. Escalate explicitly when the extra checking is worth '
                'the extra Claude-seat time: "standard" adds an adversarial '
                'falsification pass over the finished synthesis, "high" adds a '
                'Claude-prior baseline and a rubric evaluation on top. '
                '"research" stops after the cross-model briefs and returns their '
                'paths and cost with no synthesis and no sidecar — the tier to '
                'use when no local Claude seat is available, or when you want to '
                'read the substrates yourself.'
            )
        ),
    ] = 'fast',
    substrates: Annotated[
        list[str] | None,
        Field(
            description=(
                'OpenRouter research vendor slugs to fan the question across, each '
                'run as its newest frontier model. Accepted: openai, google, '
                'anthropic, deepseek, perplexity, qwen, x-ai, meta-llama, mistralai. '
                'None uses the default Path B set: openai, deepseek, google.'
            )
        ),
    ] = None,
    primary: Annotated[
        str,
        Field(
            description=(
                'Which research brief the synthesis anchors on: "claude" or '
                '"openrouter:<slug>" (e.g. "openrouter:openai"). Empty string '
                'anchors on the first substrate.'
            )
        ),
    ] = '',
    journal: Annotated[
        bool,
        Field(
            description=(
                'Also emit a mantis-ingestion journal via a second synthesis turn '
                '(slower). Off by default.'
            )
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        Field(description='Validate orchestration without spending any model calls.'),
    ] = False,
    name: Annotated[
        str,
        Field(
            description=(
                'An optional name for the run, used for its output directory. '
                'Without one the name is derived from the question, so several '
                'questions sharing a long common preamble read alike; you can '
                'also mark the key inline as "RESEARCH QUESTION (<key>)".'
            )
        ),
    ] = '',
    resume: Annotated[
        str,
        Field(
            description=(
                'Re-enter an interrupted run instead of starting a new one: pass '
                'its output directory (the "outputs_dir" of the run you lost, e.g. '
                '"outputs/research-my-question-20260811T101500Z"). Stages that '
                'already finished are skipped, and the question and settings come '
                'from that run\'s own record, so "question" is ignored.'
            )
        ),
    ] = '',
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Research a question across multiple models and return a cross-checked result.

    Runs OpenRouter research substrates plus a Claude synthesis, returning the run
    manifest (output paths, per-stage exit codes, cost) together with the epistemic
    sidecar's claims, cross-model divergences, and verification queue. The
    synthesis / falsification / evaluation / journal stages drive a local
    authenticated ``claude`` CLI (ADR-0009); research-only runs need only an
    ``OPENROUTER_API_KEY``.

    Parameters:
      - ``assurance`` (``fast`` | ``standard`` | ``high``) chooses depth. ``fast``
        — research + synthesis — is the default and what most calls want;
        ``standard`` adds a falsification pass and ``high`` adds a Claude-prior
        baseline and an evaluation pass, as explicit escalations.
      - ``substrates`` overrides the OpenRouter research vendors (slugs such as
        ``openai``, ``deepseek``, ``google``, ``anthropic``, ``qwen``, ``x-ai``,
        ``meta-llama``, ``mistralai``, ``perplexity``); each runs as its newest
        frontier model. ``None`` uses the default Path B set: openai, deepseek,
        google.
      - ``primary`` selects which research brief the synthesis anchors on —
        ``claude`` or ``openrouter:<slug>`` (e.g. ``openrouter:openai``); the empty
        default anchors on the first substrate.
      - ``journal`` also emits a mantis-ingestion journal via a second synthesis
        turn (slower); off by default.
      - ``name`` optionally names the run's output directory; without one the
        name is derived from the question.
      - ``dry_run`` validates orchestration without spending model calls.
      - ``resume`` re-enters an interrupted run by its output directory instead
        of starting a new one; completed stages are skipped and the question and
        settings are read from that run's own record.
    """
    # dispatch_stage_config nests asyncio.run per stage, so the synchronous
    # pipeline must run OFF this event loop or it raises RuntimeError (FM-1).
    # The bridge is built here, on the loop, and closes over it: the worker
    # thread hands events back rather than touching the session directly.
    bridge = _progress_bridge(ctx, asyncio.get_running_loop()) if ctx is not None else None
    return await asyncio.to_thread(
        _run_and_assemble,
        question,
        assurance=assurance,
        substrates=substrates,
        primary=primary,
        journal=journal,
        dry_run=dry_run,
        name=name,
        resume=resume,
        on_event=bridge,
    )


def build_server() -> FastMCP:
    """Construct the MCP server with the ``research`` tool registered."""
    server = FastMCP(_SERVER_NAME)
    server.tool()(research)
    return server

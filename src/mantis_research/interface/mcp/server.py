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
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mantis_research.core.sidecar import ResearchSidecar, project_for_agent
from mantis_research.interface.research_service import run_research

_SERVER_NAME = 'mantis-research'


def _agent_result(manifest: dict[str, Any]) -> dict[str, Any]:
    """Assemble the agent-facing result from a run manifest and its sidecar.

    Carries the manifest's output paths, per-stage exit codes and cost block,
    plus the sidecar's epistemic content (claims / divergences / verification
    queue, via :func:`project_for_agent`). The synthesis and briefs stay
    referenced by path in ``outputs`` — never inlined (§3). Synchronous file I/O,
    so it runs inside the worker thread the async tool offloads to (FM-1).
    """
    result: dict[str, Any] = {
        'ok': manifest['ok'],
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
    else:
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
) -> dict[str, Any]:
    """Run the pipeline and assemble the agent result (sync — runs off the loop)."""
    manifest = run_research(
        question,
        assurance=assurance,
        substrates=substrates,
        primary=primary,
        journal=journal,
        dry_run=dry_run,
    )
    return _agent_result(manifest)


async def research(
    question: str,
    assurance: str = 'standard',
    substrates: list[str] | None = None,
    primary: str = '',
    journal: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Research a question across multiple models and return a cross-checked result.

    Runs OpenRouter research substrates plus a Claude synthesis, returning the run
    manifest (output paths, per-stage exit codes, cost) together with the epistemic
    sidecar's claims, cross-model divergences, and verification queue. The
    synthesis/journal stages require a local authenticated ``claude`` CLI
    (ADR-0009). ``assurance`` is ``fast`` | ``standard`` | ``high``; ``dry_run``
    validates orchestration without spending model calls.
    """
    # dispatch_stage_config nests asyncio.run per stage, so the synchronous
    # pipeline must run OFF this event loop or it raises RuntimeError (FM-1).
    return await asyncio.to_thread(
        _run_and_assemble,
        question,
        assurance=assurance,
        substrates=substrates,
        primary=primary,
        journal=journal,
        dry_run=dry_run,
    )


def build_server() -> FastMCP:
    """Construct the MCP server with the ``research`` tool registered."""
    server = FastMCP(_SERVER_NAME)
    server.tool()(research)
    return server

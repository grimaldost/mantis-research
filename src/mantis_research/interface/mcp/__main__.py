"""Entry point: ``python -m mantis_research.interface.mcp`` (spec 0002 §2).

Starts the stdio MCP server so a Claude Code plugin (or any MCP client) can
register the ``research`` tool. In-process Python — never a blocked ``.exe`` shim
(ADR-0004).
"""

from __future__ import annotations

from mantis_research.interface.mcp.server import build_server


def main() -> None:
    """Run the MCP server over stdio."""
    build_server().run(transport='stdio')


if __name__ == '__main__':
    main()

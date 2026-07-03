"""Plugin manifest + bundled MCP launch config tests (spec 0002 §5)."""

from __future__ import annotations

import json
from pathlib import Path

_MANIFEST = Path(__file__).resolve().parents[2] / '.claude-plugin' / 'plugin.json'


def test_plugin_manifest_declares_research_server_with_project_anchor() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding='utf-8'))
    # Well-formed manifest.
    assert manifest['name'] == 'mantis-research'
    assert manifest['description']
    assert manifest['version']

    # Bundled MCP launch config declares the `research` server.
    entry = manifest['mcpServers']['mantis-research']
    args = entry.get('args', [])
    cmdline = ' '.join([entry['command'], *args])
    # In-process module launch, never a blocked .exe shim (ADR-0004).
    assert '-m mantis_research.interface.mcp' in cmdline
    # Explicit project/directory anchor so the server starts from any cwd, not a
    # bare `uv run` that resolves the project from an unspecified cwd (FM-6).
    assert '--project' in args or '--directory' in args or 'cwd' in entry
    assert '${CLAUDE_PLUGIN_ROOT}' in cmdline or entry.get('cwd', '') == '${CLAUDE_PLUGIN_ROOT}'

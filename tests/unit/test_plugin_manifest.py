"""Plugin manifest + bundled MCP launch config tests (spec 0002 §5).

The version-site tests assert EQUALITY across the copies, not presence: the
release checklist's "kept in sync by convention" was exactly that — a
convention — and nothing failed when the copies drifted.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / '.claude-plugin' / 'plugin.json'


def _pyproject_version() -> str:
    pyproject = tomllib.loads((_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    return pyproject['project']['version']


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


def test_manifest_version_equals_pyproject_version() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding='utf-8'))
    assert manifest['version'] == _pyproject_version()


def test_uv_lock_records_the_same_root_package_version() -> None:
    lock = tomllib.loads((_ROOT / 'uv.lock').read_text(encoding='utf-8'))
    entries = [pkg for pkg in lock['package'] if pkg['name'] == 'mantis-research']
    assert len(entries) == 1, 'uv.lock must record exactly one root-package entry'
    assert entries[0]['version'] == _pyproject_version()


def test_newest_changelog_release_heading_matches_pyproject_version() -> None:
    # Between releases the version sites stay at the last cut, so the first
    # versioned heading (the one below [Unreleased]) must name that version.
    changelog = (_ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    match = re.search(r'^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$', changelog, re.MULTILINE)
    assert match is not None, 'CHANGELOG.md must have at least one dated release heading'
    assert match.group(1) == _pyproject_version()

"""Core-purity gate — enforces architecture invariant I1 as a machine check.

``src/mantis_research/core/`` must contain no network or subprocess I/O
(ADR-0001). This script AST-walks every module under ``core/`` and fails if any
imports a forbidden I/O module. Run as a gate:

    uv run python scripts/check_core_purity.py

Exit 0 = pure; exit 1 = a violation (path:line and the offending import are
printed). ``find_violations`` is importable so a test can point it at a
temporary tree.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Modules that perform network or subprocess I/O. Importing any of these from
# core/ breaks I1. Plain ``import asyncio`` is allowed (async primitives), but
# ``asyncio.subprocess`` is not.
FORBIDDEN_MODULES = frozenset({'httpx', 'subprocess', 'socket', 'requests', 'aiohttp'})
FORBIDDEN_ASYNCIO_ATTRS = frozenset({'subprocess'})


def _iter_forbidden_imports(tree, path):
    """Yield (lineno, dotted_name) for each forbidden import in an AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split('.')[0]
                if top in FORBIDDEN_MODULES:
                    yield node.lineno, alias.name
                elif top == 'asyncio' and alias.name.split('.')[1:2]:
                    if alias.name.split('.')[1] in FORBIDDEN_ASYNCIO_ATTRS:
                        yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            top = module.split('.')[0]
            if top in FORBIDDEN_MODULES:
                yield node.lineno, module
            elif module == 'asyncio':
                for alias in node.names:
                    if alias.name in FORBIDDEN_ASYNCIO_ATTRS:
                        yield node.lineno, f'asyncio.{alias.name}'


def find_violations(core_dir: Path) -> list[tuple[Path, int, str]]:
    """Return (path, lineno, module) for every forbidden import under core_dir."""
    violations: list[tuple[Path, int, str]] = []
    for path in sorted(core_dir.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for lineno, name in _iter_forbidden_imports(tree, path):
            violations.append((path, lineno, name))
    return violations


def _default_core_dir() -> Path:
    return Path(__file__).resolve().parent.parent / 'src' / 'mantis_research' / 'core'


def main() -> int:
    core_dir = _default_core_dir()
    if not core_dir.is_dir():
        print(f'core dir not found: {core_dir}', file=sys.stderr)
        return 2
    violations = find_violations(core_dir)
    if violations:
        print('core purity violation (I1): core/ must not import I/O modules', file=sys.stderr)
        for path, lineno, name in violations:
            rel = path.relative_to(core_dir.parent.parent.parent)
            print(f'  {rel.as_posix()}:{lineno}  imports {name!r}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

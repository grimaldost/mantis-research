"""Core-purity gate tests (spec 0001 §7 / invariant I1).

The gate script lives under ``scripts/`` (not an importable package), so it is
loaded from its file path.
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

from mantis_research.core.paths import project_root

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


def _load_gate() -> ModuleType:
    path = project_root() / 'scripts' / 'check_core_purity.py'
    spec = importlib.util.spec_from_file_location('check_core_purity', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCorePurity:
    def test_real_core_tree_is_pure(self) -> None:
        gate = _load_gate()
        core = project_root() / 'src' / 'mantis_research' / 'core'
        assert gate.find_violations(core) == []

    def test_detects_httpx_import(self, tmp_path: Path) -> None:
        gate = _load_gate()
        (tmp_path / 'clean.py').write_text('from __future__ import annotations\nX = 1\n')
        (tmp_path / 'dirty.py').write_text('import httpx\n\n\ndef f():\n    return httpx\n')
        violations = gate.find_violations(tmp_path)
        assert len(violations) == 1
        path, lineno, name = violations[0]
        assert path.name == 'dirty.py'
        assert lineno == 1
        assert name == 'httpx'

    def test_detects_subprocess_and_from_imports(self, tmp_path: Path) -> None:
        gate = _load_gate()
        (tmp_path / 'a.py').write_text('import subprocess\n')
        (tmp_path / 'b.py').write_text('from asyncio import subprocess\n')
        (tmp_path / 'c.py').write_text('from requests import get\n')
        names = {name for _, _, name in gate.find_violations(tmp_path)}
        assert names == {'subprocess', 'asyncio.subprocess', 'requests'}

    def test_plain_asyncio_is_allowed(self, tmp_path: Path) -> None:
        gate = _load_gate()
        (tmp_path / 'ok.py').write_text('import asyncio\nfrom asyncio import Event, TaskGroup\n')
        assert gate.find_violations(tmp_path) == []

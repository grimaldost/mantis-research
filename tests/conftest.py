"""Pytest fixtures shared across the test suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Path:
    """Return a temp directory suitable for state/<id>.json round-trip tests."""
    state = tmp_path / 'state'
    state.mkdir()
    return state

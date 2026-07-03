"""Tests for the DISABLED_STAGES env-driven CLI gating."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _reload_dispatch_with_env(monkeypatch, disabled_value: str):
    """Set the env var and reload settings + dispatch so the module-level
    singleton picks up the new value."""
    monkeypatch.setenv('DISABLED_STAGES', disabled_value)
    # Clear and reload so the module-level Settings() picks up the env.
    from mantis_research.core import settings as settings_mod

    importlib.reload(settings_mod)
    from mantis_research.interface.cli import dispatch as dispatch_mod

    importlib.reload(dispatch_mod)
    return dispatch_mod


def test_disabled_stages_empty_means_all_enabled(monkeypatch):
    _reload_dispatch_with_env(monkeypatch, '')
    # No disabled stages — set is empty.
    from mantis_research.core.settings import settings

    assert settings.disabled_stages == frozenset()


def test_disabled_stages_parses_comma_separated(monkeypatch):
    _reload_dispatch_with_env(monkeypatch, 'gemini, claude ,  ')
    from mantis_research.core.settings import settings

    # Whitespace trimmed, empty entries dropped, lowercased.
    assert settings.disabled_stages == frozenset({'gemini', 'claude'})


def test_dispatch_refuses_disabled_stage(monkeypatch, tmp_path: Path):
    dispatch = _reload_dispatch_with_env(monkeypatch, 'gemini')
    # Use a non-existent config — we should fail at the disabled check
    # BEFORE config loading.
    with pytest.raises(RuntimeError, match=r"stage 'gemini' is disabled"):
        dispatch.dispatch_stage('gemini', tmp_path / 'fake.json')


def test_dispatch_unknown_stage_raises_value_error(monkeypatch, tmp_path: Path):
    dispatch = _reload_dispatch_with_env(monkeypatch, '')
    with pytest.raises(ValueError, match=r'unknown stage'):
        dispatch.dispatch_stage('nonexistent', tmp_path / 'fake.json')


def test_disabled_check_comes_before_unknown_check(monkeypatch, tmp_path: Path):
    """If a stage is BOTH disabled AND unknown (shouldn't happen but...),
    the unknown check fires first because it operates on the registry.
    This documents the actual ordering for future maintainers."""
    dispatch = _reload_dispatch_with_env(monkeypatch, 'totally-fake-stage')
    with pytest.raises(ValueError, match=r'unknown stage'):
        dispatch.dispatch_stage('totally-fake-stage', tmp_path / 'fake.json')

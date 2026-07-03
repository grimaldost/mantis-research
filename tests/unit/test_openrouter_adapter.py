"""OpenRouterHttpAdapter key handling — lazy, so --dry-run works without a key."""

from __future__ import annotations

import pytest

from mantis_research.interface.adapters import openrouter_http
from mantis_research.interface.adapters.openrouter_http import OpenRouterHttpAdapter


def test_constructs_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # No key anywhere → construction must NOT raise. The stage is built even for
    # a --dry-run (which never hits the network), so an eager check made dry-run
    # demand a key it never uses (fresh-install acceptance-test finding).
    monkeypatch.setattr(openrouter_http.settings, 'OPENROUTER_API_KEY', None)
    OpenRouterHttpAdapter()  # must not raise


def test_key_required_only_at_request_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openrouter_http.settings, 'OPENROUTER_API_KEY', None)
    adapter = OpenRouterHttpAdapter()
    with pytest.raises(RuntimeError, match='OPENROUTER_API_KEY not set'):
        adapter._headers()  # the header build is the point of use


def test_explicit_key_flows_to_headers() -> None:
    adapter = OpenRouterHttpAdapter(api_key='sk-test-123')
    assert adapter._headers()['Authorization'] == 'Bearer sk-test-123'

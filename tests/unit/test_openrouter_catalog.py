"""Unit tests for the OpenRouter catalog adapter (offline-safe fetch + cache).

These never hit the real network — httpx.Client is monkeypatched so the test
asserts the graceful-degradation contract: every failure mode returns None and
the result is memoized.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from mantis_research.interface.adapters.openrouter_catalog import OpenRouterCatalog

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    """Stands in for httpx.Client; ``behavior`` decides what .get does."""

    def __init__(self, behavior: Callable[[], _FakeResponse], **_: Any) -> None:
        self._behavior = behavior
        self.calls = 0

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get(self, _url: str, headers: dict[str, str] | None = None) -> _FakeResponse:
        self.calls += 1
        return self._behavior()


def _patch_client(monkeypatch: pytest.MonkeyPatch, behavior: Callable[[], _FakeResponse]) -> None:
    monkeypatch.setattr(
        httpx,
        'Client',
        lambda **kw: _FakeClient(behavior, **kw),
    )


def test_successful_fetch_returns_models(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {'data': [{'id': 'openai/gpt-5.5-pro'}, {'id': 'google/gemini-3.1-pro-preview'}]}
    _patch_client(monkeypatch, lambda: _FakeResponse(200, payload))
    cat = OpenRouterCatalog(api_key='k')
    models = cat.models()
    assert models is not None
    assert {m['id'] for m in models} == {'openai/gpt-5.5-pro', 'google/gemini-3.1-pro-preview'}


def test_connection_error_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> _FakeResponse:
        raise httpx.ConnectError('offline')

    _patch_client(monkeypatch, boom)
    assert OpenRouterCatalog(api_key='k').models() is None


def test_non_200_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda: _FakeResponse(503, {'data': []}))
    assert OpenRouterCatalog(api_key='k').models() is None


def test_non_json_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda: _FakeResponse(200, ValueError('not json')))
    assert OpenRouterCatalog(api_key='k').models() is None


def test_missing_data_key_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda: _FakeResponse(200, {'oops': 1}))
    assert OpenRouterCatalog(api_key='k').models() is None


def test_result_is_memoized(monkeypatch: pytest.MonkeyPatch) -> None:
    holder: dict[str, _FakeClient] = {}

    def make_client(**kw: Any) -> _FakeClient:
        c = _FakeClient(lambda: _FakeResponse(200, {'data': [{'id': 'openai/gpt-5.5-pro'}]}), **kw)
        holder['client'] = c
        return c

    monkeypatch.setattr(httpx, 'Client', make_client)
    cat = OpenRouterCatalog(api_key='k')
    first = cat.models()
    second = cat.models()
    assert first is second
    # Only one network call despite two models() calls — but a fresh client is
    # constructed per fetch, so assert the cache via identity above plus that
    # the single constructed client saw exactly one .get.
    assert holder['client'].calls == 1

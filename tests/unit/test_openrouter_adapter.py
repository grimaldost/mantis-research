"""OpenRouterHttpAdapter key handling — lazy, so --dry-run works without a key."""

from __future__ import annotations

import httpx
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


def test_coerce_content_handles_str_list_and_other() -> None:
    assert openrouter_http._coerce_content('hello') == 'hello'
    assert (
        openrouter_http._coerce_content(
            [{'type': 'text', 'text': 'a'}, {'type': 'text', 'text': 'b'}]
        )
        == 'ab'
    )
    assert openrouter_http._coerce_content(['x', 'y']) == 'xy'
    assert openrouter_http._coerce_content(None) == ''
    assert openrouter_http._coerce_content(42) == ''


def test_list_content_response_is_coerced_not_crashed() -> None:
    # Some providers return OpenAI-style content parts (a list). The parse must
    # join them, not call .strip() on a list and crash (fresh-review finding).
    resp = httpx.Response(
        200,
        json={
            'model': 'openai/gpt-5.5-pro',
            'choices': [
                {
                    'message': {
                        'content': [
                            {'type': 'text', 'text': 'part one '},
                            {'type': 'text', 'text': 'part two'},
                        ]
                    },
                    'finish_reason': 'stop',
                }
            ],
        },
    )
    opts = openrouter_http.OpenRouterHttpOptions(model='openai/gpt-5.5-pro')
    result = OpenRouterHttpAdapter._parse_response(resp, opts, 1.0)
    assert result.success
    assert result.output == 'part one part two'
    assert result.model_used == 'openai/gpt-5.5-pro'

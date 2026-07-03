"""OpenRouter HTTP adapter — drives ``POST /chat/completions``.

OpenAI-compatible JSON endpoint that fans out to many providers (Anthropic,
OpenAI, Google paid, DeepSeek, Mistral, xAI, Qwen, etc.) under one API.

Replaces the OAuth-Gemini path's quirks (banner failures, ConPTY hangs,
flash downrouting, OAuth quota windows) with a clean HTTP call. Adds
access to substrate-different models for stronger cross-model-disagreement
signal in synthesis hallucination flags.

Reference docs:
- https://openrouter.ai/docs/quickstart
- https://openrouter.ai/docs/guides/routing/provider-selection
- https://openrouter.ai/docs/guides/features/plugins/web-search
- https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import httpx
import structlog

from mantis_research.core.settings import settings
from mantis_research.interface.transcripts import TranscriptWriter

if TYPE_CHECKING:
    from pathlib import Path

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class OpenRouterHttpOptions:
    """Per-call options for the OpenRouter HTTP adapter."""

    model: str  # e.g. 'google/gemini-3.1-pro-preview', 'openai/gpt-5.5'
    web_search: bool = False
    # native = native search where the provider supports it (Anthropic /
    # OpenAI / xAI / Perplexity), otherwise OpenRouter routes to Exa.
    web_search_engine: Literal['native', 'exa'] = 'native'
    web_search_max_results: int = 5
    reasoning_effort: Literal['low', 'medium', 'high', 'xhigh'] | None = None
    reasoning_max_tokens: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    timeout_s: float = 600.0
    # Provider routing knobs (https://openrouter.ai/docs/guides/routing/provider-selection)
    provider_order: tuple[str, ...] = field(default_factory=tuple)
    require_parameters: bool = False
    data_collection_deny: bool = False  # → provider.data_collection = 'deny'


@dataclass(frozen=True, slots=True)
class OpenRouterHttpResult:
    """Return shape from ``OpenRouterHttpAdapter.run``."""

    success: bool
    status_code: int
    duration_s: float
    output: str = ''  # the assistant message content (the brief text)
    raw_output: str = ''  # the full HTTP response body for transcript / debug
    error: str | None = None
    finish_reason: str | None = None
    model_used: str | None = None  # may differ from requested if provider fallback fired
    usage: dict[str, Any] | None = None  # tokens in/out/reasoning + cost (floats)


class OpenRouterHttpAdapter:
    """OpenRouter HTTP client — one ``run()`` per topic subsession."""

    name: str = 'openrouter_http'

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        http_referer: str | None = None,
        app_title: str | None = None,
    ) -> None:
        key = api_key or (
            settings.OPENROUTER_API_KEY.get_secret_value()
            if settings.OPENROUTER_API_KEY is not None
            else None
        )
        if not key:
            msg = (
                'OPENROUTER_API_KEY not set. Add it to .env (see .env.template) or '
                'export it in your shell before invoking the openrouter stage.'
            )
            raise RuntimeError(msg)
        self._api_key = key
        self._base_url = base_url or settings.OPENROUTER_BASE_URL
        self._http_referer = http_referer or settings.MANTIS_HTTP_REFERER
        self._app_title = app_title or settings.MANTIS_APP_TITLE

    # ── lifecycle ─────────────────────────────────────────────────

    async def preflight(self) -> None:
        """Verify the API key is accepted by hitting the credits endpoint."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f'{self._base_url}/credits',
                headers=self._headers(),
            )
            if resp.status_code == httpx.codes.UNAUTHORIZED:
                msg = 'OpenRouter rejected the API key (401 Unauthorized).'
                raise RuntimeError(msg)
            resp.raise_for_status()

    # ── per-call entry point ──────────────────────────────────────

    async def run(
        self,
        prompt: str,
        options: OpenRouterHttpOptions,
        transcript_path: Path,
        *,
        dry_run: bool = False,
    ) -> OpenRouterHttpResult:
        body = self._build_body(prompt, options)

        if dry_run:
            async with TranscriptWriter(
                transcript_path, ['POST', f'{self._base_url}/chat/completions']
            ) as tx:
                tx.append_line(f'# DRY-RUN body (model={options.model})\n')
                tx.append_line(_pretty_json(body))
                tx.write_dry_run_marker()
            return OpenRouterHttpResult(
                success=True,
                status_code=0,
                duration_s=0.0,
                model_used=options.model,
            )

        cmd_label = ['POST', f'{self._base_url}/chat/completions', f'model={options.model}']
        start = time.monotonic()
        async with TranscriptWriter(transcript_path, cmd_label) as tx:
            tx.append_line(f'# Request body (model={options.model})\n')
            tx.append_line(_pretty_json(body))
            tx.append_line('\n# Response\n')
            try:
                async with httpx.AsyncClient(timeout=options.timeout_s) as client:
                    resp = await client.post(
                        f'{self._base_url}/chat/completions',
                        headers=self._headers(),
                        json=body,
                    )
            except httpx.TimeoutException as e:
                duration = time.monotonic() - start
                tx.append_line(f'# Timeout after {duration:.1f}s: {e!r}\n')
                tx.finalize(exit_code=124)
                return OpenRouterHttpResult(
                    success=False,
                    status_code=0,
                    duration_s=duration,
                    error=f'timeout after {duration:.0f}s',
                    raw_output=str(e),
                )
            duration = time.monotonic() - start
            tx.append_line(resp.text)
            tx.finalize(exit_code=0 if resp.is_success else resp.status_code)

        return self._parse_response(resp, options, duration)

    # ── helpers ────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self._api_key}',
            'HTTP-Referer': self._http_referer,
            'X-OpenRouter-Title': self._app_title,
            'Content-Type': 'application/json',
        }

    def _build_body(self, prompt: str, options: OpenRouterHttpOptions) -> dict[str, Any]:
        body: dict[str, Any] = {
            'model': options.model,
            'messages': [{'role': 'user', 'content': prompt}],
            # Ask OpenRouter to include token counts and a `cost` field in the
            # usage block so the stage can persist per-subsession spend.
            'usage': {'include': True},
        }
        if options.max_tokens is not None:
            body['max_tokens'] = options.max_tokens
        if options.temperature is not None:
            body['temperature'] = options.temperature

        # Reasoning (effort / max_tokens) — works across Anthropic / OpenAI / Gemini / DeepSeek.
        if options.reasoning_effort or options.reasoning_max_tokens:
            reasoning: dict[str, Any] = {}
            if options.reasoning_effort:
                reasoning['effort'] = options.reasoning_effort
            if options.reasoning_max_tokens:
                reasoning['max_tokens'] = options.reasoning_max_tokens
            body['reasoning'] = reasoning

        # Web search plugin — native where supported, Exa otherwise.
        if options.web_search:
            body['plugins'] = [
                {
                    'id': 'web',
                    'engine': options.web_search_engine,
                    'max_results': options.web_search_max_results,
                },
            ]

        # Provider routing.
        provider: dict[str, Any] = {}
        if options.provider_order:
            provider['order'] = list(options.provider_order)
        if options.require_parameters:
            provider['require_parameters'] = True
        if options.data_collection_deny:
            provider['data_collection'] = 'deny'
        if provider:
            body['provider'] = provider

        return body

    @staticmethod
    def _parse_response(
        resp: httpx.Response,
        options: OpenRouterHttpOptions,
        duration: float,
    ) -> OpenRouterHttpResult:
        raw_text = resp.text
        if not resp.is_success:
            return OpenRouterHttpResult(
                success=False,
                status_code=resp.status_code,
                duration_s=duration,
                error=f'HTTP {resp.status_code}',
                raw_output=raw_text,
            )
        try:
            data = resp.json()
        except ValueError:
            return OpenRouterHttpResult(
                success=False,
                status_code=resp.status_code,
                duration_s=duration,
                error='non-JSON response',
                raw_output=raw_text,
            )
        choices = data.get('choices') or []
        if not choices:
            return OpenRouterHttpResult(
                success=False,
                status_code=resp.status_code,
                duration_s=duration,
                error='no choices in response',
                raw_output=raw_text,
            )
        msg = choices[0].get('message') or {}
        content = msg.get('content') or ''
        finish_reason = choices[0].get('finish_reason')
        if not content.strip():
            return OpenRouterHttpResult(
                success=False,
                status_code=resp.status_code,
                duration_s=duration,
                error='empty content',
                raw_output=raw_text,
                finish_reason=finish_reason,
            )
        return OpenRouterHttpResult(
            success=True,
            status_code=resp.status_code,
            duration_s=duration,
            output=content,
            raw_output=raw_text,
            finish_reason=finish_reason,
            model_used=data.get('model') or options.model,
            usage=data.get('usage'),
        )


def _pretty_json(obj: dict[str, Any]) -> str:
    import json

    return json.dumps(obj, indent=2, ensure_ascii=False) + '\n'

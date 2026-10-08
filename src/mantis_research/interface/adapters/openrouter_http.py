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

import asyncio
import dataclasses
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urlsplit

import httpx
import structlog

from mantis_research.core.citations import Citation, is_grounding_redirect, url_citations
from mantis_research.core.settings import settings
from mantis_research.interface.transcripts import TranscriptWriter

if TYPE_CHECKING:
    from pathlib import Path

    from mantis_research.core.config import SearchEngine

log = structlog.get_logger(__name__)

# A grounding-redirect lookup is one GET answered by one 302; it must not hold up
# a brief that has already been paid for. Seconds, for each httpx phase of a lookup
# and for the whole resolution step.
_REDIRECT_TIMEOUT_S = 10.0


@dataclass(frozen=True, slots=True)
class OpenRouterHttpOptions:
    """Per-call options for the OpenRouter HTTP adapter."""

    model: str  # e.g. 'google/gemini-3.1-pro-preview', 'openai/gpt-5.5'
    web_search: bool = False
    # Which index the web plugin reads. 'native' is the provider's own search
    # (OpenAI / Anthropic / xAI / Perplexity / Gemini 3.x); the others are
    # OpenRouter-side engines, each with its own index and price.
    web_search_engine: SearchEngine = 'native'
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
    # The pages the web search cited, from ``message.annotations``; Google's
    # grounding redirects are resolved to the real pages where the lookup works.
    citations: tuple[Citation, ...] = ()


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
        # Do NOT require the key at construction: the stage is built even for a
        # --dry-run (which never hits the network), so an eager check here made
        # dry-run demand a key it doesn't use. The key is resolved lazily at the
        # first real request (see _require_key / _headers).
        self._explicit_key = api_key
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

        result = self._parse_response(resp, options, duration)
        if result.success and result.citations:
            result = dataclasses.replace(
                result, citations=await _resolve_grounding_redirects(result.citations)
            )
        return result

    # ── helpers ────────────────────────────────────────────────────

    def _require_key(self) -> str:
        """Resolve the API key at call time, raising only when one is needed.

        Construction stays key-free so a dry-run (which never reaches the network)
        works before a key is set; the key is required only at an actual request
        (``preflight`` and a non-dry-run ``run``, both via ``_headers``).
        """
        key = self._explicit_key or (
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
        return key

    def _headers(self) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self._require_key()}',
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

        # Web search plugin — the engine is chosen per substrate (core/search_engines.py).
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
        content = _coerce_content(msg.get('content'))
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
            citations=url_citations(msg) if isinstance(msg, dict) else (),
        )


async def _resolve_grounding_redirects(citations: tuple[Citation, ...]) -> tuple[Citation, ...]:
    """Replace each Google grounding redirect with the page it redirects to.

    Google's native search cites ``vertexaisearch.cloud.google.com/
    grounding-api-redirect/<token>`` URLs, which name no source; each answers a
    GET with one 302 whose ``Location`` is the real page. The lookups run
    concurrently, without following the redirect and without the OpenRouter
    key (they go to Google). A lookup that fails keeps the redirect URL, so the
    citation is never lost, and the count left unresolved is logged once. The
    step as a whole is bounded by ``_REDIRECT_TIMEOUT_S``: lookups still running
    at the deadline are left unresolved, those already done are kept.
    """
    targets = [i for i, c in enumerate(citations) if is_grounding_redirect(c.url)]
    if not targets:
        return citations
    resolved: dict[int, str] = {}
    async with httpx.AsyncClient(timeout=_REDIRECT_TIMEOUT_S, follow_redirects=False) as client:

        async def resolve(index: int) -> None:
            location = await _redirect_location(client, citations[index].url)
            if location is not None:
                resolved[index] = location

        # httpx's timeout bounds each phase (connect, write, read), not the lookup, so
        # a slow host could take several times it; the deadline bounds the whole step.
        # On expiry the lookups still running are cancelled and those done are kept.
        try:
            async with asyncio.timeout(_REDIRECT_TIMEOUT_S), asyncio.TaskGroup() as group:
                for index in targets:
                    group.create_task(resolve(index))
        except TimeoutError:
            pass
    unresolved = len(targets) - len(resolved)
    if unresolved:
        log.warning(
            'grounding redirects left unresolved; the brief cites the redirect URLs',
            unresolved=unresolved,
            total=len(targets),
        )
    return tuple(
        dataclasses.replace(c, url=resolved[i]) if i in resolved else c
        for i, c in enumerate(citations)
    )


async def _redirect_location(client: httpx.AsyncClient, url: str) -> str | None:
    """The absolute http(s) ``Location`` a redirect answers with, or None.

    Any failure is None: the brief is already paid for, and a lookup that
    cannot be made must cost it nothing but the resolution.
    """
    try:
        resp = await client.get(url)
    except Exception:  # any failure keeps the redirect URL
        return None
    if not resp.is_redirect:
        return None
    location = str(resp.headers.get('location', '')).strip()
    try:
        parts = urlsplit(location)
    except ValueError:
        return None
    if parts.scheme.lower() not in {'http', 'https'} or not parts.hostname:
        return None
    return location


def _coerce_content(content: object) -> str:
    """Normalize an OpenRouter message ``content`` to a string.

    Most providers return a string, but some return OpenAI-style content parts
    (a list of ``{"type": "text", "text": ...}`` dicts) for multimodal/tool
    responses. Concatenate the text parts so a non-string ``content`` never
    reaches ``content.strip()`` as a list — which would raise ``AttributeError``
    and crash the parse. Anything unrecognized coerces to an empty string, which
    the caller treats as an empty (failed) response.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                d = cast('dict[str, Any]', part)
                text = d.get('text') or d.get('content')
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(part, str):
                parts.append(part)
        return ''.join(parts)
    return ''


def _pretty_json(obj: dict[str, Any]) -> str:
    import json

    return json.dumps(obj, indent=2, ensure_ascii=False) + '\n'

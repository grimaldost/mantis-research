"""Search citations reach the brief even when the model writes no links (0.7.0 defect).

Field evidence, 2026-10-08: Google's native search ran four searches and the
response carried 11 ``url_citation`` annotations, each an opaque
``grounding-api-redirect`` URL titled only with a domain, while the message text
linked nothing. The adapter kept only the text, so the google brief had no
sources. These tests drive the adapter through a fake ``httpx.AsyncClient.send``
(nothing leaves the process) and the stage's brief writer.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from mantis_research.core.citations import Citation
from mantis_research.core.retrieval_overlap import extract_urls
from mantis_research.interface.adapters import openrouter_http
from mantis_research.interface.adapters.openrouter_http import (
    OpenRouterHttpAdapter,
    OpenRouterHttpOptions,
    OpenRouterHttpResult,
)
from mantis_research.interface.stages.openrouter_research import OpenRouterResearchStage

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

_REDIRECT = 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/'
_GOOGLE_TEXT = 'Human decisions concentrate at task framing and at review.\n'
_PAGES = {
    f'{_REDIRECT}AAA': ('https://jfrog.com/blog/agentic-review/', 'jfrog.com'),
    f'{_REDIRECT}BBB': ('https://arxiv.org/abs/2505.18286', 'arxiv.org'),
    f'{_REDIRECT}CCC': ('https://www.nist.gov/itl/ai-risk-management-framework', 'nist.gov'),
}


def _annotation(url: str, title: str) -> dict[str, Any]:
    return {
        'type': 'url_citation',
        'url_citation': {'url': url, 'title': title, 'start_index': 0, 'end_index': 0},
    }


def _completion(content: str, annotations: list[dict[str, Any]] | None) -> dict[str, Any]:
    message: dict[str, Any] = {'role': 'assistant', 'content': content}
    if annotations is not None:
        message['annotations'] = annotations
    return {
        'model': 'google/gemini-3.1-pro-preview',
        'choices': [{'message': message, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'cost': 0.01},
    }


def _google_completion() -> dict[str, Any]:
    return _completion(
        _GOOGLE_TEXT, [_annotation(url, title) for url, (_, title) in _PAGES.items()]
    )


type Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]


def _fake_send(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> list[httpx.Request]:
    """Replace the (already refused) send with an in-process handler; record requests.

    ``AsyncClient.send`` is replaced, so the client's redirect-following (which
    lives in ``send``) never runs. Each request therefore carries the setting it
    would have been sent with as ``extensions['follow_redirects']``: the
    per-call argument, or the client's own default when the call leaves it unset.
    """
    seen: list[httpx.Request] = []

    async def send(client: httpx.AsyncClient, request: httpx.Request, **kw: Any) -> httpx.Response:
        follow = kw.get('follow_redirects', httpx.USE_CLIENT_DEFAULT)
        if follow is httpx.USE_CLIENT_DEFAULT:
            follow = client.follow_redirects
        request.extensions['follow_redirects'] = follow
        seen.append(request)
        response = await handler(request)
        response.request = request
        return response

    monkeypatch.setattr('httpx.AsyncClient.send', send)
    return seen


def _completions_then(
    completion: dict[str, Any],
    on_get: Callable[[httpx.Request], Awaitable[httpx.Response]],
) -> Handler:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'POST' and str(request.url).endswith('/chat/completions'):
            return httpx.Response(200, json=completion)
        if request.method == 'GET':
            return await on_get(request)
        msg = f'unexpected request {request.method} {request.url}'
        raise AssertionError(msg)

    return handler


async def _redirect_to_page(request: httpx.Request) -> httpx.Response:
    real, _ = _PAGES[str(request.url)]
    return httpx.Response(302, headers={'Location': real})


async def _no_get_expected(request: httpx.Request) -> httpx.Response:
    msg = f'no resolution request expected, got GET {request.url}'
    raise AssertionError(msg)


def _options() -> OpenRouterHttpOptions:
    return OpenRouterHttpOptions(model='google/gemini-3.1-pro-preview', web_search=True)


async def _run(tmp_path: Path) -> OpenRouterHttpResult:
    adapter = OpenRouterHttpAdapter(api_key='sk-test', base_url='https://openrouter.test/api/v1')
    return await adapter.run('q', _options(), tmp_path / 'transcript.log')


class _Recorder:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **kw: Any) -> None:
        self.warnings.append((event, kw))

    def __getattr__(self, _name: str) -> Callable[..., None]:
        return lambda *_a, **_k: None


class TestParseResponse:
    def test_annotations_become_citations(self) -> None:
        resp = httpx.Response(200, json=_google_completion())
        result = OpenRouterHttpAdapter._parse_response(resp, _options(), 1.0)
        assert result.success
        assert result.output == _GOOGLE_TEXT
        assert result.citations == tuple(
            Citation(url=url, title=title) for url, (_, title) in _PAGES.items()
        )

    def test_no_annotations_is_no_citations(self) -> None:
        resp = httpx.Response(200, json=_completion('text', None))
        assert OpenRouterHttpAdapter._parse_response(resp, _options(), 1.0).citations == ()


class TestRedirectResolution:
    @pytest.mark.asyncio
    async def test_grounding_redirects_resolve_to_the_real_pages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _fake_send(monkeypatch, _completions_then(_google_completion(), _redirect_to_page))
        result = await _run(tmp_path)
        assert result.success
        assert result.citations == tuple(
            Citation(url=real, title=title) for real, title in _PAGES.values()
        )
        gets = [r for r in seen if r.method == 'GET']
        assert sorted(str(r.url) for r in gets) == sorted(_PAGES)
        # The lookup goes to Google, so it must not carry the OpenRouter key.
        assert all('authorization' not in r.headers for r in gets)
        assert all(r.extensions['timeout']['read'] == 10.0 for r in gets)
        # A lookup reads the 302; following it would fetch the page itself.
        assert [r.extensions['follow_redirects'] for r in gets] == [False] * len(_PAGES)

    @pytest.mark.asyncio
    async def test_redirects_are_resolved_concurrently(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Every lookup waits until all of them have started: one-by-one never gets there.
        started = 0
        all_started = asyncio.Event()

        async def on_get(request: httpx.Request) -> httpx.Response:
            nonlocal started
            started += 1
            if started == len(_PAGES):
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=2.0)
            return await _redirect_to_page(request)

        _fake_send(monkeypatch, _completions_then(_google_completion(), on_get))
        result = await _run(tmp_path)
        assert [c.url for c in result.citations] == [real for real, _ in _PAGES.values()]

    @pytest.mark.asyncio
    async def test_a_failed_lookup_keeps_the_redirect_and_warns_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        aaa, bbb, ccc = _PAGES

        async def on_get(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == aaa:
                raise httpx.ConnectError('unreachable', request=request)
            if url == bbb:
                return httpx.Response(302, headers={'Location': '/relative/page'})
            return httpx.Response(200, text='a page, not a redirect')

        recorder = _Recorder()
        monkeypatch.setattr(openrouter_http, 'log', recorder)
        _fake_send(monkeypatch, _completions_then(_google_completion(), on_get))
        result = await _run(tmp_path)
        assert result.success
        assert [c.url for c in result.citations] == [aaa, bbb, ccc]
        assert len(recorder.warnings) == 1
        _, fields = recorder.warnings[0]
        assert fields['unresolved'] == 3

    @pytest.mark.asyncio
    async def test_a_partial_failure_resolves_the_rest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        aaa, _, _ = _PAGES

        async def on_get(request: httpx.Request) -> httpx.Response:
            if str(request.url) == aaa:
                raise httpx.ReadTimeout('slow', request=request)
            return await _redirect_to_page(request)

        recorder = _Recorder()
        monkeypatch.setattr(openrouter_http, 'log', recorder)
        _fake_send(monkeypatch, _completions_then(_google_completion(), on_get))
        result = await _run(tmp_path)
        assert [c.url for c in result.citations] == [
            aaa,
            'https://arxiv.org/abs/2505.18286',
            'https://www.nist.gov/itl/ai-risk-management-framework',
        ]
        assert [fields['unresolved'] for _, fields in recorder.warnings] == [1]

    @pytest.mark.asyncio
    async def test_a_lookup_that_never_answers_is_bounded_by_the_deadline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # httpx's timeout is per phase, not a total; the whole step needs a deadline.
        aaa, bbb, ccc = _PAGES
        monkeypatch.setattr(openrouter_http, '_REDIRECT_TIMEOUT_S', 0.2)
        never = asyncio.Event()

        async def on_get(request: httpx.Request) -> httpx.Response:
            if str(request.url) == aaa:
                await never.wait()
            return await _redirect_to_page(request)

        recorder = _Recorder()
        monkeypatch.setattr(openrouter_http, 'log', recorder)
        _fake_send(monkeypatch, _completions_then(_google_completion(), on_get))
        result = await asyncio.wait_for(_run(tmp_path), timeout=5.0)
        assert result.success
        assert [c.url for c in result.citations] == [
            aaa,
            _PAGES[bbb][0],
            _PAGES[ccc][0],
        ]
        assert [fields['unresolved'] for _, fields in recorder.warnings] == [1]

    @pytest.mark.asyncio
    async def test_ordinary_citations_are_not_fetched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completion = _completion(
            'See [the study](https://arxiv.org/abs/2505.18286).',
            [_annotation('https://arxiv.org/abs/2505.18286?utm_source=openai', 'The study')],
        )
        seen = _fake_send(monkeypatch, _completions_then(completion, _no_get_expected))
        result = await _run(tmp_path)
        assert result.citations == (
            Citation(url='https://arxiv.org/abs/2505.18286?utm_source=openai', title='The study'),
        )
        assert [r.method for r in seen] == ['POST']

    @pytest.mark.asyncio
    async def test_a_dry_run_makes_no_request(self, tmp_path: Path) -> None:
        # The suite's guard refuses any send, so reaching the network would raise.
        adapter = OpenRouterHttpAdapter(api_key='sk-test')
        result = await adapter.run('q', _options(), tmp_path / 't.log', dry_run=True)
        assert result.success
        assert result.citations == ()


def _write_brief(tmp_path: Path, result: object) -> tuple[str, int | None]:
    out = tmp_path / 'google.md'
    record = OpenRouterResearchStage._build_subsession_result(
        subslug='google', result=result, out_path=out, dry_run=False
    )
    assert record.status == 'done'
    return out.read_text(encoding='utf-8'), record.output_bytes


def _result(output: str, citations: tuple[Citation, ...] = ()) -> OpenRouterHttpResult:
    return OpenRouterHttpResult(
        success=True, status_code=200, duration_s=1.0, output=output, citations=citations
    )


class TestBriefCarriesItsSources:
    def test_annotation_citations_are_written_as_links(self, tmp_path: Path) -> None:
        citations = tuple(Citation(url=real, title=title) for real, title in _PAGES.values())
        text, size = _write_brief(tmp_path, _result(_GOOGLE_TEXT, citations))
        assert extract_urls(text) == {
            'jfrog.com/blog/agentic-review',
            'arxiv.org/abs/2505.18286',
            'nist.gov/itl/ai-risk-management-framework',
        }
        assert text.startswith(_GOOGLE_TEXT.strip() + '\n\n## Sources\n\n')
        assert size == (tmp_path / 'google.md').stat().st_size

    def test_no_annotations_writes_the_brief_as_before(self, tmp_path: Path) -> None:
        content = '  A brief with [a link](https://a.example/x).\n\n'
        _, size = _write_brief(tmp_path, _result(content))
        # What 0.7.0 wrote, through the same platform newline translation.
        before = tmp_path / 'before.md'
        before.write_text(content.strip() + '\n', encoding='utf-8')
        assert (tmp_path / 'google.md').read_bytes() == before.read_bytes()
        assert size == before.stat().st_size

    def test_a_result_without_the_field_writes_the_brief_as_before(self, tmp_path: Path) -> None:
        legacy = SimpleNamespace(
            success=True, output='A brief.', raw_output='', duration_s=1.0, status_code=200,
            error=None, usage=None,
        )  # fmt: skip
        text, _ = _write_brief(tmp_path, legacy)
        assert text == 'A brief.\n'

    def test_citations_already_linked_add_no_section(self, tmp_path: Path) -> None:
        content = 'See [the study](https://arxiv.org/abs/2505.18286).'
        citations = (
            Citation(url='https://arxiv.org/abs/2505.18286?utm_source=openai', title='The study'),
        )
        text, _ = _write_brief(tmp_path, _result(content, citations))
        assert text == content + '\n'


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_google_brief_links_the_resolved_pages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_send(monkeypatch, _completions_then(_google_completion(), _redirect_to_page))
        result = await _run(tmp_path)
        text, _ = _write_brief(tmp_path, result)
        urls = extract_urls(text)
        assert len(urls) == len(_PAGES)
        assert not any('grounding-api-redirect' in u for u in urls)
        assert 'jfrog.com/blog/agentic-review' in urls

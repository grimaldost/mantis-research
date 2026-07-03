"""OpenRouter model-catalog fetch — the I/O half of the auto-latest policy.

``GET {base_url}/models`` returns the live model catalog (``{"data": [...]}``);
each entry carries ``id`` / ``created`` / ``pricing`` / … . The pure selection
logic (which entry is a given vendor's newest flagship) lives in
``core/model_policy.py``; this module only does the network call and caches the
result for the lifetime of one process.

Offline-safety is the whole point: this workspace is frequently offline. Every
failure mode — no API key, DNS failure, timeout, non-200, malformed body —
degrades to ``None`` (logged once at debug), and the caller then uses the
pinned fallback ids in ``model_policy``. A missing catalog NEVER raises and
never blocks a run.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from mantis_research.core.settings import settings

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

log = structlog.get_logger(__name__)

# Short timeout — resolving the catalog must not stall a batch. If OpenRouter
# is slow/unreachable we want to fall through to pinned ids quickly.
_DEFAULT_TIMEOUT_S: float = 8.0


class OpenRouterCatalog:
    """Process-lifetime cache of the OpenRouter ``/models`` catalog.

    Construct once (the dispatch layer does this per ``mantis run`` invocation)
    and call :meth:`models` — the first call fetches, subsequent calls return
    the cached list. A failed fetch caches ``None`` so a single offline run
    doesn't retry the network for every topic/subsession.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._base_url = (base_url or settings.OPENROUTER_BASE_URL).rstrip('/')
        # The /models endpoint is public, but send the key when we have one so
        # the request is attributed and rate-limited under the account.
        self._api_key = api_key or (
            settings.OPENROUTER_API_KEY.get_secret_value()
            if settings.OPENROUTER_API_KEY is not None
            else None
        )
        self._timeout_s = timeout_s
        self._lock = threading.Lock()
        self._fetched = False
        self._models: list[dict[str, Any]] | None = None

    def models(self) -> Sequence[Mapping[str, object]] | None:
        """Return the catalog ``data`` list, or None if unavailable.

        Thread-safe and memoized: fetches at most once per process. None means
        "fall back to pinned ids" — it is a normal, expected outcome offline,
        not an error.
        """
        with self._lock:
            if not self._fetched:
                self._models = self._fetch()
                self._fetched = True
            return self._models

    def _fetch(self) -> list[dict[str, Any]] | None:
        url = f'{self._base_url}/models'
        headers = {'Accept': 'application/json'}
        if self._api_key:
            headers['Authorization'] = f'Bearer {self._api_key}'
        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                resp = client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            # DNS failure, connection refused, timeout, etc. — offline path.
            log.debug('openrouter catalog fetch failed; using pinned fallbacks', error=str(exc))
            return None

        if resp.status_code != httpx.codes.OK:
            log.debug(
                'openrouter catalog returned non-200; using pinned fallbacks',
                status=resp.status_code,
            )
            return None

        try:
            payload = resp.json()
        except ValueError:
            log.debug('openrouter catalog returned non-JSON; using pinned fallbacks')
            return None

        data = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(data, list):
            log.debug('openrouter catalog missing data[]; using pinned fallbacks')
            return None

        models = [m for m in data if isinstance(m, dict)]
        log.info('openrouter catalog loaded', model_count=len(models))
        return models

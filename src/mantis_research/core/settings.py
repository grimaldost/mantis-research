"""Application settings — env-driven, validated by pydantic-settings.

Settings are loaded from environment variables with optional ``.env`` file
support. Secrets use ``SecretStr`` so they don't accidentally leak into
log output.

Usage::

    from mantis_research.core.settings import settings
    api_key = settings.OPENROUTER_API_KEY.get_secret_value()
"""

from __future__ import annotations

# SecretStr must be imported at runtime (not in TYPE_CHECKING) because
# pydantic-settings introspects the annotation at __init__ time.
from pydantic import SecretStr  # noqa: TC002 — runtime use, not just typing
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration loaded from env / .env."""

    # OpenRouter
    OPENROUTER_API_KEY: SecretStr | None = None
    OPENROUTER_BASE_URL: str = 'https://openrouter.ai/api/v1'
    MANTIS_HTTP_REFERER: str = 'https://github.com/grimaldost/mantis-research'
    MANTIS_APP_TITLE: str = 'mantis-research'

    # Logging
    LOG_LEVEL: str = 'INFO'
    LOG_FORCE_JSON: bool = False

    # Interface gating — comma-separated list of stage names that are
    # disabled at the CLI dispatch level. Used to enforce e.g. "no Gemini
    # subscription, the OAuth CLI is not available on this machine" by
    # setting DISABLED_STAGES=gemini. The CLI will then fail-fast
    # with a helpful pointer when a user tries `mantis run gemini`.
    #
    # Valid stage names match the keys of STAGE_REGISTRY in
    # interface/cli/dispatch.py: claude, gemini, openrouter, synthesis,
    # journal-passes, falsification, evaluation, claude-prior.
    DISABLED_STAGES: str = ''

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=True,
        extra='ignore',
    )

    @property
    def disabled_stages(self) -> frozenset[str]:
        """Return the parsed set of disabled stage names (lowercased, trimmed)."""
        return frozenset(s.strip().lower() for s in self.DISABLED_STAGES.split(',') if s.strip())


# Module-level singleton — instantiated once on import.
settings = Settings()

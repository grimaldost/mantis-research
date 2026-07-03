"""Structured-logging configuration via structlog.

Application entry points (CLI subcommands, batch entrypoints) call
``configure_logging()`` exactly once at startup. After that, every module
gets its logger via ``structlog.get_logger(__name__)``.

Logs are written to **stderr** (never stdout): stdout is reserved for program
output — the ``mantis research`` result manifest and, critically, the JSON-RPC
stream of the stdio MCP server (``interface/mcp/``), which structured logs on
stdout would corrupt. They are JSON-encoded when stderr is not a TTY (CI / files
/ piped) and human-friendly with colors when interactive. The ``contextvars``
processor allows binding context (e.g., ``topic_id``, ``stage``, ``attempt``)
once at the top of an async task and having it appear in every subsequent log.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from structlog.types import Processor


def configure_logging(*, level: str = 'INFO', force_json: bool = False) -> None:
    """Configure structlog. Idempotent — safe to call once at app startup.

    Args:
        level: stdlib log level name (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``).
        force_json: emit JSON regardless of TTY. Useful for testing the
            production renderer locally.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt='iso', utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    # Logs go to stderr; the TTY check is on stderr for the same reason.
    use_json = force_json or not sys.stderr.isatty()
    final_processor: Processor = (
        structlog.processors.JSONRenderer()
        if use_json
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, final_processor],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO),
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Convenience wrapper for ``structlog.get_logger``."""
    return structlog.get_logger(name)

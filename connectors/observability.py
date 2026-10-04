"""Shared structured-logging setup.

Every process in the stack - simulator, ticketing mock, MCP server, copilot
backend - configures logging through this module so that a single trace id
can be grepped across all of their logs.

Two rules are enforced here rather than left to each call site:

1. Log records are structured. ``LOG_FORMAT=json`` (the default) emits one
   JSON object per line for ingestion; ``console`` emits a readable form for
   local development.
2. Secrets never reach a log. :func:`scrub` redacts the values of keys whose
   name looks sensitive, and it is installed as a processor so it applies to
   every event regardless of who logged it.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable, MutableMapping
from typing import Any

import structlog

# Substrings that mark a field as sensitive. Matching is case-insensitive and
# on substrings, so `alarm_api_token` and `Authorization` are both caught.
SENSITIVE_KEY_PARTS: tuple[str, ...] = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "bearer",
    "cookie",
)

REDACTED = "***redacted***"


def is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def scrub_value(key: str, value: Any) -> Any:
    """Redact ``value`` when ``key`` looks sensitive, recursing into mappings."""
    if is_sensitive(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: scrub_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(scrub_value(key, v) for v in value)
    return value


def _scrub_processor(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    return {k: scrub_value(k, v) for k, v in event_dict.items()}


def configure_logging(
    service: str,
    *,
    level: str | None = None,
    fmt: str | None = None,
    extra_processors: Iterable[Any] = (),
) -> None:
    """Configure structlog and the stdlib root logger for ``service``."""
    level_name = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    output = (fmt or os.getenv("LOG_FORMAT") or "json").lower()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level_name, logging.INFO),
        force=True,
    )
    # uvicorn duplicates access logs that we already emit ourselves.
    logging.getLogger("uvicorn.access").disabled = True

    renderer = (
        structlog.processors.JSONRenderer()
        if output == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            *extra_processors,
            _scrub_processor,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level_name, logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)

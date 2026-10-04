"""Shared runtime for the MCP tools: clients, timing, windows, error mapping.

Every tool in :mod:`alarm_mcp.server` is a thin shell over this module, so
the cross-cutting behaviour - how long a call took, which trace it belonged
to, how an upstream failure becomes a tool error - is defined once.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from alarm_mcp.config import McpSettings, get_settings
from alarm_mcp.models import ToolMeta
from connectors import tracing
from connectors.alarm_client import AlarmApiClient
from connectors.source_client import SourceSystemError
from connectors.ticketing_client import TicketingApiClient

logger = structlog.get_logger(__name__)

# Fallback horizon if the Alarm API's health endpoint cannot be read. The
# simulator's dataset ends here; see services/alarm_api/config.py.
FALLBACK_HORIZON = datetime(2026, 9, 30, tzinfo=UTC)
DEFAULT_LOOKBACK_DAYS = 90


class ToolInputError(ValueError):
    """A tool argument is invalid in a way the schema cannot express.

    Surfaced to the MCP client as a tool error whose message tells the model
    how to correct the call, rather than as a transport-level failure.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class UpstreamToolError(RuntimeError):
    """An upstream source system failed. Carries structured diagnosis."""

    def __init__(self, error: SourceSystemError) -> None:
        super().__init__(error.message)
        self.error = error

    @property
    def payload(self) -> dict[str, Any]:
        return self.error.as_tool_payload()


# ---------------------------------------------------------------------------
# Trace propagation
# ---------------------------------------------------------------------------
# An MCP call is JSON-RPC, so the caller's trace cannot ride on an HTTP
# header alone: over stdio there is no header, and over streamable HTTP the
# SDK's transport opens one connection and reuses it for every call, so any
# header set at connect time is the same for all of them. The per-call
# channel is the request's `_meta` object, which both transports carry
# verbatim. Headers are still read as a fallback, because an MCP client that
# is not this copilot (the Inspector, Claude Desktop, a gateway) may set one.
TRACE_META_KEY = "trace_id"
REQUEST_ID_META_KEY = "request_id"
CLIENT_ID_META_KEY = "client_id"
METADATA_TAG_META_KEY = "metadata_tag"


def _first_str(source: Mapping[str, Any] | None, *keys: str) -> str | None:
    """First key in ``source`` with a non-empty string value."""
    if not source:
        return None
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def trace_context_from(
    meta: Mapping[str, Any] | None,
    headers: Mapping[str, str] | None,
) -> tracing.TraceContext:
    """Rebuild the caller's trace context, generating only what is absent.

    Precedence is `_meta`, then headers, then a fresh id. A generated id is
    prefixed `trace-mcp-` so that a log line makes it obvious the trace
    started at this hop rather than at the copilot's edge.
    """
    trace_id = _first_str(meta, TRACE_META_KEY) or _first_str(
        headers, tracing.TRACE_HEADER, "x-trace-id"
    )
    if not trace_id:
        traceparent = _first_str(headers, "traceparent")
        if traceparent:
            parts = traceparent.split("-")
            if len(parts) >= 3 and len(parts[1]) == 32:
                trace_id = parts[1]
    if not trace_id:
        trace_id = f"trace-mcp-{uuid.uuid4().hex[:12]}"

    request_id = (
        _first_str(meta, REQUEST_ID_META_KEY)
        or _first_str(headers, tracing.REQUEST_ID_HEADER)
        or uuid.uuid4().hex
    )
    client_id = _first_str(meta, CLIENT_ID_META_KEY) or _first_str(
        headers, tracing.CLIENT_ID_HEADER
    )
    metadata_tag = _first_str(meta, METADATA_TAG_META_KEY) or _first_str(
        headers, tracing.METADATA_TAG_HEADER
    )
    return tracing.TraceContext(
        trace_id=trace_id[:128],
        request_id=request_id[:128],
        client_id=client_id,
        metadata_tag=metadata_tag,
    )


async def trace_middleware(ctx: Any, call_next: Callable[[Any], Awaitable[Any]]) -> Any:
    """Bind the caller's trace for the whole of one inbound MCP message.

    Registered on the server, so it wraps every request - not just tool
    calls - and runs before argument validation. Binding here rather than
    inside each tool is what makes the id reach the Alarm and ticketing
    APIs: :class:`connectors.source_client.SourceSystemClient` reads the
    same contextvar when it builds its outbound headers.
    """
    context = trace_context_from(
        getattr(ctx, "meta", None),
        getattr(getattr(ctx, "request", None), "headers", None),
    )
    token = tracing.set_current(context)
    try:
        return await call_next(ctx)
    finally:
        tracing.reset_current(token)


@dataclass
class Runtime:
    """Holds the source-system clients for the life of the server."""

    settings: McpSettings
    alarm: AlarmApiClient
    tickets: TicketingApiClient
    _horizon: datetime | None = field(default=None, repr=False)

    @classmethod
    def build(cls, settings: McpSettings | None = None) -> Runtime:
        settings = settings or get_settings()
        return cls(
            settings=settings,
            alarm=AlarmApiClient(
                settings.alarm_api_base_url,
                settings.alarm_api_token,
                timeout_seconds=settings.alarm_api_timeout_seconds,
                max_retries=settings.alarm_api_max_retries,
            ),
            tickets=TicketingApiClient(
                settings.ticketing_api_url,
                settings.ticketing_api_token,
                timeout_seconds=settings.alarm_api_timeout_seconds,
                max_retries=settings.alarm_api_max_retries,
            ),
        )

    async def aclose(self) -> None:
        await self.alarm.aclose()
        await self.tickets.aclose()

    async def horizon(self) -> datetime:
        """The source data's notion of "now".

        The simulator's dataset ends at a fixed date, so resolving "the last
        90 days" against wall-clock time would silently return nothing. The
        horizon is read once from ``/health`` and cached.
        """
        if self._horizon is None:
            try:
                health = await self.alarm.health()
                raw = health.get("dataset", {}).get("window_end")
                self._horizon = datetime.fromisoformat(raw) if raw else FALLBACK_HORIZON
            except (SourceSystemError, ValueError, TypeError):
                logger.warning("horizon_fallback", horizon=FALLBACK_HORIZON.isoformat())
                self._horizon = FALLBACK_HORIZON
        return self._horizon

    async def resolve_window(
        self,
        start_time: str | None,
        end_time: str | None,
        lookback_days: int | None,
    ) -> tuple[str, str]:
        """Turn the three ways of expressing a window into one concrete pair.

        Precedence: explicit ``start_time``/``end_time`` win; otherwise
        ``lookback_days`` counts back from the data horizon; otherwise a
        90-day default. Returning ISO strings keeps the tool contract simple
        for a language model to fill in.
        """
        if start_time and end_time:
            start, end = _parse_iso(start_time, "start_time"), _parse_iso(end_time, "end_time")
        else:
            end = _parse_iso(end_time, "end_time") if end_time else await self.horizon()
            if start_time:
                start = _parse_iso(start_time, "start_time")
            else:
                days = lookback_days if lookback_days is not None else DEFAULT_LOOKBACK_DAYS
                if days < 1:
                    raise ToolInputError(
                        "lookback_days must be at least 1.",
                        details={"received": days},
                    )
                start = end - timedelta(days=days)

        if end <= start:
            raise ToolInputError(
                "The time window is empty: end_time must be after start_time.",
                details={"start_time": start.isoformat(), "end_time": end.isoformat()},
            )
        return _iso_z(start), _iso_z(end)


def _parse_iso(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolInputError(
            f"{field_name} must be an ISO-8601 timestamp, for example '2026-07-01T00:00:00Z'.",
            details={"field": field_name, "received": value[:64]},
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso_z(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class Timer:
    """Accumulates elapsed time and upstream call count for a tool result."""

    started: float = field(default_factory=time.perf_counter)
    calls: int = 0

    def record_call(self, count: int = 1) -> None:
        self.calls += count

    @property
    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 2)

    def meta(self, system: str, operation: str, *, truncated: bool = False) -> ToolMeta:
        return ToolMeta(
            source_system=system,
            operation=operation,
            trace_id=tracing.current_trace_id(),
            duration_ms=self.elapsed_ms,
            upstream_calls=max(self.calls, 1),
            truncated=truncated,
        )


@contextmanager
def tool_span(tool_name: str, **fields: Any) -> Iterator[Timer]:
    """Time a tool, log its outcome, and normalise upstream failures.

    Any :class:`SourceSystemError` raised inside becomes an
    :class:`UpstreamToolError`, which the tool layer renders as a structured
    MCP tool error. That is the single place where "the Alarm API returned
    503" turns into something a language model can reason about.
    """
    # Backstop. In the server, `trace_middleware` has already bound a trace
    # by the time any tool runs. This covers the other caller: a test or a
    # script that invokes a tool function directly, with no inbound message
    # and therefore no middleware.
    token = None
    if tracing.current().trace_id == "untraced":
        token = tracing.set_current(
            tracing.TraceContext(
                trace_id=f"trace-mcp-{uuid.uuid4().hex[:12]}",
                request_id=uuid.uuid4().hex,
                client_id="alarm-management-mcp",
            )
        )

    timer = Timer()
    logger.info("tool_started", tool=tool_name, trace_id=tracing.current_trace_id(), **fields)
    try:
        yield timer
    except SourceSystemError as exc:
        logger.warning(
            "tool_failed_upstream",
            tool=tool_name,
            system=exc.system,
            operation=exc.operation,
            error_code=exc.code,
            status_code=exc.status_code,
            retryable=exc.retryable,
            attempts=exc.attempts,
            duration_ms=timer.elapsed_ms,
            trace_id=tracing.current_trace_id(),
        )
        raise UpstreamToolError(exc) from exc
    except ToolInputError as exc:
        logger.info(
            "tool_failed_input",
            tool=tool_name,
            reason=str(exc),
            duration_ms=timer.elapsed_ms,
            trace_id=tracing.current_trace_id(),
        )
        raise
    else:
        logger.info(
            "tool_succeeded",
            tool=tool_name,
            duration_ms=timer.elapsed_ms,
            upstream_calls=timer.calls,
            trace_id=tracing.current_trace_id(),
        )
    finally:
        if token is not None:
            tracing.reset_current(token)


def require_one_of(**candidates: Any) -> None:
    """Guard a tool that needs at least one of several optional arguments."""
    if not any(v for v in candidates.values()):
        raise ToolInputError(
            "Provide at least one of: " + ", ".join(sorted(candidates)) + ".",
            details={"required_any_of": sorted(candidates)},
        )


def scope_body(asset_ids: list[str] | None, site: str | None, unit: str | None) -> dict[str, Any]:
    """The scope selector shared by the analytical Alarm API endpoints."""
    body: dict[str, Any] = {}
    if asset_ids:
        body["asset_ids"] = asset_ids
    if site:
        body["site"] = site
    if unit:
        body["unit"] = unit
    return body

"""Request middleware: trace binding, access logging and fault injection."""

from __future__ import annotations

import random
import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from alarm_api.config import get_settings
from connectors import tracing as trace

logger = structlog.get_logger(__name__)


class TraceMiddleware(BaseHTTPMiddleware):
    """Bind the inbound trace context and echo it on the way out.

    Also emits exactly one access log line per request, carrying the fields
    the submission guidelines ask for: request id, trace id, route, status
    and duration.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        context = trace.from_headers(request.headers)
        token = trace.set_current(context)
        structlog.contextvars.bind_contextvars(**context.as_log_fields())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "request_error",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
            )
            raise
        finally:
            structlog.contextvars.unbind_contextvars(
                "trace_id", "request_id", "client_id", "metadata_tag"
            )
            trace.reset_current(token)

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers.update(context.response_headers())
        response.headers["x-response-time-ms"] = f"{duration_ms:.2f}"
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
            **context.as_log_fields(),
        )
        return response


class FaultInjectionMiddleware(BaseHTTPMiddleware):
    """Optionally fail or delay a share of requests.

    Disabled unless ``ALARM_API_FAULT_RATE`` is set. Integration tests turn it
    on to prove that the MCP server's retry and timeout handling is real
    rather than merely configured.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        # Both knobs are independent. Gating the delay behind `fault_rate`
        # as well would make ALARM_API_FAULT_DELAY_SECONDS unreachable on
        # its own, which is exactly how you want to test a timeout: a slow
        # upstream that eventually answers, not one that fails outright.
        if request.url.path == "/health" or (
            settings.fault_rate <= 0 and settings.fault_delay_seconds <= 0
        ):
            return await call_next(request)

        if random.random() < settings.fault_rate:
            from connectors.http_errors import UpstreamUnavailableError, render_api_error

            logger.warning("fault_injected", path=request.url.path, kind="unavailable")
            # Returned, not raised. This middleware sits above the router, so
            # an exception from here would bypass the envelope handlers and
            # reach the caller as a bare 500 - which would exercise the wrong
            # path entirely, since the point of the injector is to produce
            # the *retryable* 503 the connector backs off on.
            return render_api_error(
                UpstreamUnavailableError(
                    "Injected fault: upstream temporarily unavailable.",
                    details={"retryable": True},
                )
            )

        if settings.fault_delay_seconds > 0:
            import asyncio

            await asyncio.sleep(settings.fault_delay_seconds)

        return await call_next(request)

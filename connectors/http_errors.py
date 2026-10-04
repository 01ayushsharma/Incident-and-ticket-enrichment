"""One error envelope, shared by every FastAPI service in the stack.

Both source-system simulators and the copilot backend render *every* non-2xx
response - including FastAPI's own validation failures and any unhandled
exception - as :class:`ErrorResponse`. That gives the MCP server exactly one
shape to map into MCP errors instead of three, and guarantees the trace id is
present on failures, which is when it matters most.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from connectors import tracing

logger = structlog.get_logger(__name__)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
    trace_id: str


# --------------------------------------------------------------------------
# Exception hierarchy
# --------------------------------------------------------------------------
class ApiError(Exception):
    """Base class for errors that map onto a documented status code."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class BadRequestError(ApiError):
    status_code = 400
    code = "bad_request"


class AuthenticationError(ApiError):
    status_code = 401
    code = "unauthenticated"


class ForbiddenError(ApiError):
    status_code = 403
    code = "forbidden"


class NotFoundError(ApiError):
    status_code = 404
    code = "not_found"


class ConflictError(ApiError):
    status_code = 409
    code = "conflict"


class ValidationError(ApiError):
    status_code = 422
    code = "validation_error"


class UpstreamUnavailableError(ApiError):
    """Signals a retryable failure. Used by the fault injector."""

    status_code = 503
    code = "service_unavailable"


# Status codes a client is entitled to retry. The MCP server reads this to
# decide between retrying and mapping straight to a tool error.
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})


def _render(status_code: int, code: str, message: str, details: dict[str, Any]) -> JSONResponse:
    context = tracing.current()
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details),
        trace_id=context.trace_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=context.response_headers(),
    )


def render_api_error(exc: ApiError) -> JSONResponse:
    """Render an :class:`ApiError` as the standard envelope, directly.

    For code that runs *outside* the routing layer. Starlette's exception
    handlers wrap the router, so an exception raised by middleware above it
    escapes to the server as a 500 with no envelope and no trace id. Any
    middleware that wants to fail a request returns this instead of raising.
    """
    return _render(exc.status_code, exc.code, exc.message, exc.details)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the handlers that normalise every failure onto one envelope."""

    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        # 5xx is a defect on our side; 4xx is the caller's. Log accordingly.
        log = logger.error if exc.status_code >= 500 else logger.info
        log(
            "request_failed",
            error_code=exc.code,
            status_code=exc.status_code,
            **tracing.current().as_log_fields(),
        )
        return _render(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Surface the field paths so an MCP client can correct its arguments
        # and retry, rather than being told only that "something was invalid".
        fields = [
            {
                "location": ".".join(str(p) for p in err.get("loc", ())),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        logger.info(
            "request_invalid",
            error_code="validation_error",
            field_count=len(fields),
            **tracing.current().as_log_fields(),
        )
        return _render(
            422, "validation_error", "Request failed schema validation.", {"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "unauthenticated",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
        }.get(exc.status_code, "http_error")
        return _render(exc.status_code, code, str(exc.detail), {})

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # The exception text may contain internals, so it is logged but never
        # returned. The trace id is the caller's handle for a support request.
        logger.exception(
            "unhandled_exception",
            error_type=type(exc).__name__,
            **tracing.current().as_log_fields(),
        )
        return _render(
            500,
            "internal_error",
            "An unexpected error occurred. Quote the trace_id when reporting it.",
            {},
        )

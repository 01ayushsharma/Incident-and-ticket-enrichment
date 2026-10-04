"""Base HTTP connector for the source systems behind the MCP server.

One place owns the cross-cutting concerns that the submission guidelines
call out for MCP engineering - authentication, timeouts, retries, trace
propagation, structured logging and error mapping - so that the per-system
clients stay thin and the behaviour cannot drift between them.

Retry policy in brief: retryable status codes and transport errors are
retried with exponential backoff plus full jitter, up to ``max_retries``.
Non-idempotent calls are not retried unless the caller says they are safe,
which for ticket creation means it carries an ``Idempotency-Key``.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx2
import structlog

from connectors import tracing
from connectors.http_errors import RETRYABLE_STATUS_CODES

logger = structlog.get_logger(__name__)

# Methods that are safe to replay without changing server state.
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


@dataclass
class SourceSystemError(Exception):
    """A normalised failure from a source system.

    Carries enough structure for the MCP layer to produce a useful tool
    error: whether retrying could help, what the upstream said, and the
    trace id to quote when reporting it.
    """

    message: str
    system: str
    operation: str
    status_code: int | None = None
    code: str = "upstream_error"
    retryable: bool = False
    attempts: int = 1
    trace_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message

    def as_tool_payload(self) -> dict[str, Any]:
        """The shape surfaced to an MCP client as structured error data."""
        return {
            "system": self.system,
            "operation": self.operation,
            "code": self.code,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "attempts": self.attempts,
            "trace_id": self.trace_id,
            "details": self.details,
        }


class SourceSystemClient:
    """Async HTTP client for one authenticated source system."""

    def __init__(
        self,
        *,
        system: str,
        base_url: str,
        token: str,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.25,
        backoff_max_seconds: float = 4.0,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self.system = system
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self._owns_client = client is None
        self._client = client or httpx2.AsyncClient(
            base_url=self.base_url,
            timeout=httpx2.Timeout(timeout_seconds),
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> SourceSystemClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # -- internals ----------------------------------------------------------
    def _headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Auth plus the outbound trace context.

        The token is attached here and nowhere else, and is never logged -
        see ``connectors.observability.scrub``.
        """
        context = tracing.current()
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            tracing.TRACE_HEADER: context.trace_id,
            tracing.REQUEST_ID_HEADER: context.request_id,
        }
        if context.client_id:
            headers[tracing.CLIENT_ID_HEADER] = context.client_id
        if context.metadata_tag:
            headers[tracing.METADATA_TAG_HEADER] = context.metadata_tag
        if extra:
            headers.update(extra)
        return headers

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter.

        Full jitter (rather than fixed backoff) keeps concurrent MCP tool
        calls from retrying in lockstep and re-hammering a struggling
        upstream at the same instant.
        """
        ceiling = min(self.backoff_max_seconds, self.backoff_base_seconds * (2**attempt))
        return random.uniform(0, ceiling)

    async def request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        retry_safe: bool | None = None,
        timeout_seconds: float | None = None,
        with_status: bool = False,
    ) -> Any:
        """Perform a request and return the decoded JSON body.

        With ``with_status=True`` returns ``(body, status_code)`` instead.
        The status matters where two success codes mean different things -
        ticket creation returns 201 for a new ticket and 200 for an
        idempotent replay, and the caller needs to tell those apart.

        Raises :class:`SourceSystemError` on any failure, having already
        applied the retry policy.
        """
        method = method.upper()
        if retry_safe is None:
            retry_safe = method in _IDEMPOTENT_METHODS
        attempts_allowed = (self.max_retries + 1) if retry_safe else 1
        timeout = httpx2.Timeout(timeout_seconds or self.timeout_seconds)
        trace_id = tracing.current_trace_id()

        last_error: SourceSystemError | None = None
        for attempt in range(attempts_allowed):
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=_clean_params(params),
                    json=json_body,
                    headers=self._headers(headers),
                    timeout=timeout,
                )
            except httpx2.TimeoutException as exc:
                last_error = SourceSystemError(
                    message=(
                        f"{self.system}.{operation} timed out after "
                        f"{timeout_seconds or self.timeout_seconds}s."
                    ),
                    system=self.system,
                    operation=operation,
                    code="timeout",
                    retryable=True,
                    attempts=attempt + 1,
                    trace_id=trace_id,
                    details={"error_type": type(exc).__name__},
                )
            except httpx2.HTTPError as exc:
                last_error = SourceSystemError(
                    message=f"{self.system}.{operation} could not reach {self.base_url}.",
                    system=self.system,
                    operation=operation,
                    code="connection_error",
                    retryable=True,
                    attempts=attempt + 1,
                    trace_id=trace_id,
                    details={"error_type": type(exc).__name__},
                )
            else:
                if response.status_code < 400:
                    logger.info(
                        "source_call_ok",
                        system=self.system,
                        operation=operation,
                        method=method,
                        path=path,
                        status_code=response.status_code,
                        attempt=attempt + 1,
                        trace_id=trace_id,
                    )
                    body = _decode(response, self.system, operation, trace_id)
                    return (body, response.status_code) if with_status else body

                last_error = _error_from_response(
                    response, self.system, operation, attempt + 1, trace_id
                )

            logger.warning(
                "source_call_failed",
                system=self.system,
                operation=operation,
                method=method,
                path=path,
                status_code=last_error.status_code,
                error_code=last_error.code,
                attempt=attempt + 1,
                attempts_allowed=attempts_allowed,
                retryable=last_error.retryable,
                trace_id=trace_id,
            )

            is_last = attempt == attempts_allowed - 1
            if is_last or not last_error.retryable:
                break
            await asyncio.sleep(self._backoff_delay(attempt))

        assert last_error is not None  # the loop always sets it before breaking
        last_error.attempts = min(last_error.attempts, attempts_allowed)
        raise last_error


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Drop ``None`` values so they do not become the literal string 'None'."""
    if not params:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            cleaned[key] = str(value).lower()
        else:
            cleaned[key] = value
    return cleaned or None


def _decode(response: httpx2.Response, system: str, operation: str, trace_id: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise SourceSystemError(
            message=f"{system}.{operation} returned a non-JSON response.",
            system=system,
            operation=operation,
            status_code=response.status_code,
            code="invalid_response",
            retryable=False,
            trace_id=trace_id,
            details={"content_type": response.headers.get("content-type", "")},
        ) from exc


def _error_from_response(
    response: httpx2.Response, system: str, operation: str, attempts: int, trace_id: str
) -> SourceSystemError:
    """Map an HTTP error onto the normalised error type.

    Source systems in this stack share one error envelope
    (``connectors.http_errors.ErrorResponse``), so the upstream code and
    message are lifted straight out of it when present.
    """
    status = response.status_code
    code = f"http_{status}"
    message = f"{system}.{operation} failed with HTTP {status}."
    details: dict[str, Any] = {}

    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        envelope = body["error"]
        code = str(envelope.get("code") or code)
        upstream_message = envelope.get("message")
        if upstream_message:
            message = f"{system}.{operation}: {upstream_message}"
        details = dict(envelope.get("details") or {})
        # Prefer the upstream's own trace id: it is the one in its logs.
        trace_id = body.get("trace_id") or trace_id

    return SourceSystemError(
        message=message,
        system=system,
        operation=operation,
        status_code=status,
        code=code,
        retryable=status in RETRYABLE_STATUS_CODES,
        attempts=attempts,
        trace_id=trace_id,
        details=details,
    )

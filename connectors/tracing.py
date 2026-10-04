"""Correlation and trace metadata propagation, shared by every service.

Every request carries a trace identifier from the edge down through the MCP
server to this simulator and back out again. The Postman collections send it
as a bare ``trace_id`` header, so that spelling is authoritative here; the
more conventional ``x-trace-id`` and W3C ``traceparent`` are accepted as
aliases because the MCP server and the copilot backend emit those.

The active context is held in :mod:`contextvars` so that log records and
error envelopes can pick it up without threading it through every signature.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from starlette.datastructures import Headers

TRACE_HEADER = "trace_id"
CLIENT_ID_HEADER = "x-client-id"
METADATA_TAG_HEADER = "x-metadata-tag"
REQUEST_ID_HEADER = "x-request-id"


@dataclass(frozen=True)
class TraceContext:
    """The trace metadata associated with one inbound request."""

    trace_id: str
    request_id: str
    client_id: str | None = None
    metadata_tag: str | None = None

    def response_headers(self) -> dict[str, str]:
        """Headers echoed back so a caller can stitch its own trace together."""
        headers = {TRACE_HEADER: self.trace_id, REQUEST_ID_HEADER: self.request_id}
        if self.client_id:
            headers[CLIENT_ID_HEADER] = self.client_id
        if self.metadata_tag:
            headers[METADATA_TAG_HEADER] = self.metadata_tag
        return headers

    def as_log_fields(self) -> dict[str, str]:
        fields = {"trace_id": self.trace_id, "request_id": self.request_id}
        if self.client_id:
            fields["client_id"] = self.client_id
        if self.metadata_tag:
            fields["metadata_tag"] = self.metadata_tag
        return fields


_EMPTY = TraceContext(trace_id="untraced", request_id="untraced")

_current: ContextVar[TraceContext] = ContextVar("request_trace", default=_EMPTY)


def _parse_traceparent(value: str) -> str | None:
    """Extract the trace-id field from a W3C ``traceparent`` header."""
    parts = value.split("-")
    if len(parts) >= 3 and len(parts[1]) == 32:
        return parts[1]
    return None


def from_headers(headers: Headers) -> TraceContext:
    """Build a trace context from inbound headers, generating what is absent."""
    trace_id = headers.get(TRACE_HEADER) or headers.get("x-trace-id")
    if not trace_id:
        traceparent = headers.get("traceparent")
        if traceparent:
            trace_id = _parse_traceparent(traceparent)
    if not trace_id:
        trace_id = f"trace-{uuid.uuid4().hex[:16]}"

    return TraceContext(
        trace_id=trace_id[:128],
        request_id=(headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex)[:128],
        client_id=(headers.get(CLIENT_ID_HEADER) or None),
        metadata_tag=(headers.get(METADATA_TAG_HEADER) or None),
    )


def set_current(context: TraceContext):
    """Bind ``context`` to the current task. Returns the contextvar token."""
    return _current.set(context)


def reset_current(token) -> None:
    _current.reset(token)


def current() -> TraceContext:
    return _current.get()


def current_trace_id() -> str:
    return _current.get().trace_id

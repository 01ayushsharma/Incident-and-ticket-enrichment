"""MCP client and tool registry.

This is the copilot's only route to the Alarm Management and ticketing
systems. There is deliberately no HTTP client for those systems anywhere in
``copilot`` - if this module is unavailable, the copilot has no source-system
access at all, which is the architectural property the assignment asks for.

Responsibilities:

* connect over stdio or streamable HTTP;
* discover tools and cache their schemas;
* validate arguments against the discovered schema *before* calling, so an
  obviously-bad call fails fast and locally;
* record every invocation as a :class:`ToolInvocation` for the GUI's
  execution trace and the audit record;
* distinguish the failure modes the assignment calls out - unavailable
  server, missing tool, invalid arguments, tool error - because the
  orchestrator responds differently to each.
"""

from __future__ import annotations

import json
import re
import time
from contextlib import AsyncExitStack
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

import anyio
import structlog
from pydantic import BaseModel, ConfigDict, Field

from connectors import tracing

logger = structlog.get_logger(__name__)

# The MCP server embeds a JSON diagnosis after this marker in tool errors.
_DIAGNOSIS = re.compile(r"\| diagnosis:\s*(\{.*\})\s*$", re.DOTALL)

# The execution trace is per-request, not per-client. One client instance is
# shared by every request the backend serves (it owns the MCP session), so
# the buffer of invocations lives in a contextvar: two concurrent /chat calls
# each get their own, instead of appending into - and resetting - each
# other's. Starlette runs each request in its own task, so the copy of the
# context is already the isolation boundary; tool calls made in child tasks
# within one request still share that request's list by reference.
_active_trace: ContextVar[list[ToolInvocation] | None] = ContextVar("mcp_invocations", default=None)


class McpUnavailableError(RuntimeError):
    """The MCP server could not be reached or the session failed to start."""


class ToolNotFoundError(KeyError):
    """The requested tool is not in the server's catalog."""


class ToolArgumentError(ValueError):
    """Arguments failed local validation against the discovered schema."""

    def __init__(self, message: str, *, tool: str, problems: list[str]) -> None:
        super().__init__(message)
        self.tool = tool
        self.problems = problems


class ToolDescriptor(BaseModel):
    """A discovered tool, as the GUI and the planner see it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    title: str = ""
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    read_only: bool = True
    destructive: bool = False

    @property
    def required_arguments(self) -> list[str]:
        return list(self.input_schema.get("required", []))

    @property
    def argument_names(self) -> list[str]:
        return list(self.input_schema.get("properties", {}))

    def summary(self) -> str:
        """One line for a planner prompt or a tool-discovery panel."""
        flag = "WRITE" if not self.read_only else "read"
        first_sentence = self.description.split(". ")[0].strip()
        return f"{self.name} ({flag}): {first_sentence}"


class ToolInvocation(BaseModel):
    """One tool call, start to finish. The unit of the MCP execution trace."""

    model_config = ConfigDict(extra="forbid")

    sequence: int
    tool: str
    arguments: dict[str, Any]
    status: Literal["ok", "tool_error", "invalid_arguments", "not_found", "transport_error"]
    duration_ms: float
    trace_id: str
    result: dict[str, Any] | None = None
    error_message: str | None = None
    error_diagnosis: dict[str, Any] | None = None
    upstream_calls: int = 0
    source_system: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == "ok"

    def redacted(self) -> dict[str, Any]:
        """Trace entry safe to render, without the full result payload."""
        return {
            "sequence": self.sequence,
            "tool": self.tool,
            "arguments": self.arguments,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "upstream_calls": self.upstream_calls,
            "source_system": self.source_system,
            "trace_id": self.trace_id,
            "error": self.error_message,
        }


@dataclass
class McpClientConfig:
    transport: Literal["http", "stdio"] = "http"
    url: str = "http://localhost:9000/mcp"
    command: str = "python"
    args: list[str] = field(default_factory=lambda: ["-m", "alarm_mcp"])
    env: dict[str, str] | None = None
    tool_timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 5.0


class McpToolClient:
    """A connected MCP session plus a validated tool registry."""

    def __init__(self, config: McpClientConfig) -> None:
        self.config = config
        self._stack: AsyncExitStack | None = None
        self._session: Any = None
        self._tools: dict[str, ToolDescriptor] = {}
        self.server_name: str = ""
        self.server_version: str = ""

    # ------------------------------------------------------------- lifecycle
    async def connect(self) -> None:
        """Open the session and discover tools."""
        from mcp import ClientSession

        if self.config.transport == "http":
            await self._preflight()

        stack = AsyncExitStack()
        try:
            if self.config.transport == "stdio":
                from mcp.client.stdio import StdioServerParameters, stdio_client

                params = StdioServerParameters(
                    command=self.config.command, args=self.config.args, env=self.config.env
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            else:
                from mcp.client.streamable_http import streamable_http_client

                read, write = await stack.enter_async_context(
                    streamable_http_client(self.config.url)
                )

            session = await stack.enter_async_context(ClientSession(read, write))
            init = await session.initialize()
        except Exception as exc:
            await _close_quietly(stack)
            raise McpUnavailableError(
                f"Could not connect to the MCP server over {self.config.transport} "
                f"({self.config.url if self.config.transport == 'http' else self.config.command}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        self._stack = stack
        self._session = session
        self.server_name = getattr(init.server_info, "name", "") or ""
        self.server_version = getattr(init.server_info, "version", "") or ""
        await self.discover_tools()
        logger.info(
            "mcp_connected",
            server=self.server_name,
            version=self.server_version,
            transport=self.config.transport,
            tools=len(self._tools),
        )

    async def _preflight(self) -> None:
        """Confirm something is listening before handing over to the SDK.

        Not belt-and-braces. When nothing is listening, the SDK's streamable
        HTTP transport cancels its own internal task group, and the failure
        arrives here as a `CancelledError` - a BaseException that no
        `except Exception` catches and that cannot be told apart from our
        caller cancelling us. The backend would then die at startup instead
        of starting degraded and saying so on /health. A plain TCP connect
        first turns the realistic "the MCP server is down" case into an
        ordinary error, before any of that machinery exists.
        """
        parsed = urlparse(self.config.url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with anyio.fail_after(self.config.connect_timeout_seconds):
                stream = await anyio.connect_tcp(host, port)
            await stream.aclose()
        except (OSError, TimeoutError) as exc:
            raise McpUnavailableError(
                f"Could not reach the MCP server at {self.config.url}: "
                f"nothing is listening on {host}:{port} "
                f"({type(exc).__name__})."
            ) from exc

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None

    async def __aenter__(self) -> McpToolClient:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # -------------------------------------------------------------- registry
    async def discover_tools(self) -> dict[str, ToolDescriptor]:
        """List tools and cache their schemas."""
        if self._session is None:
            raise McpUnavailableError("Not connected. Call connect() first.")

        listing = await self._session.list_tools()
        discovered: dict[str, ToolDescriptor] = {}
        for tool in listing.tools:
            annotations = tool.annotations
            discovered[tool.name] = ToolDescriptor(
                name=tool.name,
                title=getattr(tool, "title", "") or "",
                description=tool.description or "",
                input_schema=dict(tool.input_schema or {}),
                output_schema=dict(tool.output_schema) if tool.output_schema else None,
                read_only=bool(getattr(annotations, "read_only_hint", True))
                if annotations
                else True,
                destructive=bool(getattr(annotations, "destructive_hint", False))
                if annotations
                else False,
            )
        self._tools = discovered
        return discovered

    @property
    def tools(self) -> dict[str, ToolDescriptor]:
        return dict(self._tools)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def get_tool(self, name: str) -> ToolDescriptor:
        if name not in self._tools:
            raise ToolNotFoundError(name)
        return self._tools[name]

    def catalog_summary(self) -> list[str]:
        return [t.summary() for t in sorted(self._tools.values(), key=lambda t: t.name)]

    def write_tools(self) -> list[str]:
        return sorted(name for name, t in self._tools.items() if not t.read_only)

    # ------------------------------------------------------------ validation
    def validate_arguments(self, tool_name: str, arguments: dict[str, Any]) -> list[str]:
        """Check arguments against the discovered schema. Returns problems.

        Local validation is not a substitute for the server's - it is a
        latency and clarity optimisation. Catching a misspelled argument
        here costs microseconds and produces a message naming the valid
        arguments, instead of a round trip and a schema error.
        """
        descriptor = self.get_tool(tool_name)
        schema = descriptor.input_schema
        properties: dict[str, Any] = schema.get("properties", {})
        problems: list[str] = []

        for required in schema.get("required", []):
            if required not in arguments:
                problems.append(f"missing required argument '{required}'")

        for key, value in arguments.items():
            if key not in properties:
                close = _closest(key, list(properties))
                hint = f"; did you mean '{close}'?" if close else ""
                problems.append(f"unknown argument '{key}'{hint}")
                continue
            expected = properties[key].get("type")
            if expected and not _type_matches(value, expected):
                problems.append(
                    f"argument '{key}' should be {expected}, got {type(value).__name__}"
                )
        return problems

    # ---------------------------------------------------------------- invoke
    async def call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        validate: bool = True,
    ) -> ToolInvocation:
        """Invoke a tool and record the invocation.

        Never raises for an expected failure. Every outcome - missing tool,
        bad arguments, tool error, transport failure - comes back as a
        :class:`ToolInvocation` with a status, because the orchestrator
        needs to continue a multi-step chain past a single failed step
        rather than abandoning the whole request.
        """
        arguments = dict(arguments or {})
        trace = tracing.current()
        trace_id = trace.trace_id
        buffer = self.invocations
        sequence = len(buffer) + 1
        started = time.perf_counter()

        def record(**kwargs: Any) -> ToolInvocation:
            invocation = ToolInvocation(
                sequence=sequence,
                tool=tool_name,
                arguments=arguments,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                trace_id=trace_id,
                **kwargs,
            )
            buffer.append(invocation)
            logger.info(
                "mcp_tool_invoked",
                tool=tool_name,
                status=invocation.status,
                duration_ms=invocation.duration_ms,
                trace_id=trace_id,
            )
            return invocation

        if self._session is None:
            return record(
                status="transport_error",
                error_message="MCP session is not connected.",
            )

        if not self.has_tool(tool_name):
            available = ", ".join(sorted(self._tools)[:8])
            return record(
                status="not_found",
                error_message=(
                    f"Tool '{tool_name}' is not offered by this server. "
                    f"Available tools include: {available}."
                ),
            )

        if validate:
            problems = self.validate_arguments(tool_name, arguments)
            if problems:
                return record(
                    status="invalid_arguments",
                    error_message=f"Invalid arguments for '{tool_name}': " + "; ".join(problems),
                    error_diagnosis={"problems": problems},
                )

        try:
            result = await self._session.call_tool(
                tool_name,
                arguments,
                read_timeout_seconds=self.config.tool_timeout_seconds,
                # The trace travels in the request's `_meta`, not in a
                # header: the session is one long-lived connection shared by
                # every call, so a header fixed at connect time could not
                # identify the request. The MCP server reads these back in
                # `alarm_mcp.runtime.trace_middleware` and rebinds them, which
                # is what carries the id on into the source systems' logs.
                meta=_trace_meta(trace),
            )
        except Exception as exc:
            return record(
                status="transport_error",
                error_message=f"Transport failure calling '{tool_name}': "
                f"{type(exc).__name__}: {exc}",
            )

        if getattr(result, "is_error", False):
            message = _first_text(result) or f"Tool '{tool_name}' reported an error."
            return record(
                status="tool_error",
                error_message=message,
                error_diagnosis=_parse_diagnosis(message),
            )

        payload = result.structured_content or {}
        meta = payload.get("meta") or {}
        return record(
            status="ok",
            result=payload,
            upstream_calls=int(meta.get("upstream_calls") or 0),
            source_system=str(meta.get("source_system") or ""),
        )

    # ------------------------------------------------------------ trace view
    @property
    def invocations(self) -> list[ToolInvocation]:
        """This request's invocations, created on first use."""
        buffer = _active_trace.get()
        if buffer is None:
            buffer = []
            _active_trace.set(buffer)
        return buffer

    def trace(self) -> list[dict[str, Any]]:
        return [i.redacted() for i in self.invocations]

    def reset_trace(self) -> None:
        """Begin a fresh trace for the current request.

        Rebinds rather than clears: another request may be holding the old
        list, and truncating it under them is exactly the corruption this
        avoids.
        """
        _active_trace.set([])


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
async def _close_quietly(stack: AsyncExitStack) -> None:
    """Unwind ``stack``, shielded, swallowing a failed teardown.

    A transport that failed to start can leave its context managers in a
    state where unwinding raises in turn. That second failure says nothing
    useful; the first one is the diagnosis the caller needs.
    """
    with anyio.CancelScope(shield=True):
        try:
            await stack.aclose()
        except BaseException as exc:
            logger.debug("mcp_connect_cleanup_failed", error=type(exc).__name__)


def _trace_meta(trace: tracing.TraceContext) -> dict[str, str]:
    """The trace fields carried on an MCP request's ``_meta``.

    Spelled the same as the HTTP headers the source systems accept, so one
    id is greppable across all six processes without translation.
    """
    meta = {"trace_id": trace.trace_id, "request_id": trace.request_id}
    if trace.client_id:
        meta["client_id"] = trace.client_id
    if trace.metadata_tag:
        meta["metadata_tag"] = trace.metadata_tag
    return meta


_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def _type_matches(value: Any, expected: str) -> bool:
    if value is None:
        return True  # nullable fields are expressed as anyOf; leave to the server
    types = _JSON_TYPES.get(expected)
    if not types:
        return True
    if expected in {"integer", "number"} and isinstance(value, bool):
        return False  # bool is an int subclass; a flag is not a number
    return isinstance(value, types)


def _closest(name: str, candidates: list[str]) -> str | None:
    """Nearest argument name, for a 'did you mean' hint."""
    import difflib

    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _first_text(result: Any) -> str:
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            return str(text)
    return ""


def _parse_diagnosis(message: str) -> dict[str, Any] | None:
    """Pull the structured diagnosis the MCP server appends to tool errors."""
    match = _DIAGNOSIS.search(message)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

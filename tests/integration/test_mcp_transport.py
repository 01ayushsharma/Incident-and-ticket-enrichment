"""MCP over a real network transport.

Everything else in ``tests/`` drives the MCP session over in-memory streams,
which exercises the protocol but not the wire. These tests bind three real
sockets - the Alarm API, the ticketing API and the MCP server's streamable
HTTP app - and drive them with the production ``McpToolClient``.

The claim this file exists to back is trace propagation. A trace id set at
the copilot's edge has to survive two hops it does not control: a JSON-RPC
call over HTTP to the MCP server, and the MCP server's own HTTP calls to the
source systems. The ASGI recorder below reads the headers the Alarm API
actually received, so the assertion is on observed bytes rather than on a
value the copilot echoed back to itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from copilot.mcp_client import McpClientConfig, McpToolClient, McpUnavailableError

from connectors import tracing
from tests.servers import RequestRecorder, free_port, serve, temporary_env

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

ALARM_TOKEN = "transport-alarm-token"
TICKET_TOKEN = "transport-ticket-token"


@dataclass
class LiveStack:
    mcp: McpToolClient
    alarm_requests: RequestRecorder
    ticket_requests: RequestRecorder
    mcp_url: str


@asynccontextmanager
async def _live_stack() -> AsyncIterator[LiveStack]:
    """Three processes' worth of services, in one process, over real sockets."""
    from alarm_api.config import reset_settings as reset_alarm_settings
    from alarm_api.domain import store as alarm_store
    from alarm_api.main import create_app as create_alarm_app
    from alarm_mcp import server as server_module
    from alarm_mcp.config import McpSettings
    from ticketing_api.config import reset_settings as reset_ticket_settings
    from ticketing_api.main import create_app as create_ticket_app
    from ticketing_api.store import reset_store

    alarm_port, ticket_port, mcp_port = free_port(), free_port(), free_port()
    mcp_url = f"http://127.0.0.1:{mcp_port}/mcp"

    with temporary_env(ALARM_API_TOKEN=ALARM_TOKEN, TICKETING_API_TOKEN=TICKET_TOKEN):
        reset_alarm_settings()
        reset_ticket_settings()
        alarm_store.reset_dataset()
        reset_store()

        alarm_recorder = RequestRecorder(create_alarm_app())
        ticket_recorder = RequestRecorder(create_ticket_app())
        settings = McpSettings(
            alarm_api_base_url=f"http://127.0.0.1:{alarm_port}",
            alarm_api_token=ALARM_TOKEN,
            ticketing_api_url=f"http://127.0.0.1:{ticket_port}",
            ticketing_api_token=TICKET_TOKEN,
        )
        server_module.set_runtime(None)
        mcp_server = server_module.build_server(settings)

        try:
            async with (
                serve(alarm_recorder, alarm_port),
                serve(ticket_recorder, ticket_port),
                serve(mcp_server.streamable_http_app(streamable_http_path="/mcp"), mcp_port),
            ):
                client = McpToolClient(McpClientConfig(transport="http", url=mcp_url))
                await client.connect()
                try:
                    yield LiveStack(
                        mcp=client,
                        alarm_requests=alarm_recorder,
                        ticket_requests=ticket_recorder,
                        mcp_url=mcp_url,
                    )
                finally:
                    await client.aclose()
        finally:
            await server_module.runtime().aclose()
            server_module.set_runtime(None)
            reset_store()
            reset_alarm_settings()
            reset_ticket_settings()
            alarm_store.reset_dataset()


@pytest.fixture
async def live() -> AsyncIterator[LiveStack]:
    async with _live_stack() as stack:
        yield stack


# --------------------------------------------------------------------------
# The transport itself
# --------------------------------------------------------------------------
async def test_the_session_initialises_over_streamable_http(live: LiveStack):
    assert live.mcp.server_name == "alarm-management"
    assert live.mcp.server_version


async def test_discovery_works_over_the_wire(live: LiveStack):
    """Schemas survive JSON-RPC serialisation, not just in-memory passing."""
    tools = live.mcp.tools
    assert len(tools) >= 18
    assert "search_assets" in tools
    descriptor = tools["search_assets"]
    assert descriptor.input_schema.get("type") == "object"
    assert "query" in descriptor.argument_names


async def test_a_tool_call_round_trips_over_a_real_socket(live: LiveStack):
    call = await live.mcp.call("search_assets", {"query": "pump", "limit": 3})
    assert call.succeeded, call.error_message
    assert call.result["count"] >= 1
    assert call.source_system == "alarm-api"
    assert live.alarm_requests.requests, "the MCP server never reached the Alarm API"


async def test_a_tool_error_survives_the_transport_with_its_diagnosis(live: LiveStack):
    """An upstream 404 must arrive as a tool error, not a transport failure."""
    call = await live.mcp.call("get_alarm_detail", {"alarm_id": "ALM-does-not-exist"})
    assert call.status == "tool_error"
    assert call.error_diagnosis is not None
    assert call.error_diagnosis.get("kind") == "upstream"


async def test_an_unreachable_server_is_reported_as_unavailable():
    """The failure mode the backend reports at startup, over a dead port."""
    client = McpToolClient(
        McpClientConfig(transport="http", url=f"http://127.0.0.1:{free_port()}/mcp")
    )
    with pytest.raises(McpUnavailableError):
        await client.connect()


# --------------------------------------------------------------------------
# Trace propagation - the whole point of this file
# --------------------------------------------------------------------------
async def test_the_callers_trace_id_reaches_the_alarm_api(live: LiveStack):
    """One id, set at the copilot's edge, observed on the Alarm API's socket.

    This is the hop that JSON-RPC does not carry for you: the MCP session is
    one long-lived HTTP connection, so the id travels in the request's
    `_meta` and is rebound by the server's middleware before any tool runs.
    """
    token = tracing.set_current(
        tracing.TraceContext(
            trace_id="trace-transport-e2e",
            request_id="req-transport-e2e",
            client_id="pytest-copilot",
        )
    )
    try:
        live.alarm_requests.clear()
        call = await live.mcp.call("search_assets", {"query": "pump", "limit": 2})
    finally:
        tracing.reset_current(token)

    assert call.succeeded, call.error_message
    assert call.trace_id == "trace-transport-e2e"

    observed = live.alarm_requests.header_values(tracing.TRACE_HEADER)
    assert observed, "no non-health request reached the Alarm API"
    assert set(observed) == {"trace-transport-e2e"}, observed


async def test_the_client_id_travels_with_the_trace(live: LiveStack):
    token = tracing.set_current(
        tracing.TraceContext(
            trace_id="trace-client-id",
            request_id="req-client-id",
            client_id="incident-copilot-backend",
        )
    )
    try:
        live.alarm_requests.clear()
        await live.mcp.call("search_assets", {"query": "compressor", "limit": 1})
    finally:
        tracing.reset_current(token)

    clients = set(live.alarm_requests.header_values(tracing.CLIENT_ID_HEADER))
    assert clients == {"incident-copilot-backend"}


async def test_two_tool_calls_in_one_trace_share_the_id(live: LiveStack):
    """A multi-step plan is one trace, not one per tool."""
    token = tracing.set_current(
        tracing.TraceContext(trace_id="trace-multi-step", request_id="req-multi-step")
    )
    try:
        live.alarm_requests.clear()
        await live.mcp.call("search_assets", {"query": "pump", "limit": 1})
        await live.mcp.call("list_alarms", {"lookback_days": 30, "page_size": 5})
    finally:
        tracing.reset_current(token)

    assert set(live.alarm_requests.header_values(tracing.TRACE_HEADER)) == {"trace-multi-step"}


async def test_a_call_without_a_trace_still_gets_one(live: LiveStack):
    """An MCP client that sets no trace must not leave the hop untraced.

    The MCP Inspector and Claude Desktop both connect this way. The server
    mints an id prefixed `trace-mcp-` so a log reader can see the trace
    began at this hop rather than at the copilot.
    """
    live.alarm_requests.clear()
    call = await live.mcp.call("search_assets", {"query": "valve", "limit": 1})
    assert call.succeeded, call.error_message

    observed = live.alarm_requests.header_values(tracing.TRACE_HEADER)
    assert observed
    assert all(t.startswith("trace-mcp-") for t in observed), observed


async def test_the_trace_id_is_echoed_in_the_tool_result_meta(live: LiveStack):
    """The GUI's execution trace reads this; it has to be the caller's id."""
    token = tracing.set_current(
        tracing.TraceContext(trace_id="trace-meta-echo", request_id="req-meta-echo")
    )
    try:
        call = await live.mcp.call("check_source_systems", {})
    finally:
        tracing.reset_current(token)

    assert call.succeeded, call.error_message
    assert call.result["meta"]["trace_id"] == "trace-meta-echo"

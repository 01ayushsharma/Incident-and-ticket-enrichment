"""In-process test harness for the whole stack.

Wires the copilot to a real MCP session, a real MCP server, and both real
source systems - with no sockets. The source systems are mounted as ASGI
apps behind the connectors' HTTP clients, and the MCP session runs over
in-memory streams.

This matters for what the tests can claim. The MCP protocol is genuinely
exercised - initialise, list_tools, call_tool, structured content, error
results - rather than mocked away, so an integration test here fails if
the tool contracts break. What it does not cover is the network transport
itself; ``tests/integration/test_mcp_transport.py`` covers that over a
real port.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import anyio
import httpx2
from alarm_mcp.config import McpSettings
from alarm_mcp.runtime import Runtime
from copilot.config import CopilotSettings
from copilot.llm.base import LlmProvider
from copilot.llm.fake import FakeLlmProvider
from copilot.mcp_client import McpClientConfig, McpToolClient
from copilot.orchestration.workflow import IncidentWorkflow
from copilot.state import ConversationStore
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from rag.retrieval.service import RetrievalService


class InProcessMcpClient(McpToolClient):
    """An McpToolClient bound to an already-open session.

    Subclassing rather than mocking keeps every behaviour under test:
    validation, trace recording, error classification and the invocation
    log are all the production code paths.
    """

    def __init__(self, session: Any) -> None:
        super().__init__(McpClientConfig(transport="http", url="memory://mcp"))
        self._session = session

    async def aclose(self) -> None:  # the session is owned by the harness
        return None


@dataclass
class Harness:
    mcp: InProcessMcpClient
    workflow: IncidentWorkflow
    conversations: ConversationStore
    provider: LlmProvider
    retrieval: RetrievalService
    runtime: Runtime


@asynccontextmanager
async def build_harness(
    *,
    retrieval: RetrievalService,
    provider: LlmProvider | None = None,
    alarm_token: str = "demo-token",
    ticket_token: str = "demo-ticket-token",
    break_ticketing: bool = False,
    settings: CopilotSettings | None = None,
) -> AsyncIterator[Harness]:
    """Stand up the full stack in one process."""
    from alarm_api.main import create_app as create_alarm_app
    from alarm_mcp import server as server_module
    from ticketing_api.main import create_app as create_ticket_app
    from ticketing_api.store import reset_store

    from connectors.alarm_client import AlarmApiClient
    from connectors.ticketing_client import TicketingApiClient

    reset_store()
    mcp_settings = McpSettings()
    alarm_http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=create_alarm_app()), base_url="http://alarm"
    )
    ticket_http = (
        # An unroutable address: the connector sees a real transport error,
        # which is what a down source system actually looks like.
        httpx2.AsyncClient(base_url="http://127.0.0.1:9", timeout=httpx2.Timeout(0.4))
        if break_ticketing
        else httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=create_ticket_app()),
            base_url="http://tickets",
        )
    )
    runtime = Runtime(
        settings=mcp_settings,
        alarm=AlarmApiClient("http://alarm", alarm_token, client=alarm_http),
        tickets=TicketingApiClient("http://tickets", ticket_token, client=ticket_http),
    )
    server_module.set_runtime(runtime)
    server = server_module.build_server(mcp_settings)
    low = server._lowlevel_server

    # Nested rather than combined: the task group must be entered inside
    # the stream context, and anyio forbids reordering them.
    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):  # noqa: SIM117
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=False)
            )
            async with ClientSession(cr, cw) as session:
                init = await session.initialize()
                mcp = InProcessMcpClient(session)
                mcp.server_name = init.server_info.name
                mcp.server_version = init.server_info.version
                await mcp.discover_tools()

                resolved_settings = settings or CopilotSettings(llm_provider="fake")
                chosen_provider = provider or FakeLlmProvider()
                yield Harness(
                    mcp=mcp,
                    workflow=IncidentWorkflow(
                        mcp=mcp,
                        retrieval=retrieval,
                        provider=chosen_provider,
                        settings=resolved_settings,
                    ),
                    conversations=ConversationStore(),
                    provider=chosen_provider,
                    retrieval=retrieval,
                    runtime=runtime,
                )
            task_group.cancel_scope.cancel()

    await alarm_http.aclose()
    await ticket_http.aclose()
    server_module.set_runtime(None)
    reset_store()

"""Run the Alarm Management MCP server standalone.

    python -m alarm_mcp                  # streamable HTTP on :9000/mcp
    MCP_TRANSPORT=stdio python -m alarm_mcp

Running independently of the copilot is a deliberate property: the server can
be pointed at by any MCP client (including Claude Desktop or the MCP
Inspector) without the rest of this stack running.
"""

from __future__ import annotations

import anyio

from alarm_mcp.config import get_settings
from alarm_mcp.server import SERVER_NAME, build_server
from connectors.observability import configure_logging, get_logger

logger = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    configure_logging(f"mcp-{SERVER_NAME}")
    server = build_server(settings)

    transport = settings.mcp_transport.lower()
    if transport == "stdio":
        # stdout carries the JSON-RPC stream, so logs must not go there.
        logger.info("mcp_server_starting", transport="stdio")
        anyio.run(server.run_stdio_async)
        return

    logger.info(
        "mcp_server_starting",
        transport="streamable-http",
        host=settings.mcp_host,
        port=settings.mcp_port,
        path=settings.mcp_path,
        alarm_api=settings.alarm_api_base_url,
        ticketing_api=settings.ticketing_api_url,
    )
    anyio.run(
        lambda: server.run_streamable_http_async(
            host=settings.mcp_host,
            port=settings.mcp_port,
            streamable_http_path=settings.mcp_path,
        )
    )


if __name__ == "__main__":
    main()

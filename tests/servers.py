"""Run ASGI apps on real sockets, for the tests that need a real network.

Most of the suite drives the services in process over ``ASGITransport``,
which is faster and deterministic. Two things cannot be tested that way:

* the MCP streamable-HTTP transport, which needs a URL;
* client timeouts, because httpx enforces them around socket I/O and
  ``ASGITransport`` performs none - a slow ASGI app simply takes its time
  and no timeout ever fires.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import anyio
import uvicorn


@contextmanager
def temporary_env(**values: str) -> Iterator[None]:
    """Set environment variables for the block and put them back after.

    Several fixtures in ``tests/conftest.py`` configure tokens with
    ``os.environ.setdefault``, so a variable a test leaves behind is not
    merely untidy - it silently wins over the fixture, and the tests that
    run later fail somewhere unrelated with a 401.
    """
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def free_port() -> int:
    """A port that was free a moment ago.

    Racy in principle. In practice the window is microseconds and the
    alternative - binding with port 0 and reading the port back out of
    uvicorn - reaches into its internals.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@asynccontextmanager
async def serve(app: Any, port: int) -> AsyncIterator[str]:
    """Serve ``app`` on ``port`` for the life of the context. Yields its URL."""
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", lifespan="on", access_log=False
    )
    server = uvicorn.Server(config)
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(server.serve)
        with anyio.fail_after(20):
            while not server.started:
                await anyio.sleep(0.02)
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True


class RequestRecorder:
    """ASGI wrapper that records the path and headers of every HTTP request.

    Deliberately a test-only wrapper rather than a hook inside the services:
    the point is to observe the unmodified production app, and a recorder
    that shipped would be one more thing an assertion could be fooled by.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        self.requests: list[tuple[str, dict[str, str]]] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            self.requests.append((scope["path"], headers))
        await self.app(scope, receive, send)

    def clear(self) -> None:
        self.requests.clear()

    def paths(self, *, exclude: str = "/health") -> list[str]:
        return [path for path, _ in self.requests if path != exclude]

    def count(self, *, exclude: str = "/health") -> int:
        return len(self.paths(exclude=exclude))

    def header_values(self, name: str, *, exclude: str = "/health") -> list[str]:
        return [headers.get(name, "") for path, headers in self.requests if path != exclude]

"""Retry, backoff and timeout behaviour, exercised rather than configured.

``docs/mcp-tool-catalog.md`` and the README claim a retry policy and a
per-call timeout on the hop between the MCP server and the source systems.
Those are settings until something proves they fire, so these tests drive
the real code path and count what reaches the far end.

Two mechanisms do the driving:

* the simulator's ``FaultInjectionMiddleware`` (``ALARM_API_FAULT_RATE``,
  ``ALARM_API_FAULT_DELAY_SECONDS``), which ships in the production app;
* a counting ASGI wrapper, so the assertion is on requests the simulator
  actually received, not on a retry counter the client kept about itself.

The timeout tests bind a real port. ``ASGITransport`` performs no socket
I/O, so httpx has nothing to time out against and a slow app just takes its
time - testing timeouts in process would assert on nothing.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import httpx2
import pytest

from connectors.alarm_client import AlarmApiClient
from connectors.source_client import SourceSystemError
from connectors.ticketing_client import TicketingApiClient
from tests.servers import RequestRecorder, free_port, serve, temporary_env

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

TOKEN = "resilience-token"


@contextmanager
def _faulty_simulator(*, fault_rate: float = 0.0, delay: float = 0.0) -> Iterator[RequestRecorder]:
    """The real Alarm API with fault injection turned on."""
    from alarm_api.config import reset_settings
    from alarm_api.domain import store

    with temporary_env(
        ALARM_API_TOKEN=TOKEN,
        ALARM_API_FAULT_RATE=str(fault_rate),
        ALARM_API_FAULT_DELAY_SECONDS=str(delay),
    ):
        reset_settings()
        store.reset_dataset()
        try:
            from alarm_api.main import create_app

            yield RequestRecorder(create_app())
        finally:
            reset_settings()
            store.reset_dataset()


@asynccontextmanager
async def _in_process(app: Any, **kwargs: Any) -> AsyncIterator[AlarmApiClient]:
    """An Alarm API client wired to ``app`` without a socket."""
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://alarm")
    try:
        yield AlarmApiClient("http://alarm", TOKEN, client=http, **kwargs)
    finally:
        await http.aclose()


@asynccontextmanager
async def _over_a_socket(app: Any, **kwargs: Any) -> AsyncIterator[AlarmApiClient]:
    """An Alarm API client wired to ``app`` over a real port."""
    async with serve(app, free_port()) as url:
        client = AlarmApiClient(url, TOKEN, **kwargs)
        try:
            yield client
        finally:
            await client.aclose()


# --------------------------------------------------------------------------
# Retry
# --------------------------------------------------------------------------
async def test_a_retryable_failure_is_retried_up_to_the_configured_limit():
    """Every attempt reaches the simulator, so the retry is a real request
    rather than a loop over a cached failure."""
    with _faulty_simulator(fault_rate=1.0) as app:
        async with _in_process(app, max_retries=2) as client:
            with pytest.raises(SourceSystemError) as raised:
                await client.search_assets("pump")

    error = raised.value
    assert error.retryable is True
    assert error.status_code == 503
    assert error.attempts == 3, "1 initial attempt + 2 retries"
    assert app.count() == 3


async def test_a_non_retryable_failure_is_not_retried():
    """A 404 will not become a 200 on the third try; retrying it only adds
    latency to an answer the caller already has."""
    with _faulty_simulator() as app:
        async with _in_process(app, max_retries=3) as client:
            with pytest.raises(SourceSystemError) as raised:
                await client.get_alarm("ALM-nope")

    assert raised.value.retryable is False
    assert raised.value.attempts == 1
    assert app.count() == 1


async def test_retries_are_spaced_by_backoff_rather_than_fired_immediately():
    with _faulty_simulator(fault_rate=1.0) as app:
        http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://alarm")
        client = AlarmApiClient("http://alarm", TOKEN, client=http, max_retries=2)
        # Reach past the convenience wrapper: the backoff window is a
        # property of SourceSystemClient, and full jitter over the default
        # 0.25s ceiling makes a timing assertion meaningless.
        client._http.backoff_base_seconds = 0.2
        client._http.backoff_max_seconds = 0.2

        started = time.perf_counter()
        with pytest.raises(SourceSystemError):
            await client.search_assets("pump")
        elapsed = time.perf_counter() - started
        await http.aclose()

    assert app.count() == 3
    # Two sleeps, each uniform in [0, 0.2]; 0.2s expected in total. The
    # floor catches "never slept" without flaking on a fast machine.
    assert elapsed > 0.02, f"retries fired with no backoff ({elapsed:.4f}s)"


async def test_a_transient_failure_recovers_without_surfacing_to_the_caller():
    """The point of the retry: the first attempt fails and the caller never
    learns about it."""
    with _faulty_simulator() as app:
        calls = {"n": 0}
        inner = app.app

        async def flaky(scope: Any, receive: Any, send: Any) -> None:
            if scope["type"] == "http" and scope["path"] != "/health":
                calls["n"] += 1
                if calls["n"] == 1:
                    from connectors.http_errors import UpstreamUnavailableError, render_api_error

                    response = render_api_error(
                        UpstreamUnavailableError(
                            "Injected: first attempt fails.", details={"retryable": True}
                        )
                    )
                    await response(scope, receive, send)
                    return
            await inner(scope, receive, send)

        app.app = flaky
        async with _in_process(app, max_retries=2) as client:
            body = await client.search_assets("pump")

    assert body["count"] >= 1
    assert calls["n"] == 2, "the first attempt failed and the second succeeded"


# --------------------------------------------------------------------------
# Which writes may be replayed
# --------------------------------------------------------------------------
async def _broken_ticketing(**kwargs: Any) -> TicketingApiClient:
    """A ticketing client pointed at an unroutable address."""
    http = httpx2.AsyncClient(base_url="http://127.0.0.1:9", timeout=httpx2.Timeout(0.3))
    return TicketingApiClient("http://127.0.0.1:9", TOKEN, client=http, **kwargs)


async def test_a_comment_is_never_replayed_by_the_transport():
    """Comments are append-only with no idempotency key, so a blind retry
    would post the same note twice."""
    client = await _broken_ticketing(max_retries=3)
    try:
        with pytest.raises(SourceSystemError) as raised:
            await client.add_comment("TKT-1", "a note")
    finally:
        await client.aclose()

    assert raised.value.attempts == 1


async def test_a_ticket_creation_is_retried_because_it_carries_an_idempotency_key():
    """The exception that proves the rule. ``create_ticket`` is the one
    write marked retry-safe, and only because the key makes a replay return
    the original ticket instead of opening a second one."""
    client = await _broken_ticketing(max_retries=2)
    try:
        with pytest.raises(SourceSystemError) as raised:
            await client.create_ticket({"title": "t", "description": "d"}, idempotency_key="k-1")
    finally:
        await client.aclose()

    assert raised.value.attempts == 3, "1 initial attempt + 2 retries"


async def test_an_idempotent_replay_returns_the_original_ticket():
    """What makes the retry above safe, asserted against the real store."""
    from ticketing_api.config import reset_settings as reset_ticket_settings
    from ticketing_api.main import create_app
    from ticketing_api.store import reset_store

    payload = {
        "title": "Replay me",
        "description": "Only one ticket should exist.",
        "confirmed": True,
    }
    with temporary_env(TICKETING_API_TOKEN=TOKEN):
        reset_ticket_settings()
        reset_store()
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=create_app()), base_url="http://tickets"
        )
        client = TicketingApiClient("http://tickets", TOKEN, client=http)
        try:
            first, created_first = await client.create_ticket(payload, idempotency_key="replay-1")
            second, created_second = await client.create_ticket(payload, idempotency_key="replay-1")
        finally:
            await http.aclose()
            reset_store()
            reset_ticket_settings()

    assert created_first is True
    assert created_second is False, "a replayed key must not create a second ticket"
    assert first["key"] == second["key"]


# --------------------------------------------------------------------------
# Timeout - over a real socket, because that is the only place it can fire
# --------------------------------------------------------------------------
async def test_a_slow_upstream_times_out_rather_than_hanging():
    with _faulty_simulator(delay=1.5) as app:
        async with _over_a_socket(app, timeout_seconds=0.2, max_retries=0) as client:
            with pytest.raises(SourceSystemError) as raised:
                await client.search_assets("pump")

    error = raised.value
    assert error.code == "timeout"
    assert error.retryable is True
    assert "timed out" in error.message


async def test_a_timeout_is_retried_because_it_may_be_transient():
    with _faulty_simulator(delay=1.5) as app:
        async with _over_a_socket(app, timeout_seconds=0.2, max_retries=1) as client:
            with pytest.raises(SourceSystemError) as raised:
                await client.search_assets("pump")

    assert raised.value.code == "timeout"
    assert raised.value.attempts == 2
    assert app.count() == 2


async def test_a_call_inside_the_timeout_budget_succeeds():
    """The timeout is a budget, not a race the slow path always loses."""
    with _faulty_simulator(delay=0.05) as app:
        async with _over_a_socket(app, timeout_seconds=5.0, max_retries=0) as client:
            body = await client.search_assets("pump")

    assert body["count"] >= 1


# --------------------------------------------------------------------------
# How it reaches the model, through the MCP server
# --------------------------------------------------------------------------
async def test_an_exhausted_retry_reaches_the_tool_caller_as_a_diagnosable_error(
    indexed_retrieval,
):
    """The model has to be able to tell "try again" from "stop asking"."""
    from alarm_api.config import reset_settings

    from tests.harness import build_harness

    with temporary_env(ALARM_API_FAULT_RATE="1.0"):
        reset_settings()
        try:
            async with build_harness(retrieval=indexed_retrieval) as harness:
                call = await harness.mcp.call("search_assets", {"query": "pump"})
        finally:
            reset_settings()

    assert call.status == "tool_error"
    assert call.error_diagnosis is not None
    assert call.error_diagnosis["kind"] == "upstream"
    assert call.error_diagnosis["retryable"] is True
    assert call.error_diagnosis["attempts"] >= 2, "the MCP server retried before giving up"
    assert "retrying shortly may work" in (call.error_message or "")

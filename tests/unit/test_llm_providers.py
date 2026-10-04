"""Tests for the LLM provider adapters.

No test here hits a live endpoint — CI has no keys, and a test that needs
one is a test that does not run. Instead each adapter is pointed at a local
ASGI mock that returns the real provider's documented response shape, which
verifies the parts that actually break: the request body, the auth header,
the structured-output wiring and the error mapping.

What this does *not* prove is that the live service accepts the request.
That gap is recorded in docs/known-limitations.md.
"""

from __future__ import annotations

import pytest
from copilot.llm.base import LlmMessage, LlmUnavailableError, ProviderKind
from copilot.llm.fake import FakeLlmProvider
from copilot.llm.providers import build_provider
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx2 import ASGITransport, AsyncClient

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

PLAN_SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string"}},
    "required": ["intent"],
}


def _bind(provider, app: FastAPI, base_url: str, headers: dict | None = None):
    """Point an already-built provider at a local ASGI mock."""
    provider._client = AsyncClient(
        transport=ASGITransport(app=app), base_url=base_url, headers=headers or {}
    )
    return provider


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------
def test_the_default_provider_is_deterministic():
    provider = build_provider("")
    assert provider.kind == ProviderKind.FAKE


def test_an_unknown_provider_name_degrades_to_fake_rather_than_raising():
    provider = build_provider("sentient-oracle-9000")
    assert provider.kind == ProviderKind.FAKE


def test_a_hosted_provider_without_a_key_degrades_to_fake():
    """A misconfigured provider must not take the service down at startup."""
    for name in ("gemini", "anthropic", "openai"):
        assert build_provider(name, api_key="").kind == ProviderKind.FAKE


def test_each_provider_has_a_sensible_default_model():
    assert build_provider("openai", api_key="k").model == "gpt-4o-mini"
    assert build_provider("gemini", api_key="k").model == "gemini-2.0-flash"
    assert build_provider("ollama").model == "llama3.1:8b"


def test_describe_never_includes_the_key():
    described = build_provider("openai", api_key="sk-secret-value").describe()
    assert "sk-secret-value" not in str(described)


# --------------------------------------------------------------------------
# OpenAI-compatible adapter (also serves Groq, Together, Fireworks)
# --------------------------------------------------------------------------
@pytest.fixture
def openai_mock():
    """A mock of the OpenAI chat-completions endpoint."""
    seen: dict = {}
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def completions(request: Request):
        seen["body"] = await request.json()
        seen["auth"] = request.headers.get("authorization", "")
        return {
            "id": "chatcmpl-mock",
            "model": seen["body"]["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Grounded answer [1]."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 123, "completion_tokens": 45},
        }

    return app, seen


async def test_openai_adapter_sends_a_well_formed_request(openai_mock):
    app, seen = openai_mock
    provider = _bind(
        build_provider("openai", api_key="gsk_test", base_url="http://mock/v1"),
        app,
        "http://mock/v1",
        {"Authorization": "Bearer gsk_test"},
    )
    response = await provider.complete(
        [
            LlmMessage(role="system", content="You are a copilot."),
            LlmMessage(role="user", content="Summarise the alarm."),
        ],
        temperature=0.2,
    )
    await provider.aclose()

    assert seen["auth"].startswith("Bearer ")
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]
    assert seen["body"]["temperature"] == 0.2
    assert seen["body"]["max_tokens"] == 2048

    assert response.text == "Grounded answer [1]."
    assert response.usage.input_tokens == 123
    assert response.usage.output_tokens == 45
    assert response.finish_reason == "stop"
    assert response.duration_ms >= 0


async def test_openai_adapter_forwards_a_json_schema_for_planning(openai_mock):
    """The planner relies on structured output; this is that wiring."""
    app, seen = openai_mock
    provider = _bind(
        build_provider("openai", api_key="k", base_url="http://mock/v1"),
        app,
        "http://mock/v1",
    )
    await provider.complete(
        [LlmMessage(role="user", content="Plan this.")], json_schema=PLAN_SCHEMA
    )
    await provider.aclose()

    fmt = seen["body"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"] == PLAN_SCHEMA


async def test_a_groq_base_url_is_honoured():
    """Groq is served by this adapter with only a base-URL change."""
    provider = build_provider(
        "openai",
        api_key="gsk_x",
        base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
    )
    assert provider.kind == ProviderKind.OPENAI
    assert str(provider._client.base_url).rstrip("/") == "https://api.groq.com/openai/v1"
    await provider.aclose()


@pytest.mark.parametrize(
    "status,retryable",
    [(401, False), (400, False), (429, True), (500, True), (503, True)],
)
async def test_openai_adapter_maps_status_codes_to_retryability(status, retryable):
    """A bad key must not be retried; a rate limit must be."""
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def failing():
        return JSONResponse(status_code=status, content={"error": {"message": "nope"}})

    provider = _bind(
        build_provider("openai", api_key="k", base_url="http://mock/v1"),
        app,
        "http://mock/v1",
    )
    with pytest.raises(LlmUnavailableError) as caught:
        await provider.complete([LlmMessage(role="user", content="hi")])
    await provider.aclose()

    assert caught.value.retryable is retryable
    assert str(status) in str(caught.value)


async def test_openai_adapter_reads_retry_after_from_a_rate_limit():
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def limited():
        return JSONResponse(status_code=429, content={}, headers={"retry-after": "3"})

    provider = _bind(
        build_provider("openai", api_key="k", base_url="http://mock/v1"), app, "http://mock/v1"
    )
    with pytest.raises(LlmUnavailableError) as caught:
        await provider.complete([LlmMessage(role="user", content="hi")])
    await provider.aclose()
    assert caught.value.retry_after_seconds == 3.0


# --------------------------------------------------------------------------
# Retry wrapper
# --------------------------------------------------------------------------
class _FlakyProvider(FakeLlmProvider):
    """Fails ``failures`` times with the given error, then answers."""

    def __init__(self, failures: int, error: LlmUnavailableError) -> None:
        super().__init__()
        self.failures = failures
        self.error = error
        self.attempts = 0

    async def complete(self, messages, *, temperature=0.2, json_schema=None):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise self.error
        return await super().complete(messages, temperature=temperature, json_schema=json_schema)


def _retrying(inner, **kwargs):
    from copilot.llm.base import RetryingProvider

    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    return RetryingProvider(inner, sleep=record, **kwargs), waits


async def test_a_rate_limit_is_retried_until_the_call_succeeds():
    inner = _FlakyProvider(2, LlmUnavailableError("429", provider="openai", retryable=True))
    provider, waits = _retrying(inner, max_retries=2, base_delay_seconds=1.0)

    response = await provider.complete([LlmMessage(role="user", content="hi")])

    assert not response.is_empty
    assert inner.attempts == 3
    assert waits == [1.0, 2.0], "exponential backoff between attempts"


async def test_retry_after_is_honoured_but_capped():
    error = LlmUnavailableError("429", provider="openai", retry_after_seconds=60.0)
    provider, waits = _retrying(_FlakyProvider(1, error), max_delay_seconds=10.0)

    await provider.complete([LlmMessage(role="user", content="hi")])

    assert waits == [10.0]


async def test_a_non_retryable_error_is_raised_immediately():
    inner = _FlakyProvider(5, LlmUnavailableError("401", provider="openai", retryable=False))
    provider, waits = _retrying(inner, max_retries=3)

    with pytest.raises(LlmUnavailableError):
        await provider.complete([LlmMessage(role="user", content="hi")])

    assert inner.attempts == 1
    assert waits == []


async def test_retries_are_bounded():
    inner = _FlakyProvider(10, LlmUnavailableError("503", provider="openai"))
    provider, _ = _retrying(inner, max_retries=2)

    with pytest.raises(LlmUnavailableError):
        await provider.complete([LlmMessage(role="user", content="hi")])

    assert inner.attempts == 3
    assert provider.describe()["provider"] == "fake"


async def test_an_unreachable_endpoint_raises_llm_unavailable():
    provider = build_provider(
        "openai", api_key="k", base_url="http://127.0.0.1:9/v1", timeout_seconds=0.4
    )
    with pytest.raises(LlmUnavailableError):
        await provider.complete([LlmMessage(role="user", content="hi")])
    await provider.aclose()


# --------------------------------------------------------------------------
# Gemini adapter
# --------------------------------------------------------------------------
async def test_gemini_adapter_splits_system_from_turns_and_parses_the_response():
    """Gemini takes the system prompt separately, unlike the others."""
    seen: dict = {}
    app = FastAPI()

    @app.post("/models/{model}:generateContent")
    async def generate(model: str, request: Request):
        seen["body"] = await request.json()
        seen["key"] = request.headers.get("x-goog-api-key", "")
        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Gemini answer [1]."}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 77, "candidatesTokenCount": 22},
        }

    provider = _bind(
        build_provider("gemini", api_key="AIza-test", model="gemini-2.0-flash"),
        app,
        "http://mock",
    )
    response = await provider.complete(
        [
            LlmMessage(role="system", content="You are a copilot."),
            LlmMessage(role="user", content="Summarise."),
        ]
    )
    await provider.aclose()

    assert seen["key"] == "AIza-test"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "You are a copilot."
    assert len(seen["body"]["contents"]) == 1, "the system turn must not be a content"
    assert response.text == "Gemini answer [1]."
    assert response.usage.input_tokens == 77


async def test_gemini_schema_is_stripped_of_unsupported_keywords():
    """`responseSchema` rejects additionalProperties and friends."""
    seen: dict = {}
    app = FastAPI()

    @app.post("/models/{model}:generateContent")
    async def generate(model: str, request: Request):
        seen["body"] = await request.json()
        return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

    provider = _bind(build_provider("gemini", api_key="k"), app, "http://mock")
    await provider.complete(
        [LlmMessage(role="user", content="Plan.")],
        json_schema={
            "type": "object",
            "title": "Plan",
            "additionalProperties": False,
            "properties": {"intent": {"type": "string", "default": "x"}},
        },
    )
    await provider.aclose()

    schema = seen["body"]["generationConfig"]["responseSchema"]
    assert "additionalProperties" not in schema
    assert "title" not in schema
    assert "default" not in schema["properties"]["intent"]


# --------------------------------------------------------------------------
# Ollama adapter
# --------------------------------------------------------------------------
async def test_ollama_adapter_posts_to_the_chat_endpoint_and_parses_counts():
    seen: dict = {}
    app = FastAPI()

    @app.post("/api/chat")
    async def chat(request: Request):
        seen["body"] = await request.json()
        return {
            "message": {"role": "assistant", "content": "Local answer."},
            "prompt_eval_count": 50,
            "eval_count": 10,
        }

    provider = _bind(
        build_provider("ollama", model="llama3.1:8b", base_url="http://mock"),
        app,
        "http://mock",
    )
    response = await provider.complete(
        [LlmMessage(role="user", content="hi")], json_schema=PLAN_SCHEMA
    )
    await provider.aclose()

    assert seen["body"]["stream"] is False
    assert seen["body"]["format"] == PLAN_SCHEMA, "Ollama constrains output via `format`"
    assert response.text == "Local answer."
    assert response.usage.total == 60


# --------------------------------------------------------------------------
# The deterministic provider
# --------------------------------------------------------------------------
async def test_the_fake_provider_is_deterministic():
    provider = FakeLlmProvider()
    messages = [LlmMessage(role="user", content="Summarise alarms on Unit 2")]
    first = await provider.complete(messages)
    second = await provider.complete(messages)
    assert first.text == second.text


async def test_the_fake_provider_returns_schema_valid_plans():
    import json

    provider = FakeLlmProvider()
    response = await provider.complete(
        [LlmMessage(role="user", content="Prepare an incident for EastRefinery")],
        json_schema={
            "type": "object",
            "properties": {"intent": {}, "steps": {}},
            "required": ["intent", "steps"],
        },
    )
    plan = json.loads(response.text)
    assert plan["intent"] == "create_ticket"
    assert plan["steps"]
    assert all("tool" in step for step in plan["steps"])


async def test_the_fake_provider_only_cites_markers_it_was_given():
    """Citation integrity has to hold for the default provider too."""
    import re

    provider = FakeLlmProvider()
    response = await provider.complete(
        [LlmMessage(role="user", content="Evidence:\n[1] OP-114\n[2] SAF-020")]
    )
    used = set(re.findall(r"\[\d+\]", response.text))
    assert used <= {"[1]", "[2]"}


async def test_the_fake_provider_reports_a_health_probe():
    assert await FakeLlmProvider().health() is True

"""The LLM provider boundary.

The copilot depends on this interface and nothing else, which is what makes
the provider genuinely replaceable rather than nominally so. Three
consequences follow, and they are the point of the design:

* The whole system - including CI - runs with ``LLM_PROVIDER=fake``, so no
  test needs an API key and no evaluator needs one to run the stack.
* A provider outage degrades to the deterministic planner instead of
  failing the request (see ``copilot.orchestration.planner``).
* Swapping Gemini for Claude is a config change, not a code change.

The interface is deliberately narrow. The copilot asks the model for two
things only: a *plan* (structured) and a *narrative* (prose grounded in
evidence it was given). Everything else - ranking alarms, retrieving
documents, chaining tools - is deterministic code, because it is cheaper,
faster and testable.
"""

from __future__ import annotations

import abc
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class LlmUnavailableError(RuntimeError):
    """The provider could not be reached or refused the request.

    Callers are expected to degrade rather than propagate this: the
    orchestrator falls back to the rule-based planner and marks the
    response as degraded so the GUI can say so.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        retryable: bool = True,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class ProviderKind(StrEnum):
    FAKE = "fake"
    OLLAMA = "ollama"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


@dataclass
class LlmMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LlmUsage:
    """Token accounting, surfaced in the GUI trace and the audit record."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LlmResponse:
    text: str
    provider: str
    model: str
    usage: LlmUsage = field(default_factory=LlmUsage)
    duration_ms: float = 0.0
    degraded: bool = False
    finish_reason: str = "stop"

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class LlmProvider(abc.ABC):
    """A text-in, text-out model, optionally able to return JSON."""

    kind: ProviderKind

    def __init__(
        self, model: str, *, timeout_seconds: float = 60.0, max_output_tokens: int = 2048
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        """Generate a completion.

        ``json_schema`` asks the provider to constrain the output. Providers
        that cannot enforce it must still make a best effort and the caller
        must validate, because "the model returned JSON" is never a
        guarantee - see ``copilot.llm.parsing.extract_json``.
        """

    async def health(self) -> bool:
        """Cheap reachability probe. Never raises."""
        try:
            response = await self.complete(
                [LlmMessage(role="user", content="Reply with the single word: ok")],
                temperature=0.0,
            )
            return not response.is_empty
        except Exception:
            return False

    async def aclose(self) -> None:  # noqa: B027 - intentional no-op default
        """Release any transport resources.

        Concrete rather than abstract on purpose: a provider with no
        transport to close should not be forced to write an empty method.
        """

    def describe(self) -> dict[str, Any]:
        return {
            "provider": str(self.kind),
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "max_output_tokens": self.max_output_tokens,
        }


class RetryingProvider(LlmProvider):
    """Retry transient provider failures (429, 5xx, network) with backoff.

    Free-tier endpoints rate-limit per minute, and one request makes two
    calls (plan, then synthesis), so a single 429 is routine rather than an
    outage. Retrying here keeps that from degrading the answer. The wait
    honours ``Retry-After`` when the provider sends one, capped so a slow
    provider cannot hold a chat request open indefinitely; a non-retryable
    error (bad key, bad request) is raised at once.
    """

    def __init__(
        self,
        inner: LlmProvider,
        *,
        max_retries: int = 2,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 10.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(
            inner.model,
            timeout_seconds=inner.timeout_seconds,
            max_output_tokens=inner.max_output_tokens,
        )
        self.inner = inner
        self.kind = inner.kind
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self._sleep = sleep

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        attempt = 0
        while True:
            try:
                return await self.inner.complete(
                    messages, temperature=temperature, json_schema=json_schema
                )
            except LlmUnavailableError as exc:
                if not exc.retryable or attempt >= self.max_retries:
                    raise
                delay = exc.retry_after_seconds or self.base_delay_seconds * 2**attempt
                attempt += 1
                await self._sleep(min(delay, self.max_delay_seconds))

    async def aclose(self) -> None:
        await self.inner.aclose()

    def describe(self) -> dict[str, Any]:
        return {**self.inner.describe(), "max_retries": self.max_retries}

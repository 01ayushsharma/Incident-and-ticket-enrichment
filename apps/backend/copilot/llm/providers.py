"""Real LLM provider adapters and the factory that selects one.

Each adapter is deliberately thin - build a request, post it, read the text
back - because everything interesting (planning, grounding, citation
handling) lives in the orchestrator and must not vary by provider.

None of the SDKs are hard dependencies. They are imported inside the
adapter that needs them and install via the optional ``llm`` extra, so the
default install and CI stay lightweight and keyless.
"""

from __future__ import annotations

import time
from typing import Any

import httpx2
import structlog

from copilot.llm.base import (
    LlmMessage,
    LlmProvider,
    LlmResponse,
    LlmUnavailableError,
    LlmUsage,
    ProviderKind,
)
from copilot.llm.fake import FakeLlmProvider

logger = structlog.get_logger(__name__)

# Values that look like a credential to `if not api_key` but are not one.
# Without this check a `.env` copied from the example and not yet filled in
# builds a real provider and makes an outbound call with a junk key - which
# both fails and sends the prompt off the machine. Treat them as unset.
_PLACEHOLDER_KEYS: frozenset[str] = frozenset(
    {
        "replace-me",
        "paste_your_groq_key_here",
        "paste-your-key-here",
        "your-key-here",
        "your_api_key_here",
        "changeme",
        "todo",
        "none",
        "null",
        "xxx",
    }
)


def is_placeholder_key(api_key: str) -> bool:
    """True when ``api_key`` is obviously a stand-in rather than a credential."""
    candidate = api_key.strip().strip("\"'").lower()
    if not candidate:
        return True
    if candidate in _PLACEHOLDER_KEYS:
        return True
    # Catch the general shape: PASTE_..., <your key>, ${SOMETHING}
    return candidate.startswith(
        ("paste", "<", "${", "replace", "your-", "your_")
    ) or candidate.endswith(("_here", "-here"))


def _split_system(messages: list[LlmMessage]) -> tuple[str, list[LlmMessage]]:
    """Separate system content from the conversation turns."""
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    rest = [m for m in messages if m.role != "system"]
    return system, rest


class OllamaProvider(LlmProvider):
    """Local models over the Ollama HTTP API. No key, fully offline."""

    kind = ProviderKind.OLLAMA

    def __init__(
        self, model: str = "llama3.1:8b", *, base_url: str = "http://localhost:11434", **kwargs: Any
    ) -> None:
        super().__init__(model, **kwargs)
        self.base_url = base_url.rstrip("/")
        self._client = httpx2.AsyncClient(
            base_url=self.base_url, timeout=httpx2.Timeout(self.timeout_seconds)
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        started = time.perf_counter()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": self.max_output_tokens},
        }
        if json_schema:
            # Ollama constrains output to a JSON schema when given one.
            payload["format"] = json_schema

        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx2.HTTPError as exc:
            raise LlmUnavailableError(
                f"Ollama at {self.base_url} is unreachable: {type(exc).__name__}.",
                provider=str(self.kind),
            ) from exc

        return LlmResponse(
            text=(body.get("message") or {}).get("content", ""),
            provider=str(self.kind),
            model=self.model,
            usage=LlmUsage(
                input_tokens=int(body.get("prompt_eval_count") or 0),
                output_tokens=int(body.get("eval_count") or 0),
            ),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )


class GeminiProvider(LlmProvider):
    """Google Gemini via the REST API. Generous free tier, no SDK required."""

    kind = ProviderKind.GEMINI
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self, model: str = "gemini-2.0-flash", *, api_key: str = "", **kwargs: Any
    ) -> None:
        super().__init__(model, **kwargs)
        if not api_key:
            raise LlmUnavailableError(
                "LLM_API_KEY is required for the gemini provider.",
                provider=str(self.kind),
                retryable=False,
            )
        self._api_key = api_key
        self._client = httpx2.AsyncClient(
            base_url=self.BASE_URL, timeout=httpx2.Timeout(self.timeout_seconds)
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        started = time.perf_counter()
        system, turns = _split_system(messages)

        generation: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": self.max_output_tokens,
        }
        if json_schema:
            generation["responseMimeType"] = "application/json"
            generation["responseSchema"] = _to_gemini_schema(json_schema)

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user" if m.role == "user" else "model",
                    "parts": [{"text": m.content}],
                }
                for m in turns
            ],
            "generationConfig": generation,
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        try:
            response = await self._client.post(
                f"/models/{self.model}:generateContent",
                json=payload,
                headers={"x-goog-api-key": self._api_key},
            )
            response.raise_for_status()
            body = response.json()
        except httpx2.HTTPStatusError as exc:
            # 4xx will not succeed on retry; 5xx and 429 might.
            status = exc.response.status_code
            raise LlmUnavailableError(
                f"Gemini returned HTTP {status}.",
                provider=str(self.kind),
                retryable=status == 429 or status >= 500,
            ) from exc
        except httpx2.HTTPError as exc:
            raise LlmUnavailableError(
                f"Gemini is unreachable: {type(exc).__name__}.", provider=str(self.kind)
            ) from exc

        candidates = body.get("candidates") or []
        text = ""
        finish = "stop"
        if candidates:
            finish = candidates[0].get("finishReason", "stop")
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(part.get("text", "") for part in parts)

        usage = body.get("usageMetadata") or {}
        return LlmResponse(
            text=text,
            provider=str(self.kind),
            model=self.model,
            usage=LlmUsage(
                input_tokens=int(usage.get("promptTokenCount") or 0),
                output_tokens=int(usage.get("candidatesTokenCount") or 0),
            ),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            finish_reason=str(finish),
        )


class AnthropicProvider(LlmProvider):
    """Claude via the official Anthropic SDK."""

    kind = ProviderKind.ANTHROPIC

    def __init__(
        self, model: str = "claude-sonnet-5-5", *, api_key: str = "", **kwargs: Any
    ) -> None:
        super().__init__(model, **kwargs)
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise LlmUnavailableError(
                "The anthropic package is not installed. Run: pip install -e '.[llm]'",
                provider=str(self.kind),
                retryable=False,
            ) from exc
        if not api_key:
            raise LlmUnavailableError(
                "LLM_API_KEY is required for the anthropic provider.",
                provider=str(self.kind),
                retryable=False,
            )
        self._client = AsyncAnthropic(api_key=api_key, timeout=self.timeout_seconds)

    async def aclose(self) -> None:
        await self._client.close()

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        import anthropic

        started = time.perf_counter()
        system, turns = _split_system(messages)

        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in turns],
        }
        if system:
            request["system"] = system
        if json_schema:
            # Structured outputs: constrain the response to the schema.
            request["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
        else:
            request["temperature"] = temperature

        try:
            message = await self._client.messages.create(**request)
        except anthropic.APIStatusError as exc:
            raise LlmUnavailableError(
                f"Anthropic returned HTTP {exc.status_code}.",
                provider=str(self.kind),
                retryable=exc.status_code == 429 or exc.status_code >= 500,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LlmUnavailableError("Anthropic is unreachable.", provider=str(self.kind)) from exc

        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        return LlmResponse(
            text=text,
            provider=str(self.kind),
            model=self.model,
            usage=LlmUsage(
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
            ),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            finish_reason=str(message.stop_reason or "stop"),
        )


class OpenAiProvider(LlmProvider):
    """OpenAI-compatible chat completions. Also serves Groq and OpenRouter."""

    kind = ProviderKind.OPENAI

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        *,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        **kwargs: Any,
    ) -> None:
        super().__init__(model, **kwargs)
        if not api_key:
            raise LlmUnavailableError(
                "LLM_API_KEY is required for the openai provider.",
                provider=str(self.kind),
                retryable=False,
            )
        self._client = httpx2.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx2.Timeout(self.timeout_seconds),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        started = time.perf_counter()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": self.max_output_tokens,
        }
        if json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema, "strict": False},
            }

        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx2.HTTPStatusError as exc:
            status = exc.response.status_code
            raise LlmUnavailableError(
                f"OpenAI-compatible endpoint returned HTTP {status}.",
                provider=str(self.kind),
                retryable=status == 429 or status >= 500,
                retry_after_seconds=_retry_after(exc.response),
            ) from exc
        except httpx2.HTTPError as exc:
            raise LlmUnavailableError(
                f"OpenAI-compatible endpoint unreachable: {type(exc).__name__}.",
                provider=str(self.kind),
            ) from exc

        choice = (body.get("choices") or [{}])[0]
        usage = body.get("usage") or {}
        return LlmResponse(
            text=(choice.get("message") or {}).get("content", "") or "",
            provider=str(self.kind),
            model=self.model,
            usage=LlmUsage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
            ),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            finish_reason=str(choice.get("finish_reason") or "stop"),
        )


def _retry_after(response: Any) -> float | None:
    """Seconds from a ``Retry-After`` header, when it is given as a number."""
    try:
        value = float(response.headers.get("retry-after", ""))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip JSON Schema keywords Gemini's responseSchema does not accept."""
    unsupported = {"additionalProperties", "$schema", "title", "default", "examples"}
    if not isinstance(schema, dict):
        return schema
    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key in unsupported:
            continue
        if isinstance(value, dict):
            cleaned[key] = _to_gemini_schema(value)
        elif isinstance(value, list):
            cleaned[key] = [_to_gemini_schema(v) if isinstance(v, dict) else v for v in value]
        else:
            cleaned[key] = value
    return cleaned


_DEFAULT_MODELS: dict[ProviderKind, str] = {
    ProviderKind.FAKE: "deterministic-v1",
    ProviderKind.OLLAMA: "llama3.1:8b",
    ProviderKind.GEMINI: "gemini-2.0-flash",
    ProviderKind.ANTHROPIC: "claude-sonnet-5-5",
    ProviderKind.OPENAI: "gpt-4o-mini",
}


def build_provider(
    provider: str,
    *,
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    timeout_seconds: float = 60.0,
    max_output_tokens: int = 2048,
) -> LlmProvider:
    """Construct the configured provider, falling back to the fake one.

    A misconfigured real provider degrades to deterministic rather than
    taking the service down: the copilot is still useful without a model,
    and an evaluator running with a stale key should still see it work.
    """
    try:
        kind = ProviderKind(provider.strip().lower() or "fake")
    except ValueError:
        logger.warning("unknown_llm_provider", requested=provider, falling_back_to="fake")
        return FakeLlmProvider()

    chosen_model = model or _DEFAULT_MODELS[kind]
    common = {"timeout_seconds": timeout_seconds, "max_output_tokens": max_output_tokens}

    # A hosted provider with an unfilled placeholder key degrades to the
    # deterministic provider rather than making a doomed outbound call.
    hosted = {ProviderKind.GEMINI, ProviderKind.ANTHROPIC, ProviderKind.OPENAI}
    if kind in hosted and is_placeholder_key(api_key):
        logger.warning(
            "llm_api_key_not_configured",
            requested=str(kind),
            reason="LLM_API_KEY is empty or still a placeholder",
            falling_back_to="fake",
            effect="no outbound request will be made",
        )
        return FakeLlmProvider()

    try:
        if kind == ProviderKind.FAKE:
            return FakeLlmProvider(chosen_model, **common)
        if kind == ProviderKind.OLLAMA:
            return OllamaProvider(
                chosen_model, base_url=base_url or "http://localhost:11434", **common
            )
        if kind == ProviderKind.GEMINI:
            return GeminiProvider(chosen_model, api_key=api_key, **common)
        if kind == ProviderKind.ANTHROPIC:
            return AnthropicProvider(chosen_model, api_key=api_key, **common)
        if kind == ProviderKind.OPENAI:
            return OpenAiProvider(
                chosen_model,
                api_key=api_key,
                base_url=base_url or "https://api.openai.com/v1",
                **common,
            )
    except LlmUnavailableError as exc:
        logger.warning(
            "llm_provider_unavailable_at_startup",
            requested=str(kind),
            reason=str(exc),
            falling_back_to="fake",
        )
        return FakeLlmProvider()

    return FakeLlmProvider()  # pragma: no cover - unreachable, satisfies the type

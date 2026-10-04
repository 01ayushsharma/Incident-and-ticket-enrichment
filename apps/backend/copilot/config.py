"""Configuration for the copilot backend."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CopilotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- server ------------------------------------------------------------
    backend_host: str = "0.0.0.0"
    backend_port: int = 8080

    # --- MCP ---------------------------------------------------------------
    mcp_transport: str = "http"
    mcp_server_url: str = "http://localhost:9000/mcp"
    mcp_tool_timeout_seconds: float = 30.0

    # --- LLM ---------------------------------------------------------------
    llm_provider: str = "fake"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_timeout_seconds: float = 60.0
    llm_max_output_tokens: int = 2048
    # Retries for transient provider failures (429 / 5xx / network).
    llm_max_retries: int = 2
    # When the provider fails, fall back to the deterministic planner rather
    # than failing the request. The response is marked degraded either way.
    llm_degraded_fallback: bool = True

    # --- RAG ---------------------------------------------------------------
    rag_top_k: int = 5

    # --- conversation ------------------------------------------------------
    # Turns of history kept per conversation. Enough for follow-ups such as
    # "now raise a ticket for that" without unbounded growth.
    max_history_turns: int = 12
    max_conversations: int = 200


_settings: CopilotSettings | None = None


def get_settings() -> CopilotSettings:
    global _settings
    if _settings is None:
        _settings = CopilotSettings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None

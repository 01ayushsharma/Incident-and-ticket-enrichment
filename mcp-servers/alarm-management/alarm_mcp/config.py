"""Configuration for the Alarm Management MCP server.

Credentials arrive only through the environment. Nothing here has a value
that would work against a real system, and the tokens are never echoed in a
tool response, a log line or an error.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Alarm Management API ---------------------------------------------
    alarm_api_base_url: str = "http://localhost:8000"
    alarm_api_token: str = "demo-token"
    alarm_api_timeout_seconds: float = 10.0
    alarm_api_max_retries: int = 3

    # --- Ticketing API -----------------------------------------------------
    ticketing_api_url: str = "http://localhost:8100"
    ticketing_api_token: str = "demo-ticket-token"

    # --- Server ------------------------------------------------------------
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 9000
    mcp_transport: str = "http"
    mcp_path: str = "/mcp"

    # Caps that keep a tool result inside a sensible context budget.
    max_alarms_per_tool_call: int = 200
    max_rank_candidates: int = 50


_settings: McpSettings | None = None


def get_settings() -> McpSettings:
    global _settings
    if _settings is None:
        _settings = McpSettings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None

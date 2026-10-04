"""Configuration for the Alarm Management API simulator.

The simulator is deliberately deterministic: the synthetic dataset is derived
from ``ALARM_API_SEED`` and spans a *fixed* absolute window rather than a
window relative to wall-clock time. Two runs on different days therefore
produce byte-identical data, which is what makes the Postman collections and
the automated test suite reproducible.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic_settings import BaseSettings, SettingsConfigDict

# The dataset's fixed horizon. `DATA_NOW` is the simulator's notion of "now";
# anything after it does not exist. Chosen to cover both the Postman window
# (2026-05-01 .. 2026-07-01) and a trailing 90-day window for the acceptance
# scenario ("recurring high-severity alarms ... over the last 90 days").
DATA_START = datetime(2026, 4, 1, tzinfo=UTC)
DATA_NOW = datetime(2026, 9, 30, tzinfo=UTC)


class AlarmApiSettings(BaseSettings):
    """Environment-driven settings. No secrets have insecure defaults."""

    model_config = SettingsConfigDict(
        env_prefix="ALARM_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    token: str = "demo-token"
    seed: int = 20260501
    host: str = "0.0.0.0"
    port: int = 8000

    # Pagination guards - an unbounded page_size is a trivial DoS vector.
    default_page_size: int = 50
    max_page_size: int = 500

    # Deliberate fault injection, used to exercise the MCP server's retry and
    # timeout paths in integration tests. Disabled by default.
    fault_rate: float = 0.0
    fault_delay_seconds: float = 0.0


_settings: AlarmApiSettings | None = None


def get_settings() -> AlarmApiSettings:
    """Return the process-wide settings singleton."""
    global _settings
    if _settings is None:
        _settings = AlarmApiSettings()
    return _settings


def reset_settings() -> None:
    """Drop the cached settings. Used by tests that patch the environment."""
    global _settings
    _settings = None

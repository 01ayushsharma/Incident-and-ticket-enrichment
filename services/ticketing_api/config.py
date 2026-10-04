"""Configuration for the mock ticketing API."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class TicketingApiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TICKETING_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    token: str = "demo-ticket-token"
    host: str = "0.0.0.0"
    port: int = 8100

    # Historical corpus, produced by scripts/generate_ticket_seed.py.
    seed_file: str = str(REPO_ROOT / "test-data" / "seed_tickets.json")

    default_page_size: int = 25
    max_page_size: int = 200


_settings: TicketingApiSettings | None = None


def get_settings() -> TicketingApiSettings:
    global _settings
    if _settings is None:
        _settings = TicketingApiSettings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None

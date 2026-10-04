"""Typed connector for the mock ticketing API.

Note the asymmetry with :mod:`connectors.alarm_client`: the alarm system is
read-only, this one is not. Ticket creation is the single write in the whole
stack, so it is the only call that generates an ``Idempotency-Key`` and the
only one whose retry behaviour needed thinking about.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from typing import Any

import httpx2

from connectors.source_client import SourceSystemClient

SYSTEM = "ticketing-api"


def build_idempotency_key(*parts: str | None) -> str:
    """Derive a stable key from the things that identify one logical write.

    Deriving it from the conversation and alarm - rather than a fresh UUID -
    means that if the copilot is asked twice to raise a ticket for the same
    alarm in the same conversation, the second attempt returns the first
    ticket instead of opening a duplicate.
    """
    material = "|".join(p for p in parts if p)
    if not material:
        return uuid.uuid4().hex
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]


class TicketingApiClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._http = SourceSystemClient(
            system=SYSTEM,
            base_url=base_url,
            token=token,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            client=client,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def health(self) -> dict[str, Any]:
        return await self._http.request("GET", "/health", operation="health")

    # -- reads --------------------------------------------------------------
    async def list_tickets(
        self,
        *,
        status: Sequence[str] | None = None,
        priority: Sequence[str] | None = None,
        asset_id: str | None = None,
        asset_ids: Sequence[str] | None = None,
        site: str | None = None,
        unit: str | None = None,
        alarm_name: str | None = None,
        label: str | None = None,
        q: str | None = None,
        open_only: bool = False,
        page: int = 1,
        page_size: int = 25,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        return await self._http.request(
            "GET",
            "/tickets",
            operation="list_tickets",
            params={
                "status": list(status) if status else None,
                "priority": list(priority) if priority else None,
                "asset_id": asset_id,
                "asset_ids": list(asset_ids) if asset_ids else None,
                "site": site,
                "unit": unit,
                "alarm_name": alarm_name,
                "label": label,
                "q": q,
                "open_only": open_only,
                "page": page,
                "page_size": page_size,
                "sort_by": sort_by,
                "sort_order": sort_order,
            },
        )

    async def get_ticket(self, key: str) -> dict[str, Any]:
        return await self._http.request("GET", f"/tickets/{key}", operation="get_ticket")

    async def search_similar(self, body: dict[str, Any]) -> dict[str, Any]:
        # Read-only despite being a POST, so replaying it is safe.
        return await self._http.request(
            "POST",
            "/tickets/search",
            operation="search_similar",
            json_body=body,
            retry_safe=True,
        )

    async def fields(self) -> dict[str, Any]:
        return await self._http.request("GET", "/tickets/fields", operation="fields")

    # -- writes -------------------------------------------------------------
    async def create_ticket(
        self, payload: dict[str, Any], *, idempotency_key: str
    ) -> tuple[dict[str, Any], bool]:
        """Create a ticket. Returns ``(ticket, created)``.

        Marked ``retry_safe`` *because* of the idempotency key: without it a
        retry after a timeout could silently open a second ticket. The
        server returns the original ticket with 200 on a replayed key, and
        201 only for a genuinely new one - which is how ``created`` is
        determined rather than by guessing from timestamps.
        """
        body, status = await self._http.request(
            "POST",
            "/tickets",
            operation="create_ticket",
            json_body=payload,
            headers={"Idempotency-Key": idempotency_key},
            retry_safe=True,
            with_status=True,
        )
        return body, status == 201

    async def update_ticket(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._http.request(
            "PATCH",
            f"/tickets/{key}",
            operation="update_ticket",
            json_body=payload,
            retry_safe=False,
        )

    async def add_comment(
        self, key: str, body: str, author: str = "alarm-copilot"
    ) -> dict[str, Any]:
        # Comments are append-only with no idempotency key, so a blind retry
        # would post the note twice. Not retried.
        return await self._http.request(
            "POST",
            f"/tickets/{key}/comments",
            operation="add_comment",
            json_body={"body": body, "author": author},
            retry_safe=False,
        )

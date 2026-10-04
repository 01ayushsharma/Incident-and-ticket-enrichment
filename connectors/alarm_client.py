"""Typed connector for the Alarm Management API.

One method per endpoint in the Postman contract. Deliberately thin: it owns
URL shapes and parameter names, while retries, timeouts, auth and tracing
live in :class:`connectors.source_client.SourceSystemClient`.

The analytical endpoints are POSTs but are *read-only*, so they are marked
``retry_safe`` - a replayed summary or correlation cannot change state.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx2

from connectors.source_client import SourceSystemClient

SYSTEM = "alarm-api"


class AlarmApiClient:
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

    # -- health -------------------------------------------------------------
    async def health(self) -> dict[str, Any]:
        return await self._http.request("GET", "/health", operation="health")

    # -- assets -------------------------------------------------------------
    async def search_assets(
        self,
        query: str,
        *,
        site: str | None = None,
        unit: str | None = None,
        asset_type: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        return await self._http.request(
            "GET",
            "/assets/search",
            operation="search_assets",
            params={
                "query": query,
                "site": site,
                "unit": unit,
                "asset_type": asset_type,
                "limit": limit,
            },
        )

    async def asset_metadata(self, asset_id: str) -> dict[str, Any]:
        return await self._http.request(
            "GET", f"/assets/{asset_id}/metadata", operation="asset_metadata"
        )

    # -- alarms -------------------------------------------------------------
    async def list_alarms(
        self,
        *,
        asset_id: str | None = None,
        site: str | None = None,
        unit: str | None = None,
        status: Sequence[str] | None = None,
        severity: Sequence[str] | None = None,
        alarm_type: Sequence[str] | None = None,
        alarm_name: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "start_time",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        return await self._http.request(
            "GET",
            "/alarms",
            operation="list_alarms",
            params={
                "asset_id": asset_id,
                "site": site,
                "unit": unit,
                "status": list(status) if status else None,
                "severity": list(severity) if severity else None,
                "alarm_type": list(alarm_type) if alarm_type else None,
                "alarm_name": alarm_name,
                "start_time": start_time,
                "end_time": end_time,
                "page": page,
                "page_size": page_size,
                "sort_by": sort_by,
                "sort_order": sort_order,
            },
        )

    async def get_alarm(self, alarm_id: str) -> dict[str, Any]:
        return await self._http.request("GET", f"/alarms/{alarm_id}", operation="get_alarm")

    async def iter_all_alarms(
        self, *, page_size: int = 200, max_pages: int = 25, **filters: Any
    ) -> list[dict[str, Any]]:
        """Walk every page of a filtered alarm query.

        ``max_pages`` is a deliberate guard: an MCP tool that accidentally
        pulls the whole plant history would blow the model's context window
        and the request timeout together.
        """
        collected: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            body = await self.list_alarms(page=page, page_size=page_size, **filters)
            collected.extend(body.get("data", []))
            pagination = body.get("pagination", {})
            if not pagination.get("has_next"):
                break
        return collected

    # -- analytics (read-only POSTs) ----------------------------------------
    async def _analytic(self, path: str, operation: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._http.request(
            "POST", path, operation=operation, json_body=body, retry_safe=True
        )

    async def alarm_summary(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._analytic("/alarms/summary", "alarm_summary", body)

    async def alarm_trends(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._analytic("/alarms/trends", "alarm_trends", body)

    async def correlation(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._analytic("/alarms/correlation", "correlation", body)

    async def flood_analysis(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._analytic("/alarms/flood-analysis", "flood_analysis", body)

    async def rationalization_candidates(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._analytic(
            "/alarms/rationalization-candidates", "rationalization_candidates", body
        )

    async def priority_score(self, alarm_id: str) -> dict[str, Any]:
        return await self._analytic(
            "/alarms/priority-score", "priority_score", {"alarm_id": alarm_id}
        )

    async def operator_recommendations(
        self,
        alarm_id: str,
        *,
        include_related: bool = False,
        include_asset_context: bool = False,
        include_historical_pattern: bool = False,
    ) -> dict[str, Any]:
        return await self._analytic(
            "/recommendations/operator-actions",
            "operator_recommendations",
            {
                "alarm_id": alarm_id,
                "include_related": include_related,
                "include_asset_context": include_asset_context,
                "include_historical_pattern": include_historical_pattern,
            },
        )

    # -- calculations -------------------------------------------------------
    async def generate_calculation(
        self, calculation_type: str, filters: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._analytic(
            "/calculation-code/generate",
            "generate_calculation",
            {"calculation_type": calculation_type, "filters": filters},
        )

    async def execute_calculation(
        self, calculation_id: str, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"calculation_id": calculation_id}
        if filters is not None:
            body["filters"] = filters
        return await self._analytic("/calculation-code/execute", "execute_calculation", body)

    async def compute_kpi(self, calculation_type: str, filters: dict[str, Any]) -> dict[str, Any]:
        """Generate then execute, as a single logical operation.

        The simulator holds generated calculations in memory only, so the
        two calls must be adjacent; pairing them here means an MCP client
        cannot be handed a calculation id that has already been lost.
        """
        generated = await self.generate_calculation(calculation_type, filters)
        executed = await self.execute_calculation(generated["calculation_id"], filters)
        return {"generated": generated, "executed": executed}

    async def kpi_definitions(self) -> dict[str, Any]:
        return await self._http.request(
            "GET", "/analytics/kpi-definitions", operation="kpi_definitions"
        )

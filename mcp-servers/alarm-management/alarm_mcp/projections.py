"""Projections from source-system payloads onto the MCP tool contracts.

Kept apart from the tool definitions so that ``server.py`` reads as a tool
catalog rather than a pile of dictionary shuffling, and so these mappings
can be unit-tested against recorded payloads without a running server.

A projection failure is a *contract* failure: it means the source system no
longer returns what the tool promises. Pydantic raises, and the tool layer
turns that into an explicit tool error rather than passing bad data on.
"""

from __future__ import annotations

from typing import Any

from alarm_mcp.models import (
    AlarmRecord,
    AssetDetail,
    AssetSummary,
    CorrelatedAsset,
    CorrelationPair,
    FloodWindow,
    HistoricalPattern,
    KpiDefinition,
    LikelyCause,
    PriorityFactor,
    RationalizationCandidate,
    RecommendedAction,
    SimilarTicket,
    SummaryGroup,
    TicketRecord,
    TrendPoint,
)


def _pick(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Select ``keys`` that are present, so optional fields stay optional."""
    return {k: source[k] for k in keys if k in source}


def asset_summary(raw: dict[str, Any]) -> AssetSummary:
    return AssetSummary(
        **_pick(raw, "asset_id", "asset_name", "asset_type", "site", "unit", "criticality", "tag")
    )


def asset_detail(raw: dict[str, Any]) -> AssetDetail:
    return AssetDetail(
        **_pick(
            raw,
            "asset_id",
            "asset_name",
            "asset_type",
            "site",
            "unit",
            "criticality",
            "tag",
            "manufacturer",
            "model_number",
            "serial_number",
            "installation_date",
            "last_maintenance_date",
            "next_maintenance_due",
            "operating_hours",
            "related_asset_ids",
            "design_limits",
            "alarm_count_total",
            "alarm_count_active",
        )
    )


def alarm_record(raw: dict[str, Any]) -> AlarmRecord:
    return AlarmRecord(
        **_pick(
            raw,
            "alarm_id",
            "asset_id",
            "asset_name",
            "site",
            "unit",
            "alarm_name",
            "alarm_type",
            "severity",
            "status",
            "start_time",
            "ack_delay_seconds",
            "duration_seconds",
            "description",
        )
    )


def alarm_records(rows: list[dict[str, Any]]) -> list[AlarmRecord]:
    return [alarm_record(row) for row in rows]


def summary_groups(rows: list[dict[str, Any]]) -> list[SummaryGroup]:
    return [SummaryGroup(key=row["key"], metrics=row["metrics"]) for row in rows]


def trend_points(rows: list[dict[str, Any]]) -> list[TrendPoint]:
    return [TrendPoint(bucket_start=row["bucket_start"], values=row["values"]) for row in rows]


def correlation_pairs(rows: list[dict[str, Any]]) -> list[CorrelationPair]:
    return [
        CorrelationPair(
            **_pick(
                row,
                "alarm_name_a",
                "alarm_name_b",
                "asset_name_a",
                "asset_name_b",
                "asset_id_a",
                "asset_id_b",
                "support",
                "confidence",
                "correlation_score",
                "median_lag_seconds",
            )
        )
        for row in rows
    ]


def correlated_assets(rows: list[dict[str, Any]]) -> list[CorrelatedAsset]:
    return [
        CorrelatedAsset(
            **_pick(
                row, "asset_id", "asset_name", "site", "unit", "correlation_score", "shared_events"
            )
        )
        for row in rows
    ]


def flood_windows(rows: list[dict[str, Any]]) -> list[FloodWindow]:
    return [
        FloodWindow(
            **_pick(
                row,
                "start",
                "end",
                "alarm_count",
                "peak_rate_per_minute",
                "dominant_alarm_name",
                "asset_ids",
            )
        )
        for row in rows
    ]


def rationalization_candidates(rows: list[dict[str, Any]]) -> list[RationalizationCandidate]:
    return [
        RationalizationCandidate(
            **_pick(
                row,
                "asset_id",
                "asset_name",
                "alarm_name",
                "occurrences",
                "reason",
                "median_duration_seconds",
                "suppression_candidate",
                "recommendation",
            )
        )
        for row in rows
    ]


def priority_factors(rows: list[dict[str, Any]]) -> list[PriorityFactor]:
    return [
        PriorityFactor(**_pick(row, "name", "weight", "value", "contribution", "explanation"))
        for row in rows
    ]


def recommended_actions(rows: list[dict[str, Any]]) -> list[RecommendedAction]:
    return [
        RecommendedAction(
            **_pick(row, "rank", "action", "rationale", "expected_outcome", "estimated_minutes")
        )
        for row in rows
    ]


def likely_causes(rows: list[dict[str, Any]]) -> list[LikelyCause]:
    return [LikelyCause(**_pick(row, "cause", "confidence", "evidence")) for row in rows]


def historical_pattern(raw: dict[str, Any] | None) -> HistoricalPattern | None:
    if not raw:
        return None
    return HistoricalPattern(
        **_pick(
            raw,
            "occurrences_last_90_days",
            "median_duration_seconds",
            "recurrence_interval_hours",
            "most_common_hour_utc",
            "trend",
        )
    )


def kpi_definitions(rows: list[dict[str, Any]]) -> list[KpiDefinition]:
    return [
        KpiDefinition(**_pick(row, "name", "display_name", "description", "unit", "formula"))
        for row in rows
    ]


def ticket_record(raw: dict[str, Any]) -> TicketRecord:
    return TicketRecord(
        **_pick(
            raw,
            "key",
            "title",
            "status",
            "priority",
            "asset_id",
            "asset_name",
            "site",
            "unit",
            "alarm_name",
            "assignee",
            "created_at",
            "resolved_at",
            "root_cause",
            "resolution",
            "time_to_resolve_hours",
        )
    )


def ticket_records(rows: list[dict[str, Any]]) -> list[TicketRecord]:
    return [ticket_record(row) for row in rows]


def similar_tickets(rows: list[dict[str, Any]]) -> list[SimilarTicket]:
    return [
        SimilarTicket(
            ticket=ticket_record(row["ticket"]),
            score=row["score"],
            matched_on=row["matched_on"],
        )
        for row in rows
    ]

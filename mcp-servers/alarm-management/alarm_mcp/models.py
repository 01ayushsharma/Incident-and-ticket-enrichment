"""Typed output contracts for the MCP tools.

These are deliberately *not* the source systems' own response models. The
MCP server projects each upstream payload onto a model defined here, which
buys three things:

1. **Output validation.** If the Alarm API changes a field, the projection
   fails loudly in the MCP server instead of silently handing a malformed
   object to the language model.
2. **Context economy.** An alarm record has eighteen fields upstream; the
   copilot needs about ten. Everything sent to a model costs tokens, and
   trimming here is the cheapest place to do it.
3. **A stable tool contract.** ``docs/mcp-tool-catalog.md`` documents these
   shapes, and they can stay stable across changes to the source system.

Every tool result carries :class:`ToolMeta`, which is what the GUI renders
as the MCP execution trace.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolMeta(BaseModel):
    """Provenance for one tool invocation, surfaced in the GUI trace."""

    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(description="Which source system served the data.")
    operation: str = Field(description="The upstream operation that was invoked.")
    trace_id: str = Field(description="Correlation id shared with the source system's logs.")
    duration_ms: float = Field(description="Wall-clock time for the upstream call(s).")
    upstream_calls: int = Field(default=1, description="Number of HTTP calls made.")
    truncated: bool = Field(
        default=False,
        description="True when the result was capped to protect the context window.",
    )


class _Result(BaseModel):
    """Base for every tool result."""

    model_config = ConfigDict(extra="forbid")

    meta: ToolMeta


# --------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------
class AssetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    asset_name: str
    asset_type: str
    site: str
    unit: str
    criticality: str
    tag: str


class AssetSearchResult(_Result):
    query: str
    count: int
    assets: list[AssetSummary]


class AssetDetail(AssetSummary):
    manufacturer: str
    model_number: str
    serial_number: str
    installation_date: str
    last_maintenance_date: str
    next_maintenance_due: str
    operating_hours: int
    related_asset_ids: list[str]
    design_limits: dict[str, float]
    alarm_count_total: int
    alarm_count_active: int


class AssetMetadataResult(_Result):
    asset: AssetDetail


# --------------------------------------------------------------------------
# Alarms
# --------------------------------------------------------------------------
class AlarmRecord(BaseModel):
    """A compact alarm. Trimmed from the upstream record for context economy."""

    model_config = ConfigDict(extra="forbid")

    alarm_id: str
    asset_id: str
    asset_name: str
    site: str
    unit: str
    alarm_name: str
    alarm_type: str
    severity: str
    status: str
    start_time: str
    ack_delay_seconds: int | None = None
    duration_seconds: int | None = None
    description: str


class AlarmListResult(_Result):
    alarms: list[AlarmRecord]
    total_items: int
    page: int
    page_size: int
    has_next: bool


class AlarmDetailResult(_Result):
    alarm: AlarmRecord
    asset: AssetSummary
    related_alarm_ids: list[str]
    occurrences_last_90_days: int
    measured_value: float | None = None
    limit_value: float | None = None
    unit_of_measure: str | None = None


# --------------------------------------------------------------------------
# Summary and trends
# --------------------------------------------------------------------------
class SummaryGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: dict[str, str]
    metrics: dict[str, float]


class AlarmSummaryResult(_Result):
    total_alarms: int
    group_by: list[str]
    kpis: list[str]
    groups: list[SummaryGroup]


class TrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket_start: str
    values: dict[str, float]


class AlarmTrendsResult(_Result):
    bucket: str
    metrics: list[str]
    series: list[TrendPoint]
    non_empty_buckets: int


# --------------------------------------------------------------------------
# Correlation
# --------------------------------------------------------------------------
class CorrelationPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alarm_name_a: str
    alarm_name_b: str
    asset_name_a: str
    asset_name_b: str
    asset_id_a: str
    asset_id_b: str
    support: int
    confidence: float
    correlation_score: float
    median_lag_seconds: float


class CorrelatedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    asset_name: str
    site: str
    unit: str
    correlation_score: float
    shared_events: int


class CorrelationResult(_Result):
    method: str
    lag_window_minutes: int
    pairs: list[CorrelationPair]
    correlated_assets: list[CorrelatedAsset]


# --------------------------------------------------------------------------
# Flood and rationalization
# --------------------------------------------------------------------------
class FloodWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str
    end: str
    alarm_count: int
    peak_rate_per_minute: float
    dominant_alarm_name: str
    asset_ids: list[str]


class FloodAnalysisResult(_Result):
    threshold_count: int
    rolling_window_minutes: int
    flood_windows: list[FloodWindow]
    total_flood_minutes: int
    total_alarms_in_floods: int


class RationalizationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    asset_name: str
    alarm_name: str
    occurrences: int
    reason: str
    median_duration_seconds: float
    suppression_candidate: bool
    recommendation: str


class RationalizationResult(_Result):
    recurrence_threshold: int
    stale_minutes_threshold: int
    candidates: list[RationalizationCandidate]


# --------------------------------------------------------------------------
# Priority and recommendations
# --------------------------------------------------------------------------
class PriorityFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    weight: float
    value: float
    contribution: float
    explanation: str


class PriorityScoreResult(_Result):
    alarm_id: str
    asset_id: str
    asset_name: str
    priority_score: float
    priority_band: str
    factors: list[PriorityFactor]
    rationale: str


class RankedAlarm(BaseModel):
    """An alarm with its priority score attached."""

    model_config = ConfigDict(extra="forbid")

    alarm: AlarmRecord
    priority_score: float
    priority_band: str
    rationale: str


class RankedAlarmsResult(_Result):
    alarms: list[RankedAlarm]
    considered: int
    scored: int


class RecommendedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int
    action: str
    rationale: str
    expected_outcome: str
    estimated_minutes: int


class LikelyCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cause: str
    confidence: float
    evidence: str


class HistoricalPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurrences_last_90_days: int
    median_duration_seconds: float
    recurrence_interval_hours: float | None = None
    most_common_hour_utc: int | None = None
    trend: str


class RecommendationResult(_Result):
    alarm_id: str
    alarm_name: str
    severity: str
    recommended_actions: list[RecommendedAction]
    likely_causes: list[LikelyCause]
    related_alarm_count: int
    historical_pattern: HistoricalPattern | None = None


# --------------------------------------------------------------------------
# KPIs
# --------------------------------------------------------------------------
class KpiResult(_Result):
    calculation_type: str
    calculation_id: str
    result: dict[str, float]
    rows: list[dict[str, Any]]
    code: str


class KpiDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str
    description: str
    unit: str
    formula: str


class KpiDefinitionsResult(_Result):
    kpis: list[KpiDefinition]


# --------------------------------------------------------------------------
# Tickets
# --------------------------------------------------------------------------
class TicketRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    status: str
    priority: str
    asset_id: str | None = None
    asset_name: str | None = None
    site: str | None = None
    unit: str | None = None
    alarm_name: str | None = None
    assignee: str | None = None
    created_at: str
    resolved_at: str | None = None
    root_cause: str | None = None
    resolution: str | None = None
    time_to_resolve_hours: float | None = None


class TicketListResult(_Result):
    tickets: list[TicketRecord]
    total_items: int
    page: int
    has_next: bool


class SimilarTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket: TicketRecord
    score: float
    matched_on: list[str]


class SimilarTicketsResult(_Result):
    count: int
    results: list[SimilarTicket]
    low_confidence: bool = Field(
        description="True when no ticket cleared the requested similarity threshold."
    )


class TicketDetailResult(_Result):
    ticket: TicketRecord
    description: str
    labels: list[str]
    linked_alarm_ids: list[str]
    comment_count: int


class TicketWriteResult(_Result):
    ticket: TicketRecord
    created: bool = Field(
        description="False when an idempotent replay returned an existing ticket."
    )
    idempotency_key: str
    url_path: str


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
class SourceSystemHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: str
    reachable: bool
    status: Literal["ok", "unreachable", "error"]
    detail: str
    base_url: str


class HealthResult(_Result):
    systems: list[SourceSystemHealth]
    all_healthy: bool

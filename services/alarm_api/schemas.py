"""Typed request/response contracts for the Alarm Management API simulator.

These models are the single source of truth for the API surface described by
the Postman collections in ``postman/``. FastAPI derives the OpenAPI document
from them, and the MCP server's tool schemas are generated from that document,
so a change here propagates to the tool catalog rather than drifting from it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The error envelope is shared across every service in the stack.
from connectors.http_errors import ErrorDetail, ErrorResponse


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_RANK: dict[str, int] = {
    Severity.LOW.value: 1,
    Severity.MEDIUM.value: 2,
    Severity.HIGH.value: 3,
    Severity.CRITICAL.value: 4,
}


class AlarmStatus(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    CLEARED = "cleared"
    SUPPRESSED = "suppressed"


class AlarmType(StrEnum):
    PROCESS = "process"
    DEVICE = "device"
    SAFETY = "safety"
    SYSTEM = "system"
    DIAGNOSTIC = "diagnostic"


class Criticality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Bucket(StrEnum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"


class CalculationType(StrEnum):
    ALARM_FLOOD_INDEX = "alarm_flood_index"
    CRITICAL_ALARM_DENSITY = "critical_alarm_density"
    OPERATOR_RESPONSE_EFFICIENCY = "operator_response_efficiency"
    NUISANCE_ALARM_SCORE = "nuisance_alarm_score"


# --------------------------------------------------------------------------
# Shared building blocks
# --------------------------------------------------------------------------
class TimeRange(BaseModel):
    """An inclusive-start, exclusive-end UTC interval."""

    model_config = ConfigDict(extra="forbid")

    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def _check_order(self) -> TimeRange:
        if self.end_time <= self.start_time:
            raise ValueError("time_range.end_time must be strictly after start_time")
        return self


class Pagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool


__all__ = ["ErrorDetail", "ErrorResponse"]  # re-exported for the OpenAPI document


# --------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------
class Asset(BaseModel):
    asset_id: str
    asset_name: str
    asset_type: str
    site: str
    unit: str
    criticality: Criticality
    tag: str


class AssetMetadata(Asset):
    manufacturer: str
    model_number: str
    serial_number: str
    installation_date: datetime
    last_maintenance_date: datetime
    next_maintenance_due: datetime
    operating_hours: int
    parent_asset_id: str | None = None
    related_asset_ids: list[str] = Field(default_factory=list)
    design_limits: dict[str, float] = Field(default_factory=dict)
    alarm_count_total: int
    alarm_count_active: int


class AssetSearchResponse(BaseModel):
    query: str
    count: int
    results: list[Asset]


# --------------------------------------------------------------------------
# Alarms
# --------------------------------------------------------------------------
class Alarm(BaseModel):
    alarm_id: str
    asset_id: str
    asset_name: str
    site: str
    unit: str
    alarm_name: str
    alarm_type: AlarmType
    severity: Severity
    status: AlarmStatus
    start_time: datetime
    ack_time: datetime | None = None
    clear_time: datetime | None = None
    ack_delay_seconds: int | None = None
    duration_seconds: int | None = None
    source_tag: str
    measured_value: float | None = None
    limit_value: float | None = None
    unit_of_measure: str | None = None
    description: str


class AlarmDetail(Alarm):
    """Single-alarm view, enriched with the asset record and sibling alarms."""

    asset: Asset
    related_alarm_ids: list[str] = Field(default_factory=list)
    occurrences_last_90_days: int


class AlarmListResponse(BaseModel):
    data: list[Alarm]
    pagination: Pagination


# --------------------------------------------------------------------------
# Summary / trends
# --------------------------------------------------------------------------
class ScopeFilters(BaseModel):
    """The scope selector shared by every analytical endpoint.

    At least one of ``asset_ids``, ``site`` or ``unit`` narrows the result;
    all three absent means "the whole plant", which the Postman flows rely on.
    """

    model_config = ConfigDict(extra="forbid")

    asset_ids: list[str] | None = None
    site: str | None = None
    unit: str | None = None


class AlarmSummaryRequest(ScopeFilters):
    time_range: TimeRange
    severity: list[Severity] | None = None
    alarm_types: list[AlarmType] | None = None
    group_by: list[str] = Field(default_factory=lambda: ["alarm_name"])
    kpis: list[str] = Field(default_factory=lambda: ["alarm_count"])


class SummaryGroup(BaseModel):
    key: dict[str, str]
    metrics: dict[str, float]


class AlarmSummaryResponse(BaseModel):
    time_range: TimeRange
    group_by: list[str]
    kpis: list[str]
    total_alarms: int
    groups: list[SummaryGroup]


class AlarmTrendsRequest(ScopeFilters):
    time_range: TimeRange
    bucket: Bucket = Bucket.DAILY
    metrics: list[str] = Field(default_factory=lambda: ["alarm_count"])
    severity: list[Severity] | None = None


class TrendPoint(BaseModel):
    bucket_start: datetime
    bucket_end: datetime
    values: dict[str, float]


class AlarmTrendsResponse(BaseModel):
    time_range: TimeRange
    bucket: Bucket
    metrics: list[str]
    series: list[TrendPoint]


# --------------------------------------------------------------------------
# Correlation
# --------------------------------------------------------------------------
class CorrelationRequest(ScopeFilters):
    time_range: TimeRange
    correlation_method: Literal["cooccurrence", "temporal"] = "cooccurrence"
    lag_window_minutes: int = Field(default=15, ge=1, le=1440)
    severity_threshold: Severity = Severity.MEDIUM
    min_support: int = Field(default=1, ge=1)


class CorrelationPair(BaseModel):
    alarm_name_a: str
    alarm_name_b: str
    asset_id_a: str
    asset_id_b: str
    asset_name_a: str
    asset_name_b: str
    support: int
    confidence: float
    correlation_score: float
    median_lag_seconds: float


class CorrelatedAsset(BaseModel):
    asset_id: str
    asset_name: str
    site: str
    unit: str
    correlation_score: float
    shared_events: int


class CorrelationResponse(BaseModel):
    time_range: TimeRange
    method: str
    lag_window_minutes: int
    pairs: list[CorrelationPair]
    correlated_assets: list[CorrelatedAsset]


# --------------------------------------------------------------------------
# Flood analysis
# --------------------------------------------------------------------------
class FloodAnalysisRequest(ScopeFilters):
    time_range: TimeRange
    threshold_count: int = Field(default=10, ge=1)
    rolling_window_minutes: int = Field(default=10, ge=1, le=1440)


class FloodWindow(BaseModel):
    start: datetime
    end: datetime
    alarm_count: int
    peak_rate_per_minute: float
    dominant_alarm_name: str
    asset_ids: list[str]


class FloodAnalysisResponse(BaseModel):
    time_range: TimeRange
    threshold_count: int
    rolling_window_minutes: int
    flood_windows: list[FloodWindow]
    total_flood_minutes: int
    total_alarms_in_floods: int


# --------------------------------------------------------------------------
# Rationalization
# --------------------------------------------------------------------------
class RationalizationRequest(ScopeFilters):
    time_range: TimeRange
    recurrence_threshold: int = Field(default=5, ge=1)
    stale_minutes_threshold: int = Field(default=180, ge=1)


class RationalizationCandidate(BaseModel):
    asset_id: str
    asset_name: str
    alarm_name: str
    occurrences: int
    reason: Literal["recurring", "stale", "chattering"]
    median_duration_seconds: float
    suppression_candidate: bool
    recommendation: str


class RationalizationResponse(BaseModel):
    time_range: TimeRange
    recurrence_threshold: int
    stale_minutes_threshold: int
    candidates: list[RationalizationCandidate]


# --------------------------------------------------------------------------
# Priority scoring
# --------------------------------------------------------------------------
class PriorityScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alarm_id: str = Field(min_length=1)


class PriorityFactor(BaseModel):
    name: str
    weight: float
    value: float
    contribution: float
    explanation: str


class PriorityScoreResponse(BaseModel):
    alarm_id: str
    asset_id: str
    asset_name: str
    priority_score: float
    priority_band: Literal["P1", "P2", "P3", "P4"]
    factors: list[PriorityFactor]
    rationale: str


# --------------------------------------------------------------------------
# Operator recommendations
# --------------------------------------------------------------------------
class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alarm_id: str = Field(min_length=1)
    include_related: bool = False
    include_asset_context: bool = False
    include_historical_pattern: bool = False


class RecommendedAction(BaseModel):
    rank: int
    action: str
    rationale: str
    expected_outcome: str
    estimated_minutes: int


class LikelyCause(BaseModel):
    cause: str
    confidence: float
    evidence: str


class HistoricalPattern(BaseModel):
    occurrences_last_90_days: int
    median_duration_seconds: float
    recurrence_interval_hours: float | None
    most_common_hour_utc: int | None
    trend: Literal["increasing", "stable", "decreasing"]


class RecommendationResponse(BaseModel):
    alarm_id: str
    alarm_name: str
    severity: Severity
    recommended_actions: list[RecommendedAction]
    likely_causes: list[LikelyCause]
    related_alarms: list[Alarm] = Field(default_factory=list)
    asset_context: AssetMetadata | None = None
    historical_pattern: HistoricalPattern | None = None


# --------------------------------------------------------------------------
# Calculation code
# --------------------------------------------------------------------------
class CalculationFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str | None = None
    unit: str | None = None
    asset_ids: list[str] | None = None
    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def _check_order(self) -> CalculationFilters:
        if self.end_time <= self.start_time:
            raise ValueError("filters.end_time must be strictly after start_time")
        return self


class CalculationGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_type: CalculationType
    filters: CalculationFilters


class CalculationGenerateResponse(BaseModel):
    calculation_id: str
    calculation_type: CalculationType
    language: Literal["python"]
    code: str
    parameters: dict[str, Any]
    created_at: datetime


class CalculationExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: str = Field(min_length=1)
    filters: CalculationFilters | None = None


class CalculationExecuteResponse(BaseModel):
    calculation_id: str
    calculation_type: CalculationType
    result: dict[str, float]
    rows: list[dict[str, Any]]
    executed_at: datetime
    duration_ms: float


# --------------------------------------------------------------------------
# Feedback
# --------------------------------------------------------------------------
class FeedbackRating(StrEnum):
    VERY_HAPPY = "very_happy"  # 😄
    HAPPY = "happy"  # 🙂
    NEUTRAL = "neutral"  # 😐
    UNHAPPY = "unhappy"  # 🙁
    VERY_UNHAPPY = "very_unhappy"  # 😞


FEEDBACK_EMOJI: dict[str, str] = {
    FeedbackRating.VERY_HAPPY: "😄",
    FeedbackRating.HAPPY: "🙂",
    FeedbackRating.NEUTRAL: "😐",
    FeedbackRating.UNHAPPY: "🙁",
    FeedbackRating.VERY_UNHAPPY: "😞",
}


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alarm_id: str = Field(
        min_length=1, description="The alarm whose recommendation is being rated."
    )
    rating: FeedbackRating
    comment: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional free-text comment to accompany the rating.",
    )


class FeedbackResponse(BaseModel):
    feedback_id: str
    alarm_id: str
    rating: FeedbackRating
    emoji: str
    comment: str | None
    created_at: datetime


class FeedbackListResponse(BaseModel):
    total: int
    feedback: list[FeedbackResponse]


# --------------------------------------------------------------------------
# KPI definitions
# --------------------------------------------------------------------------
class KpiDefinition(BaseModel):
    name: str
    display_name: str
    description: str
    unit: str
    formula: str
    applies_to: list[str]


class KpiDefinitionsResponse(BaseModel):
    kpis: list[KpiDefinition]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    dataset: dict[str, Any]

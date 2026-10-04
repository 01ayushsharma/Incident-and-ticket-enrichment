"""Alarm retrieval and the analytical alarm endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Path, Query

from alarm_api.config import DATA_NOW, get_settings
from alarm_api.domain import analytics, store
from alarm_api.schemas import (
    AlarmDetail,
    AlarmListResponse,
    AlarmStatus,
    AlarmSummaryRequest,
    AlarmSummaryResponse,
    AlarmTrendsRequest,
    AlarmTrendsResponse,
    AlarmType,
    Asset,
    CorrelationRequest,
    CorrelationResponse,
    FloodAnalysisRequest,
    FloodAnalysisResponse,
    PriorityScoreRequest,
    PriorityScoreResponse,
    RationalizationRequest,
    RationalizationResponse,
    Severity,
)
from alarm_api.security import require_bearer_token
from connectors.http_errors import BadRequestError, NotFoundError

router = APIRouter(tags=["alarms"], dependencies=[Depends(require_bearer_token)])


def _reject_unknown_assets(dataset, asset_ids: list[str] | None) -> None:
    """Fail fast on a typo'd asset id instead of silently returning nothing.

    An empty result is indistinguishable from a bad identifier, which makes
    multi-step MCP chains very hard to debug. A 404 here tells the caller
    exactly which id it got wrong.
    """
    if not asset_ids:
        return
    unknown = store.unknown_asset_ids(dataset, asset_ids)
    if unknown:
        raise NotFoundError(
            f"Unknown asset_id(s): {', '.join(unknown)}.",
            details={"unknown_asset_ids": unknown},
        )


@router.get("/alarms", response_model=AlarmListResponse, summary="List alarms with filters")
def list_alarms(
    asset_id: str | None = Query(None, description="Single asset id to filter on."),
    site: str | None = Query(None),
    unit: str | None = Query(None),
    status: list[AlarmStatus] | None = Query(None, description="Repeatable status filter."),
    severity: list[Severity] | None = Query(None, description="Repeatable severity filter."),
    alarm_type: list[AlarmType] | None = Query(None, description="Repeatable type filter."),
    alarm_name: str | None = Query(None, description="Substring match on the alarm name."),
    start_time: datetime | None = Query(None, description="Inclusive lower bound on alarm onset."),
    end_time: datetime | None = Query(None, description="Exclusive upper bound on alarm onset."),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(
        None, ge=1, description="Defaults to ALARM_API_DEFAULT_PAGE_SIZE."
    ),
    sort_by: str = Query(
        "start_time",
        description="start_time|severity|status|alarm_name|asset_name|alarm_id|ack_delay_seconds",
    ),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
) -> AlarmListResponse:
    settings = get_settings()
    dataset = store.get_dataset()

    size = page_size or settings.default_page_size
    if size > settings.max_page_size:
        raise BadRequestError(
            f"page_size {size} exceeds the maximum of {settings.max_page_size}.",
            details={"max_page_size": settings.max_page_size},
        )
    if start_time and end_time and end_time <= start_time:
        raise BadRequestError("end_time must be strictly after start_time.")

    _reject_unknown_assets(dataset, [asset_id] if asset_id else None)

    alarms = store.filter_alarms(
        dataset,
        asset_ids=[asset_id] if asset_id else None,
        site=site,
        unit=unit,
        status=status,
        severity=severity,
        alarm_types=alarm_type,
        alarm_name=alarm_name,
        start_time=start_time,
        end_time=end_time,
    )
    try:
        alarms = store.sort_alarms(alarms, sort_by, sort_order)
    except store.UnknownSortFieldError as exc:
        raise BadRequestError(
            f"Cannot sort by '{exc.args[0]}'.",
            details={"sortable_fields": sorted(store.SORTABLE_ALARM_FIELDS)},
        ) from exc

    window, pagination = store.paginate(alarms, page, size)
    return AlarmListResponse(data=window, pagination=pagination)


@router.get(
    "/alarms/{alarm_id}",
    response_model=AlarmDetail,
    summary="One alarm, enriched with asset context and siblings",
)
def get_alarm(alarm_id: str = Path(..., min_length=1, max_length=64)) -> AlarmDetail:
    dataset = store.get_dataset()
    alarm = store.get_alarm(dataset, alarm_id)
    if alarm is None:
        raise NotFoundError(
            f"No alarm with id '{alarm_id}'.",
            details={"alarm_id": alarm_id, "hint": "Use GET /alarms to list valid ids."},
        )
    asset = dataset.assets_by_id[alarm.asset_id]
    lo = alarm.start_time - timedelta(minutes=30)
    hi = alarm.start_time + timedelta(minutes=30)
    related = [
        a.alarm_id
        for a in dataset.alarms_by_asset.get(alarm.asset_id, ())
        if a.alarm_id != alarm.alarm_id and lo <= a.start_time <= hi
    ][:20]

    return AlarmDetail(
        **alarm.model_dump(),
        asset=Asset(**asset.model_dump(include=set(Asset.model_fields))),
        related_alarm_ids=related,
        occurrences_last_90_days=store.occurrences_since(
            dataset, alarm.asset_id, alarm.alarm_name, DATA_NOW - timedelta(days=90)
        ),
    )


@router.post(
    "/alarms/summary",
    response_model=AlarmSummaryResponse,
    summary="Grouped KPI rollup over a time range",
)
def alarm_summary(req: AlarmSummaryRequest) -> AlarmSummaryResponse:
    dataset = store.get_dataset()
    _reject_unknown_assets(dataset, req.asset_ids)
    try:
        return analytics.alarm_summary(dataset, req)
    except analytics.UnknownGroupByFieldError as exc:
        raise BadRequestError(
            f"Unsupported group_by field(s): {exc.args[0]}.",
            details={"supported": sorted(analytics.GROUPABLE_FIELDS)},
        ) from exc
    except analytics.UnknownKpiError as exc:
        raise BadRequestError(
            f"Unsupported KPI '{exc.args[0]}'.",
            details={"supported": sorted(analytics.KPI_FUNCTIONS)},
        ) from exc


@router.post(
    "/alarms/trends",
    response_model=AlarmTrendsResponse,
    summary="Bucketed time series of alarm metrics",
)
def alarm_trends(req: AlarmTrendsRequest) -> AlarmTrendsResponse:
    dataset = store.get_dataset()
    _reject_unknown_assets(dataset, req.asset_ids)

    # A weekly bucket over two years is fine; an hourly bucket over two years
    # is 17k points and nobody wants that in a tool response.
    span_hours = (req.time_range.end_time - req.time_range.start_time).total_seconds() / 3600
    max_hours = {"hourly": 24 * 62, "daily": 24 * 365 * 3, "weekly": 24 * 365 * 10}
    if span_hours > max_hours[req.bucket.value]:
        raise BadRequestError(
            f"Time range is too long for a '{req.bucket.value}' bucket.",
            details={
                "bucket": req.bucket.value,
                "max_span_hours": max_hours[req.bucket.value],
                "requested_span_hours": round(span_hours, 1),
            },
        )
    try:
        return analytics.alarm_trends(dataset, req)
    except analytics.UnknownKpiError as exc:
        raise BadRequestError(
            f"Unsupported metric '{exc.args[0]}'.",
            details={"supported": sorted(analytics.KPI_FUNCTIONS)},
        ) from exc


@router.post(
    "/alarms/correlation",
    response_model=CorrelationResponse,
    summary="Co-occurrence correlation between alarms and assets",
)
def alarm_correlation(req: CorrelationRequest) -> CorrelationResponse:
    dataset = store.get_dataset()
    _reject_unknown_assets(dataset, req.asset_ids)
    return analytics.alarm_correlation(dataset, req)


@router.post(
    "/alarms/flood-analysis",
    response_model=FloodAnalysisResponse,
    summary="Detect alarm flood windows (EEMUA 191 style)",
)
def flood_analysis(req: FloodAnalysisRequest) -> FloodAnalysisResponse:
    dataset = store.get_dataset()
    _reject_unknown_assets(dataset, req.asset_ids)
    return analytics.flood_analysis(dataset, req)


@router.post(
    "/alarms/rationalization-candidates",
    response_model=RationalizationResponse,
    summary="Alarms that are recurring, stale or chattering",
)
def rationalization_candidates(req: RationalizationRequest) -> RationalizationResponse:
    dataset = store.get_dataset()
    _reject_unknown_assets(dataset, req.asset_ids)
    return analytics.rationalization_candidates(dataset, req)


@router.post(
    "/alarms/priority-score",
    response_model=PriorityScoreResponse,
    summary="Explainable multi-factor priority score for one alarm",
)
def priority_score(req: PriorityScoreRequest) -> PriorityScoreResponse:
    dataset = store.get_dataset()
    alarm = store.get_alarm(dataset, req.alarm_id)
    if alarm is None:
        raise NotFoundError(
            f"No alarm with id '{req.alarm_id}'.", details={"alarm_id": req.alarm_id}
        )
    return analytics.priority_score(dataset, alarm)

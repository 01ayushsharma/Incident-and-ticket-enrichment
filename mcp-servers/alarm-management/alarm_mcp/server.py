"""Alarm Management MCP server - the tool catalog.

Exposes the Alarm Management API and the ticketing system as MCP tools. The
copilot reaches both source systems *only* through this server; it holds no
HTTP client of its own.

Error mapping note, which drove the shape of this module: the MCP SDK
preserves the message of a raised :class:`ToolError` and reaches the model
as ``isError``, but replaces the message of any other exception with a
generic "Error executing tool X". Every failure we can anticipate is
therefore converted into a ``ToolError`` carrying an actionable message plus
a compact JSON diagnosis; genuine crashes are deliberately left opaque so
that internal detail stays on the server.
"""

# NOTE: deliberately no `from __future__ import annotations` here.
# The MCP SDK derives each tool's output schema from the function's return
# annotation at registration time. With PEP 563 the annotation is a string
# that the SDK cannot resolve from its own module namespace, and every tool
# fails to build its output model. Python 3.11 evaluates `X | None` and
# `list[str]` natively, so nothing here needs the future import.

import functools
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, TypeVar

import structlog
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from alarm_mcp import projections as p
from alarm_mcp.config import McpSettings, get_settings
from alarm_mcp.models import (
    AlarmDetailResult,
    AlarmListResult,
    AlarmSummaryResult,
    AlarmTrendsResult,
    AssetMetadataResult,
    AssetSearchResult,
    CorrelationResult,
    FloodAnalysisResult,
    HealthResult,
    KpiDefinitionsResult,
    KpiResult,
    PriorityScoreResult,
    RankedAlarm,
    RankedAlarmsResult,
    RationalizationResult,
    RecommendationResult,
    SimilarTicketsResult,
    SourceSystemHealth,
    TicketDetailResult,
    TicketListResult,
    TicketWriteResult,
)
from alarm_mcp.runtime import (
    Runtime,
    ToolInputError,
    UpstreamToolError,
    require_one_of,
    scope_body,
    tool_span,
)
from connectors.source_client import SourceSystemError
from connectors.ticketing_client import build_idempotency_key

logger = structlog.get_logger(__name__)

SERVER_NAME = "alarm-management"
SERVER_VERSION = "0.1.0"

INSTRUCTIONS = """\
Tools for an industrial Alarm Management system and its linked ticketing system.

Typical incident-enrichment flow:
  1. `search_assets` to turn an asset name into an asset_id.
  2. `rank_active_alarms_by_priority` (or `list_alarms` + `score_alarm_priority`)
     to pick the alarm that matters.
  3. `get_alarm_detail`, `get_asset_metadata`, `summarize_alarms` and
     `correlate_alarms` to build context.
  4. `recommend_operator_actions` for suggested next steps.
  5. `find_similar_tickets` for how comparable cases were resolved.
  6. `create_ticket` ONLY after a human has approved the draft.

Time windows: pass `lookback_days` for relative ranges, or explicit
`start_time`/`end_time` in ISO-8601. Relative ranges resolve against the data
horizon, not the wall clock. Omitting all three gives the last 90 days.

`create_ticket` is the only tool that changes state.\
"""

T = TypeVar("T")

_runtime: Runtime | None = None


def runtime() -> Runtime:
    if _runtime is None:  # pragma: no cover - guarded by build_server
        raise RuntimeError("MCP runtime has not been initialised")
    return _runtime


def set_runtime(value: Runtime | None) -> None:
    """Install the runtime. Tests use this to inject stubbed clients."""
    global _runtime
    _runtime = value


def _diagnose(message: str, payload: dict[str, Any]) -> str:
    """Compose an actionable message with a machine-readable tail.

    The model reads the sentence; the GUI parses the JSON to render the
    failed step in the MCP execution trace.
    """
    return f"{message} | diagnosis: {json.dumps(payload, default=str, separators=(',', ':'))}"


def mcp_tool(
    name: str,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Time the call, log it, and convert expected failures into ToolError.

    Each tool body takes a keyword-only ``timer`` that this decorator
    supplies. That parameter is an implementation detail, so the wrapper
    publishes a signature with it removed - otherwise the SDK derives the
    tool's input schema from the inner signature and demands that callers
    pass a ``timer``.
    """

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        signature = inspect.signature(fn)
        public = signature.replace(
            parameters=[p for n, p in signature.parameters.items() if n != "timer"]
        )

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                with tool_span(name) as timer:
                    return await fn(*args, timer=timer, **kwargs)
            except ToolInputError as exc:
                raise ToolError(
                    _diagnose(
                        str(exc),
                        {"kind": "invalid_input", "tool": name, **exc.details},
                    )
                ) from exc
            except UpstreamToolError as exc:
                data = exc.payload
                hint = (
                    "The source system is temporarily unavailable; retrying shortly may work."
                    if data.get("retryable")
                    else "This will not succeed on retry without changing the arguments."
                )
                raise ToolError(
                    _diagnose(f"{exc.error.message} {hint}", {"kind": "upstream", **data})
                ) from exc

        wrapper.__signature__ = public  # type: ignore[attr-defined]
        wrapper.__annotations__ = {
            k: v for k, v in getattr(fn, "__annotations__", {}).items() if k != "timer"
        }
        # `functools.wraps` sets __wrapped__, which inspect.signature follows
        # back to the inner signature and undoes the removal above.
        del wrapper.__wrapped__
        return wrapper

    return decorator


READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)


def build_server(settings: McpSettings | None = None) -> MCPServer:
    """Construct the MCP server and register every tool."""
    settings = settings or get_settings()
    if _runtime is None:
        set_runtime(Runtime.build(settings))

    server = MCPServer(
        name=SERVER_NAME,
        title="Alarm Management and Ticketing",
        version=SERVER_VERSION,
        instructions=INSTRUCTIONS,
    )

    # ----------------------------------------------------------------------
    # Assets
    # ----------------------------------------------------------------------
    @server.tool(
        name="search_assets",
        title="Search assets",
        description=(
            "Resolve a plant asset by name, tag, type or id. Always the first step "
            "when a request names equipment in prose, such as 'Boiler Feed Pump 101' "
            "or 'the compressors in Unit 3'. Returns ranked matches with asset_id."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("search_assets")
    async def search_assets(
        query: Annotated[
            str,
            Field(
                description="Asset name or fragment, e.g. 'compressor'.",
                min_length=1,
                max_length=120,
            ),
        ],
        site: Annotated[str | None, Field(description="Restrict to a site.")] = None,
        unit: Annotated[str | None, Field(description="Restrict to a unit, e.g. 'Unit 5'.")] = None,
        asset_type: Annotated[
            str | None, Field(description="Restrict to a type, e.g. 'pump'.")
        ] = None,
        limit: Annotated[int, Field(description="Max results.", ge=1, le=50)] = 10,
        *,
        timer: Any,
    ) -> AssetSearchResult:
        body = await runtime().alarm.search_assets(
            query, site=site, unit=unit, asset_type=asset_type, limit=limit
        )
        timer.record_call()
        return AssetSearchResult(
            meta=timer.meta("alarm-api", "search_assets"),
            query=query,
            count=body["count"],
            assets=[p.asset_summary(a) for a in body["results"]],
        )

    @server.tool(
        name="get_asset_metadata",
        title="Get asset metadata",
        description=(
            "Full engineering record for one asset: manufacturer, model, criticality, "
            "maintenance dates, design limits, related assets and alarm counts. Use it "
            "to enrich an incident with asset context."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("get_asset_metadata")
    async def get_asset_metadata(
        asset_id: Annotated[
            str,
            Field(
                description="Asset id from search_assets, e.g. 'AST-0001'.",
                min_length=1,
                max_length=64,
            ),
        ],
        *,
        timer: Any,
    ) -> AssetMetadataResult:
        body = await runtime().alarm.asset_metadata(asset_id)
        timer.record_call()
        return AssetMetadataResult(
            meta=timer.meta("alarm-api", "asset_metadata"), asset=p.asset_detail(body)
        )

    # ----------------------------------------------------------------------
    # Alarms
    # ----------------------------------------------------------------------
    @server.tool(
        name="list_alarms",
        title="List alarms",
        description=(
            "Retrieve alarms with filters for asset, site, unit, status, severity, type "
            "and time window. Use status='active' for what is currently in alarm. "
            "Results are paginated and capped to protect the context window."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("list_alarms")
    async def list_alarms(
        asset_id: Annotated[str | None, Field(description="Single asset id.")] = None,
        site: Annotated[str | None, Field(description="Site name, e.g. 'EastRefinery'.")] = None,
        unit: Annotated[str | None, Field(description="Unit name, e.g. 'Unit 2'.")] = None,
        status: Annotated[
            list[str] | None, Field(description="active | acknowledged | cleared | suppressed.")
        ] = None,
        severity: Annotated[
            list[str] | None, Field(description="low | medium | high | critical.")
        ] = None,
        alarm_type: Annotated[
            list[str] | None, Field(description="process | device | safety | system | diagnostic.")
        ] = None,
        alarm_name: Annotated[str | None, Field(description="Substring of the alarm name.")] = None,
        start_time: Annotated[str | None, Field(description="ISO-8601 lower bound.")] = None,
        end_time: Annotated[str | None, Field(description="ISO-8601 upper bound.")] = None,
        lookback_days: Annotated[
            int | None,
            Field(
                description="Relative window from the data horizon. Ignored if start_time is set.",
                ge=1,
                le=3650,
            ),
        ] = None,
        page: Annotated[int, Field(ge=1)] = 1,
        page_size: Annotated[int, Field(ge=1, le=200)] = 50,
        sort_by: Annotated[
            str, Field(description="start_time | severity | status | alarm_name | asset_name")
        ] = "start_time",
        sort_order: Annotated[str, Field(description="asc | desc")] = "desc",
        *,
        timer: Any,
    ) -> AlarmListResult:
        rt = runtime()
        window_start = window_end = None
        if start_time or end_time or lookback_days:
            window_start, window_end = await rt.resolve_window(start_time, end_time, lookback_days)
        body = await rt.alarm.list_alarms(
            asset_id=asset_id,
            site=site,
            unit=unit,
            status=status,
            severity=severity,
            alarm_type=alarm_type,
            alarm_name=alarm_name,
            start_time=window_start,
            end_time=window_end,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        timer.record_call()
        pagination = body["pagination"]
        return AlarmListResult(
            meta=timer.meta("alarm-api", "list_alarms", truncated=pagination["has_next"]),
            alarms=p.alarm_records(body["data"]),
            total_items=pagination["total_items"],
            page=pagination["page"],
            page_size=pagination["page_size"],
            has_next=pagination["has_next"],
        )

    @server.tool(
        name="get_alarm_detail",
        title="Get alarm detail",
        description=(
            "One alarm with its asset context, measured value against limit, sibling "
            "alarms raised nearby in time, and how often it has recurred in 90 days."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("get_alarm_detail")
    async def get_alarm_detail(
        alarm_id: Annotated[
            str, Field(description="Alarm id, e.g. 'ALM-005007'.", min_length=1, max_length=64)
        ],
        *,
        timer: Any,
    ) -> AlarmDetailResult:
        body = await runtime().alarm.get_alarm(alarm_id)
        timer.record_call()
        return AlarmDetailResult(
            meta=timer.meta("alarm-api", "get_alarm"),
            alarm=p.alarm_record(body),
            asset=p.asset_summary(body["asset"]),
            related_alarm_ids=body.get("related_alarm_ids", []),
            occurrences_last_90_days=body["occurrences_last_90_days"],
            measured_value=body.get("measured_value"),
            limit_value=body.get("limit_value"),
            unit_of_measure=body.get("unit_of_measure"),
        )

    @server.tool(
        name="rank_active_alarms_by_priority",
        title="Rank active alarms by priority",
        description=(
            "Find the highest-priority open alarms in a scope and score each one. "
            "This is the tool for requests like 'prepare an incident for the "
            "highest-priority active alarm in EastRefinery' - it chains alarm "
            "retrieval and priority scoring so the caller does not have to."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("rank_active_alarms_by_priority")
    async def rank_active_alarms_by_priority(
        site: Annotated[str | None, Field(description="Site to search.")] = None,
        unit: Annotated[str | None, Field(description="Unit to search.")] = None,
        asset_id: Annotated[str | None, Field(description="Single asset to search.")] = None,
        severity: Annotated[
            list[str] | None, Field(description="Restrict to these severities before scoring.")
        ] = None,
        include_acknowledged: Annotated[
            bool, Field(description="Also consider acknowledged-but-not-cleared alarms.")
        ] = True,
        top_n: Annotated[int, Field(description="How many to return.", ge=1, le=20)] = 5,
        *,
        timer: Any,
    ) -> RankedAlarmsResult:
        rt = runtime()
        require_one_of(site=site, unit=unit, asset_id=asset_id)

        statuses = ["active", "acknowledged"] if include_acknowledged else ["active"]
        listing = await rt.alarm.list_alarms(
            asset_id=asset_id,
            site=site,
            unit=unit,
            status=statuses,
            severity=severity,
            page=1,
            page_size=rt.settings.max_rank_candidates,
            sort_by="severity",
            sort_order="desc",
        )
        timer.record_call()
        candidates = listing["data"]
        if not candidates:
            # An empty result is a legitimate answer, not an error: there may
            # genuinely be no open alarms in scope.
            return RankedAlarmsResult(
                meta=timer.meta("alarm-api", "rank_active_alarms_by_priority"),
                alarms=[],
                considered=0,
                scored=0,
            )

        # Score the strongest candidates only: each score is an upstream call,
        # and scoring fifty alarms to return five is wasteful.
        shortlist = candidates[: max(top_n * 2, top_n)]
        ranked: list[RankedAlarm] = []
        for alarm in shortlist:
            score = await rt.alarm.priority_score(alarm["alarm_id"])
            timer.record_call()
            ranked.append(
                RankedAlarm(
                    alarm=p.alarm_record(alarm),
                    priority_score=score["priority_score"],
                    priority_band=score["priority_band"],
                    rationale=score["rationale"],
                )
            )
        ranked.sort(key=lambda r: (-r.priority_score, r.alarm.alarm_id))
        return RankedAlarmsResult(
            meta=timer.meta(
                "alarm-api",
                "rank_active_alarms_by_priority",
                truncated=len(candidates) > len(shortlist),
            ),
            alarms=ranked[:top_n],
            considered=len(candidates),
            scored=len(ranked),
        )

    # ----------------------------------------------------------------------
    # Analytics
    # ----------------------------------------------------------------------
    @server.tool(
        name="summarize_alarms",
        title="Summarise alarms",
        description=(
            "Grouped KPI rollup over a time window. Group by any of alarm_name, "
            "asset_id, asset_name, severity, status, unit, site, alarm_type. KPIs "
            "include alarm_count, critical_count, recurring_rate, avg_ack_delay, "
            "avg_duration and suppression_candidate_rate. Use list_kpi_definitions "
            "for the full catalogue."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("summarize_alarms")
    async def summarize_alarms(
        asset_ids: Annotated[list[str] | None, Field(description="Assets to include.")] = None,
        site: Annotated[str | None, Field(description="Site scope.")] = None,
        unit: Annotated[str | None, Field(description="Unit scope.")] = None,
        severity: Annotated[list[str] | None, Field(description="Severity filter.")] = None,
        alarm_types: Annotated[list[str] | None, Field(description="Alarm type filter.")] = None,
        group_by: Annotated[list[str], Field(description="Grouping fields.")] = ["alarm_name"],  # noqa: B006 - read-only default; shown in the tool schema
        kpis: Annotated[list[str], Field(description="KPIs to compute.")] = ["alarm_count"],  # noqa: B006 - read-only default; shown in the tool schema
        start_time: Annotated[str | None, Field(description="ISO-8601 start.")] = None,
        end_time: Annotated[str | None, Field(description="ISO-8601 end.")] = None,
        lookback_days: Annotated[int | None, Field(ge=1, le=3650)] = None,
        *,
        timer: Any,
    ) -> AlarmSummaryResult:
        rt = runtime()
        start, end = await rt.resolve_window(start_time, end_time, lookback_days)
        body = await rt.alarm.alarm_summary(
            {
                **scope_body(asset_ids, site, unit),
                "time_range": {"start_time": start, "end_time": end},
                **({"severity": severity} if severity else {}),
                **({"alarm_types": alarm_types} if alarm_types else {}),
                "group_by": group_by,
                "kpis": kpis,
            }
        )
        timer.record_call()
        return AlarmSummaryResult(
            meta=timer.meta("alarm-api", "alarm_summary"),
            total_alarms=body["total_alarms"],
            group_by=body["group_by"],
            kpis=body["kpis"],
            groups=p.summary_groups(body["groups"]),
        )

    @server.tool(
        name="get_alarm_trends",
        title="Get alarm trends",
        description=(
            "Bucketed time series (hourly, daily or weekly) of alarm metrics. Use it "
            "to establish whether a problem is getting worse over a period."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("get_alarm_trends")
    async def get_alarm_trends(
        asset_ids: Annotated[list[str] | None, Field(description="Assets to include.")] = None,
        site: Annotated[str | None, Field(description="Site scope.")] = None,
        unit: Annotated[str | None, Field(description="Unit scope.")] = None,
        bucket: Annotated[str, Field(description="hourly | daily | weekly")] = "daily",
        metrics: Annotated[list[str], Field(description="Metrics per bucket.")] = ["alarm_count"],  # noqa: B006 - read-only default; shown in the tool schema
        start_time: Annotated[str | None, Field(description="ISO-8601 start.")] = None,
        end_time: Annotated[str | None, Field(description="ISO-8601 end.")] = None,
        lookback_days: Annotated[int | None, Field(ge=1, le=3650)] = None,
        *,
        timer: Any,
    ) -> AlarmTrendsResult:
        rt = runtime()
        start, end = await rt.resolve_window(start_time, end_time, lookback_days)
        body = await rt.alarm.alarm_trends(
            {
                **scope_body(asset_ids, site, unit),
                "time_range": {"start_time": start, "end_time": end},
                "bucket": bucket,
                "metrics": metrics,
            }
        )
        timer.record_call()
        series = p.trend_points(body["series"])
        lead = metrics[0] if metrics else "alarm_count"
        return AlarmTrendsResult(
            meta=timer.meta("alarm-api", "alarm_trends"),
            bucket=body["bucket"],
            metrics=body["metrics"],
            series=series,
            non_empty_buckets=sum(1 for pt in series if pt.values.get(lead, 0)),
        )

    @server.tool(
        name="correlate_alarms",
        title="Correlate alarms",
        description=(
            "Find alarms that repeatedly occur together within a lag window, and the "
            "assets that alarm alongside the ones in scope. Use it to identify likely "
            "contributing factors and to find assets whose tickets may be related."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("correlate_alarms")
    async def correlate_alarms(
        asset_ids: Annotated[list[str] | None, Field(description="Assets to correlate.")] = None,
        site: Annotated[str | None, Field(description="Site scope.")] = None,
        unit: Annotated[str | None, Field(description="Unit scope.")] = None,
        lag_window_minutes: Annotated[
            int,
            Field(
                description="Maximum gap between two alarms to count as co-occurring.",
                ge=1,
                le=1440,
            ),
        ] = 15,
        severity_threshold: Annotated[
            str, Field(description="Ignore alarms below this severity.")
        ] = "medium",
        min_support: Annotated[
            int, Field(description="Minimum co-occurrence count for a pair to be reported.", ge=1)
        ] = 2,
        start_time: Annotated[str | None, Field(description="ISO-8601 start.")] = None,
        end_time: Annotated[str | None, Field(description="ISO-8601 end.")] = None,
        lookback_days: Annotated[int | None, Field(ge=1, le=3650)] = None,
        *,
        timer: Any,
    ) -> CorrelationResult:
        rt = runtime()
        start, end = await rt.resolve_window(start_time, end_time, lookback_days)
        body = await rt.alarm.correlation(
            {
                **scope_body(asset_ids, site, unit),
                "time_range": {"start_time": start, "end_time": end},
                "correlation_method": "cooccurrence",
                "lag_window_minutes": lag_window_minutes,
                "severity_threshold": severity_threshold,
                "min_support": min_support,
            }
        )
        timer.record_call()
        return CorrelationResult(
            meta=timer.meta("alarm-api", "correlation"),
            method=body["method"],
            lag_window_minutes=body["lag_window_minutes"],
            pairs=p.correlation_pairs(body["pairs"]),
            correlated_assets=p.correlated_assets(body["correlated_assets"]),
        )

    @server.tool(
        name="analyze_alarm_floods",
        title="Analyse alarm floods",
        description=(
            "Detect periods where the alarm rate exceeded an operator's capacity to "
            "respond (EEMUA 191 style flood analysis), returning each flood window "
            "with its dominant alarm and the assets involved."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("analyze_alarm_floods")
    async def analyze_alarm_floods(
        site: Annotated[str | None, Field(description="Site scope.")] = None,
        unit: Annotated[str | None, Field(description="Unit scope.")] = None,
        asset_ids: Annotated[list[str] | None, Field(description="Assets to include.")] = None,
        threshold_count: Annotated[
            int, Field(description="Alarms within the window that constitute a flood.", ge=1)
        ] = 10,
        rolling_window_minutes: Annotated[int, Field(ge=1, le=1440)] = 10,
        start_time: Annotated[str | None, Field(description="ISO-8601 start.")] = None,
        end_time: Annotated[str | None, Field(description="ISO-8601 end.")] = None,
        lookback_days: Annotated[int | None, Field(ge=1, le=3650)] = None,
        *,
        timer: Any,
    ) -> FloodAnalysisResult:
        rt = runtime()
        start, end = await rt.resolve_window(start_time, end_time, lookback_days)
        body = await rt.alarm.flood_analysis(
            {
                **scope_body(asset_ids, site, unit),
                "time_range": {"start_time": start, "end_time": end},
                "threshold_count": threshold_count,
                "rolling_window_minutes": rolling_window_minutes,
            }
        )
        timer.record_call()
        return FloodAnalysisResult(
            meta=timer.meta("alarm-api", "flood_analysis"),
            threshold_count=body["threshold_count"],
            rolling_window_minutes=body["rolling_window_minutes"],
            flood_windows=p.flood_windows(body["flood_windows"]),
            total_flood_minutes=body["total_flood_minutes"],
            total_alarms_in_floods=body["total_alarms_in_floods"],
        )

    @server.tool(
        name="find_rationalization_candidates",
        title="Find rationalization candidates",
        description=(
            "Identify alarms that are recurring, stale or chattering and therefore "
            "candidates for an alarm rationalization review, each with a specific "
            "recommendation."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("find_rationalization_candidates")
    async def find_rationalization_candidates(
        asset_ids: Annotated[list[str] | None, Field(description="Assets to include.")] = None,
        site: Annotated[str | None, Field(description="Site scope.")] = None,
        unit: Annotated[str | None, Field(description="Unit scope.")] = None,
        recurrence_threshold: Annotated[
            int, Field(description="Occurrences before an alarm counts as recurring.", ge=1)
        ] = 5,
        stale_minutes_threshold: Annotated[
            int,
            Field(description="How long an active alarm may stand before counting as stale.", ge=1),
        ] = 180,
        start_time: Annotated[str | None, Field(description="ISO-8601 start.")] = None,
        end_time: Annotated[str | None, Field(description="ISO-8601 end.")] = None,
        lookback_days: Annotated[int | None, Field(ge=1, le=3650)] = None,
        *,
        timer: Any,
    ) -> RationalizationResult:
        rt = runtime()
        start, end = await rt.resolve_window(start_time, end_time, lookback_days)
        body = await rt.alarm.rationalization_candidates(
            {
                **scope_body(asset_ids, site, unit),
                "time_range": {"start_time": start, "end_time": end},
                "recurrence_threshold": recurrence_threshold,
                "stale_minutes_threshold": stale_minutes_threshold,
            }
        )
        timer.record_call()
        return RationalizationResult(
            meta=timer.meta("alarm-api", "rationalization_candidates"),
            recurrence_threshold=body["recurrence_threshold"],
            stale_minutes_threshold=body["stale_minutes_threshold"],
            candidates=p.rationalization_candidates(body["candidates"]),
        )

    @server.tool(
        name="score_alarm_priority",
        title="Score alarm priority",
        description=(
            "Explainable priority score from 0 to 100 for one alarm, with the "
            "weighted factor breakdown (severity, asset criticality, recurrence, open "
            "exposure, safety function). Include the breakdown in an incident so the "
            "ranking can be justified."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("score_alarm_priority")
    async def score_alarm_priority(
        alarm_id: Annotated[
            str, Field(description="Alarm id to score.", min_length=1, max_length=64)
        ],
        *,
        timer: Any,
    ) -> PriorityScoreResult:
        body = await runtime().alarm.priority_score(alarm_id)
        timer.record_call()
        return PriorityScoreResult(
            meta=timer.meta("alarm-api", "priority_score"),
            alarm_id=body["alarm_id"],
            asset_id=body["asset_id"],
            asset_name=body["asset_name"],
            priority_score=body["priority_score"],
            priority_band=body["priority_band"],
            factors=p.priority_factors(body["factors"]),
            rationale=body["rationale"],
        )

    @server.tool(
        name="recommend_operator_actions",
        title="Recommend operator actions",
        description=(
            "Ranked operator actions and likely causes for one alarm, optionally with "
            "the asset's historical pattern for that alarm. These are the source "
            "system's engineered recommendations - combine them with retrieved "
            "procedures rather than treating either alone as complete."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("recommend_operator_actions")
    async def recommend_operator_actions(
        alarm_id: Annotated[str, Field(description="Alarm id.", min_length=1, max_length=64)],
        include_related: Annotated[
            bool, Field(description="Count alarms raised nearby in time.")
        ] = True,
        include_historical_pattern: Annotated[
            bool, Field(description="Include recurrence interval and trend.")
        ] = True,
        *,
        timer: Any,
    ) -> RecommendationResult:
        body = await runtime().alarm.operator_recommendations(
            alarm_id,
            include_related=include_related,
            include_asset_context=False,
            include_historical_pattern=include_historical_pattern,
        )
        timer.record_call()
        return RecommendationResult(
            meta=timer.meta("alarm-api", "operator_recommendations"),
            alarm_id=body["alarm_id"],
            alarm_name=body["alarm_name"],
            severity=body["severity"],
            recommended_actions=p.recommended_actions(body["recommended_actions"]),
            likely_causes=p.likely_causes(body["likely_causes"]),
            related_alarm_count=len(body.get("related_alarms", [])),
            historical_pattern=p.historical_pattern(body.get("historical_pattern")),
        )

    # ----------------------------------------------------------------------
    # KPIs
    # ----------------------------------------------------------------------
    @server.tool(
        name="compute_kpi",
        title="Compute a KPI",
        description=(
            "Generate and execute a named KPI calculation in one step. Supported: "
            "alarm_flood_index, critical_alarm_density, operator_response_efficiency, "
            "nuisance_alarm_score. Returns the numeric result, supporting rows, and "
            "the source of the calculation for transparency."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("compute_kpi")
    async def compute_kpi(
        calculation_type: Annotated[
            str,
            Field(
                description="alarm_flood_index | critical_alarm_density | "
                "operator_response_efficiency | nuisance_alarm_score"
            ),
        ],
        site: Annotated[str | None, Field(description="Site scope.")] = None,
        unit: Annotated[str | None, Field(description="Unit scope.")] = None,
        asset_ids: Annotated[list[str] | None, Field(description="Assets to include.")] = None,
        start_time: Annotated[str | None, Field(description="ISO-8601 start.")] = None,
        end_time: Annotated[str | None, Field(description="ISO-8601 end.")] = None,
        lookback_days: Annotated[int | None, Field(ge=1, le=3650)] = None,
        *,
        timer: Any,
    ) -> KpiResult:
        rt = runtime()
        start, end = await rt.resolve_window(start_time, end_time, lookback_days)
        filters: dict[str, Any] = {"start_time": start, "end_time": end}
        if site:
            filters["site"] = site
        if unit:
            filters["unit"] = unit
        if asset_ids:
            filters["asset_ids"] = asset_ids

        outcome = await rt.alarm.compute_kpi(calculation_type, filters)
        timer.record_call(2)
        generated, executed = outcome["generated"], outcome["executed"]
        return KpiResult(
            meta=timer.meta("alarm-api", "compute_kpi"),
            calculation_type=executed["calculation_type"],
            calculation_id=executed["calculation_id"],
            result=executed["result"],
            rows=executed["rows"][:20],
            code=generated["code"],
        )

    @server.tool(
        name="list_kpi_definitions",
        title="List KPI definitions",
        description=(
            "Catalogue of every KPI the alarm system can compute, with its formula "
            "and unit. Call this when unsure which KPI name to pass to "
            "summarize_alarms or get_alarm_trends."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("list_kpi_definitions")
    async def list_kpi_definitions(*, timer: Any) -> KpiDefinitionsResult:
        body = await runtime().alarm.kpi_definitions()
        timer.record_call()
        return KpiDefinitionsResult(
            meta=timer.meta("alarm-api", "kpi_definitions"),
            kpis=p.kpi_definitions(body["kpis"]),
        )

    # ----------------------------------------------------------------------
    # Ticketing
    # ----------------------------------------------------------------------
    @server.tool(
        name="find_similar_tickets",
        title="Find similar historical tickets",
        description=(
            "Search historical tickets resembling a situation, blending text "
            "similarity with agreement on alarm name, asset and asset type. Use "
            "resolved_only=true to answer 'how was this fixed before'. Reports "
            "low_confidence when nothing clears the threshold - say so rather than "
            "presenting weak matches as precedent."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("find_similar_tickets")
    async def find_similar_tickets(
        query: Annotated[
            str | None, Field(description="Free text describing the situation.", max_length=2000)
        ] = None,
        alarm_name: Annotated[str | None, Field(description="Exact alarm name.")] = None,
        asset_id: Annotated[str | None, Field(description="Asset id.")] = None,
        asset_type: Annotated[str | None, Field(description="Asset type, e.g. 'pump'.")] = None,
        site: Annotated[str | None, Field(description="Site scope.")] = None,
        unit: Annotated[str | None, Field(description="Unit scope.")] = None,
        resolved_only: Annotated[
            bool, Field(description="Only tickets that carry a resolution.")
        ] = False,
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
        min_score: Annotated[
            float,
            Field(
                description="Similarity floor; below it the result is low confidence.",
                ge=0.0,
                le=1.0,
            ),
        ] = 0.25,
        *,
        timer: Any,
    ) -> SimilarTicketsResult:
        require_one_of(query=query, alarm_name=alarm_name, asset_id=asset_id)
        body = await runtime().tickets.search_similar(
            {
                k: v
                for k, v in {
                    "query": query,
                    "alarm_name": alarm_name,
                    "asset_id": asset_id,
                    "asset_type": asset_type,
                    "site": site,
                    "unit": unit,
                    "resolved_only": resolved_only,
                    "limit": limit,
                    "min_score": min_score,
                }.items()
                if v is not None
            }
        )
        timer.record_call()
        return SimilarTicketsResult(
            meta=timer.meta("ticketing-api", "search_similar"),
            count=body["count"],
            results=p.similar_tickets(body["results"]),
            low_confidence=body["low_confidence"],
        )

    @server.tool(
        name="list_tickets",
        title="List tickets",
        description=(
            "List tickets with filters. Pass several asset_ids to answer 'show open "
            "tickets linked to correlated assets'; combine with open_only=true for "
            "what is still outstanding."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("list_tickets")
    async def list_tickets(
        asset_ids: Annotated[
            list[str] | None,
            Field(description="One or more asset ids, typically from correlate_alarms."),
        ] = None,
        status: Annotated[
            list[str] | None,
            Field(description="open | in_progress | resolved | closed | cancelled"),
        ] = None,
        site: Annotated[str | None, Field(description="Site scope.")] = None,
        unit: Annotated[str | None, Field(description="Unit scope.")] = None,
        alarm_name: Annotated[str | None, Field(description="Exact alarm name.")] = None,
        open_only: Annotated[bool, Field(description="Shorthand for open/in_progress.")] = False,
        page: Annotated[int, Field(ge=1)] = 1,
        page_size: Annotated[int, Field(ge=1, le=100)] = 25,
        *,
        timer: Any,
    ) -> TicketListResult:
        body = await runtime().tickets.list_tickets(
            asset_ids=asset_ids,
            status=status,
            site=site,
            unit=unit,
            alarm_name=alarm_name,
            open_only=open_only,
            page=page,
            page_size=page_size,
        )
        timer.record_call()
        pagination = body["pagination"]
        return TicketListResult(
            meta=timer.meta("ticketing-api", "list_tickets", truncated=pagination["has_next"]),
            tickets=p.ticket_records(body["data"]),
            total_items=pagination["total_items"],
            page=pagination["page"],
            has_next=pagination["has_next"],
        )

    @server.tool(
        name="get_ticket",
        title="Get one ticket",
        description="Full detail for one ticket, including its description and linked alarms.",
        annotations=READ_ONLY,
    )
    @mcp_tool("get_ticket")
    async def get_ticket(
        key: Annotated[
            str, Field(description="Ticket key, e.g. 'INC-1042'.", min_length=3, max_length=32)
        ],
        *,
        timer: Any,
    ) -> TicketDetailResult:
        body = await runtime().tickets.get_ticket(key)
        timer.record_call()
        return TicketDetailResult(
            meta=timer.meta("ticketing-api", "get_ticket"),
            ticket=p.ticket_record(body),
            description=body["description"],
            labels=body.get("labels", []),
            linked_alarm_ids=body.get("linked_alarm_ids", []),
            comment_count=len(body.get("comments", [])),
        )

    @server.tool(
        name="create_ticket",
        title="Create a ticket (WRITE - requires human approval)",
        description=(
            "Create an incident ticket. THIS IS A WRITE OPERATION AND THE ONLY TOOL "
            "THAT CHANGES STATE. Do not call it until a human has reviewed the draft "
            "and explicitly approved it; `approved` must be true. Pass a stable "
            "`approval_reference` (for example the conversation id plus the alarm id) "
            "so that a repeated call returns the ticket already created rather than "
            "opening a duplicate."
        ),
        annotations=WRITE,
    )
    @mcp_tool("create_ticket")
    async def create_ticket(
        title: Annotated[str, Field(description="Ticket title.", min_length=3, max_length=300)],
        description: Annotated[
            str,
            Field(
                description="Full incident body, including evidence and citations.",
                min_length=1,
                max_length=20000,
            ),
        ],
        approved: Annotated[
            bool,
            Field(description="Must be true, and only after a human approved this exact draft."),
        ],
        approval_reference: Annotated[
            str,
            Field(
                description="Stable identifier for this approval, e.g. '<conversation_id>:<alarm_id>'.",
                min_length=4,
                max_length=200,
            ),
        ],
        priority: Annotated[str, Field(description="P1 | P2 | P3 | P4")] = "P3",
        asset_id: Annotated[str | None, Field(description="Asset the incident concerns.")] = None,
        asset_name: Annotated[str | None, Field(description="Asset name, for readability.")] = None,
        site: Annotated[str | None, Field(description="Site.")] = None,
        unit: Annotated[str | None, Field(description="Unit.")] = None,
        alarm_name: Annotated[str | None, Field(description="Alarm that triggered this.")] = None,
        labels: Annotated[list[str] | None, Field(description="Labels to apply.")] = None,
        assignee: Annotated[str | None, Field(description="Assignee username.")] = None,
        linked_alarm_ids: Annotated[
            list[str] | None, Field(description="Alarm ids this incident covers.")
        ] = None,
        *,
        timer: Any,
    ) -> TicketWriteResult:
        if not approved:
            # Refusing here - rather than in the copilot alone - means the
            # approval gate holds even if this server is driven by some other
            # MCP client.
            raise ToolInputError(
                "Refusing to create a ticket without approval. Present the draft to "
                "the user, obtain explicit confirmation, then call again with "
                "approved=true.",
                details={"field": "approved", "received": approved},
            )

        rt = runtime()
        idempotency_key = build_idempotency_key(approval_reference, alarm_name, asset_id)
        payload = {
            "title": title,
            "description": description,
            "priority": priority,
            "confirmed": True,
            "reporter": "alarm-copilot",
            **{
                k: v
                for k, v in {
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                    "site": site,
                    "unit": unit,
                    "alarm_name": alarm_name,
                    "labels": labels or [],
                    "assignee": assignee,
                    "linked_alarm_ids": linked_alarm_ids or [],
                }.items()
                if v is not None
            },
        }
        body, created = await rt.tickets.create_ticket(payload, idempotency_key=idempotency_key)
        timer.record_call()
        logger.info(
            "ticket_write",
            ticket_key=body["key"],
            created=created,
            approval_reference=approval_reference,
        )
        return TicketWriteResult(
            meta=timer.meta("ticketing-api", "create_ticket"),
            ticket=p.ticket_record(body),
            created=created,
            idempotency_key=idempotency_key,
            url_path=f"/tickets/{body['key']}",
        )

    @server.tool(
        name="add_ticket_comment",
        title="Add a comment to a ticket (WRITE)",
        description=(
            "Append a comment to an existing ticket. A write operation: only call it "
            "when the user has asked for the note to be added."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        ),
    )
    @mcp_tool("add_ticket_comment")
    async def add_ticket_comment(
        key: Annotated[str, Field(description="Ticket key.", min_length=3, max_length=32)],
        body: Annotated[str, Field(description="Comment text.", min_length=1, max_length=10000)],
        approved: Annotated[bool, Field(description="Must be true.")] = False,
        *,
        timer: Any,
    ) -> TicketDetailResult:
        if not approved:
            raise ToolInputError(
                "Refusing to comment without approval. Confirm with the user, then "
                "call again with approved=true.",
                details={"field": "approved"},
            )
        result = await runtime().tickets.add_comment(key, body)
        timer.record_call()
        return TicketDetailResult(
            meta=timer.meta("ticketing-api", "add_comment"),
            ticket=p.ticket_record(result),
            description=result["description"],
            labels=result.get("labels", []),
            linked_alarm_ids=result.get("linked_alarm_ids", []),
            comment_count=len(result.get("comments", [])),
        )

    # ----------------------------------------------------------------------
    # Operations
    # ----------------------------------------------------------------------
    @server.tool(
        name="check_source_systems",
        title="Check source system health",
        description=(
            "Probe both source systems and report reachability. Use it to distinguish "
            "'there is no data' from 'the system is down' before telling the user a "
            "query returned nothing."
        ),
        annotations=READ_ONLY,
    )
    @mcp_tool("check_source_systems")
    async def check_source_systems(*, timer: Any) -> HealthResult:
        rt = runtime()
        systems: list[SourceSystemHealth] = []
        for name, probe, url in (
            ("alarm-api", rt.alarm.health, rt.settings.alarm_api_base_url),
            ("ticketing-api", rt.tickets.health, rt.settings.ticketing_api_url),
        ):
            try:
                body = await probe()
                timer.record_call()
                systems.append(
                    SourceSystemHealth(
                        system=name,
                        reachable=True,
                        status="ok",
                        detail=json.dumps(body.get("dataset", {}), default=str)[:300],
                        base_url=url,
                    )
                )
            except SourceSystemError as exc:
                # Deliberately not re-raised: the point of this tool is to
                # report degraded state, so a failure here is a valid result.
                systems.append(
                    SourceSystemHealth(
                        system=name,
                        reachable=False,
                        status="unreachable" if exc.retryable else "error",
                        detail=exc.message,
                        base_url=url,
                    )
                )
        return HealthResult(
            meta=timer.meta("mcp", "check_source_systems"),
            systems=systems,
            all_healthy=all(s.reachable for s in systems),
        )

    return server


__all__ = ["SERVER_NAME", "SERVER_VERSION", "build_server", "runtime", "set_runtime"]

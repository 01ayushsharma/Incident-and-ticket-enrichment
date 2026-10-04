"""Analytical operations over the alarm dataset.

These are the computations behind the summary, trend, correlation, flood,
rationalization, priority and recommendation endpoints. They are ordinary
pure functions taking a :class:`Dataset` and a request model, which keeps
them unit-testable without an HTTP layer or a running server.
"""

from __future__ import annotations

import statistics
import uuid
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

from alarm_api.config import DATA_NOW
from alarm_api.domain import store
from alarm_api.domain.catalog import TEMPLATES_BY_TYPE
from alarm_api.domain.seed import Dataset
from alarm_api.schemas import (
    SEVERITY_RANK,
    Alarm,
    AlarmStatus,
    AlarmSummaryRequest,
    AlarmSummaryResponse,
    AlarmTrendsRequest,
    AlarmTrendsResponse,
    Bucket,
    CalculationExecuteResponse,
    CalculationFilters,
    CalculationGenerateResponse,
    CalculationType,
    CorrelatedAsset,
    CorrelationPair,
    CorrelationRequest,
    CorrelationResponse,
    Criticality,
    FloodAnalysisRequest,
    FloodAnalysisResponse,
    FloodWindow,
    HistoricalPattern,
    KpiDefinition,
    LikelyCause,
    PriorityFactor,
    PriorityScoreResponse,
    RationalizationCandidate,
    RationalizationRequest,
    RationalizationResponse,
    RecommendationRequest,
    RecommendationResponse,
    RecommendedAction,
    Severity,
    SummaryGroup,
    TimeRange,
    TrendPoint,
)

# Fields a caller may group a summary by.
GROUPABLE_FIELDS = frozenset(
    {"alarm_name", "asset_id", "asset_name", "severity", "status", "unit", "site", "alarm_type"}
)

# Operator acknowledgement target used by the response-efficiency KPI.
ACK_TARGET_SECONDS = 600

# An alarm shorter than this is treated as chattering rather than a real event.
CHATTER_DURATION_SECONDS = 300


class UnknownGroupByFieldError(ValueError):
    """Raised when a summary requests grouping by an unsupported field."""


class UnknownKpiError(ValueError):
    """Raised when a summary or trend requests an unsupported metric."""


class UnknownCalculationError(KeyError):
    """Raised when executing a calculation id that was never generated."""


# --------------------------------------------------------------------------
# KPI computation
# --------------------------------------------------------------------------
def _ack_delays(alarms: Sequence[Alarm]) -> list[int]:
    return [a.ack_delay_seconds for a in alarms if a.ack_delay_seconds is not None]


def _durations(alarms: Sequence[Alarm]) -> list[int]:
    return [a.duration_seconds for a in alarms if a.duration_seconds is not None]


def _recurring_rate(alarms: Sequence[Alarm]) -> float:
    """Share of alarms in the set that are repeats of an (asset, name) pair."""
    if not alarms:
        return 0.0
    distinct = len({(a.asset_id, a.alarm_name) for a in alarms})
    return round((len(alarms) - distinct) / len(alarms), 4)


def _suppression_candidate_rate(alarms: Sequence[Alarm]) -> float:
    """Share of alarms that look like nuisance: suppressed or very short."""
    if not alarms:
        return 0.0
    hits = sum(
        1
        for a in alarms
        if a.status == AlarmStatus.SUPPRESSED
        or (a.duration_seconds is not None and a.duration_seconds < CHATTER_DURATION_SECONDS)
    )
    return round(hits / len(alarms), 4)


KPI_FUNCTIONS: dict[str, Callable[[Sequence[Alarm]], float]] = {
    "alarm_count": lambda a: float(len(a)),
    "critical_count": lambda a: float(sum(1 for x in a if x.severity == Severity.CRITICAL)),
    "high_count": lambda a: float(sum(1 for x in a if x.severity == Severity.HIGH)),
    "active_count": lambda a: float(sum(1 for x in a if x.status == AlarmStatus.ACTIVE)),
    "recurring_rate": _recurring_rate,
    "avg_ack_delay": lambda a: (
        round(statistics.fmean(_ack_delays(a)), 2) if _ack_delays(a) else 0.0
    ),
    "max_ack_delay": lambda a: float(max(_ack_delays(a))) if _ack_delays(a) else 0.0,
    "avg_duration": lambda a: round(statistics.fmean(_durations(a)), 2) if _durations(a) else 0.0,
    "mttr_seconds": lambda a: round(statistics.fmean(_durations(a)), 2) if _durations(a) else 0.0,
    "suppression_candidate_rate": _suppression_candidate_rate,
    "distinct_assets": lambda a: float(len({x.asset_id for x in a})),
}


def _compute_kpis(alarms: Sequence[Alarm], kpis: Sequence[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for kpi in kpis:
        fn = KPI_FUNCTIONS.get(kpi)
        if fn is None:
            raise UnknownKpiError(kpi)
        out[kpi] = fn(alarms)
    return out


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
def alarm_summary(dataset: Dataset, req: AlarmSummaryRequest) -> AlarmSummaryResponse:
    bad = [f for f in req.group_by if f not in GROUPABLE_FIELDS]
    if bad:
        raise UnknownGroupByFieldError(", ".join(bad))

    alarms = store.filter_alarms(
        dataset,
        asset_ids=req.asset_ids,
        site=req.site,
        unit=req.unit,
        severity=req.severity,
        alarm_types=req.alarm_types,
        start_time=req.time_range.start_time,
        end_time=req.time_range.end_time,
    )

    buckets: dict[tuple[str, ...], list[Alarm]] = defaultdict(list)
    for alarm in alarms:
        key = tuple(
            str(
                getattr(alarm, f).value
                if hasattr(getattr(alarm, f), "value")
                else getattr(alarm, f)
            )
            for f in req.group_by
        )
        buckets[key].append(alarm)

    groups = [
        SummaryGroup(
            key=dict(zip(req.group_by, key, strict=True)),
            metrics=_compute_kpis(members, req.kpis),
        )
        for key, members in buckets.items()
    ]
    # Rank by the first requested KPI so the most significant group leads.
    lead = req.kpis[0] if req.kpis else "alarm_count"
    groups.sort(key=lambda g: (-g.metrics.get(lead, 0.0), tuple(sorted(g.key.items()))))

    return AlarmSummaryResponse(
        time_range=req.time_range,
        group_by=req.group_by,
        kpis=req.kpis,
        total_alarms=len(alarms),
        groups=groups,
    )


# --------------------------------------------------------------------------
# Trends
# --------------------------------------------------------------------------
_BUCKET_DELTA: dict[Bucket, timedelta] = {
    Bucket.HOURLY: timedelta(hours=1),
    Bucket.DAILY: timedelta(days=1),
    Bucket.WEEKLY: timedelta(weeks=1),
}


def _floor_to_bucket(moment: datetime, bucket: Bucket) -> datetime:
    if bucket == Bucket.HOURLY:
        return moment.replace(minute=0, second=0, microsecond=0)
    floored = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == Bucket.WEEKLY:
        floored -= timedelta(days=floored.weekday())
    return floored


def alarm_trends(dataset: Dataset, req: AlarmTrendsRequest) -> AlarmTrendsResponse:
    alarms = store.filter_alarms(
        dataset,
        asset_ids=req.asset_ids,
        site=req.site,
        unit=req.unit,
        severity=req.severity,
        start_time=req.time_range.start_time,
        end_time=req.time_range.end_time,
    )
    delta = _BUCKET_DELTA[req.bucket]

    grouped: dict[datetime, list[Alarm]] = defaultdict(list)
    for alarm in alarms:
        grouped[_floor_to_bucket(alarm.start_time, req.bucket)].append(alarm)

    # Emit an unbroken series, including empty buckets - a gap in a chart is
    # ambiguous between "no alarms" and "no data".
    series: list[TrendPoint] = []
    cursor = _floor_to_bucket(req.time_range.start_time, req.bucket)
    while cursor < req.time_range.end_time:
        members = grouped.get(cursor, [])
        series.append(
            TrendPoint(
                bucket_start=cursor,
                bucket_end=cursor + delta,
                values=_compute_kpis(members, req.metrics),
            )
        )
        cursor += delta

    return AlarmTrendsResponse(
        time_range=req.time_range,
        bucket=req.bucket,
        metrics=req.metrics,
        series=series,
    )


# --------------------------------------------------------------------------
# Correlation
# --------------------------------------------------------------------------
def alarm_correlation(dataset: Dataset, req: CorrelationRequest) -> CorrelationResponse:
    alarms = store.filter_alarms(
        dataset,
        asset_ids=req.asset_ids,
        site=req.site,
        unit=req.unit,
        min_severity=req.severity_threshold,
        start_time=req.time_range.start_time,
        end_time=req.time_range.end_time,
    )
    events = sorted(alarms, key=lambda a: a.start_time)
    lag = timedelta(minutes=req.lag_window_minutes)

    occurrences: Counter[tuple[str, str]] = Counter((a.asset_id, a.alarm_name) for a in events)
    pair_lags: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)

    # Forward sliding window: for each event, pair it with every later event
    # that starts inside the lag window.
    for i, leader in enumerate(events):
        horizon = leader.start_time + lag
        for follower in events[i + 1 :]:
            if follower.start_time > horizon:
                break
            if leader.asset_id == follower.asset_id and leader.alarm_name == follower.alarm_name:
                continue
            key = (leader.asset_id, leader.alarm_name, follower.asset_id, follower.alarm_name)
            pair_lags[key].append((follower.start_time - leader.start_time).total_seconds())

    pairs: list[CorrelationPair] = []
    for (asset_a, name_a, asset_b, name_b), lags in pair_lags.items():
        support = len(lags)
        if support < req.min_support:
            continue
        count_a = occurrences[(asset_a, name_a)]
        count_b = occurrences[(asset_b, name_b)]
        confidence = support / count_a if count_a else 0.0
        union = count_a + count_b - support
        jaccard = support / union if union > 0 else 0.0
        pairs.append(
            CorrelationPair(
                alarm_name_a=name_a,
                alarm_name_b=name_b,
                asset_id_a=asset_a,
                asset_id_b=asset_b,
                asset_name_a=dataset.assets_by_id[asset_a].asset_name,
                asset_name_b=dataset.assets_by_id[asset_b].asset_name,
                support=support,
                confidence=round(min(confidence, 1.0), 4),
                correlation_score=round(jaccard, 4),
                median_lag_seconds=round(statistics.median(lags), 1),
            )
        )
    pairs.sort(key=lambda p: (-p.correlation_score, -p.support, p.alarm_name_a))
    pairs = pairs[:50]

    correlated_assets = _correlated_assets(dataset, req, events, lag)

    return CorrelationResponse(
        time_range=req.time_range,
        method=req.correlation_method,
        lag_window_minutes=req.lag_window_minutes,
        pairs=pairs,
        correlated_assets=correlated_assets,
    )


def _correlated_assets(
    dataset: Dataset,
    req: CorrelationRequest,
    events: list[Alarm],
    lag: timedelta,
) -> list[CorrelatedAsset]:
    """Assets that repeatedly alarm alongside the scope's assets.

    This is what the copilot uses to answer "show open tickets linked to
    correlated assets", so it deliberately looks *outside* the requested
    asset list - widening to the sites those assets belong to.
    """
    primary = store.resolve_scope_asset_ids(
        dataset, asset_ids=req.asset_ids, site=req.site, unit=req.unit
    )
    if primary is None:
        primary = {a.asset_id for a in dataset.assets}

    sites = {dataset.assets_by_id[a].site for a in primary if a in dataset.assets_by_id}
    neighbourhood = store.filter_alarms(
        dataset,
        min_severity=req.severity_threshold,
        start_time=req.time_range.start_time,
        end_time=req.time_range.end_time,
    )
    neighbourhood = sorted(
        (a for a in neighbourhood if a.site in sites), key=lambda a: a.start_time
    )

    primary_events = [a for a in events if a.asset_id in primary]
    # Binary-search the window bounds rather than rescanning the neighbourhood
    # for every anchor: at plant scope both lists hold thousands of events.
    times = [a.start_time for a in neighbourhood]
    shared: Counter[str] = Counter()
    for anchor in primary_events:
        lo = bisect_left(times, anchor.start_time - lag)
        hi = bisect_right(times, anchor.start_time + lag)
        for other in neighbourhood[lo:hi]:
            if other.asset_id != anchor.asset_id:
                shared[other.asset_id] += 1

    denominator = max(1, len(primary_events))
    out = [
        CorrelatedAsset(
            asset_id=asset_id,
            asset_name=dataset.assets_by_id[asset_id].asset_name,
            site=dataset.assets_by_id[asset_id].site,
            unit=dataset.assets_by_id[asset_id].unit,
            correlation_score=round(min(count / denominator, 1.0), 4),
            shared_events=count,
        )
        for asset_id, count in shared.items()
        if asset_id in dataset.assets_by_id
    ]
    out.sort(key=lambda c: (-c.shared_events, c.asset_id))
    return out[:20]


# --------------------------------------------------------------------------
# Flood analysis
# --------------------------------------------------------------------------
def flood_analysis(dataset: Dataset, req: FloodAnalysisRequest) -> FloodAnalysisResponse:
    alarms = sorted(
        store.filter_alarms(
            dataset,
            asset_ids=req.asset_ids,
            site=req.site,
            unit=req.unit,
            start_time=req.time_range.start_time,
            end_time=req.time_range.end_time,
        ),
        key=lambda a: a.start_time,
    )
    window = timedelta(minutes=req.rolling_window_minutes)

    # Find every rolling window whose alarm count breaches the threshold,
    # then merge the overlapping ones into contiguous flood periods.
    raw: list[tuple[datetime, datetime]] = []
    for i, alarm in enumerate(alarms):
        horizon = alarm.start_time + window
        j = i
        while j < len(alarms) and alarms[j].start_time <= horizon:
            j += 1
        if j - i >= req.threshold_count:
            raw.append((alarm.start_time, alarms[j - 1].start_time))

    merged: list[list[datetime]] = []
    for start, end in raw:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    windows: list[FloodWindow] = []
    total_minutes = 0
    total_alarms = 0
    for start, end in merged:
        members = [a for a in alarms if start <= a.start_time <= end]
        if not members:
            continue
        span_minutes = max(1.0, (end - start).total_seconds() / 60.0)
        peak = _peak_rate_per_minute(members, window)
        names = Counter(a.alarm_name for a in members)
        windows.append(
            FloodWindow(
                start=start,
                end=end,
                alarm_count=len(members),
                peak_rate_per_minute=round(peak, 2),
                dominant_alarm_name=names.most_common(1)[0][0],
                asset_ids=sorted({a.asset_id for a in members}),
            )
        )
        total_minutes += round(span_minutes)
        total_alarms += len(members)

    windows.sort(key=lambda w: (-w.alarm_count, w.start))
    return FloodAnalysisResponse(
        time_range=req.time_range,
        threshold_count=req.threshold_count,
        rolling_window_minutes=req.rolling_window_minutes,
        flood_windows=windows,
        total_flood_minutes=total_minutes,
        total_alarms_in_floods=total_alarms,
    )


def _peak_rate_per_minute(members: list[Alarm], window: timedelta) -> float:
    minutes = max(1.0, window.total_seconds() / 60.0)
    peak = 0
    for i, alarm in enumerate(members):
        horizon = alarm.start_time + window
        j = i
        while j < len(members) and members[j].start_time <= horizon:
            j += 1
        peak = max(peak, j - i)
    return peak / minutes


# --------------------------------------------------------------------------
# Rationalization
# --------------------------------------------------------------------------
def rationalization_candidates(
    dataset: Dataset, req: RationalizationRequest
) -> RationalizationResponse:
    alarms = store.filter_alarms(
        dataset,
        asset_ids=req.asset_ids,
        site=req.site,
        unit=req.unit,
        start_time=req.time_range.start_time,
        end_time=req.time_range.end_time,
    )
    stale_cutoff = timedelta(minutes=req.stale_minutes_threshold)

    grouped: dict[tuple[str, str], list[Alarm]] = defaultdict(list)
    for alarm in alarms:
        grouped[(alarm.asset_id, alarm.alarm_name)].append(alarm)

    candidates: list[RationalizationCandidate] = []
    for (asset_id, alarm_name), members in grouped.items():
        durations = _durations(members)
        median_duration = statistics.median(durations) if durations else 0.0
        stale_hits = [
            a
            for a in members
            if a.status == AlarmStatus.ACTIVE and (DATA_NOW - a.start_time) > stale_cutoff
        ]
        recurring = len(members) >= req.recurrence_threshold
        chattering = recurring and durations and median_duration < CHATTER_DURATION_SECONDS

        if chattering:
            reason = "chattering"
            recommendation = (
                f"Apply an on-delay or deadband to {alarm_name}: it recurs "
                f"{len(members)} times with a median duration of "
                f"{median_duration:.0f}s, below the {CHATTER_DURATION_SECONDS}s "
                "chattering threshold."
            )
        elif stale_hits:
            reason = "stale"
            oldest = min(a.start_time for a in stale_hits)
            age_hours = (DATA_NOW - oldest).total_seconds() / 3600
            recommendation = (
                f"Review {alarm_name}: {len(stale_hits)} occurrence(s) remain active, "
                f"the oldest for {age_hours:.0f}h. Either resolve the underlying "
                "condition or reassess the setpoint."
            )
        elif recurring:
            reason = "recurring"
            recommendation = (
                f"Assess {alarm_name} against the alarm philosophy: {len(members)} "
                f"occurrences exceed the recurrence threshold of {req.recurrence_threshold}. "
                "Consider a setpoint review or a root-cause work order."
            )
        else:
            continue

        severities = Counter(a.severity for a in members)
        low_grade = severities[Severity.LOW] + severities[Severity.MEDIUM] >= len(members) / 2

        candidates.append(
            RationalizationCandidate(
                asset_id=asset_id,
                asset_name=dataset.assets_by_id[asset_id].asset_name,
                alarm_name=alarm_name,
                occurrences=len(members),
                reason=reason,
                median_duration_seconds=round(float(median_duration), 1),
                suppression_candidate=bool(chattering or (recurring and low_grade)),
                recommendation=recommendation,
            )
        )

    candidates.sort(key=lambda c: (-c.occurrences, c.asset_id, c.alarm_name))
    return RationalizationResponse(
        time_range=req.time_range,
        recurrence_threshold=req.recurrence_threshold,
        stale_minutes_threshold=req.stale_minutes_threshold,
        candidates=candidates[:50],
    )


# --------------------------------------------------------------------------
# Priority scoring
# --------------------------------------------------------------------------
_CRITICALITY_VALUE: dict[Criticality, float] = {
    Criticality.LOW: 0.2,
    Criticality.MEDIUM: 0.45,
    Criticality.HIGH: 0.75,
    Criticality.CRITICAL: 1.0,
}


def priority_score(dataset: Dataset, alarm: Alarm) -> PriorityScoreResponse:
    """Weighted multi-factor score in [0, 100].

    The factor breakdown is part of the response on purpose: the copilot
    surfaces it in the ticket draft, so an operator can see *why* an alarm was
    ranked first rather than being asked to trust an opaque number.
    """
    asset = dataset.assets_by_id[alarm.asset_id]
    since = DATA_NOW - timedelta(days=90)
    recurrence = store.occurrences_since(dataset, alarm.asset_id, alarm.alarm_name, since)

    severity_value = SEVERITY_RANK[alarm.severity.value] / 4.0
    criticality_value = _CRITICALITY_VALUE[asset.criticality]
    recurrence_value = min(1.0, recurrence / 20.0)

    if alarm.status == AlarmStatus.ACTIVE:
        age_hours = max(0.0, (DATA_NOW - alarm.start_time).total_seconds() / 3600)
        openness_value = min(1.0, age_hours / 24.0)
        openness_note = f"active for {age_hours:.1f}h without resolution"
    elif alarm.status == AlarmStatus.ACKNOWLEDGED:
        openness_value = 0.4
        openness_note = "acknowledged but not yet cleared"
    else:
        openness_value = 0.0
        openness_note = f"status is {alarm.status.value}; no open exposure"

    safety_value = 1.0 if alarm.alarm_type.value == "safety" else 0.0

    factors = [
        PriorityFactor(
            name="severity",
            weight=0.35,
            value=round(severity_value, 4),
            contribution=round(0.35 * severity_value * 100, 2),
            explanation=f"alarm severity is {alarm.severity.value}",
        ),
        PriorityFactor(
            name="asset_criticality",
            weight=0.25,
            value=round(criticality_value, 4),
            contribution=round(0.25 * criticality_value * 100, 2),
            explanation=f"{asset.asset_name} is classified {asset.criticality.value} criticality",
        ),
        PriorityFactor(
            name="recurrence_90d",
            weight=0.15,
            value=round(recurrence_value, 4),
            contribution=round(0.15 * recurrence_value * 100, 2),
            explanation=f"{recurrence} occurrence(s) of this alarm on this asset in 90 days",
        ),
        PriorityFactor(
            name="open_exposure",
            weight=0.15,
            value=round(openness_value, 4),
            contribution=round(0.15 * openness_value * 100, 2),
            explanation=openness_note,
        ),
        PriorityFactor(
            name="safety_function",
            weight=0.10,
            value=safety_value,
            contribution=round(0.10 * safety_value * 100, 2),
            explanation=(
                "alarm is part of a safety function"
                if safety_value
                else f"alarm type is {alarm.alarm_type.value}, not a safety function"
            ),
        ),
    ]

    score = round(sum(f.contribution for f in factors), 2)
    band = "P1" if score >= 75 else "P2" if score >= 55 else "P3" if score >= 35 else "P4"
    lead = max(factors, key=lambda f: f.contribution)

    return PriorityScoreResponse(
        alarm_id=alarm.alarm_id,
        asset_id=alarm.asset_id,
        asset_name=asset.asset_name,
        priority_score=score,
        priority_band=band,
        factors=factors,
        rationale=(
            f"Scored {score}/100 ({band}). Largest contributor: {lead.name} "
            f"({lead.contribution} points) because {lead.explanation}."
        ),
    )


# --------------------------------------------------------------------------
# Operator recommendations
# --------------------------------------------------------------------------
_GENERIC_ACTIONS: tuple[tuple[str, str, str, int], ...] = (
    (
        "Verify the reading against a second indication",
        "Rules out a transmitter fault before any process intervention.",
        "Alarm confirmed as genuine or attributed to instrumentation.",
        10,
    ),
    (
        "Inspect the asset locally for audible or visual abnormality",
        "Field observation frequently identifies the failure mode directly.",
        "Failure mode narrowed to a mechanical or process cause.",
        20,
    ),
    (
        "Review the trend over the preceding shift",
        "Distinguishes a step change from gradual degradation.",
        "Degradation rate established, informing urgency.",
        15,
    ),
    (
        "Raise a work order if the condition persists beyond one shift",
        "Ensures the condition is tracked to closure rather than repeatedly acknowledged.",
        "Maintenance engaged with documented history.",
        10,
    ),
)

_ACTION_RULES: dict[str, tuple[tuple[str, str, str, int], ...]] = {
    "High Discharge Temperature": (
        (
            "Confirm cooling water flow and temperature to the pump",
            "Loss of cooling is the most frequent direct cause of a discharge temperature rise.",
            "Cooling circuit confirmed available or isolated as the cause.",
            15,
        ),
        (
            "Check the minimum-flow recirculation line for restriction",
            "Operating below minimum flow drives heat into the process fluid.",
            "Recirculation path confirmed clear.",
            20,
        ),
        (
            "Inspect the mechanical seal and its flush plan",
            "Seal degradation raises local temperature and precedes seal failure.",
            "Seal condition assessed; replacement scheduled if degraded.",
            30,
        ),
    ),
    "Low Suction Pressure": (
        (
            "Verify upstream vessel level and suction valve position",
            "A closed or throttled suction valve and low upstream level are the dominant causes.",
            "Suction path confirmed open with adequate NPSH.",
            10,
        ),
        (
            "Check the suction strainer differential pressure",
            "Strainer blockage starves the pump and risks cavitation damage.",
            "Strainer confirmed clear or scheduled for cleaning.",
            20,
        ),
        (
            "Reduce flow demand until suction pressure recovers",
            "Continued operation below NPSH-required causes rapid impeller damage.",
            "Cavitation risk removed while the cause is investigated.",
            5,
        ),
    ),
    "High Vibration": (
        (
            "Take a spectrum reading and compare with the last route measurement",
            "Spectral signature separates imbalance, misalignment and bearing defects.",
            "Failure mode identified from the frequency signature.",
            30,
        ),
        (
            "Check coupling alignment and foundation bolt torque",
            "Misalignment and soft foot are common and inexpensive to correct.",
            "Alignment verified within tolerance.",
            45,
        ),
        (
            "Trend bearing temperature alongside vibration",
            "A joint rise confirms bearing degradation rather than a process excitation.",
            "Bearing condition confirmed.",
            15,
        ),
    ),
    "Lube Oil Pressure Low": (
        (
            "Verify lube oil level and the standby pump auto-start",
            "Protects the machine before any diagnosis; a trip on low-low is imminent.",
            "Lube supply restored or the machine safely shut down.",
            10,
        ),
        (
            "Check the lube oil filter differential pressure",
            "A blocked filter is the most common cause of a gradual pressure decay.",
            "Filter condition established; changeover performed if required.",
            20,
        ),
        (
            "Confirm the pressure transmitter against the local gauge",
            "Avoids an unnecessary shutdown on a failed transmitter.",
            "Reading confirmed as genuine.",
            10,
        ),
    ),
    "Motor Winding Temperature High": (
        (
            "Confirm the motor cooling fan and air path are unobstructed",
            "Blocked cooling is the most frequent cause of a winding temperature rise.",
            "Cooling path confirmed clear.",
            15,
        ),
        (
            "Check the driven equipment for increased load or binding",
            "Sustained overload heats the windings and precedes an overload trip.",
            "Load confirmed within rating.",
            20,
        ),
        (
            "Measure phase currents for imbalance",
            "Phase imbalance causes disproportionate heating in one winding.",
            "Supply balance verified.",
            15,
        ),
    ),
    "Surge Detected": (
        (
            "Verify anti-surge valve travel and response time",
            "A slow or stuck anti-surge valve is the direct cause of a surge event.",
            "Anti-surge protection confirmed functional.",
            20,
        ),
        (
            "Check for a downstream restriction or an unexpected valve closure",
            "A rising discharge resistance pushes the operating point across the surge line.",
            "Discharge path confirmed clear.",
            15,
        ),
        (
            "Increase recycle flow to move the operating point right of the surge line",
            "Immediate protection of the machine while the cause is investigated.",
            "Machine returned to a stable operating region.",
            5,
        ),
    ),
    "Drum Level Low": (
        (
            "Confirm feedwater flow and feed pump status",
            "A tripped or degraded feed pump is the dominant cause of a falling drum level.",
            "Feedwater supply restored.",
            10,
        ),
        (
            "Cross-check the level against a second transmitter and the gauge glass",
            "A single failed transmitter can present as a genuine low level.",
            "Level reading confirmed.",
            10,
        ),
        (
            "Reduce firing rate if the level continues to fall",
            "Protects the tubes from dry-out while feedwater is restored.",
            "Tube dry-out risk mitigated.",
            5,
        ),
    ),
}


def _historical_pattern(dataset: Dataset, alarm: Alarm) -> HistoricalPattern:
    since = DATA_NOW - timedelta(days=90)
    history = sorted(
        (
            a
            for a in dataset.alarms_by_asset.get(alarm.asset_id, ())
            if a.alarm_name == alarm.alarm_name and a.start_time >= since
        ),
        key=lambda a: a.start_time,
    )
    durations = _durations(history)
    median_duration = float(statistics.median(durations)) if durations else 0.0

    interval_hours: float | None = None
    if len(history) > 1:
        gaps = [(b.start_time - a.start_time).total_seconds() / 3600 for a, b in pairwise(history)]
        interval_hours = round(float(statistics.median(gaps)), 2)

    hour_mode: int | None = None
    if history:
        hour_mode = Counter(a.start_time.hour for a in history).most_common(1)[0][0]

    # Compare the most recent 30 days against the preceding 60.
    recent_cut = DATA_NOW - timedelta(days=30)
    recent = sum(1 for a in history if a.start_time >= recent_cut)
    earlier = sum(1 for a in history if a.start_time < recent_cut)
    expected = earlier / 2.0 if earlier else 0.0
    if recent > expected * 1.3 and recent >= 2:
        trend = "increasing"
    elif expected and recent < expected * 0.7:
        trend = "decreasing"
    else:
        trend = "stable"

    return HistoricalPattern(
        occurrences_last_90_days=len(history),
        median_duration_seconds=round(median_duration, 1),
        recurrence_interval_hours=interval_hours,
        most_common_hour_utc=hour_mode,
        trend=trend,
    )


def operator_recommendations(
    dataset: Dataset, alarm: Alarm, req: RecommendationRequest
) -> RecommendationResponse:
    asset = dataset.assets_by_id[alarm.asset_id]

    rules = _ACTION_RULES.get(alarm.alarm_name, ())
    chosen = list(rules) + [a for a in _GENERIC_ACTIONS if a not in rules]
    actions = [
        RecommendedAction(
            rank=i,
            action=action,
            rationale=rationale,
            expected_outcome=outcome,
            estimated_minutes=minutes,
        )
        for i, (action, rationale, outcome, minutes) in enumerate(chosen[:5], start=1)
    ]

    template = next(
        (t for t in TEMPLATES_BY_TYPE.get(asset.asset_type, ()) if t.name == alarm.alarm_name),
        None,
    )
    pattern = _historical_pattern(dataset, alarm)
    base_confidence = 0.75 if template and template.causes else 0.5
    likely_causes = [
        LikelyCause(
            cause=cause,
            confidence=round(max(0.2, base_confidence - 0.12 * i), 2),
            evidence=(
                f"Known failure mode for {asset.asset_type} assets raising "
                f"'{alarm.alarm_name}'; this alarm has occurred "
                f"{pattern.occurrences_last_90_days} time(s) on {asset.asset_name} "
                "in the last 90 days."
            ),
        )
        for i, cause in enumerate(template.causes if template else ())
    ]

    related: list[Alarm] = []
    if req.include_related:
        lo = alarm.start_time - timedelta(minutes=30)
        hi = alarm.start_time + timedelta(minutes=30)
        related = [
            a
            for a in dataset.alarms
            if a.alarm_id != alarm.alarm_id
            and lo <= a.start_time <= hi
            and (a.asset_id == alarm.asset_id or a.unit == alarm.unit)
        ][:15]

    return RecommendationResponse(
        alarm_id=alarm.alarm_id,
        alarm_name=alarm.alarm_name,
        severity=alarm.severity,
        recommended_actions=actions,
        likely_causes=likely_causes,
        related_alarms=related,
        asset_context=asset if req.include_asset_context else None,
        historical_pattern=pattern if req.include_historical_pattern else None,
    )


# --------------------------------------------------------------------------
# Calculation code generation and execution
# --------------------------------------------------------------------------
# Generated calculations live in memory for the process lifetime. A real
# deployment would persist these; the simulator does not, and the MCP server
# therefore always regenerates before executing.
_CALCULATIONS: dict[str, tuple[CalculationType, CalculationFilters]] = {}

_CALC_NAMESPACE = uuid.UUID("2f9b6d5e-2c1a-4f93-9b0e-5c7a1d84f0aa")

_CALC_CODE: dict[CalculationType, str] = {
    CalculationType.ALARM_FLOOD_INDEX: '''
def alarm_flood_index(alarms, window_minutes=10, threshold=10):
    """Share of the observation period spent in an alarm flood (EEMUA 191)."""
    events = sorted(a.start_time for a in alarms)
    flooded = 0
    for i, start in enumerate(events):
        horizon = start + timedelta(minutes=window_minutes)
        count = sum(1 for t in events[i:] if t <= horizon)
        if count >= threshold:
            flooded += 1
    return flooded / len(events) if events else 0.0
'''.strip(),
    CalculationType.CRITICAL_ALARM_DENSITY: '''
def critical_alarm_density(alarms, assets, days):
    """Critical alarms raised per asset per day over the window."""
    critical = [a for a in alarms if a.severity == "critical"]
    denominator = max(1, len(assets)) * max(1.0, days)
    return len(critical) / denominator
'''.strip(),
    CalculationType.OPERATOR_RESPONSE_EFFICIENCY: '''
def operator_response_efficiency(alarms, target_seconds=600):
    """Share of acknowledged alarms answered inside the response target."""
    delays = [a.ack_delay_seconds for a in alarms if a.ack_delay_seconds is not None]
    if not delays:
        return 0.0
    return sum(1 for d in delays if d <= target_seconds) / len(delays)
'''.strip(),
    CalculationType.NUISANCE_ALARM_SCORE: '''
def nuisance_alarm_score(alarms, chatter_seconds=300):
    """Weighted share of alarms that are suppressed, chattering or repeats."""
    if not alarms:
        return 0.0
    suppressed = sum(1 for a in alarms if a.status == "suppressed")
    chattering = sum(1 for a in alarms
                     if a.duration_seconds is not None and a.duration_seconds < chatter_seconds)
    distinct = len({(a.asset_id, a.alarm_name) for a in alarms})
    repeats = len(alarms) - distinct
    return (0.4 * suppressed + 0.4 * chattering + 0.2 * repeats) / len(alarms)
'''.strip(),
}


def generate_calculation(
    calculation_type: CalculationType, filters: CalculationFilters
) -> CalculationGenerateResponse:
    """Register a calculation and return its source and identifier.

    The identifier is a UUID5 over the type and filters, so generating the
    same calculation twice is idempotent - which matters because the MCP
    server regenerates before every execution.
    """
    fingerprint = f"{calculation_type.value}|{filters.model_dump_json()}"
    calculation_id = str(uuid.uuid5(_CALC_NAMESPACE, fingerprint))
    _CALCULATIONS[calculation_id] = (calculation_type, filters)
    return CalculationGenerateResponse(
        calculation_id=calculation_id,
        calculation_type=calculation_type,
        language="python",
        code=_CALC_CODE[calculation_type],
        parameters={
            "site": filters.site,
            "unit": filters.unit,
            "asset_ids": filters.asset_ids,
            "start_time": filters.start_time.isoformat(),
            "end_time": filters.end_time.isoformat(),
        },
        created_at=DATA_NOW,
    )


def execute_calculation(
    dataset: Dataset,
    calculation_id: str,
    override_filters: CalculationFilters | None = None,
) -> CalculationExecuteResponse:
    """Run a previously generated calculation against the dataset."""
    if calculation_id not in _CALCULATIONS:
        raise UnknownCalculationError(calculation_id)
    calculation_type, stored_filters = _CALCULATIONS[calculation_id]
    filters = override_filters or stored_filters

    started = datetime.now(UTC)
    alarms = store.filter_alarms(
        dataset,
        asset_ids=filters.asset_ids,
        site=filters.site,
        unit=filters.unit,
        start_time=filters.start_time,
        end_time=filters.end_time,
    )
    scope_ids = store.resolve_scope_asset_ids(
        dataset, asset_ids=filters.asset_ids, site=filters.site, unit=filters.unit
    )
    asset_count = len(scope_ids) if scope_ids is not None else len(dataset.assets)
    days = max(1.0, (filters.end_time - filters.start_time).total_seconds() / 86400)

    result, rows = _CALC_IMPLS[calculation_type](dataset, alarms, asset_count, days)
    duration_ms = (datetime.now(UTC) - started).total_seconds() * 1000

    return CalculationExecuteResponse(
        calculation_id=calculation_id,
        calculation_type=calculation_type,
        result=result,
        rows=rows,
        executed_at=started,
        duration_ms=round(duration_ms, 3),
    )


def _calc_flood_index(
    dataset: Dataset, alarms: list[Alarm], asset_count: int, days: float
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    events = sorted(a.start_time for a in alarms)
    window = timedelta(minutes=10)
    flooded = 0
    for i, start in enumerate(events):
        horizon = start + window
        j = i
        while j < len(events) and events[j] <= horizon:
            j += 1
        if j - i >= 10:
            flooded += 1
    index = flooded / len(events) if events else 0.0
    by_unit: Counter[str] = Counter(a.unit for a in alarms)
    rows = [
        {"unit": unit, "alarm_count": count, "alarms_per_day": round(count / days, 3)}
        for unit, count in sorted(by_unit.items())
    ]
    return (
        {
            "alarm_flood_index": round(index, 4),
            "alarms_in_flood_conditions": float(flooded),
            "total_alarms": float(len(alarms)),
            "alarms_per_day": round(len(alarms) / days, 3),
        },
        rows,
    )


def _calc_critical_density(
    dataset: Dataset, alarms: list[Alarm], asset_count: int, days: float
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    critical = [a for a in alarms if a.severity == Severity.CRITICAL]
    density = len(critical) / (max(1, asset_count) * days)
    per_asset: Counter[str] = Counter(a.asset_id for a in critical)
    rows = [
        {
            "asset_id": asset_id,
            "asset_name": dataset.assets_by_id[asset_id].asset_name,
            "critical_alarms": count,
            "critical_per_day": round(count / days, 4),
        }
        for asset_id, count in per_asset.most_common(20)
    ]
    return (
        {
            "critical_alarm_density": round(density, 5),
            "critical_alarms": float(len(critical)),
            "assets_in_scope": float(asset_count),
            "window_days": round(days, 2),
        },
        rows,
    )


def _calc_response_efficiency(
    dataset: Dataset, alarms: list[Alarm], asset_count: int, days: float
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    delays = _ack_delays(alarms)
    within = sum(1 for d in delays if d <= ACK_TARGET_SECONDS)
    efficiency = within / len(delays) if delays else 0.0
    by_unit: dict[str, list[int]] = defaultdict(list)
    for alarm in alarms:
        if alarm.ack_delay_seconds is not None:
            by_unit[alarm.unit].append(alarm.ack_delay_seconds)
    rows = [
        {
            "unit": unit,
            "acknowledged": len(values),
            "avg_ack_delay_seconds": round(statistics.fmean(values), 1),
            "within_target_rate": round(
                sum(1 for v in values if v <= ACK_TARGET_SECONDS) / len(values), 4
            ),
        }
        for unit, values in sorted(by_unit.items())
    ]
    return (
        {
            "operator_response_efficiency": round(efficiency, 4),
            "acknowledged_alarms": float(len(delays)),
            "avg_ack_delay_seconds": round(statistics.fmean(delays), 1) if delays else 0.0,
            "target_seconds": float(ACK_TARGET_SECONDS),
        },
        rows,
    )


def _calc_nuisance_score(
    dataset: Dataset, alarms: list[Alarm], asset_count: int, days: float
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    if not alarms:
        return {"nuisance_alarm_score": 0.0, "total_alarms": 0.0}, []
    suppressed = sum(1 for a in alarms if a.status == AlarmStatus.SUPPRESSED)
    chattering = sum(
        1
        for a in alarms
        if a.duration_seconds is not None and a.duration_seconds < CHATTER_DURATION_SECONDS
    )
    distinct = len({(a.asset_id, a.alarm_name) for a in alarms})
    repeats = len(alarms) - distinct
    score = (0.4 * suppressed + 0.4 * chattering + 0.2 * repeats) / len(alarms)

    per_pair: Counter[tuple[str, str]] = Counter((a.asset_id, a.alarm_name) for a in alarms)
    rows = [
        {
            "asset_id": asset_id,
            "asset_name": dataset.assets_by_id[asset_id].asset_name,
            "alarm_name": name,
            "occurrences": count,
        }
        for (asset_id, name), count in per_pair.most_common(20)
    ]
    return (
        {
            "nuisance_alarm_score": round(score, 4),
            "suppressed_alarms": float(suppressed),
            "chattering_alarms": float(chattering),
            "repeat_alarms": float(repeats),
            "total_alarms": float(len(alarms)),
        },
        rows,
    )


_CALC_IMPLS: dict[
    CalculationType,
    Callable[[Dataset, list[Alarm], int, float], tuple[dict[str, float], list[dict[str, Any]]]],
] = {
    CalculationType.ALARM_FLOOD_INDEX: _calc_flood_index,
    CalculationType.CRITICAL_ALARM_DENSITY: _calc_critical_density,
    CalculationType.OPERATOR_RESPONSE_EFFICIENCY: _calc_response_efficiency,
    CalculationType.NUISANCE_ALARM_SCORE: _calc_nuisance_score,
}


def reset_calculations() -> None:
    """Clear the calculation registry (tests)."""
    _CALCULATIONS.clear()


# --------------------------------------------------------------------------
# KPI catalogue
# --------------------------------------------------------------------------
KPI_DEFINITIONS: tuple[KpiDefinition, ...] = (
    KpiDefinition(
        name="alarm_count",
        display_name="Alarm Count",
        description="Number of alarm occurrences in scope.",
        unit="count",
        formula="count(alarms)",
        applies_to=["summary", "trends"],
    ),
    KpiDefinition(
        name="critical_count",
        display_name="Critical Alarm Count",
        description="Number of alarms at critical severity.",
        unit="count",
        formula="count(alarms where severity = 'critical')",
        applies_to=["summary", "trends"],
    ),
    KpiDefinition(
        name="high_count",
        display_name="High Alarm Count",
        description="Number of alarms at high severity.",
        unit="count",
        formula="count(alarms where severity = 'high')",
        applies_to=["summary", "trends"],
    ),
    KpiDefinition(
        name="active_count",
        display_name="Active Alarm Count",
        description="Alarms still in the active state.",
        unit="count",
        formula="count(alarms where status = 'active')",
        applies_to=["summary", "trends"],
    ),
    KpiDefinition(
        name="recurring_rate",
        display_name="Recurring Rate",
        description="Share of occurrences that repeat an (asset, alarm) pair already seen.",
        unit="ratio",
        formula="(count(alarms) - count(distinct asset+alarm)) / count(alarms)",
        applies_to=["summary"],
    ),
    KpiDefinition(
        name="avg_ack_delay",
        display_name="Average Acknowledgement Delay",
        description="Mean time from alarm onset to operator acknowledgement.",
        unit="seconds",
        formula="mean(ack_time - start_time)",
        applies_to=["summary", "trends"],
    ),
    KpiDefinition(
        name="max_ack_delay",
        display_name="Maximum Acknowledgement Delay",
        description="Worst acknowledgement delay in scope.",
        unit="seconds",
        formula="max(ack_time - start_time)",
        applies_to=["summary"],
    ),
    KpiDefinition(
        name="avg_duration",
        display_name="Average Alarm Duration",
        description="Mean time an alarm remained in the alarm state.",
        unit="seconds",
        formula="mean(clear_time - start_time)",
        applies_to=["summary", "trends"],
    ),
    KpiDefinition(
        name="mttr_seconds",
        display_name="Mean Time To Resolve",
        description="Mean duration of cleared alarms.",
        unit="seconds",
        formula="mean(clear_time - start_time) where status = 'cleared'",
        applies_to=["summary"],
    ),
    KpiDefinition(
        name="suppression_candidate_rate",
        display_name="Suppression Candidate Rate",
        description=(
            "Share of alarms that are suppressed or shorter than the chattering "
            f"threshold of {CHATTER_DURATION_SECONDS}s."
        ),
        unit="ratio",
        formula="count(suppressed or duration < 300s) / count(alarms)",
        applies_to=["summary"],
    ),
    KpiDefinition(
        name="distinct_assets",
        display_name="Distinct Assets",
        description="Number of distinct assets contributing alarms in scope.",
        unit="count",
        formula="count(distinct asset_id)",
        applies_to=["summary"],
    ),
)


def default_time_range() -> TimeRange:
    """A sensible 90-day window ending at the dataset horizon."""
    return TimeRange(start_time=DATA_NOW - timedelta(days=90), end_time=DATA_NOW)

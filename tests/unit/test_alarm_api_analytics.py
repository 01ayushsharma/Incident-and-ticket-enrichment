"""Tests for the simulator's analytical endpoints.

These check that the computations mean something - that a flood window is
actually dense, that a correlation pair really co-occurs, that a priority
score's factors sum to its total - rather than merely that a 200 came back.
"""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise

import pytest
from alarm_api.domain import analytics
from alarm_api.schemas import (
    Bucket,
    CorrelationRequest,
    Severity,
    TimeRange,
)

from tests.conftest import AUTH_HEADERS, POSTMAN_END, POSTMAN_START

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
def test_summary_totals_match_the_sum_of_its_groups(client, bfp101_id, time_range):
    response = client.post(
        "/alarms/summary",
        json={
            "asset_ids": [bfp101_id],
            "time_range": time_range,
            "group_by": ["alarm_name"],
            "kpis": ["alarm_count"],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    summed = sum(g["metrics"]["alarm_count"] for g in body["groups"])
    assert summed == body["total_alarms"]


def test_summary_supports_multi_field_grouping(client, time_range):
    response = client.post(
        "/alarms/summary",
        json={
            "unit": "Unit 2",
            "time_range": time_range,
            "group_by": ["asset_id", "asset_name", "severity"],
            "kpis": ["alarm_count"],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    groups = response.json()["groups"]
    assert groups
    assert set(groups[0]["key"]) == {"asset_id", "asset_name", "severity"}


def test_summary_severity_filter_excludes_other_severities(client, time_range):
    response = client.post(
        "/alarms/summary",
        json={
            "unit": "Unit 1",
            "time_range": time_range,
            "severity": ["critical"],
            "group_by": ["severity"],
            "kpis": ["alarm_count"],
        },
        headers=AUTH_HEADERS,
    )
    groups = response.json()["groups"]
    assert {g["key"]["severity"] for g in groups} <= {"critical"}


def test_summary_rejects_an_unknown_group_by_field(client, time_range):
    response = client.post(
        "/alarms/summary",
        json={"time_range": time_range, "group_by": ["colour"], "kpis": ["alarm_count"]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "alarm_name" in response.json()["error"]["details"]["supported"]


def test_summary_rejects_an_unknown_kpi(client, time_range):
    response = client.post(
        "/alarms/summary",
        json={"time_range": time_range, "group_by": ["severity"], "kpis": ["vibes"]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "alarm_count" in response.json()["error"]["details"]["supported"]


def test_summary_rejects_an_inverted_time_range(client):
    response = client.post(
        "/alarms/summary",
        json={
            "time_range": {
                "start_time": "2026-07-01T00:00:00Z",
                "end_time": "2026-05-01T00:00:00Z",
            },
            "group_by": ["severity"],
            "kpis": ["alarm_count"],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


def test_summary_rejects_unknown_fields_rather_than_ignoring_them(client, time_range):
    """``extra="forbid"`` catches an MCP client sending a misspelled argument."""
    response = client.post(
        "/alarms/summary",
        json={
            "time_range": time_range,
            "group_by": ["severity"],
            "kpis": ["alarm_count"],
            "assetids": ["AST-0001"],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


def test_recurring_rate_is_zero_when_every_alarm_is_distinct(dataset):
    alarms = dataset.alarms[:1]
    assert analytics.KPI_FUNCTIONS["recurring_rate"](alarms) == 0.0


def test_recurring_rate_detects_repeats(dataset, bfp101_id):
    alarms = list(dataset.alarms_by_asset[bfp101_id])[:50]
    rate = analytics.KPI_FUNCTIONS["recurring_rate"](alarms)
    assert 0.0 < rate < 1.0


# --------------------------------------------------------------------------
# Trends
# --------------------------------------------------------------------------
def test_trends_emits_a_contiguous_series_including_empty_buckets(client, bfp101_id, time_range):
    response = client.post(
        "/alarms/trends",
        json={
            "asset_ids": [bfp101_id],
            "time_range": time_range,
            "bucket": "daily",
            "metrics": ["alarm_count"],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    series = response.json()["series"]
    assert len(series) == 61  # 2026-05-01 .. 2026-07-01 exclusive
    for previous, following in pairwise(series):
        assert previous["bucket_end"] == following["bucket_start"]


def test_trends_rejects_an_hourly_bucket_over_an_absurd_span(client):
    response = client.post(
        "/alarms/trends",
        json={
            "time_range": {
                "start_time": "2020-01-01T00:00:00Z",
                "end_time": "2026-01-01T00:00:00Z",
            },
            "bucket": "hourly",
            "metrics": ["alarm_count"],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["bucket"] == "hourly"


def test_weekly_buckets_start_on_a_monday(dataset):
    from alarm_api.schemas import AlarmTrendsRequest

    result = analytics.alarm_trends(
        dataset,
        AlarmTrendsRequest(
            time_range=TimeRange(start_time=POSTMAN_START, end_time=POSTMAN_END),
            bucket=Bucket.WEEKLY,
            metrics=["alarm_count"],
        ),
    )
    assert all(p.bucket_start.weekday() == 0 for p in result.series)


# --------------------------------------------------------------------------
# Correlation
# --------------------------------------------------------------------------
def test_correlation_surfaces_a_genuine_causal_pair(client, time_range):
    """The seed injects 'High Discharge Pressure' -> 'Surge Detected' on
    compressors; correlation must find it rather than report noise."""
    search = client.get(
        "/assets/search", params={"query": "compressor", "limit": 5}, headers=AUTH_HEADERS
    ).json()["results"]
    asset_ids = [a["asset_id"] for a in search[:3]]

    response = client.post(
        "/alarms/correlation",
        json={
            "asset_ids": asset_ids,
            "time_range": time_range,
            "correlation_method": "cooccurrence",
            "severity_threshold": "medium",
            "min_support": 1,
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    pairs = response.json()["pairs"]
    assert pairs
    names = {(p["alarm_name_a"], p["alarm_name_b"]) for p in pairs}
    assert ("High Discharge Pressure", "Surge Detected") in names


def test_correlation_lag_never_exceeds_the_requested_window(client, time_range):
    response = client.post(
        "/alarms/correlation",
        json={
            "unit": "Unit 5",
            "time_range": time_range,
            "lag_window_minutes": 10,
            "severity_threshold": "medium",
            "min_support": 1,
        },
        headers=AUTH_HEADERS,
    )
    for pair in response.json()["pairs"]:
        assert pair["median_lag_seconds"] <= 10 * 60


def test_correlation_min_support_filters_weak_pairs(client, time_range):
    def pair_count(min_support: int) -> int:
        return len(
            client.post(
                "/alarms/correlation",
                json={
                    "unit": "Unit 5",
                    "time_range": time_range,
                    "severity_threshold": "medium",
                    "min_support": min_support,
                },
                headers=AUTH_HEADERS,
            ).json()["pairs"]
        )

    assert pair_count(10) <= pair_count(1)


def test_correlation_confidence_is_a_probability(client, time_range):
    response = client.post(
        "/alarms/correlation",
        json={
            "unit": "Unit 5",
            "time_range": time_range,
            "severity_threshold": "medium",
            "min_support": 1,
        },
        headers=AUTH_HEADERS,
    )
    for pair in response.json()["pairs"]:
        assert 0.0 <= pair["confidence"] <= 1.0
        assert 0.0 <= pair["correlation_score"] <= 1.0


def test_correlated_assets_exclude_nothing_but_rank_by_shared_events(client, time_range):
    response = client.post(
        "/alarms/correlation",
        json={
            "unit": "Unit 5",
            "time_range": time_range,
            "severity_threshold": "medium",
            "min_support": 1,
        },
        headers=AUTH_HEADERS,
    )
    assets = response.json()["correlated_assets"]
    assert assets
    counts = [a["shared_events"] for a in assets]
    assert counts == sorted(counts, reverse=True)


def test_severity_threshold_excludes_lower_severities(dataset):
    result = analytics.alarm_correlation(
        dataset,
        CorrelationRequest(
            unit="Unit 5",
            time_range=TimeRange(start_time=POSTMAN_START, end_time=POSTMAN_END),
            severity_threshold=Severity.CRITICAL,
            min_support=1,
        ),
    )
    high_result = analytics.alarm_correlation(
        dataset,
        CorrelationRequest(
            unit="Unit 5",
            time_range=TimeRange(start_time=POSTMAN_START, end_time=POSTMAN_END),
            severity_threshold=Severity.LOW,
            min_support=1,
        ),
    )
    assert len(result.pairs) <= len(high_result.pairs)


# --------------------------------------------------------------------------
# Flood analysis
# --------------------------------------------------------------------------
def test_flood_analysis_finds_the_seeded_unit_2_burst(client, time_range):
    response = client.post(
        "/alarms/flood-analysis",
        json={
            "unit": "Unit 2",
            "time_range": time_range,
            "threshold_count": 10,
            "rolling_window_minutes": 10,
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    windows = response.json()["flood_windows"]
    assert windows, "Postman CHAIN-02 reads flood_windows[0]"
    top = windows[0]
    assert top["alarm_count"] >= 10
    assert top["start"] < top["end"]
    assert top["dominant_alarm_name"]
    assert top["asset_ids"]


def test_flood_windows_actually_contain_the_alarms_they_claim(client, dataset, time_range):
    response = client.post(
        "/alarms/flood-analysis",
        json={
            "unit": "Unit 2",
            "time_range": time_range,
            "threshold_count": 10,
            "rolling_window_minutes": 10,
        },
        headers=AUTH_HEADERS,
    )
    window = response.json()["flood_windows"][0]
    start = datetime.fromisoformat(window["start"])
    end = datetime.fromisoformat(window["end"])
    actual = [a for a in dataset.alarms if a.unit == "Unit 2" and start <= a.start_time <= end]
    assert len(actual) == window["alarm_count"]


def test_an_impossible_threshold_yields_no_flood_windows(client, time_range):
    response = client.post(
        "/alarms/flood-analysis",
        json={
            "unit": "Unit 2",
            "time_range": time_range,
            "threshold_count": 10_000,
            "rolling_window_minutes": 10,
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["flood_windows"] == []
    assert response.json()["total_alarms_in_floods"] == 0


# --------------------------------------------------------------------------
# Rationalization
# --------------------------------------------------------------------------
def test_rationalization_returns_candidates_with_a_reason_and_advice(client, time_range):
    response = client.post(
        "/alarms/rationalization-candidates",
        json={
            "site": "NorthPlant",
            "unit": "Unit 1",
            "time_range": time_range,
            "recurrence_threshold": 6,
            "stale_minutes_threshold": 180,
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert candidates
    for candidate in candidates:
        assert candidate["reason"] in {"recurring", "stale", "chattering"}
        assert candidate["recommendation"]


def test_every_recurring_candidate_meets_the_threshold(client, time_range):
    threshold = 8
    response = client.post(
        "/alarms/rationalization-candidates",
        json={"unit": "Unit 2", "time_range": time_range, "recurrence_threshold": threshold},
        headers=AUTH_HEADERS,
    )
    for candidate in response.json()["candidates"]:
        if candidate["reason"] in {"recurring", "chattering"}:
            assert candidate["occurrences"] >= threshold


def test_raising_the_threshold_cannot_increase_the_candidate_count(client, time_range):
    def count(threshold: int) -> int:
        return len(
            client.post(
                "/alarms/rationalization-candidates",
                json={
                    "unit": "Unit 2",
                    "time_range": time_range,
                    "recurrence_threshold": threshold,
                    "stale_minutes_threshold": 180,
                },
                headers=AUTH_HEADERS,
            ).json()["candidates"]
        )

    assert count(50) <= count(5)


# --------------------------------------------------------------------------
# Priority scoring
# --------------------------------------------------------------------------
def test_priority_factor_contributions_sum_to_the_score(client):
    listing = client.get(
        "/alarms",
        params={"site": "EastRefinery", "status": "active", "page_size": 5},
        headers=AUTH_HEADERS,
    ).json()["data"]
    alarm_id = listing[0]["alarm_id"]

    response = client.post(
        "/alarms/priority-score", json={"alarm_id": alarm_id}, headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    total = sum(f["contribution"] for f in body["factors"])
    assert abs(total - body["priority_score"]) < 0.05
    assert 0.0 <= body["priority_score"] <= 100.0
    assert body["rationale"]


def test_priority_weights_sum_to_one(client):
    listing = client.get("/alarms", params={"page_size": 1}, headers=AUTH_HEADERS).json()
    alarm_id = listing["data"][0]["alarm_id"]
    response = client.post(
        "/alarms/priority-score", json={"alarm_id": alarm_id}, headers=AUTH_HEADERS
    )
    weights = sum(f["weight"] for f in response.json()["factors"])
    assert abs(weights - 1.0) < 1e-9


def test_a_critical_alarm_outranks_a_low_one_on_the_same_asset(dataset):
    by_asset: dict[str, dict[str, object]] = {}
    for alarm in dataset.alarms:
        slot = by_asset.setdefault(alarm.asset_id, {})
        slot.setdefault(alarm.severity.value, alarm)

    pair = next((v for v in by_asset.values() if "critical" in v and "low" in v), None)
    assert pair is not None, "dataset should contain an asset with both severities"
    critical = analytics.priority_score(dataset, pair["critical"]).priority_score
    low = analytics.priority_score(dataset, pair["low"]).priority_score
    assert critical > low


def test_priority_score_for_an_unknown_alarm_is_a_404(client):
    response = client.post(
        "/alarms/priority-score", json={"alarm_id": "ALM-NOPE"}, headers=AUTH_HEADERS
    )
    assert response.status_code == 404


def test_priority_score_rejects_a_blank_alarm_id(client):
    response = client.post("/alarms/priority-score", json={"alarm_id": ""}, headers=AUTH_HEADERS)
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Operator recommendations
# --------------------------------------------------------------------------
def test_recommendations_are_ranked_and_non_empty(client):
    listing = client.get(
        "/alarms",
        params={"site": "EastRefinery", "status": "active", "page_size": 1},
        headers=AUTH_HEADERS,
    ).json()["data"]
    alarm_id = listing[0]["alarm_id"]

    response = client.post(
        "/recommendations/operator-actions",
        json={
            "alarm_id": alarm_id,
            "include_related": True,
            "include_asset_context": True,
            "include_historical_pattern": True,
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    ranks = [a["rank"] for a in body["recommended_actions"]]
    assert ranks == list(range(1, len(ranks) + 1))
    assert body["asset_context"] is not None
    assert body["historical_pattern"] is not None
    assert body["historical_pattern"]["trend"] in {"increasing", "stable", "decreasing"}


def test_optional_blocks_are_omitted_when_not_requested(client):
    listing = client.get("/alarms", params={"page_size": 1}, headers=AUTH_HEADERS).json()
    alarm_id = listing["data"][0]["alarm_id"]
    response = client.post(
        "/recommendations/operator-actions",
        json={"alarm_id": alarm_id},
        headers=AUTH_HEADERS,
    )
    body = response.json()
    assert body["asset_context"] is None
    assert body["historical_pattern"] is None
    assert body["related_alarms"] == []


def test_alarm_specific_advice_beats_the_generic_fallback(dataset):
    """A pump discharge-temperature alarm should get cooling-water advice."""
    from alarm_api.schemas import RecommendationRequest

    alarm = next(a for a in dataset.alarms if a.alarm_name == "High Discharge Temperature")
    result = analytics.operator_recommendations(
        dataset, alarm, RecommendationRequest(alarm_id=alarm.alarm_id)
    )
    assert "cooling water" in result.recommended_actions[0].action.lower()


def test_likely_causes_carry_descending_confidence(dataset):
    from alarm_api.schemas import RecommendationRequest

    alarm = next(a for a in dataset.alarms if a.alarm_name == "High Vibration")
    result = analytics.operator_recommendations(
        dataset, alarm, RecommendationRequest(alarm_id=alarm.alarm_id)
    )
    confidences = [c.confidence for c in result.likely_causes]
    assert confidences == sorted(confidences, reverse=True)


# --------------------------------------------------------------------------
# Calculations and KPI catalogue
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "calculation_type",
    [
        "alarm_flood_index",
        "critical_alarm_density",
        "operator_response_efficiency",
        "nuisance_alarm_score",
    ],
)
def test_every_calculation_type_generates_and_executes(client, calculation_type, time_range):
    filters = {"unit": "Unit 3", **{k: time_range[k] for k in ("start_time", "end_time")}}
    generated = client.post(
        "/calculation-code/generate",
        json={"calculation_type": calculation_type, "filters": filters},
        headers=AUTH_HEADERS,
    )
    assert generated.status_code == 200
    body = generated.json()
    assert body["language"] == "python"
    assert body["code"].strip()

    executed = client.post(
        "/calculation-code/execute",
        json={"calculation_id": body["calculation_id"], "filters": filters},
        headers=AUTH_HEADERS,
    )
    assert executed.status_code == 200
    result = executed.json()
    assert result["calculation_type"] == calculation_type
    assert calculation_type in result["result"]


def test_generating_the_same_calculation_twice_is_idempotent(client, time_range):
    payload = {
        "calculation_type": "nuisance_alarm_score",
        "filters": {
            "unit": "Unit 4",
            "start_time": time_range["start_time"],
            "end_time": time_range["end_time"],
        },
    }
    first = client.post("/calculation-code/generate", json=payload, headers=AUTH_HEADERS)
    second = client.post("/calculation-code/generate", json=payload, headers=AUTH_HEADERS)
    assert first.json()["calculation_id"] == second.json()["calculation_id"]


def test_executing_an_unknown_calculation_id_returns_404(client):
    response = client.post(
        "/calculation-code/execute",
        json={"calculation_id": "00000000-0000-0000-0000-000000000000"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404
    assert "generate" in response.json()["error"]["details"]["hint"]


def test_unknown_calculation_type_is_rejected_at_the_schema(client, time_range):
    response = client.post(
        "/calculation-code/generate",
        json={
            "calculation_type": "make_me_a_sandwich",
            "filters": {
                "unit": "Unit 3",
                "start_time": time_range["start_time"],
                "end_time": time_range["end_time"],
            },
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


def test_kpi_definitions_cover_every_implemented_kpi(client):
    response = client.get("/analytics/kpi-definitions", headers=AUTH_HEADERS)
    assert response.status_code == 200
    documented = {k["name"] for k in response.json()["kpis"]}
    assert documented == set(analytics.KPI_FUNCTIONS), (
        "every computable KPI must be documented, and vice versa"
    )


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------
def test_the_dataset_is_reproducible_from_its_seed():
    from alarm_api.domain.seed import build_dataset

    first = build_dataset(4242)
    second = build_dataset(4242)
    assert len(first.alarms) == len(second.alarms)
    assert [a.alarm_id for a in first.alarms[:200]] == [a.alarm_id for a in second.alarms[:200]]
    assert first.alarms[100] == second.alarms[100]


def test_a_different_seed_produces_a_different_dataset():
    from alarm_api.domain.seed import build_dataset

    assert build_dataset(1).alarms[50] != build_dataset(2).alarms[50]

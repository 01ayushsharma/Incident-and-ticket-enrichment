"""Replay of the ten multi-step flows in ``postman/chaining/``.

Each test mirrors one CHAIN-nn folder from
``Alarm-API-Chaining.postman_collection.json``, including the variable
chaining the collection performs in its ``pm.collectionVariables.set`` test
scripts and the assertions it makes. These are the executable form of the
API contract: if the simulator drifts from the collection, these fail.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

AUTH = {"Authorization": "Bearer demo-token"}
TRACE = {
    **AUTH,
    "trace_id": "trace-chain-001",
    "x-client-id": "postman-chain",
    "x-metadata-tag": "chain-test",
}

START = "2026-05-01T00:00:00Z"
END = "2026-07-01T00:00:00Z"
WINDOW = {"start_time": START, "end_time": END}


def _ok(response, step: str):
    """Assert a 200 and return the JSON body, naming the step on failure."""
    assert response.status_code == 200, f"{step}: {response.status_code} {response.text[:400]}"
    return response.json()


def _search_one(client, query: str, **params) -> str:
    body = _ok(
        client.get("/assets/search", params={"query": query, "limit": 5, **params}, headers=AUTH),
        f"search '{query}'",
    )
    assert body["results"], f"search '{query}' must return at least one asset"
    return body["results"][0]["asset_id"]


# --------------------------------------------------------------------------
def test_chain_01_asset_summary_rationalization(client):
    """CHAIN-01 Asset -> Summary -> Rationalization."""
    asset_id = _search_one(client, "Boiler Feed Pump 101")

    summary = _ok(
        client.post(
            "/alarms/summary",
            json={
                "asset_ids": [asset_id],
                "time_range": WINDOW,
                "severity": ["high", "critical"],
                "group_by": ["alarm_name"],
                "kpis": ["alarm_count", "recurring_rate", "avg_ack_delay"],
            },
            headers=TRACE,
        ),
        "summary",
    )
    assert summary["total_alarms"] > 0
    assert summary["groups"]

    rationalization = _ok(
        client.post(
            "/alarms/rationalization-candidates",
            json={"asset_ids": [asset_id], "time_range": WINDOW, "recurrence_threshold": 5},
            headers=AUTH,
        ),
        "rationalization",
    )
    assert isinstance(rationalization["candidates"], list)


def test_chain_02_flood_alarms_summary(client):
    """CHAIN-02 Flood -> Alarms for the flood window -> Summary."""
    flood = _ok(
        client.post(
            "/alarms/flood-analysis",
            json={
                "unit": "Unit 2",
                "time_range": WINDOW,
                "threshold_count": 10,
                "rolling_window_minutes": 10,
            },
            headers=AUTH,
        ),
        "flood-analysis",
    )
    windows = flood["flood_windows"]
    assert windows, "CHAIN-02 reads flood_windows[0]"
    window_start, window_end = windows[0]["start"], windows[0]["end"]

    alarms = _ok(
        client.get(
            "/alarms",
            params={
                "unit": "Unit 2",
                "start_time": window_start,
                "end_time": window_end,
                "page": 1,
                "page_size": 200,
            },
            headers=AUTH,
        ),
        "alarms in flood window",
    )
    assert alarms["data"], "the flood window must contain alarms"

    summary = _ok(
        client.post(
            "/alarms/summary",
            json={
                "unit": "Unit 2",
                "time_range": WINDOW,
                "group_by": ["asset_id", "asset_name", "severity"],
                "kpis": ["alarm_count"],
            },
            headers=AUTH,
        ),
        "summary by asset+severity",
    )
    assert summary["groups"]


def test_chain_03_root_cause_and_recommendations(client):
    """CHAIN-03 Compressors -> Correlation -> Latest alarm -> Metadata -> Recommendations."""
    results = _ok(
        client.get("/assets/search", params={"query": "compressor", "limit": 5}, headers=AUTH),
        "search compressors",
    )["results"]
    assert results
    ids = [r["asset_id"] for r in results[:3]]
    while len(ids) < 3:
        ids.append(ids[0])

    correlation = _ok(
        client.post(
            "/alarms/correlation",
            json={
                "asset_ids": ids,
                "time_range": WINDOW,
                "correlation_method": "cooccurrence",
                "severity_threshold": "medium",
                "min_support": 1,
            },
            headers=TRACE,
        ),
        "correlation",
    )
    assert "pairs" in correlation and "correlated_assets" in correlation

    latest = _ok(
        client.get(
            "/alarms",
            params={
                "asset_id": ids[0],
                "page": 1,
                "page_size": 1,
                "sort_by": "start_time",
                "sort_order": "desc",
            },
            headers=AUTH,
        ),
        "latest alarm",
    )
    assert latest["data"]
    alarm_id = latest["data"][0]["alarm_id"]

    metadata = _ok(client.get(f"/assets/{ids[0]}/metadata", headers=AUTH), "asset metadata")
    assert metadata["asset_id"] == ids[0]

    recommendations = _ok(
        client.post(
            "/recommendations/operator-actions",
            json={"alarm_id": alarm_id, "include_related": True},
            headers=TRACE,
        ),
        "recommendations",
    )
    assert recommendations["recommended_actions"]


def test_chain_04_critical_density_execute_summary(client):
    """CHAIN-04 Generate -> Execute -> Summary."""
    generated = _ok(
        client.post(
            "/calculation-code/generate",
            json={
                "calculation_type": "critical_alarm_density",
                "filters": {"unit": "Unit 3", "start_time": START, "end_time": END},
            },
            headers=AUTH,
        ),
        "generate",
    )
    calculation_id = generated["calculation_id"]

    executed = _ok(
        client.post(
            "/calculation-code/execute",
            json={
                "calculation_id": calculation_id,
                "filters": {"unit": "Unit 3", "start_time": START, "end_time": END},
            },
            headers=TRACE,
        ),
        "execute",
    )
    assert "critical_alarm_density" in executed["result"]

    summary = _ok(
        client.post(
            "/alarms/summary",
            json={
                "unit": "Unit 3",
                "time_range": WINDOW,
                "group_by": ["asset_id", "asset_name"],
                "kpis": ["alarm_count", "critical_count"],
            },
            headers=AUTH,
        ),
        "summary",
    )
    assert summary["groups"]


def test_chain_05_active_alarm_to_recommendation(client):
    """CHAIN-05 Search BFP 102 -> Active alarms -> Recommendations."""
    asset_id = _search_one(client, "Boiler Feed Pump 102")

    active = _ok(
        client.get(
            "/alarms",
            params={"asset_id": asset_id, "status": "active", "page": 1, "page_size": 20},
            headers=AUTH,
        ),
        "active alarms",
    )
    rows = active["data"]
    if not rows:
        # The collection guards this step with `if (rows.length > 0)`; mirror
        # that rather than inventing an assertion the collection does not make.
        pytest.skip("no active alarms on this asset in the seeded dataset")

    recommendations = _ok(
        client.post(
            "/recommendations/operator-actions",
            json={"alarm_id": rows[0]["alarm_id"], "include_related": True},
            headers=TRACE,
        ),
        "recommendations",
    )
    assert recommendations["recommended_actions"]


def test_chain_06_stale_and_severity_context(client):
    """CHAIN-06 Rationalization -> Summary by severity."""
    rationalization = _ok(
        client.post(
            "/alarms/rationalization-candidates",
            json={
                "site": "NorthPlant",
                "unit": "Unit 1",
                "time_range": WINDOW,
                "stale_minutes_threshold": 180,
                "recurrence_threshold": 6,
            },
            headers=AUTH,
        ),
        "rationalization",
    )
    assert rationalization["candidates"]

    summary = _ok(
        client.post(
            "/alarms/summary",
            json={
                "site": "NorthPlant",
                "unit": "Unit 1",
                "time_range": WINDOW,
                "group_by": ["severity"],
                "kpis": ["alarm_count", "suppression_candidate_rate"],
            },
            headers=AUTH,
        ),
        "summary by severity",
    )
    assert summary["groups"]
    for group in summary["groups"]:
        assert 0.0 <= group["metrics"]["suppression_candidate_rate"] <= 1.0


def test_chain_07_response_efficiency_and_trend(client):
    """CHAIN-07 Generate -> Execute -> Trends, scoped to SouthPlant."""
    generated = _ok(
        client.post(
            "/calculation-code/generate",
            json={
                "calculation_type": "operator_response_efficiency",
                "filters": {"site": "SouthPlant", "start_time": START, "end_time": END},
            },
            headers=AUTH,
        ),
        "generate",
    )
    executed = _ok(
        client.post(
            "/calculation-code/execute",
            json={
                "calculation_id": generated["calculation_id"],
                "filters": {"site": "SouthPlant", "start_time": START, "end_time": END},
            },
            headers=TRACE,
        ),
        "execute",
    )
    efficiency = executed["result"]["operator_response_efficiency"]
    assert 0.0 <= efficiency <= 1.0

    trends = _ok(
        client.post(
            "/alarms/trends",
            json={
                "site": "SouthPlant",
                "time_range": WINDOW,
                "bucket": "daily",
                "metrics": ["avg_ack_delay"],
            },
            headers=AUTH,
        ),
        "trends",
    )
    assert trends["series"]


def test_chain_08_motor_correlation(client):
    """CHAIN-08 Motors in Unit 5 -> Correlation at high severity -> Summary."""
    results = _ok(
        client.get(
            "/assets/search",
            params={"query": "motor", "unit": "Unit 5", "limit": 5},
            headers=AUTH,
        ),
        "search motors in Unit 5",
    )["results"]
    assert results, "CHAIN-08 asserts results.length > 0"
    ids = [r["asset_id"] for r in results[:3]]
    while len(ids) < 3:
        ids.append(ids[0])

    correlation = _ok(
        client.post(
            "/alarms/correlation",
            json={
                "asset_ids": ids,
                "time_range": WINDOW,
                "severity_threshold": "high",
                "correlation_method": "cooccurrence",
                "min_support": 1,
            },
            headers=TRACE,
        ),
        "correlation",
    )
    # The seed injects "Motor Winding Temperature High" -> "Motor Overload Trip"
    # on motors, both at high severity, so this filter must still find pairs.
    assert correlation["pairs"], "high-severity motor correlation must find the seeded pair"

    summary = _ok(
        client.post(
            "/alarms/summary",
            json={
                "unit": "Unit 5",
                "time_range": WINDOW,
                "alarm_types": ["safety", "device"],
                "group_by": ["asset_id", "alarm_name"],
                "kpis": ["alarm_count"],
            },
            headers=AUTH,
        ),
        "summary",
    )
    assert summary["groups"]


def test_chain_09_east_active_priority_recommendation(client):
    """CHAIN-09 EastRefinery actives -> Detail -> Priority -> Recommendations."""
    listing = _ok(
        client.get(
            "/alarms",
            params={
                "site": "EastRefinery",
                "status": "active",
                "page": 1,
                "page_size": 50,
                "sort_by": "start_time",
                "sort_order": "desc",
            },
            headers=AUTH,
        ),
        "EastRefinery active alarms",
    )
    rows = listing["data"]
    assert rows, "CHAIN-09 asserts rows.length > 0"
    alarm_id = rows[0]["alarm_id"]

    detail = _ok(client.get(f"/alarms/{alarm_id}", headers=AUTH), "alarm detail")
    assert detail["alarm_id"] == alarm_id

    priority = _ok(
        client.post("/alarms/priority-score", json={"alarm_id": alarm_id}, headers=AUTH),
        "priority score",
    )
    assert priority["priority_band"] in {"P1", "P2", "P3", "P4"}

    recommendations = _ok(
        client.post(
            "/recommendations/operator-actions", json={"alarm_id": alarm_id}, headers=TRACE
        ),
        "recommendations",
    )
    assert recommendations["recommended_actions"]


def test_chain_10_nuisance_kpi_execute_candidates(client):
    """CHAIN-10 Generate -> Execute -> Rationalization, scoped to Unit 4."""
    generated = _ok(
        client.post(
            "/calculation-code/generate",
            json={
                "calculation_type": "nuisance_alarm_score",
                "filters": {"unit": "Unit 4", "start_time": START, "end_time": END},
            },
            headers=AUTH,
        ),
        "generate",
    )
    executed = _ok(
        client.post(
            "/calculation-code/execute",
            json={
                "calculation_id": generated["calculation_id"],
                "filters": {"unit": "Unit 4", "start_time": START, "end_time": END},
            },
            headers=TRACE,
        ),
        "execute",
    )
    assert 0.0 <= executed["result"]["nuisance_alarm_score"] <= 1.0

    rationalization = _ok(
        client.post(
            "/alarms/rationalization-candidates",
            json={"unit": "Unit 4", "time_range": WINDOW, "recurrence_threshold": 8},
            headers=AUTH,
        ),
        "rationalization",
    )
    assert isinstance(rationalization["candidates"], list)


def test_every_chained_step_propagates_the_same_trace_id(client):
    """Trace continuity is what makes a multi-step chain debuggable."""
    responses = [
        client.get("/assets/search", params={"query": "pump", "limit": 1}, headers=TRACE),
        client.post(
            "/alarms/summary",
            json={"time_range": WINDOW, "group_by": ["severity"], "kpis": ["alarm_count"]},
            headers=TRACE,
        ),
        client.get("/analytics/kpi-definitions", headers=TRACE),
    ]
    assert {r.headers["trace_id"] for r in responses} == {"trace-chain-001"}

"""Contract tests for the Alarm Management API simulator.

These assert the behaviours the Postman collections depend on: the response
shapes, the authentication policy, trace echoing, pagination, sorting and the
error envelope. If one of these breaks, the MCP server's tool contracts break
with it.
"""

from __future__ import annotations

import pytest

from tests.conftest import AUTH_HEADERS, TRACE_HEADERS

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Health and authentication
# --------------------------------------------------------------------------
def test_health_requires_no_authentication(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dataset"]["alarms"] > 0
    assert body["dataset"]["assets"] > 0


@pytest.mark.parametrize(
    "path,method",
    [
        ("/assets/search?query=pump", "get"),
        ("/assets/AST-0001/metadata", "get"),
        ("/alarms", "get"),
        ("/alarms/ALM-000001", "get"),
        ("/analytics/kpi-definitions", "get"),
    ],
)
def test_protected_endpoints_reject_anonymous_requests(client, path, method):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthenticated"
    assert body["trace_id"]


def test_invalid_token_is_rejected_without_revealing_the_expected_value(client):
    response = client.get(
        "/assets/search?query=pump", headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401
    serialised = response.text.lower()
    assert "demo-token" not in serialised
    assert "wrong-token" not in serialised


def test_malformed_authorization_scheme_is_rejected(client):
    response = client.get("/assets/search?query=pump", headers={"Authorization": "Basic abc123"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


# --------------------------------------------------------------------------
# Trace propagation
# --------------------------------------------------------------------------
def test_inbound_trace_metadata_is_echoed_on_the_response(client):
    response = client.get("/assets/search?query=pump", headers=TRACE_HEADERS)
    assert response.status_code == 200
    assert response.headers["trace_id"] == "trace-pytest-001"
    assert response.headers["x-client-id"] == "pytest-client"
    assert response.headers["x-metadata-tag"] == "automated-test"
    assert response.headers["x-request-id"]


def test_trace_id_is_generated_when_the_caller_supplies_none(client):
    response = client.get("/assets/search?query=pump", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.headers["trace_id"].startswith("trace-")


def test_w3c_traceparent_is_accepted_as_an_alias(client):
    traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    response = client.get(
        "/assets/search?query=pump",
        headers={**AUTH_HEADERS, "traceparent": traceparent},
    )
    assert response.headers["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_error_responses_also_carry_the_trace_id(client):
    response = client.get("/alarms/ALM-DOES-NOT-EXIST", headers=TRACE_HEADERS)
    assert response.status_code == 404
    assert response.json()["trace_id"] == "trace-pytest-001"


# --------------------------------------------------------------------------
# Asset search
# --------------------------------------------------------------------------
def test_asset_search_ranks_an_exact_name_match_first(client):
    response = client.get(
        "/assets/search",
        params={"query": "Boiler Feed Pump 101", "limit": 10},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results, "the acceptance scenario's asset must be resolvable"
    assert results[0]["asset_name"] == "Boiler Feed Pump 101"


def test_asset_search_is_case_insensitive_and_matches_substrings(client):
    response = client.get(
        "/assets/search", params={"query": "COMPRESSOR", "limit": 5}, headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) >= 1
    assert all("compressor" in r["asset_name"].lower() for r in results)


def test_asset_search_honours_the_unit_filter(client):
    response = client.get(
        "/assets/search",
        params={"query": "motor", "unit": "Unit 5", "limit": 5},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) >= 1
    assert {r["unit"] for r in results} == {"Unit 5"}


def test_asset_search_respects_the_limit(client):
    response = client.get("/assets/search", params={"query": "p", "limit": 3}, headers=AUTH_HEADERS)
    assert len(response.json()["results"]) <= 3


def test_asset_search_rejects_an_empty_query(client):
    response = client.get("/assets/search", params={"query": ""}, headers=AUTH_HEADERS)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_asset_metadata_returns_a_helpful_404(client):
    response = client.get("/assets/AST-9999/metadata", headers=AUTH_HEADERS)
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["details"]["asset_id"] == "AST-9999"


# --------------------------------------------------------------------------
# Alarm listing, pagination and sorting
# --------------------------------------------------------------------------
def test_alarm_list_returns_data_and_pagination(client, bfp101_id):
    response = client.get(
        "/alarms",
        params={"asset_id": bfp101_id, "page": 1, "page_size": 25},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) <= 25
    pagination = body["pagination"]
    assert pagination["page"] == 1
    assert pagination["page_size"] == 25
    assert pagination["total_items"] >= len(body["data"])
    assert pagination["has_previous"] is False


def test_pagination_pages_do_not_overlap_and_cover_the_result_set(client, bfp101_id):
    first = client.get(
        "/alarms",
        params={"asset_id": bfp101_id, "page": 1, "page_size": 20},
        headers=AUTH_HEADERS,
    ).json()
    second = client.get(
        "/alarms",
        params={"asset_id": bfp101_id, "page": 2, "page_size": 20},
        headers=AUTH_HEADERS,
    ).json()

    ids_first = {a["alarm_id"] for a in first["data"]}
    ids_second = {a["alarm_id"] for a in second["data"]}
    assert not ids_first & ids_second, "pages must be disjoint"
    assert second["pagination"]["has_previous"] is True


def test_page_beyond_the_end_returns_an_empty_page_not_an_error(client, bfp101_id):
    response = client.get(
        "/alarms",
        params={"asset_id": bfp101_id, "page": 9999, "page_size": 50},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["data"] == []


def test_page_size_above_the_maximum_is_rejected(client):
    response = client.get("/alarms", params={"page_size": 100000}, headers=AUTH_HEADERS)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_descending_sort_by_start_time_is_actually_descending(client, bfp101_id):
    response = client.get(
        "/alarms",
        params={
            "asset_id": bfp101_id,
            "sort_by": "start_time",
            "sort_order": "desc",
            "page_size": 30,
        },
        headers=AUTH_HEADERS,
    )
    times = [a["start_time"] for a in response.json()["data"]]
    assert times == sorted(times, reverse=True)


def test_sorting_by_severity_orders_by_rank_not_alphabetically(client):
    response = client.get(
        "/alarms",
        params={"sort_by": "severity", "sort_order": "desc", "page_size": 40},
        headers=AUTH_HEADERS,
    )
    severities = [a["severity"] for a in response.json()["data"]]
    # Alphabetically "low" > "high"; by rank, critical must lead.
    assert severities[0] == "critical"


def test_unsupported_sort_field_is_rejected_with_the_allowed_list(client):
    response = client.get("/alarms", params={"sort_by": "nonsense"}, headers=AUTH_HEADERS)
    assert response.status_code == 400
    assert "start_time" in response.json()["error"]["details"]["sortable_fields"]


def test_status_filter_narrows_to_active_alarms(client):
    response = client.get(
        "/alarms",
        params={"site": "EastRefinery", "status": "active", "page_size": 50},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    # Postman CHAIN-09 asserts this is non-empty.
    assert rows, "EastRefinery must expose active alarms"
    assert {r["status"] for r in rows} == {"active"}
    assert {r["site"] for r in rows} == {"EastRefinery"}


def test_time_window_filter_excludes_alarms_outside_the_range(client, time_range):
    response = client.get(
        "/alarms",
        params={
            "start_time": time_range["start_time"],
            "end_time": time_range["end_time"],
            "page_size": 100,
        },
        headers=AUTH_HEADERS,
    )
    rows = response.json()["data"]
    assert rows
    for row in rows:
        assert time_range["start_time"].rstrip("Z") <= row["start_time"].rstrip("Z")
        assert row["start_time"].rstrip("Z") < time_range["end_time"].rstrip("Z")


def test_inverted_time_window_is_rejected(client):
    response = client.get(
        "/alarms",
        params={"start_time": "2026-07-01T00:00:00Z", "end_time": "2026-05-01T00:00:00Z"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400


def test_unknown_asset_id_filter_returns_404_rather_than_an_empty_list(client):
    response = client.get("/alarms", params={"asset_id": "AST-NOPE"}, headers=AUTH_HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["details"]["unknown_asset_ids"] == ["AST-NOPE"]


# --------------------------------------------------------------------------
# Alarm detail
# --------------------------------------------------------------------------
def test_alarm_detail_includes_asset_context_and_recurrence(client, bfp101_id):
    listing = client.get(
        "/alarms", params={"asset_id": bfp101_id, "page_size": 1}, headers=AUTH_HEADERS
    ).json()
    alarm_id = listing["data"][0]["alarm_id"]

    response = client.get(f"/alarms/{alarm_id}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["alarm_id"] == alarm_id
    assert body["asset"]["asset_id"] == bfp101_id
    assert body["occurrences_last_90_days"] >= 1
    assert isinstance(body["related_alarm_ids"], list)


def test_unknown_alarm_detail_returns_404(client):
    response = client.get("/alarms/ALM-000000", headers=AUTH_HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

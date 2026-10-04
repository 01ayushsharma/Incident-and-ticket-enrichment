"""Tests for the mock ticketing API.

Particular attention to the write path: it is the only state-changing
operation in the system, and the guidelines treat an unguarded write as a
red flag. Confirmation, idempotency and authentication are all covered here.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

TICKET_AUTH = {"Authorization": "Bearer demo-ticket-token"}


def _create_payload(**overrides) -> dict:
    payload = {
        "title": "High Discharge Temperature on Boiler Feed Pump 101",
        "description": "Drafted by the copilot from alarm ALM-005007.",
        "priority": "P1",
        "asset_id": "AST-0001",
        "asset_name": "Boiler Feed Pump 101",
        "alarm_name": "High Discharge Temperature",
        "linked_alarm_ids": ["ALM-005007"],
        "confirmed": True,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Health, auth, reads
# --------------------------------------------------------------------------
def test_health_is_unauthenticated_and_reports_the_corpus(ticketing_client):
    response = ticketing_client.get("/health")
    assert response.status_code == 200
    dataset = response.json()["dataset"]
    assert dataset["tickets"] > 0
    assert dataset["open_tickets"] > 0


@pytest.mark.parametrize("path", ["/tickets", "/tickets/fields", "/tickets/INC-1001"])
def test_reads_require_authentication(ticketing_client, path):
    assert ticketing_client.get(path).status_code == 401


def test_invalid_token_does_not_leak_the_expected_value(ticketing_client):
    response = ticketing_client.get("/tickets", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401
    assert "demo-ticket-token" not in response.text


def test_open_only_returns_only_open_and_in_progress(ticketing_client):
    response = ticketing_client.get(
        "/tickets", params={"open_only": True, "page_size": 100}, headers=TICKET_AUTH
    )
    assert response.status_code == 200
    statuses = {t["status"] for t in response.json()["data"]}
    assert statuses <= {"open", "in_progress"}


def test_filtering_by_multiple_asset_ids_supports_correlated_assets(ticketing_client):
    """The use case asks for "open tickets linked to correlated assets"."""
    response = ticketing_client.get(
        "/tickets",
        params={"asset_ids": ["AST-0001", "AST-0002"], "page_size": 100},
        headers=TICKET_AUTH,
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows
    assert {t["asset_id"] for t in rows} <= {"AST-0001", "AST-0002"}


def test_pagination_is_disjoint(ticketing_client):
    first = ticketing_client.get(
        "/tickets", params={"page": 1, "page_size": 10}, headers=TICKET_AUTH
    ).json()
    second = ticketing_client.get(
        "/tickets", params={"page": 2, "page_size": 10}, headers=TICKET_AUTH
    ).json()
    assert not {t["key"] for t in first["data"]} & {t["key"] for t in second["data"]}


def test_page_size_above_the_maximum_is_rejected(ticketing_client):
    response = ticketing_client.get("/tickets", params={"page_size": 100000}, headers=TICKET_AUTH)
    assert response.status_code == 422


def test_unknown_ticket_returns_404(ticketing_client):
    response = ticketing_client.get("/tickets/INC-999999", headers=TICKET_AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_fields_endpoint_is_reachable_and_not_shadowed_by_the_key_route(ticketing_client):
    """`/tickets/fields` must not be captured by `/tickets/{key}`."""
    response = ticketing_client.get("/tickets/fields", headers=TICKET_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["priorities"] == ["P1", "P2", "P3", "P4"]
    assert body["open_statuses"] == ["open", "in_progress"]
    assert body["labels"]


# --------------------------------------------------------------------------
# Similarity search
# --------------------------------------------------------------------------
def test_similar_search_ranks_same_asset_and_same_alarm_first(ticketing_client):
    response = ticketing_client.post(
        "/tickets/search",
        json={
            "query": "pump discharge temperature rising, mechanical seal suspected",
            "alarm_name": "High Discharge Temperature",
            "asset_id": "AST-0001",
            "asset_type": "pump",
            "limit": 5,
        },
        headers=TICKET_AUTH,
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results
    top = results[0]
    assert top["ticket"]["asset_id"] == "AST-0001"
    assert top["ticket"]["alarm_name"] == "High Discharge Temperature"
    assert {"alarm_name", "asset"} <= set(top["matched_on"])


def test_similar_scores_are_bounded_and_descending(ticketing_client):
    response = ticketing_client.post(
        "/tickets/search",
        json={"alarm_name": "High Vibration", "asset_type": "pump", "limit": 10},
        headers=TICKET_AUTH,
    )
    scores = [r["score"] for r in response.json()["results"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_resolved_only_returns_tickets_that_carry_a_resolution(ticketing_client):
    response = ticketing_client.post(
        "/tickets/search",
        json={"alarm_name": "High Vibration", "resolved_only": True, "limit": 10},
        headers=TICKET_AUTH,
    )
    results = response.json()["results"]
    assert results
    assert all(r["ticket"]["resolution"] for r in results)


def test_exclude_keys_removes_a_ticket_from_the_results(ticketing_client):
    base = ticketing_client.post(
        "/tickets/search",
        json={"alarm_name": "High Vibration", "limit": 5},
        headers=TICKET_AUTH,
    ).json()["results"]
    assert base
    excluded = base[0]["ticket"]["key"]

    response = ticketing_client.post(
        "/tickets/search",
        json={"alarm_name": "High Vibration", "limit": 5, "exclude_keys": [excluded]},
        headers=TICKET_AUTH,
    )
    assert excluded not in {r["ticket"]["key"] for r in response.json()["results"]}


def test_search_without_any_criteria_is_rejected(ticketing_client):
    response = ticketing_client.post("/tickets/search", json={}, headers=TICKET_AUTH)
    assert response.status_code == 422
    assert "required_any_of" in response.json()["error"]["details"]


def test_an_unmatchable_query_reports_low_confidence_rather_than_guessing(ticketing_client):
    response = ticketing_client.post(
        "/tickets/search",
        json={
            "query": "quarterly marketing budget reconciliation spreadsheet",
            "min_score": 0.6,
            "limit": 5,
        },
        headers=TICKET_AUTH,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["low_confidence"] is True
    assert body["count"] == 0


def test_min_score_filters_weak_matches(ticketing_client):
    def count(min_score: float) -> int:
        return ticketing_client.post(
            "/tickets/search",
            json={"alarm_name": "High Vibration", "limit": 50, "min_score": min_score},
            headers=TICKET_AUTH,
        ).json()["count"]

    assert count(0.9) <= count(0.0)


# --------------------------------------------------------------------------
# The write path
# --------------------------------------------------------------------------
def test_creation_without_confirmation_is_refused(ticketing_client):
    response = ticketing_client.post(
        "/tickets",
        json=_create_payload(confirmed=False),
        headers={**TICKET_AUTH, "Idempotency-Key": "no-confirm-0001"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["field"] == "confirmed"


def test_creation_without_an_idempotency_key_is_refused(ticketing_client):
    response = ticketing_client.post("/tickets", json=_create_payload(), headers=TICKET_AUTH)
    assert response.status_code == 422


def test_creation_requires_authentication(ticketing_client):
    response = ticketing_client.post(
        "/tickets", json=_create_payload(), headers={"Idempotency-Key": "anon-0001"}
    )
    assert response.status_code == 401


def test_a_confirmed_create_returns_201_and_a_new_key(ticketing_client):
    response = ticketing_client.post(
        "/tickets",
        json=_create_payload(),
        headers={**TICKET_AUTH, "Idempotency-Key": "create-happy-0001"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["key"].startswith("INC-")
    assert body["status"] == "open"
    assert body["linked_alarm_ids"] == ["ALM-005007"]
    assert body["reporter"] == "alarm-copilot"


def test_replaying_an_idempotency_key_does_not_create_a_duplicate(ticketing_client):
    """The MCP server retries on 5xx; a retried create must be safe."""
    headers = {**TICKET_AUTH, "Idempotency-Key": "retry-safety-0001"}
    first = ticketing_client.post("/tickets", json=_create_payload(), headers=headers)
    second = ticketing_client.post("/tickets", json=_create_payload(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200, "a replay is not a new resource"
    assert first.json()["key"] == second.json()["key"]


def test_distinct_idempotency_keys_create_distinct_tickets(ticketing_client):
    first = ticketing_client.post(
        "/tickets",
        json=_create_payload(),
        headers={**TICKET_AUTH, "Idempotency-Key": "distinct-a-0001"},
    )
    second = ticketing_client.post(
        "/tickets",
        json=_create_payload(),
        headers={**TICKET_AUTH, "Idempotency-Key": "distinct-b-0001"},
    )
    assert first.json()["key"] != second.json()["key"]


def test_a_created_ticket_is_immediately_readable_and_searchable(ticketing_client):
    created = ticketing_client.post(
        "/tickets",
        json=_create_payload(
            title="Surge Detected on Recycle Gas Compressor 601",
            alarm_name="Surge Detected",
            asset_id="AST-0025",
        ),
        headers={**TICKET_AUTH, "Idempotency-Key": "readback-0001"},
    ).json()

    read = ticketing_client.get(f"/tickets/{created['key']}", headers=TICKET_AUTH)
    assert read.status_code == 200
    assert read.json()["title"] == created["title"]

    # The BM25 index must have been rebuilt, or the new ticket is invisible.
    found = ticketing_client.post(
        "/tickets/search",
        json={"alarm_name": "Surge Detected", "asset_id": "AST-0025", "limit": 20},
        headers=TICKET_AUTH,
    ).json()["results"]
    assert created["key"] in {r["ticket"]["key"] for r in found}


def test_update_requires_confirmation(ticketing_client):
    created = ticketing_client.post(
        "/tickets",
        json=_create_payload(),
        headers={**TICKET_AUTH, "Idempotency-Key": "update-gate-0001"},
    ).json()
    response = ticketing_client.patch(
        f"/tickets/{created['key']}", json={"status": "closed"}, headers=TICKET_AUTH
    )
    assert response.status_code == 422


def test_resolving_a_ticket_stamps_resolution_time(ticketing_client):
    created = ticketing_client.post(
        "/tickets",
        json=_create_payload(),
        headers={**TICKET_AUTH, "Idempotency-Key": "resolve-0001"},
    ).json()
    response = ticketing_client.patch(
        f"/tickets/{created['key']}",
        json={"status": "resolved", "resolution": "Cleaned the flush orifice.", "confirmed": True},
        headers=TICKET_AUTH,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["resolved_at"] is not None
    assert body["time_to_resolve_hours"] is not None


def test_updating_an_unknown_ticket_returns_404(ticketing_client):
    response = ticketing_client.patch(
        "/tickets/INC-999999",
        json={"status": "closed", "confirmed": True},
        headers=TICKET_AUTH,
    )
    assert response.status_code == 404


def test_comments_append_in_order(ticketing_client):
    created = ticketing_client.post(
        "/tickets",
        json=_create_payload(),
        headers={**TICKET_AUTH, "Idempotency-Key": "comments-0001"},
    ).json()
    for body in ("First note.", "Second note."):
        response = ticketing_client.post(
            f"/tickets/{created['key']}/comments", json={"body": body}, headers=TICKET_AUTH
        )
        assert response.status_code == 200
    comments = response.json()["comments"]
    assert [c["body"] for c in comments] == ["First note.", "Second note."]


def test_unknown_field_in_a_create_payload_is_rejected(ticketing_client):
    response = ticketing_client.post(
        "/tickets",
        json={**_create_payload(), "priorty": "P1"},
        headers={**TICKET_AUTH, "Idempotency-Key": "typo-0001"},
    )
    assert response.status_code == 422


def test_trace_id_is_echoed_on_ticket_responses(ticketing_client):
    response = ticketing_client.get(
        "/tickets",
        params={"page_size": 1},
        headers={**TICKET_AUTH, "trace_id": "trace-ticket-xyz"},
    )
    assert response.headers["trace_id"] == "trace-ticket-xyz"

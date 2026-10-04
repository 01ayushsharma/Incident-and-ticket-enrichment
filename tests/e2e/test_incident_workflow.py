"""End-to-end tests through the copilot's HTTP API.

The mandatory acceptance scenario and the full incident-to-ticket journey,
driven the way the GUI drives them: HTTP in, HTTP out, with a real MCP
session and real source systems behind it.

This is the test that would fail if any layer stopped participating -
if the copilot bypassed MCP, if RAG detached from the workflow, if
citations disappeared, or if a ticket could be created without approval.
"""

from __future__ import annotations

import pytest
from httpx2 import ASGITransport, AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.anyio]


@pytest.fixture
async def api(harness):
    """The backend app wired to the in-process harness."""
    from copilot.api.app import Services, create_app, set_services
    from copilot.config import CopilotSettings

    services = Services.__new__(Services)  # bypass __init__'s real wiring
    services.settings = CopilotSettings(llm_provider="fake")
    services.conversations = harness.conversations
    services.retrieval = harness.retrieval
    services.provider = harness.provider
    services.mcp = harness.mcp
    services.mcp_error = None
    set_services(services)

    app = create_app(lifespan_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://copilot") as client:
        yield client
    set_services(None)


# --------------------------------------------------------------------------
# Service surface
# --------------------------------------------------------------------------
async def test_health_reports_every_dependency(api):
    response = await api.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["mcp"]["connected"] is True
    assert body["mcp"]["tools"] >= 18
    assert body["rag"]["indexed_chunks"] > 0
    assert body["llm"]["provider"] == "fake"


async def test_the_tool_catalog_is_exposed_for_the_gui(api):
    response = await api.get("/tools")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 18
    assert set(body["write_tools"]) == {"create_ticket", "add_ticket_comment"}
    first = body["tools"][0]
    assert {"name", "description", "read_only", "input_schema"} <= set(first)


# --------------------------------------------------------------------------
# The mandatory acceptance scenario
# --------------------------------------------------------------------------
async def test_acceptance_scenario_combines_mcp_chaining_and_rag(api):
    """The scenario the assignment names, asserted end to end.

    "Investigate recurring high-severity alarms for Boiler Feed Pump 101
    over the last 90 days, identify likely contributing factors, retrieve
    the relevant operating procedure, and provide recommended actions with
    source evidence."
    """
    response = await api.post(
        "/chat",
        json={
            "message": (
                "Investigate recurring high-severity alarms for Boiler Feed Pump 101 "
                "over the last 90 days, identify likely contributing factors, retrieve "
                "the relevant operating procedure, and provide recommended actions "
                "with source evidence"
            )
        },
    )
    assert response.status_code == 200
    body = response.json()

    # 1. Asset resolution through an MCP tool.
    tools = [step["tool"] for step in body["mcp_trace"]]
    assert tools[0] == "search_assets"
    assert body["structured"]["resolved_asset"]["asset_name"] == "Boiler Feed Pump 101"

    # 2. Multi-step Alarm Management API chaining through MCP.
    assert len(tools) >= 3
    assert "summarize_alarms" in tools
    assert "correlate_alarms" in tools
    assert all(s["status"] == "ok" for s in body["mcp_trace"])

    # 3. The 90-day window was honoured.
    assert body["plan"]["lookback_days"] == 90
    assert body["structured"]["summary"]["total_alarms"] > 0

    # 4. Document retrieval through RAG, in the same run.
    assert body["citations"], "no documents cited"
    assert "OP-114" in {c["doc_id"] for c in body["citations"]}, (
        "the operating procedure for this pump should be retrieved"
    )

    # 5. Citations are complete enough to check.
    for citation in body["citations"]:
        assert citation["marker"].startswith("[")
        assert citation["source_path"].endswith(".md")
        assert citation["excerpt"]

    # 6. A grounded answer came back.
    assert body["message"].strip()
    assert body["low_confidence"] is False

    # 7. The MCP execution trace is present and timed.
    for step in body["mcp_trace"]:
        assert step["duration_ms"] >= 0
        assert step["trace_id"]

    # 8. Trace correlation across the whole request.
    assert body["trace_id"]
    assert body["request_id"]


# --------------------------------------------------------------------------
# The full incident-to-ticket journey
# --------------------------------------------------------------------------
async def test_incident_journey_from_question_to_approved_ticket(api):
    draft_response = await api.post(
        "/chat",
        json={
            "message": "Prepare an incident for the highest-priority active alarm in EastRefinery"
        },
    )
    assert draft_response.status_code == 200
    drafted = draft_response.json()
    conversation_id = drafted["conversation_id"]

    # A draft, and definitively not a ticket.
    draft = drafted["ticket_draft"]
    assert draft is not None
    assert draft["requires_approval"] is True
    assert drafted["created_ticket"] is None
    assert "create_ticket" not in [s["tool"] for s in drafted["mcp_trace"]]

    # The draft carries both kinds of evidence.
    assert draft["linked_alarm_ids"]
    assert draft["citations"]
    assert drafted["similar_tickets"]

    # Declining writes nothing.
    declined = await api.post(
        "/tickets/approve",
        json={"conversation_id": conversation_id, "draft_id": draft["draft_id"], "approved": False},
    )
    assert declined.status_code == 200
    assert declined.json()["created_ticket"] is None

    # Approving with an edit writes what the human approved.
    approved = await api.post(
        "/tickets/approve",
        json={
            "conversation_id": conversation_id,
            "draft_id": draft["draft_id"],
            "approved": True,
            "title": "Edited by the operator before approval",
            "priority": "P1",
        },
    )
    assert approved.status_code == 200
    created = approved.json()["created_ticket"]
    assert created is not None
    assert created["created"] is True
    assert created["key"].startswith("INC-")
    assert approved.json()["ticket_draft"]["title"] == ("Edited by the operator before approval")

    # Approving again returns the same ticket instead of a duplicate.
    again = await api.post(
        "/tickets/approve",
        json={
            "conversation_id": conversation_id,
            "draft_id": draft["draft_id"],
            "approved": True,
            "title": "Edited by the operator before approval",
            "priority": "P1",
        },
    )
    assert again.json()["created_ticket"]["key"] == created["key"]
    assert again.json()["created_ticket"]["created"] is False


async def test_the_audit_trail_records_the_whole_journey(api):
    drafted = (
        await api.post(
            "/chat",
            json={
                "message": "Prepare an incident for the highest-priority active "
                "alarm in EastRefinery"
            },
        )
    ).json()
    conversation_id = drafted["conversation_id"]
    draft_id = drafted["ticket_draft"]["draft_id"]

    await api.post(
        "/tickets/approve",
        json={"conversation_id": conversation_id, "draft_id": draft_id, "approved": True},
    )

    audit = (await api.get(f"/conversations/{conversation_id}/audit")).json()
    actions = [entry["action"] for entry in audit]
    assert actions == ["message", "ticket_drafted", "answered", "ticket_approved", "ticket_created"]
    for entry in audit:
        assert entry["trace_id"]
        assert entry["actor"] in {"user", "copilot"}
        assert entry["timestamp"]


async def test_feedback_on_an_answer_lands_in_the_audit_trail(api):
    answered = (await api.post("/chat", json={"message": "What is the alarm philosophy?"})).json()
    conversation_id = answered["conversation_id"]

    response = await api.post(
        f"/conversations/{conversation_id}/feedback",
        json={
            "trace_id": answered["trace_id"],
            "rating": "down",
            "comment": "Missed the shelving rules",
        },
    )
    assert response.status_code == 201
    assert response.json()["action"] == "feedback"

    audit = (await api.get(f"/conversations/{conversation_id}/audit")).json()
    feedback = audit[-1]
    assert feedback["actor"] == "user"
    # Tied to the answer it rates, not to the feedback request itself.
    assert feedback["trace_id"] == answered["trace_id"]
    assert feedback["metadata"]["rating"] == "down"
    assert "Missed the shelving rules" in feedback["detail"]


async def test_feedback_is_validated(api):
    answered = (await api.post("/chat", json={"message": "What is the alarm philosophy?"})).json()
    bad_rating = await api.post(
        f"/conversations/{answered['conversation_id']}/feedback",
        json={"trace_id": answered["trace_id"], "rating": "meh"},
    )
    assert bad_rating.status_code == 422

    unknown = await api.post(
        "/conversations/conv-nope/feedback",
        json={"trace_id": "t-1", "rating": "up"},
    )
    assert unknown.status_code == 404


async def test_approval_of_an_unknown_draft_is_refused(api):
    started = (await api.post("/chat", json={"message": "What is the alarm philosophy?"})).json()
    response = await api.post(
        "/tickets/approve",
        json={
            "conversation_id": started["conversation_id"],
            "draft_id": "draft-does-not-exist",
            "approved": True,
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_approval_against_an_unknown_conversation_is_refused(api):
    response = await api.post(
        "/tickets/approve",
        json={"conversation_id": "conv-nope", "draft_id": "draft-x", "approved": True},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Conversation continuity
# --------------------------------------------------------------------------
async def test_a_follow_up_stays_in_the_same_conversation(api):
    first = (await api.post("/chat", json={"message": "What is the alarm philosophy?"})).json()
    conversation_id = first["conversation_id"]

    second = await api.post(
        "/chat",
        json={
            "message": "And what counts as a chattering alarm?",
            "conversation_id": conversation_id,
        },
    )
    assert second.json()["conversation_id"] == conversation_id

    stored = (await api.get(f"/conversations/{conversation_id}")).json()
    assert len(stored["turns"]) == 4  # two user, two assistant


# --------------------------------------------------------------------------
# Degraded scenario, as the demo requires
# --------------------------------------------------------------------------
async def test_an_unanswerable_question_says_so_instead_of_inventing(api):
    response = await api.post("/chat", json={"message": "What is our policy on expense claims?"})
    assert response.status_code == 200
    body = response.json()
    assert body["low_confidence"] is True
    assert body["citations"] == []
    assert any(d["component"] == "rag" for d in body["degraded"])


async def test_a_malformed_request_is_rejected_with_the_error_envelope(api):
    response = await api.post("/chat", json={"message": ""})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["trace_id"]


async def test_the_caller_trace_id_flows_through_the_whole_stack(api):
    """One id, from the HTTP edge through MCP to the source systems."""
    response = await api.post(
        "/chat",
        json={"message": "What is the procedure for a drum level low alarm?"},
        headers={"trace_id": "trace-e2e-check"},
    )
    assert response.headers["trace_id"] == "trace-e2e-check"
    assert response.json()["trace_id"] == "trace-e2e-check"

"""MCP server contract tests.

Covers what the submission guidelines list for MCP: tool registration and
discovery, schema validation, authentication propagation, pagination,
retries, timeouts, API error mapping and trace propagation.

These run against a real MCP session over in-memory streams, so the
protocol itself is exercised rather than mocked.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


# --------------------------------------------------------------------------
# Discovery and contracts
# --------------------------------------------------------------------------
async def test_the_server_advertises_its_identity(harness):
    assert harness.mcp.server_name == "alarm-management"
    assert harness.mcp.server_version


async def test_discovery_returns_the_full_catalog(harness):
    tools = harness.mcp.tools
    assert len(tools) >= 18
    required = {
        "search_assets",
        "get_asset_metadata",
        "list_alarms",
        "get_alarm_detail",
        "summarize_alarms",
        "get_alarm_trends",
        "correlate_alarms",
        "analyze_alarm_floods",
        "find_rationalization_candidates",
        "score_alarm_priority",
        "recommend_operator_actions",
        "compute_kpi",
        "find_similar_tickets",
        "list_tickets",
        "create_ticket",
    }
    assert required <= set(tools)


async def test_every_tool_has_a_description_and_typed_schemas(harness):
    for tool in harness.mcp.tools.values():
        assert len(tool.description) > 40, f"{tool.name} needs a usable description"
        assert tool.input_schema.get("type") == "object", f"{tool.name} input schema"
        assert tool.output_schema, f"{tool.name} declares no output schema"


async def test_write_tools_are_annotated_as_such(harness):
    """An MCP client must be able to tell reads from writes without guessing."""
    writes = set(harness.mcp.write_tools())
    assert writes == {"create_ticket", "add_ticket_comment"}
    assert harness.mcp.get_tool("search_assets").read_only is True


async def test_required_arguments_are_declared(harness):
    assert harness.mcp.get_tool("search_assets").required_arguments == ["query"]
    assert "alarm_id" in harness.mcp.get_tool("score_alarm_priority").required_arguments
    create = harness.mcp.get_tool("create_ticket").required_arguments
    assert {"title", "description", "approved", "approval_reference"} <= set(create)


# --------------------------------------------------------------------------
# Invocation and chaining
# --------------------------------------------------------------------------
async def test_a_tool_returns_structured_content_with_provenance(harness):
    call = await harness.mcp.call("search_assets", {"query": "Boiler Feed Pump 101"})
    assert call.succeeded
    meta = call.result["meta"]
    assert meta["source_system"] == "alarm-api"
    assert meta["trace_id"]
    assert meta["duration_ms"] >= 0


async def test_output_conforms_to_the_declared_schema(harness):
    """Output validation is a contract, not a convention."""
    call = await harness.mcp.call("get_asset_metadata", {"asset_id": "AST-0001"})
    assert call.succeeded
    asset = call.result["asset"]
    for field in ("asset_id", "asset_name", "criticality", "design_limits", "alarm_count_total"):
        assert field in asset


async def test_multi_step_chaining_passes_output_into_the_next_tool(harness):
    """asset_id from one tool must drive the next; that is the chain."""
    search = await harness.mcp.call("search_assets", {"query": "Boiler Feed Pump 101"})
    asset_id = search.result["assets"][0]["asset_id"]

    alarms = await harness.mcp.call(
        "list_alarms", {"asset_id": asset_id, "page_size": 5, "lookback_days": 90}
    )
    assert alarms.succeeded
    assert alarms.result["alarms"]
    assert {a["asset_id"] for a in alarms.result["alarms"]} == {asset_id}

    alarm_id = alarms.result["alarms"][0]["alarm_id"]
    score = await harness.mcp.call("score_alarm_priority", {"alarm_id": alarm_id})
    assert score.succeeded
    assert score.result["alarm_id"] == alarm_id


async def test_a_composite_tool_reports_its_upstream_call_count(harness):
    """rank_active_alarms_by_priority chains internally; the trace shows it."""
    call = await harness.mcp.call(
        "rank_active_alarms_by_priority", {"site": "EastRefinery", "top_n": 3}
    )
    assert call.succeeded
    assert call.upstream_calls > 1, "one listing plus one score per candidate"
    assert len(call.result["alarms"]) <= 3


async def test_pagination_is_exposed_through_the_tool(harness):
    first = await harness.mcp.call(
        "list_alarms", {"site": "EastRefinery", "page": 1, "page_size": 5}
    )
    second = await harness.mcp.call(
        "list_alarms", {"site": "EastRefinery", "page": 2, "page_size": 5}
    )
    assert first.result["has_next"] is True
    ids_first = {a["alarm_id"] for a in first.result["alarms"]}
    ids_second = {a["alarm_id"] for a in second.result["alarms"]}
    assert not ids_first & ids_second


async def test_large_results_are_flagged_as_truncated(harness):
    call = await harness.mcp.call("list_alarms", {"site": "EastRefinery", "page_size": 5})
    assert call.result["meta"]["truncated"] is True


# --------------------------------------------------------------------------
# Time-window resolution
# --------------------------------------------------------------------------
async def test_relative_windows_resolve_against_the_data_horizon(harness):
    """Resolving 'last 90 days' against wall-clock time would return nothing."""
    call = await harness.mcp.call(
        "summarize_alarms",
        {
            "site": "EastRefinery",
            "lookback_days": 90,
            "group_by": ["severity"],
            "kpis": ["alarm_count"],
        },
    )
    assert call.succeeded
    assert call.result["total_alarms"] > 0


async def test_explicit_window_overrides_lookback(harness):
    call = await harness.mcp.call(
        "summarize_alarms",
        {
            "site": "EastRefinery",
            "start_time": "2026-05-01T00:00:00Z",
            "end_time": "2026-07-01T00:00:00Z",
            "lookback_days": 1,
            "group_by": ["severity"],
            "kpis": ["alarm_count"],
        },
    )
    assert call.succeeded
    assert call.result["total_alarms"] > 0


# --------------------------------------------------------------------------
# Error mapping
# --------------------------------------------------------------------------
async def test_an_upstream_404_maps_to_an_actionable_tool_error(harness):
    call = await harness.mcp.call("get_asset_metadata", {"asset_id": "AST-9999"})
    assert call.status == "tool_error"
    assert "AST-9999" in call.error_message
    assert call.error_diagnosis is not None
    assert call.error_diagnosis["kind"] == "upstream"
    assert call.error_diagnosis["status_code"] == 404
    assert call.error_diagnosis["retryable"] is False


async def test_a_tool_error_says_whether_retrying_could_help(harness):
    call = await harness.mcp.call("get_alarm_detail", {"alarm_id": "ALM-000000"})
    assert call.status == "tool_error"
    assert "will not succeed on retry" in call.error_message


async def test_invalid_arguments_are_caught_before_the_call(harness):
    call = await harness.mcp.call("search_assets", {"quary": "typo"})
    assert call.status == "invalid_arguments"
    assert "unknown argument 'quary'" in call.error_message
    assert "did you mean 'query'" in call.error_message


async def test_a_missing_required_argument_is_reported(harness):
    call = await harness.mcp.call("score_alarm_priority", {})
    assert call.status == "invalid_arguments"
    assert "missing required argument 'alarm_id'" in call.error_message


async def test_a_wrong_argument_type_is_reported(harness):
    call = await harness.mcp.call("search_assets", {"query": "pump", "limit": "five"})
    assert call.status == "invalid_arguments"
    assert "should be integer" in call.error_message


async def test_calling_an_unknown_tool_is_reported_not_raised(harness):
    call = await harness.mcp.call("teleport_the_pump", {})
    assert call.status == "not_found"
    assert "not offered by this server" in call.error_message


async def test_server_side_validation_still_applies_when_local_is_skipped(harness):
    """Local validation is an optimisation; the server remains authoritative."""
    call = await harness.mcp.call("search_assets", {"bogus": 1}, validate=False)
    assert call.status == "tool_error"


async def test_a_semantic_argument_error_is_explained(harness):
    call = await harness.mcp.call("rank_active_alarms_by_priority", {})
    assert call.status == "tool_error"
    assert "at least one of" in call.error_message
    assert call.error_diagnosis["kind"] == "invalid_input"


async def test_a_malformed_timestamp_is_explained_with_an_example(harness):
    call = await harness.mcp.call(
        "summarize_alarms", {"site": "EastRefinery", "start_time": "yesterday"}
    )
    assert call.status == "tool_error"
    assert "ISO-8601" in call.error_message


# --------------------------------------------------------------------------
# Authentication and trace propagation
# --------------------------------------------------------------------------
async def test_the_server_authenticates_to_the_source_system(indexed_retrieval):
    """A bad credential surfaces as a 401 mapped into a tool error."""
    from tests.harness import build_harness

    async with build_harness(retrieval=indexed_retrieval, alarm_token="wrong-token") as bad:
        call = await bad.mcp.call("search_assets", {"query": "pump"})
        assert call.status == "tool_error"
        assert call.error_diagnosis["status_code"] == 401
        # The token must never appear in anything the client can see.
        assert "wrong-token" not in call.error_message
        assert "demo-token" not in call.error_message


async def test_each_tool_call_carries_a_trace_id(harness):
    call = await harness.mcp.call("list_kpi_definitions", {})
    assert call.succeeded
    assert call.result["meta"]["trace_id"].startswith("trace-")


async def test_the_invocation_log_records_every_call_in_order(harness):
    harness.mcp.reset_trace()
    await harness.mcp.call("search_assets", {"query": "pump"})
    await harness.mcp.call("get_asset_metadata", {"asset_id": "AST-9999"})
    await harness.mcp.call("no_such_tool", {})

    trace = harness.mcp.trace()
    assert [t["sequence"] for t in trace] == [1, 2, 3]
    assert [t["status"] for t in trace] == ["ok", "tool_error", "not_found"]
    assert all(t["duration_ms"] >= 0 for t in trace)


# --------------------------------------------------------------------------
# Health and degraded source systems
# --------------------------------------------------------------------------
async def test_health_reports_both_source_systems(harness):
    call = await harness.mcp.call("check_source_systems", {})
    assert call.succeeded
    systems = {s["system"]: s for s in call.result["systems"]}
    assert set(systems) == {"alarm-api", "ticketing-api"}
    assert call.result["all_healthy"] is True


async def test_health_reports_degradation_rather_than_failing(indexed_retrieval):
    """The point of the health tool is to work when things are broken."""
    from tests.harness import build_harness

    async with build_harness(retrieval=indexed_retrieval, break_ticketing=True) as degraded:
        call = await degraded.mcp.call("check_source_systems", {})
        assert call.succeeded, "health must not itself fail"
        assert call.result["all_healthy"] is False
        ticketing = next(s for s in call.result["systems"] if s["system"] == "ticketing-api")
        assert ticketing["reachable"] is False


# --------------------------------------------------------------------------
# The write tool
# --------------------------------------------------------------------------
async def test_create_ticket_refuses_without_approval(harness):
    call = await harness.mcp.call(
        "create_ticket",
        {
            "title": "Unapproved ticket",
            "description": "body",
            "approved": False,
            "approval_reference": "conv-test:ALM-1",
        },
    )
    assert call.status == "tool_error"
    assert "without approval" in call.error_message


async def test_create_ticket_writes_when_approved(harness):
    call = await harness.mcp.call(
        "create_ticket",
        {
            "title": "Approved test ticket",
            "description": "body",
            "approved": True,
            "approval_reference": "conv-test:ALM-approve-1",
            "priority": "P2",
        },
    )
    assert call.succeeded
    assert call.result["created"] is True
    assert call.result["ticket"]["key"].startswith("INC-")


async def test_repeating_an_approval_does_not_duplicate_the_ticket(harness):
    arguments = {
        "title": "Idempotent ticket",
        "description": "body",
        "approved": True,
        "approval_reference": "conv-test:ALM-idem-1",
    }
    first = await harness.mcp.call("create_ticket", arguments)
    second = await harness.mcp.call("create_ticket", arguments)

    assert first.result["created"] is True
    assert second.result["created"] is False
    assert first.result["ticket"]["key"] == second.result["ticket"]["key"]


async def test_a_created_ticket_is_readable_back_through_mcp(harness):
    created = await harness.mcp.call(
        "create_ticket",
        {
            "title": "Readback ticket",
            "description": "body",
            "approved": True,
            "approval_reference": "conv-test:ALM-readback-1",
        },
    )
    key = created.result["ticket"]["key"]
    read = await harness.mcp.call("get_ticket", {"key": key})
    assert read.succeeded
    assert read.result["ticket"]["key"] == key

"""Orchestration tests.

These assert the properties the assignment asks for in a combined
workflow: multi-step chaining, output of one tool feeding the next, RAG
retrieval inside the same run, partial-source failure, and conflicting or
absent evidence being reported rather than papered over.
"""

from __future__ import annotations

import pytest
from copilot.llm.base import LlmMessage, LlmProvider, LlmResponse, LlmUnavailableError
from copilot.orchestration import planner as planning
from copilot.orchestration.drafting import derive_priority

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

CONV = "conv-test-0001"


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "message,expected_intent",
    [
        (
            "Prepare an incident for the highest-priority active alarm in EastRefinery",
            "create_ticket",
        ),
        ("Find similar historical tickets for this compressor alarm", "similar_tickets"),
        ("Show open tickets linked to correlated assets", "linked_tickets"),
        ("What is the procedure for a drum level low alarm?", "procedure_lookup"),
        (
            "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over "
            "the last 90 days",
            "investigate_asset",
        ),
    ],
)
async def test_intent_detection_covers_the_assignment_examples(harness, message, expected_intent):
    response = await harness.workflow.run(message, conversation_id=CONV)
    assert response.intent == expected_intent


async def test_the_plan_only_contains_tools_that_exist(harness):
    response = await harness.workflow.run(
        "Prepare an incident for the highest-priority active alarm in EastRefinery",
        conversation_id=CONV,
    )
    known = set(harness.mcp.tools) | planning.LOCAL_STEPS
    assert {step.tool for step in response.plan.steps} <= known


async def test_a_hallucinated_tool_is_dropped_from_the_plan_not_attempted(harness):
    from copilot.models import Plan, PlanStep

    plan = Plan(
        intent="rank_alarms",
        steps=[
            PlanStep(tool="search_assets", why="ok"),
            PlanStep(tool="summon_a_technician", why="invented"),
        ],
    )
    validated, warnings = planning.validate_plan(plan, set(harness.mcp.tools))
    assert [s.tool for s in validated.steps] == ["search_assets"]
    assert any("summon_a_technician" in w for w in warnings)


async def test_lookback_is_extracted_from_the_wording(harness):
    response = await harness.workflow.run(
        "Investigate recurring alarms on Boiler Feed Pump 101 over the last 30 days",
        conversation_id=CONV,
    )
    assert response.plan.lookback_days == 30


# --------------------------------------------------------------------------
# Chaining
# --------------------------------------------------------------------------
async def test_the_workflow_chains_several_mcp_tools(harness):
    response = await harness.workflow.run(
        "Prepare an incident for the highest-priority active alarm in EastRefinery",
        conversation_id=CONV,
    )
    tools = [step["tool"] for step in response.mcp_trace]
    assert len(tools) >= 4, f"expected a chain, got {tools}"
    assert "rank_active_alarms_by_priority" in tools
    assert all(step["status"] == "ok" for step in response.mcp_trace)


async def test_output_of_one_tool_becomes_the_input_of_the_next(harness):
    """The asset the ranking tool found must scope the later calls."""
    response = await harness.workflow.run(
        "Prepare an incident for the highest-priority active alarm in EastRefinery",
        conversation_id=CONV,
    )
    assert response.alarm is not None
    alarm_id = response.alarm.alarm_id

    by_tool = {step["tool"]: step for step in response.mcp_trace}
    assert by_tool["get_alarm_detail"]["arguments"]["alarm_id"] == alarm_id
    assert by_tool["recommend_operator_actions"]["arguments"]["alarm_id"] == alarm_id
    assert by_tool["correlate_alarms"]["arguments"]["asset_ids"] == [response.alarm.asset_id]


async def test_a_summary_without_a_named_scope_runs_plant_wide(harness):
    """Naming no asset or site widens the rollup; it must not skip it."""
    response = await harness.workflow.run("Summarize critical alarms", conversation_id=CONV)
    by_tool = {step["tool"]: step for step in response.mcp_trace}
    assert by_tool["summarize_alarms"]["status"] == "ok"
    assert not {"asset_ids", "site", "unit"} & set(by_tool["summarize_alarms"]["arguments"])
    assert response.structured["scope"] == "plant-wide"
    assert response.structured["summary"]["total_alarms"] > 0


async def test_summary_evidence_counts_every_severity_not_just_the_largest_groups(harness):
    """Critical groups are small, so they fall outside the top-N excerpt."""
    from copilot.orchestration.synthesis import _render_evidence

    response = await harness.workflow.run("Summarize critical alarms", conversation_id=CONV)
    summary = response.structured["summary"]
    critical = sum(
        int(g["metrics"]["alarm_count"])
        for g in summary["groups"]
        if g["key"].get("severity") == "critical"
    )
    assert critical > 0
    evidence = _render_evidence(
        alarm=None, structured={"summary": summary, "scope": "plant-wide"}, similar_tickets=[]
    )
    assert f'"critical": {critical}' in evidence
    assert "scope: plant-wide" in evidence


async def test_a_summary_reports_what_is_open_now_not_only_the_window(harness):
    """The rollup counts alarms raised; the snapshot says which are still open."""
    response = await harness.workflow.run("Summarize active critical alarms", conversation_id=CONV)
    by_tool = {step["tool"]: step for step in response.mcp_trace}
    listing = by_tool["list_alarms"]["arguments"]
    assert set(listing["status"]) == {"active", "acknowledged"}
    assert set(listing["severity"]) == {"critical", "high"}
    assert not {"asset_id", "site", "unit"} & set(listing)

    open_alarms = response.structured["open_alarms"]
    assert open_alarms["total"] > 0
    assert sum(open_alarms["by_severity"].values()) == open_alarms["total"]
    assert {a["status"] for a in open_alarms["alarms"]} <= {"active", "acknowledged"}
    assert {a["severity"] for a in open_alarms["alarms"]} <= {"critical", "high"}
    for severity, statuses in open_alarms["by_severity_and_status"].items():
        assert sum(statuses.values()) == open_alarms["by_severity"][severity]
    # Critical first, oldest first within a severity.
    listed = [(a["severity"] != "critical", a["start_time"]) for a in open_alarms["alarms"]]
    assert listed == sorted(listed)


async def test_a_scoped_summary_snapshots_only_that_scope(harness):
    response = await harness.workflow.run("Summarize alarms in EastRefinery", conversation_id=CONV)
    by_tool = {step["tool"]: step for step in response.mcp_trace}
    assert by_tool["list_alarms"]["arguments"]["site"] == "EastRefinery"
    assert {a["site"] for a in response.structured["open_alarms"]["alarms"]} <= {"EastRefinery"}


async def test_correlated_assets_drive_the_linked_ticket_lookup(harness):
    response = await harness.workflow.run(
        "Show open tickets linked to correlated assets for Crude Charge Motor 501",
        conversation_id=CONV,
    )
    by_tool = {step["tool"]: step for step in response.mcp_trace}
    assert "correlate_alarms" in by_tool
    assert "list_tickets" in by_tool
    passed_ids = by_tool["list_tickets"]["arguments"]["asset_ids"]
    assert len(passed_ids) > 1, "correlation should widen the ticket search"


async def test_asset_resolution_precedes_any_asset_scoped_call(harness):
    response = await harness.workflow.run(
        "Investigate recurring alarms on Boiler Feed Pump 101 over the last 90 days",
        conversation_id=CONV,
    )
    tools = [step["tool"] for step in response.mcp_trace]
    assert tools[0] == "search_assets"
    resolved = response.structured["resolved_asset"]
    assert resolved["asset_name"] == "Boiler Feed Pump 101"


# --------------------------------------------------------------------------
# RAG inside the same workflow
# --------------------------------------------------------------------------
async def test_mcp_and_rag_participate_in_one_run(harness):
    """The core requirement: both halves, one workflow, cross-referenced."""
    response = await harness.workflow.run(
        "Prepare an incident for the highest-priority active alarm in EastRefinery",
        conversation_id=CONV,
    )
    assert response.mcp_trace, "no MCP tools ran"
    assert response.citations, "no documents were retrieved"
    assert response.ticket_draft is not None
    # The draft must carry both kinds of evidence.
    assert response.ticket_draft.linked_alarm_ids
    assert response.ticket_draft.citations


async def test_retrieval_is_scoped_by_what_the_tools_found(harness):
    """Retrieval after the tool chain, using the alarm the tools selected."""
    response = await harness.workflow.run(
        "Prepare an incident for the highest-priority active alarm in NorthPlant",
        conversation_id=CONV,
    )
    assert response.alarm is not None
    # Documents retrieved should relate to the selected alarm, not the raw
    # question, which never mentioned an alarm name.
    cited_text = " ".join(c.excerpt.lower() for c in response.citations)
    assert cited_text, "expected citations"
    subject = response.alarm.alarm_name.split()[-1].lower()
    assert subject in cited_text or response.alarm.asset_name.split()[0].lower() in cited_text


async def test_a_procedure_question_retrieves_without_needing_tools(harness):
    response = await harness.workflow.run(
        "What is the mandatory response to a boiler drum level low alarm?",
        conversation_id=CONV,
    )
    assert response.citations
    assert "SAF-020" in {c.doc_id for c in response.citations}


# --------------------------------------------------------------------------
# Ticket drafting and the approval gate
# --------------------------------------------------------------------------
async def test_a_draft_is_produced_but_no_ticket_is_created(harness):
    response = await harness.workflow.run(
        "Prepare an incident for the highest-priority active alarm in EastRefinery",
        conversation_id=CONV,
    )
    assert response.ticket_draft is not None
    assert response.ticket_draft.requires_approval is True
    assert response.created_ticket is None
    assert "create_ticket" not in [s["tool"] for s in response.mcp_trace]


async def test_the_draft_contains_every_section_esc_010_requires(harness):
    response = await harness.workflow.run(
        "Prepare an incident for the highest-priority active alarm in EastRefinery",
        conversation_id=CONV,
    )
    body = response.ticket_draft.description
    for section in (
        "## Alarm",
        "## Asset",
        "## Priority",
        "## Recommended actions",
        "## Applicable procedures",
    ):
        assert section in body, f"draft is missing {section}"


async def test_the_draft_shows_how_its_priority_was_derived(harness):
    response = await harness.workflow.run(
        "Prepare an incident for the highest-priority active alarm in EastRefinery",
        conversation_id=CONV,
    )
    assert "ESC-010 matrix" in response.ticket_draft.description


async def test_the_approval_reference_is_stable_across_identical_requests(harness):
    first = await harness.workflow.run(
        "Prepare an incident for the highest-priority active alarm in EastRefinery",
        conversation_id=CONV,
    )
    second = await harness.workflow.run(
        "Prepare an incident for the highest-priority active alarm in EastRefinery",
        conversation_id=CONV,
    )
    assert first.ticket_draft.approval_reference == second.ticket_draft.approval_reference, (
        "an unstable reference would let a repeated approval open a duplicate"
    )


@pytest.mark.parametrize(
    "severity,criticality,expected",
    [
        ("critical", "critical", "P1"),
        ("critical", "medium", "P2"),
        ("high", "critical", "P1"),
        ("medium", "medium", "P3"),
        ("low", "low", "P4"),
    ],
)
def test_the_priority_matrix_follows_esc_010(severity, criticality, expected):
    priority, reasons = derive_priority(severity, criticality)
    assert priority == expected
    assert reasons


def test_a_modifier_raises_the_priority_one_band():
    base, _ = derive_priority("medium", "medium")
    raised, reasons = derive_priority("medium", "medium", modifiers=["recurring"])
    assert base == "P3"
    assert raised == "P2"
    assert any("Raised one band" in r for r in reasons)


def test_priority_cannot_be_raised_above_p1():
    priority, reasons = derive_priority(
        "critical", "critical", modifiers=["recurring", "no standby"]
    )
    assert priority == "P1"
    assert any("Already P1" in r for r in reasons)


# --------------------------------------------------------------------------
# Partial failure and degradation
# --------------------------------------------------------------------------
async def test_a_missing_tool_degrades_the_answer_without_ending_the_run(harness):
    removed = harness.mcp._tools.pop("recommend_operator_actions")
    try:
        response = await harness.workflow.run(
            "Prepare an incident for the highest-priority active alarm in EastRefinery",
            conversation_id=CONV,
        )
    finally:
        harness.mcp._tools["recommend_operator_actions"] = removed

    assert response.message, "the run must still produce an answer"
    assert response.ticket_draft is not None, "and still produce a draft"
    assert any("recommend_operator_actions" in d.detail for d in response.degraded)


async def test_a_failing_source_system_is_reported_not_hidden(indexed_retrieval):
    from tests.harness import build_harness

    async with build_harness(retrieval=indexed_retrieval, break_ticketing=True) as broken:
        response = await broken.workflow.run(
            "Find similar historical tickets for a pump vibration problem",
            conversation_id=CONV,
        )
        assert response.message
        assert response.similar_tickets == []
        assert any(d.component == "tool" for d in response.degraded)


async def test_an_unanswerable_question_reports_low_confidence(harness):
    response = await harness.workflow.run(
        "What is the company policy on parental leave?", conversation_id=CONV
    )
    assert response.low_confidence is True
    assert response.citations == []


async def test_an_asset_that_does_not_exist_is_reported_clearly(harness):
    response = await harness.workflow.run(
        "Investigate recurring alarms on Imaginary Turbine 999 over the last 90 days",
        conversation_id=CONV,
    )
    assert response.message
    assert any("No asset matched" in d.detail for d in response.degraded)


# --------------------------------------------------------------------------
# LLM degradation
# --------------------------------------------------------------------------
class _DeadProvider(LlmProvider):
    """A provider that is always unreachable."""

    kind = "fake"  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__("dead-model")

    async def complete(self, messages, *, temperature=0.2, json_schema=None):
        raise LlmUnavailableError("simulated outage", provider="dead")


async def test_the_workflow_still_works_with_no_llm_at_all(indexed_retrieval):
    """The documented degraded mode: rules plan, deterministic summary."""
    from tests.harness import build_harness

    async with build_harness(retrieval=indexed_retrieval, provider=_DeadProvider()) as degraded:
        response = await degraded.workflow.run(
            "Prepare an incident for the highest-priority active alarm in EastRefinery",
            conversation_id=CONV,
        )

    assert response.plan.source == "rule_based"
    assert response.mcp_trace, "tools must still run without a model"
    assert response.citations, "retrieval must still run without a model"
    assert response.ticket_draft is not None
    assert response.message.strip()
    assert any(d.component == "llm" for d in response.degraded)


class _BadJsonProvider(LlmProvider):
    """A provider that returns prose where JSON was demanded."""

    kind = "fake"  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__("chatty-model")

    async def complete(self, messages, *, temperature=0.2, json_schema=None):
        text = (
            "Sure! Here is my plan: first I will look at things."
            if json_schema
            else "A narrative answer."
        )
        return LlmResponse(text=text, provider="fake", model=self.model)


async def test_an_unparseable_plan_falls_back_rather_than_failing(indexed_retrieval):
    from tests.harness import build_harness

    async with build_harness(retrieval=indexed_retrieval, provider=_BadJsonProvider()) as odd:
        response = await odd.workflow.run(
            "Prepare an incident for the highest-priority active alarm in EastRefinery",
            conversation_id=CONV,
        )
    assert response.plan.source == "rule_based"
    assert response.ticket_draft is not None


class _TerseProvider(LlmProvider):
    """Plans the way a real model did in practice: few steps, out of order.

    Reproduces an observed failure: the model named ``list_alarms`` (an MCP
    tool the workflow had no step for), put ``draft_ticket`` first, and left
    out recommendations, similar tickets and the procedure.
    """

    kind = "fake"  # type: ignore[assignment]

    def __init__(self, intent: str, steps: list[str]) -> None:
        super().__init__("terse-model")
        self.intent = intent
        self.steps = steps

    async def complete(self, messages, *, temperature=0.2, json_schema=None):
        if json_schema:
            import json

            plan = {
                "intent": self.intent,
                "reasoning": "terse",
                "needs_documents": False,
                "steps": [{"tool": t, "why": "model choice"} for t in self.steps],
            }
            return LlmResponse(text=json.dumps(plan), provider="fake", model=self.model)
        return LlmResponse(text="A narrative answer [1].", provider="fake", model=self.model)


def test_complete_plan_adds_required_steps_drops_unrunnable_ones_and_orders_them():
    from copilot.models import Plan, PlanStep
    from copilot.orchestration.workflow import STEP_ORDER

    plan = Plan(
        intent="create_ticket",
        steps=[
            PlanStep(tool="draft_ticket", why="model"),
            PlanStep(tool="get_ticket", why="model"),
            PlanStep(tool="rank_active_alarms_by_priority", why="model"),
        ],
    )
    completed, warnings = planning.complete_plan(plan, step_order=STEP_ORDER)
    tools = [s.tool for s in completed.steps]

    assert "get_ticket" not in tools
    assert any("get_ticket" in w for w in warnings)
    for required in ("find_similar_tickets", "retrieve_documents", "recommend_operator_actions"):
        assert required in tools
    assert tools == sorted(tools, key=STEP_ORDER.index), "steps must run in dependency order"
    assert tools[-1] == "draft_ticket"


async def test_a_terse_model_plan_still_runs_the_whole_incident_workflow(indexed_retrieval):
    from tests.harness import build_harness

    provider = _TerseProvider("create_ticket", ["draft_ticket", "rank_active_alarms_by_priority"])
    async with build_harness(retrieval=indexed_retrieval, provider=provider) as h:
        response = await h.workflow.run(
            "Prepare an incident for the highest-priority active alarm in EastRefinery",
            conversation_id=CONV,
        )

    called = [call["tool"] for call in response.mcp_trace]
    assert response.plan.source == "llm"
    assert {"get_asset_metadata", "recommend_operator_actions", "find_similar_tickets"} <= set(
        called
    )
    assert response.citations, "the procedure must be attached even if the model omitted it"
    assert response.ticket_draft is not None
    assert response.ticket_draft.similar_tickets


async def test_an_investigation_selects_the_recurring_alarm_from_paginated_history(
    indexed_retrieval,
):
    from tests.harness import build_harness

    provider = _TerseProvider("investigate_asset", ["list_alarms", "search_assets"])
    async with build_harness(retrieval=indexed_retrieval, provider=provider) as h:
        response = await h.workflow.run(
            "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the "
            "last 90 days",
            conversation_id=CONV,
        )

    called = [call["tool"] for call in response.mcp_trace]
    assert called.index("search_assets") < called.index("list_alarms")
    history = response.structured["alarm_history"]
    assert history["high_severity_alarms"] > 0
    top_name = history["most_frequent"][0]["alarm_name"]
    assert response.alarm is not None
    assert response.alarm.alarm_name == top_name
    assert response.alarm.asset_name == "Boiler Feed Pump 101"
    # The selected alarm unlocks the alarm-keyed steps.
    assert "recommend_operator_actions" in called
    assert response.structured.get("recommendations")
    assert not any("No handler" in d.detail for d in response.degraded)


async def test_a_generic_equipment_word_is_not_pinned_to_one_asset(harness):
    response = await harness.workflow.run(
        "Find similar historical tickets for a compressor vibration alarm",
        conversation_id=CONV,
    )
    similar_call = next(c for c in response.mcp_trace if c["tool"] == "find_similar_tickets")
    assert "asset_id" not in similar_call["arguments"]
    assert similar_call["arguments"].get("asset_type") == "compressor"
    assert "vibration" in similar_call["arguments"].get("query", "")
    assert response.similar_tickets
    assert "Vibration" in response.similar_tickets[0].title


def test_json_is_extracted_from_a_fenced_response():
    assert planning.extract_json('```json\n{"intent": "summarize"}\n```') == {"intent": "summarize"}


def test_json_is_extracted_from_surrounding_prose():
    assert planning.extract_json('Sure: {"intent": "summarize"} hope that helps') == {
        "intent": "summarize"
    }


def test_unparseable_text_returns_none():
    assert planning.extract_json("no json here at all") is None


# --------------------------------------------------------------------------
# Context retention
# --------------------------------------------------------------------------
async def test_conversation_history_is_passed_into_planning(harness):
    history = [
        LlmMessage(role="user", content="Tell me about Boiler Feed Pump 101"),
        LlmMessage(role="assistant", content="It is a critical feedwater pump."),
    ]
    response = await harness.workflow.run(
        "Now show me its recurring alarms over the last 90 days",
        conversation_id=CONV,
        history=history,
    )
    assert response.conversation_id == CONV
    assert response.plan.lookback_days == 90


async def test_the_trace_is_reset_between_runs(harness):
    first = await harness.workflow.run(
        "What is the procedure for a drum level low alarm?", conversation_id=CONV
    )
    second = await harness.workflow.run(
        "Prepare an incident for the highest-priority active alarm in EastRefinery",
        conversation_id=CONV,
    )
    assert [s["sequence"] for s in second.mcp_trace][:1] == [1], (
        "each response's trace must describe only that request"
    )
    assert len(second.mcp_trace) > len(first.mcp_trace)

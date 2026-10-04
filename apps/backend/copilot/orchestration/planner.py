"""Intent detection and planning.

Two planners, one interface. The LLM planner asks the model for a
structured plan constrained by a JSON schema; the rule-based planner
derives the same structure from keyword rules. The rule-based one is not a
toy - it is the documented degraded mode, and it is what runs when the
provider is unreachable, so the copilot keeps working without a model.

The plan is always *validated* before use: a hallucinated tool name is
dropped with a warning rather than attempted, so a bad plan degrades the
answer instead of breaking the request.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import structlog

from copilot.llm.base import LlmMessage, LlmProvider, LlmUnavailableError
from copilot.llm.fake import (
    _STEPS_BY_INTENT,
    _classify,
    _extract_asset_hint,
    _extract_lookback_days,
    _extract_site_hint,
)
from copilot.models import Plan, PlanStep

logger = structlog.get_logger(__name__)

# Pseudo-tools the orchestrator services itself rather than over MCP.
LOCAL_STEPS = frozenset({"retrieve_documents", "draft_ticket"})

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "rank_alarms",
                "create_ticket",
                "investigate_asset",
                "similar_tickets",
                "linked_tickets",
                "procedure_lookup",
                "summarize",
            ],
        },
        "reasoning": {"type": "string"},
        "asset_hint": {"type": "string"},
        "site_hint": {"type": "string"},
        "alarm_hint": {"type": "string"},
        "lookback_days": {"type": "integer"},
        "needs_documents": {"type": "boolean"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "why": {"type": "string"},
                    "optional": {"type": "boolean"},
                },
                "required": ["tool", "why"],
            },
        },
    },
    "required": ["intent", "reasoning", "needs_documents", "steps"],
}

PLANNER_SYSTEM_PROMPT = """\
You plan tool calls for an industrial incident-management copilot.

Given a user request and the available tools, produce a plan: the intent,
the ordered tool calls needed, and any asset, site or time-window hints you
can extract from the wording.

Rules:
- Use only tool names from the provided catalog, plus the two local steps
  `retrieve_documents` (search the procedure corpus) and `draft_ticket`
  (assemble a draft for human approval).
- Resolve an asset name to an id with `search_assets` before any tool that
  takes an asset_id.
- Never plan `create_ticket`. Plan `draft_ticket` instead: a ticket may only
  be written after a human approves the draft.
- Prefer few, well-chosen steps over many.
- `lookback_days` only when the request implies a period.

Respond with JSON matching the schema. No prose.\
"""


def build_rule_based_plan(message: str, *, reason: str | None = None) -> Plan:
    """Derive a plan from keyword rules. No model involved."""
    intent = _classify(message)
    steps = _STEPS_BY_INTENT.get(intent, _STEPS_BY_INTENT["investigate_asset"])
    return Plan(
        intent=intent,
        reasoning=(
            f"Rule-based planner selected intent '{intent}' from the request wording."
            + (f" {reason}" if reason else "")
        ),
        asset_hint=_extract_asset_hint(message),
        site_hint=_extract_site_hint(message),
        alarm_hint=None,
        lookback_days=_extract_lookback_days(message),
        needs_documents=intent in {"procedure_lookup", "create_ticket", "investigate_asset"},
        steps=[PlanStep(**step) for step in steps],
        source="rule_based",
        degraded_reason=reason,
    )


def validate_plan(plan: Plan, available_tools: set[str]) -> tuple[Plan, list[str]]:
    """Drop steps naming tools that do not exist. Returns (plan, warnings).

    A model can invent a plausible tool name. Attempting it would waste a
    round trip and produce a confusing error, so unknown steps are removed
    here and reported, which is also what the GUI shows in the trace.
    """
    warnings: list[str] = []
    kept: list[PlanStep] = []
    for step in plan.steps:
        if step.tool in LOCAL_STEPS or step.tool in available_tools:
            kept.append(step)
        else:
            warnings.append(f"planner proposed unknown tool '{step.tool}'; step dropped")

    if not kept:
        warnings.append("no usable steps in the plan; falling back to the rule-based plan")
        fallback = build_rule_based_plan(plan.reasoning or plan.intent)
        kept = [s for s in fallback.steps if s.tool in LOCAL_STEPS or s.tool in available_tools]

    return plan.model_copy(update={"steps": kept}), warnings


def complete_plan(plan: Plan, *, step_order: Sequence[str]) -> tuple[Plan, list[str]]:
    """Make a plan executable and complete for its intent. Returns (plan, warnings).

    The model chooses the intent and may add useful steps, but a business
    workflow has steps it cannot do without: an incident draft with no
    similar tickets or procedure is not an incident draft. A real model
    routinely "prefers few steps" and omits them, so the intent's template
    steps are merged in. Steps the workflow has no handler for are dropped,
    and the result is put in dependency order, because chaining only works
    if a step runs after the step that produces its input.
    """
    rank = {tool: index for index, tool in enumerate(step_order)}
    warnings: list[str] = []
    steps: dict[str, PlanStep] = {}

    for step in plan.steps:
        if step.tool not in rank:
            warnings.append(f"planner proposed '{step.tool}', which this workflow does not run")
            continue
        steps.setdefault(step.tool, step)

    template = _STEPS_BY_INTENT.get(plan.intent, _STEPS_BY_INTENT["investigate_asset"])
    added = [s["tool"] for s in template if s["tool"] in rank and s["tool"] not in steps]
    for raw in template:
        if raw["tool"] in added:
            steps[raw["tool"]] = PlanStep(**{**raw, "why": f"{raw['why']} (required for intent)"})
    if added and plan.source == "llm":
        logger.info("plan_completed_from_template", intent=plan.intent, added=added)

    ordered = sorted(steps.values(), key=lambda s: rank[s.tool])
    return plan.model_copy(update={"steps": ordered}), warnings


async def build_plan(
    message: str,
    *,
    provider: LlmProvider,
    tool_catalog: list[str],
    available_tools: set[str],
    history: list[LlmMessage] | None = None,
    allow_fallback: bool = True,
) -> tuple[Plan, list[str]]:
    """Plan with the model, degrading to rules on any failure."""
    catalog = "\n".join(f"- {line}" for line in tool_catalog)
    messages: list[LlmMessage] = [
        LlmMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
        LlmMessage(role="system", content=f"Available tools:\n{catalog}"),
        *(history or []),
        LlmMessage(role="user", content=message),
    ]

    try:
        response = await provider.complete(messages, temperature=0.0, json_schema=PLAN_SCHEMA)
    except LlmUnavailableError as exc:
        if not allow_fallback:
            raise
        logger.warning("planner_llm_unavailable", provider=exc.provider, reason=str(exc))
        plan = build_rule_based_plan(
            message, reason=f"LLM provider unavailable ({exc}); used the rule-based planner."
        )
        return validate_plan(plan, available_tools)

    parsed = extract_json(response.text)
    if parsed is None:
        logger.warning("planner_returned_unparseable_json", provider=response.provider)
        plan = build_rule_based_plan(
            message, reason="The model did not return valid JSON; used the rule-based planner."
        )
        return validate_plan(plan, available_tools)

    try:
        plan = Plan.model_validate({**parsed, "source": "llm"})
    except Exception as exc:
        logger.warning("planner_schema_mismatch", error=str(exc)[:200])
        plan = build_rule_based_plan(
            message,
            reason="The model's plan did not match the schema; used the rule-based planner.",
        )
        return validate_plan(plan, available_tools)

    # A model that returns an empty plan is not useful; treat it as a miss.
    if not plan.steps:
        plan = build_rule_based_plan(
            message, reason="The model returned an empty plan; used the rule-based planner."
        )

    # Fill hints the model omitted but that are cheap to extract.
    if plan.asset_hint is None:
        plan = plan.model_copy(update={"asset_hint": _extract_asset_hint(message)})
    if plan.site_hint is None:
        plan = plan.model_copy(update={"site_hint": _extract_site_hint(message)})
    if plan.lookback_days is None:
        plan = plan.model_copy(update={"lookback_days": _extract_lookback_days(message)})

    return validate_plan(plan, available_tools)


def extract_json(text: str) -> dict[str, Any] | None:
    """Parse JSON from a model response, tolerating the usual wrappers.

    Models wrap JSON in prose or fences even when told not to. This tries
    the strict parse first, then a fenced block, then the outermost braces.
    """
    candidate = text.strip()
    if not candidate:
        return None

    try:
        value = json.loads(candidate)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass

    if "```" in candidate:
        for block in candidate.split("```")[1::2]:
            body = block.removeprefix("json").strip()
            try:
                value = json.loads(body)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue

    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        try:
            value = json.loads(candidate[start : end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None

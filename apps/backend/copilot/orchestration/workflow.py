"""The combined MCP + RAG workflow.

This is the module the assignment's "MCP and RAG must participate in the
same business workflow" requirement lands on. One run does all of:

  natural language -> plan -> MCP tool discovery -> multi-step MCP chaining
  (output of one tool feeding the next) -> document retrieval scoped by what
  the tools found -> grounded synthesis with citations -> ticket draft held
  for human approval.

Two design choices worth stating:

**Chaining is deterministic, not model-driven.** The planner chooses *which*
steps to run; this module decides how each step's arguments are built from
what previous steps returned. Letting a model thread ids between tool calls
adds a failure mode for no benefit, and makes the chain untestable.

**A failed step degrades the answer rather than ending the run.** An
incident draft missing its correlation section is still useful; a request
that returns an error because one of seven tools timed out is not. Every
failure is recorded and surfaced.
"""

from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import structlog

from connectors import tracing
from copilot.config import CopilotSettings
from copilot.llm.base import LlmMessage, LlmProvider, LlmUnavailableError
from copilot.mcp_client import McpToolClient, ToolInvocation
from copilot.models import (
    AlarmSummaryView,
    ChatResponse,
    DegradationNotice,
    EvidenceCitation,
    Plan,
    SimilarTicketSummary,
)
from copilot.orchestration import planner as planning
from copilot.orchestration.drafting import build_ticket_draft
from copilot.orchestration.synthesis import synthesise_answer
from rag.models import RetrievalResult
from rag.retrieval.service import RetrievalService

logger = structlog.get_logger(__name__)

DEFAULT_LOOKBACK_DAYS = 90

# Every step this workflow can run, in dependency order: a step that consumes
# an id (asset, alarm, correlated assets) comes after the step producing it.
# The planner's output is re-ordered against this, so a model listing steps
# in a different order cannot break the chain.
STEP_ORDER: tuple[str, ...] = (
    "search_assets",
    "rank_active_alarms_by_priority",
    "list_alarms",
    "get_asset_metadata",
    "get_alarm_detail",
    "score_alarm_priority",
    "summarize_alarms",
    "get_alarm_trends",
    "correlate_alarms",
    "analyze_alarm_floods",
    "find_rationalization_candidates",
    "compute_kpi",
    "recommend_operator_actions",
    "find_similar_tickets",
    "list_tickets",
    "retrieve_documents",
    "draft_ticket",
)

# Pages fetched when scanning an alarm history. Bounded so a wide scope
# cannot turn one request into hundreds of upstream calls.
MAX_ALARM_PAGES = 5
ALARM_PAGE_SIZE = 200

# "Open" as the ranking tool defines it: raised and not yet cleared.
OPEN_STATUSES: tuple[str, ...] = ("active", "acknowledged")
# Open alarms itemised in a summary; the counts cover all of them. Sized to
# list every open critical alarm in the demo plant.
OPEN_ALARMS_SHOWN = 25


@dataclass
class WorkflowContext:
    """State threaded between steps. This is what makes chaining real."""

    message: str
    conversation_id: str
    plan: Plan

    asset_id: str | None = None
    asset_name: str | None = None
    site: str | None = None
    unit: str | None = None
    asset_type: str | None = None

    alarm_id: str | None = None
    alarm_name: str | None = None
    alarm_view: AlarmSummaryView | None = None
    ranked_alarms: list[AlarmSummaryView] = field(default_factory=list)

    correlated_asset_ids: list[str] = field(default_factory=list)
    recommended_actions: list[dict[str, Any]] = field(default_factory=list)
    likely_causes: list[dict[str, Any]] = field(default_factory=list)
    similar_tickets: list[SimilarTicketSummary] = field(default_factory=list)
    open_linked_tickets: list[SimilarTicketSummary] = field(default_factory=list)

    retrieval: RetrievalResult | None = None
    structured: dict[str, Any] = field(default_factory=dict)
    degraded: list[DegradationNotice] = field(default_factory=list)

    @property
    def lookback_days(self) -> int:
        return self.plan.lookback_days or DEFAULT_LOOKBACK_DAYS

    def note_degradation(self, component: str, detail: str, impact: str) -> None:
        self.degraded.append(DegradationNotice(component=component, detail=detail, impact=impact))


class IncidentWorkflow:
    """Runs one natural-language request end to end."""

    def __init__(
        self,
        *,
        mcp: McpToolClient,
        retrieval: RetrievalService,
        provider: LlmProvider,
        settings: CopilotSettings,
    ) -> None:
        self.mcp = mcp
        self.retrieval = retrieval
        self.provider = provider
        self.settings = settings

    # ------------------------------------------------------------------ run
    async def run(
        self,
        message: str,
        *,
        conversation_id: str,
        history: list[LlmMessage] | None = None,
    ) -> ChatResponse:
        started = time.perf_counter()
        trace = tracing.current()
        self.mcp.reset_trace()

        available = set(self.mcp.tools)
        plan, warnings = await planning.build_plan(
            message,
            provider=self.provider,
            tool_catalog=self.mcp.catalog_summary(),
            available_tools=available,
            history=history,
            allow_fallback=self.settings.llm_degraded_fallback,
        )
        plan, completion_warnings = planning.complete_plan(plan, step_order=STEP_ORDER)
        warnings = [*warnings, *completion_warnings]

        context = WorkflowContext(message=message, conversation_id=conversation_id, plan=plan)
        if plan.source == "rule_based" and plan.degraded_reason:
            context.note_degradation(
                "llm",
                plan.degraded_reason,
                "Planning used deterministic rules; the answer is still grounded in "
                "retrieved evidence.",
            )
        for warning in warnings:
            context.note_degradation("mcp", warning, "That step was skipped.")

        # Seed the context from the planner's hints before any tool runs.
        context.site = plan.site_hint
        context.alarm_name = plan.alarm_hint

        for step in plan.steps:
            await self._execute_step(step.tool, context)

        answer, llm_meta = await self._synthesise(context)

        draft = context.structured.pop("ticket_draft", None)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        response = ChatResponse(
            conversation_id=conversation_id,
            request_id=trace.request_id,
            trace_id=trace.trace_id,
            message=answer,
            intent=plan.intent,
            plan=plan,
            alarm=context.alarm_view,
            alarms=context.ranked_alarms,
            citations=_citations(context.retrieval),
            similar_tickets=context.similar_tickets,
            open_linked_tickets=context.open_linked_tickets,
            structured=context.structured,
            ticket_draft=draft,
            mcp_trace=self.mcp.trace(),
            tools_discovered=len(available),
            low_confidence=bool(context.retrieval and context.retrieval.low_confidence),
            degraded=context.degraded,
            duration_ms=duration_ms,
            llm=llm_meta,
        )
        logger.info(
            "workflow_completed",
            intent=plan.intent,
            plan_source=plan.source,
            steps=len(plan.steps),
            tool_calls=len(self.mcp.invocations),
            degraded=len(context.degraded),
            duration_ms=duration_ms,
            trace_id=trace.trace_id,
        )
        return response

    # ---------------------------------------------------------------- steps
    async def _execute_step(self, tool: str, context: WorkflowContext) -> None:
        handler = getattr(self, f"_step_{tool}", None)
        if handler is None:
            context.note_degradation(
                "mcp", f"No handler for planned step '{tool}'.", "Step skipped."
            )
            return
        try:
            await handler(context)
        except Exception as exc:
            logger.exception("workflow_step_failed", tool=tool)
            context.note_degradation(
                "tool",
                f"Step '{tool}' failed: {type(exc).__name__}.",
                "That evidence is missing from the answer.",
            )

    def _record_failure(self, context: WorkflowContext, call: ToolInvocation) -> None:
        context.note_degradation(
            "tool",
            f"{call.tool} ({call.status}): {call.error_message}",
            "The answer continues without this evidence.",
        )

    # -- asset resolution ---------------------------------------------------
    async def _step_search_assets(self, context: WorkflowContext) -> None:
        query = context.plan.asset_hint
        if not query:
            # Nothing named; scope-only requests are legitimate.
            return
        call = await self.mcp.call(
            "search_assets",
            {"query": query, **({"site": context.site} if context.site else {}), "limit": 5},
        )
        if not call.succeeded or not call.result:
            self._record_failure(context, call)
            return
        assets = call.result.get("assets") or []
        if not assets:
            context.note_degradation(
                "tool",
                f"No asset matched '{query}'.",
                "Continuing with the wider scope rather than a single asset.",
            )
            return
        top = assets[0]
        if len(assets) > 1 and not any(ch.isdigit() for ch in query):
            # "a compressor alarm" names a kind of equipment, not one asset.
            # Pinning it to whichever compressor ranked first would scope
            # every later step to an asset the user never mentioned.
            # The hint usually *is* the type ("compressor"); the top hit may
            # not be ("Compressor Lube Oil Pump" is a pump).
            types = [a["asset_type"] for a in assets if a.get("asset_type")]
            needle = query.strip().lower().replace(" ", "_")
            context.asset_type = next((t for t in types if needle in t), None) or (
                Counter(types).most_common(1)[0][0] if types else None
            )
            context.structured["asset_candidates"] = assets[:5]
            return
        context.asset_id = top["asset_id"]
        context.asset_name = top["asset_name"]
        context.asset_type = top.get("asset_type")
        context.site = context.site or top.get("site")
        context.unit = top.get("unit")
        context.structured["resolved_asset"] = top
        context.structured["asset_candidates"] = assets[:5]

    async def _step_get_asset_metadata(self, context: WorkflowContext) -> None:
        if not context.asset_id:
            return
        call = await self.mcp.call("get_asset_metadata", {"asset_id": context.asset_id})
        if call.succeeded and call.result:
            context.structured["asset_metadata"] = call.result["asset"]
        else:
            self._record_failure(context, call)

    # -- alarm selection ----------------------------------------------------
    async def _step_rank_active_alarms_by_priority(self, context: WorkflowContext) -> None:
        scope: dict[str, Any] = {"top_n": 5}
        if context.asset_id:
            scope["asset_id"] = context.asset_id
        elif context.site:
            scope["site"] = context.site
        elif context.unit:
            scope["unit"] = context.unit
        else:
            context.note_degradation(
                "mcp",
                "No asset, site or unit to rank alarms within.",
                "Alarm ranking was skipped; ask about a specific asset or site.",
            )
            return

        call = await self.mcp.call("rank_active_alarms_by_priority", scope)
        if not call.succeeded or not call.result:
            self._record_failure(context, call)
            return

        ranked = call.result.get("alarms") or []
        context.ranked_alarms = [_ranked_to_view(row) for row in ranked]
        context.structured["ranked_alarms"] = ranked
        if not ranked:
            context.note_degradation(
                "tool",
                "No open alarms in scope.",
                "There is nothing currently in alarm to raise an incident for.",
            )
            return

        leader = ranked[0]
        context.alarm_id = leader["alarm"]["alarm_id"]
        context.alarm_name = leader["alarm"]["alarm_name"]
        context.alarm_view = context.ranked_alarms[0]
        # Chain: the alarm's asset becomes the scope for everything after.
        context.asset_id = context.asset_id or leader["alarm"]["asset_id"]
        context.asset_name = context.asset_name or leader["alarm"]["asset_name"]
        context.site = context.site or leader["alarm"].get("site")
        context.unit = context.unit or leader["alarm"].get("unit")

    async def _step_list_alarms(self, context: WorkflowContext) -> None:
        """Scan the high-severity alarm history and pick the recurring one.

        An investigation ("recurring alarms on Boiler Feed Pump 101") has no
        single active alarm to start from, yet recommendations, similar
        tickets and the document filters all key off one. The most frequent
        high-severity alarm in the window is that alarm; its latest
        occurrence is the representative instance. Pages are followed until
        the history is exhausted or the page budget runs out.
        """
        scope: dict[str, Any] = {}
        if context.asset_id:
            scope["asset_id"] = context.asset_id
        elif context.unit:
            scope["unit"] = context.unit
        elif context.site:
            scope["site"] = context.site
        else:
            return

        alarms: list[dict[str, Any]] = []
        total_items, truncated = 0, False
        for page in range(1, MAX_ALARM_PAGES + 1):
            call = await self.mcp.call(
                "list_alarms",
                {
                    **scope,
                    "severity": ["high", "critical"],
                    "lookback_days": context.lookback_days,
                    "page": page,
                    "page_size": ALARM_PAGE_SIZE,
                    "sort_by": "start_time",
                    "sort_order": "desc",
                },
            )
            if not call.succeeded or not call.result:
                self._record_failure(context, call)
                break
            alarms.extend(call.result.get("alarms") or [])
            total_items = call.result.get("total_items", len(alarms))
            if not call.result.get("has_next"):
                break
        else:
            truncated = True

        counts = Counter(a["alarm_name"] for a in alarms)
        context.structured["alarm_history"] = {
            "high_severity_alarms": total_items,
            "scanned": len(alarms),
            "truncated": truncated,
            "lookback_days": context.lookback_days,
            "most_frequent": [
                {"alarm_name": n, "occurrences": c} for n, c in counts.most_common(5)
            ],
        }
        if context.alarm_id or not alarms:
            return

        # A name the user gave wins over the statistical choice.
        hinted = context.alarm_name if context.alarm_name in counts else None
        name, occurrences = (hinted, counts[hinted]) if hinted else counts.most_common(1)[0]
        latest = next(a for a in alarms if a["alarm_name"] == name)
        context.alarm_id = latest["alarm_id"]
        context.alarm_name = name
        context.alarm_view = AlarmSummaryView(
            alarm_id=latest["alarm_id"],
            alarm_name=name,
            asset_id=latest["asset_id"],
            asset_name=latest["asset_name"],
            site=latest["site"],
            unit=latest["unit"],
            severity=latest["severity"],
            status=latest["status"],
            start_time=latest["start_time"],
            occurrences_last_90_days=occurrences if context.lookback_days == 90 else None,
        )
        context.asset_id = context.asset_id or latest["asset_id"]
        context.asset_name = context.asset_name or latest["asset_name"]

    async def _step_get_alarm_detail(self, context: WorkflowContext) -> None:
        if not context.alarm_id:
            return
        call = await self.mcp.call("get_alarm_detail", {"alarm_id": context.alarm_id})
        if not call.succeeded or not call.result:
            self._record_failure(context, call)
            return
        payload = call.result
        context.structured["alarm_detail"] = payload
        context.asset_type = context.asset_type or payload.get("asset", {}).get("asset_type")
        if context.alarm_view:
            context.alarm_view = context.alarm_view.model_copy(
                update={
                    "occurrences_last_90_days": payload.get("occurrences_last_90_days"),
                    "measured_value": payload.get("measured_value"),
                    "limit_value": payload.get("limit_value"),
                    "unit_of_measure": payload.get("unit_of_measure"),
                }
            )
        else:
            context.alarm_view = _detail_to_view(payload)
            context.alarm_name = context.alarm_view.alarm_name

    async def _step_score_alarm_priority(self, context: WorkflowContext) -> None:
        if not context.alarm_id:
            return
        call = await self.mcp.call("score_alarm_priority", {"alarm_id": context.alarm_id})
        if not call.succeeded or not call.result:
            self._record_failure(context, call)
            return
        payload = call.result
        context.structured["priority"] = payload
        if context.alarm_view:
            context.alarm_view = context.alarm_view.model_copy(
                update={
                    "priority_score": payload["priority_score"],
                    "priority_band": payload["priority_band"],
                    "priority_rationale": payload["rationale"],
                }
            )

    # -- analytics ----------------------------------------------------------
    async def _step_summarize_alarms(self, context: WorkflowContext) -> None:
        # A rollup is meaningful across the whole plant: "summarise critical
        # alarms" names no asset and should not come back empty.
        scope = self._scope_args(context)
        if not scope:
            context.structured["scope"] = "plant-wide"
        call = await self.mcp.call(
            "summarize_alarms",
            {
                **scope,
                "lookback_days": context.lookback_days,
                "group_by": ["alarm_name", "severity"],
                "kpis": ["alarm_count", "critical_count", "recurring_rate", "avg_ack_delay"],
            },
        )
        if call.succeeded and call.result:
            context.structured["summary"] = call.result
        else:
            self._record_failure(context, call)
        await self._snapshot_open_alarms(context, scope)

    async def _snapshot_open_alarms(self, context: WorkflowContext, scope: dict[str, Any]) -> None:
        """What is in alarm *now*, alongside the window rollup.

        The rollup counts alarms raised over a period and cannot say which
        are still open, yet "summarise active critical alarms" asks exactly
        that. One listing of open high and critical alarms answers it.
        """
        listing_scope: dict[str, Any] = {}
        if context.asset_id:
            listing_scope["asset_id"] = context.asset_id
        elif scope:
            listing_scope = {k: v for k, v in scope.items() if k in ("unit", "site")}
        call = await self.mcp.call(
            "list_alarms",
            {
                **listing_scope,
                "status": list(OPEN_STATUSES),
                "severity": ["critical", "high"],
                "page_size": ALARM_PAGE_SIZE,
                "sort_by": "severity",
                "sort_order": "desc",
            },
        )
        if not call.succeeded or not call.result:
            self._record_failure(context, call)
            return
        alarms = call.result.get("alarms") or []
        context.structured["open_alarms"] = {
            "total": call.result.get("total_items", len(alarms)),
            "truncated": bool(call.result.get("has_next")),
            "by_severity": dict(Counter(a["severity"] for a in alarms)),
            # Per severity, so "how many critical are unacknowledged" is
            # answered from counts, not inferred from the itemised excerpt.
            "by_severity_and_status": {
                severity: dict(Counter(a["status"] for a in alarms if a["severity"] == severity))
                for severity in ("critical", "high")
                if any(a["severity"] == severity for a in alarms)
            },
            # Critical first, oldest first within a severity: the longest-
            # standing critical alarm is the one an operator asks about.
            "alarms": sorted(alarms, key=lambda a: (a["severity"] != "critical", a["start_time"]))[
                :OPEN_ALARMS_SHOWN
            ],
        }

    async def _step_get_alarm_trends(self, context: WorkflowContext) -> None:
        # Like the summary, a trend line is meaningful plant-wide.
        scope = self._scope_args(context)
        if not scope:
            context.structured["scope"] = "plant-wide"
        call = await self.mcp.call(
            "get_alarm_trends",
            {
                **scope,
                "lookback_days": context.lookback_days,
                "bucket": "weekly",
                "metrics": ["alarm_count", "critical_count"],
            },
        )
        if call.succeeded and call.result:
            context.structured["trends"] = call.result
        else:
            self._record_failure(context, call)

    async def _step_correlate_alarms(self, context: WorkflowContext) -> None:
        scope = self._scope_args(context)
        if not scope:
            return
        call = await self.mcp.call(
            "correlate_alarms",
            {
                **scope,
                "lookback_days": context.lookback_days,
                "min_support": 2,
                "severity_threshold": "medium",
            },
        )
        if not call.succeeded or not call.result:
            self._record_failure(context, call)
            return
        payload = call.result
        context.structured["correlation"] = payload
        # Chain: correlated assets become the scope for the ticket lookup.
        context.correlated_asset_ids = [
            row["asset_id"] for row in (payload.get("correlated_assets") or [])[:5]
        ]

    async def _step_analyze_alarm_floods(self, context: WorkflowContext) -> None:
        scope = self._scope_args(context)
        if not scope:
            return
        call = await self.mcp.call(
            "analyze_alarm_floods", {**scope, "lookback_days": context.lookback_days}
        )
        if call.succeeded and call.result:
            context.structured["floods"] = call.result
        else:
            self._record_failure(context, call)

    async def _step_find_rationalization_candidates(self, context: WorkflowContext) -> None:
        scope = self._scope_args(context)
        if not scope:
            return
        call = await self.mcp.call(
            "find_rationalization_candidates",
            {**scope, "lookback_days": context.lookback_days},
        )
        if call.succeeded and call.result:
            context.structured["rationalization"] = call.result
        else:
            self._record_failure(context, call)

    async def _step_recommend_operator_actions(self, context: WorkflowContext) -> None:
        if not context.alarm_id:
            return
        call = await self.mcp.call(
            "recommend_operator_actions",
            {
                "alarm_id": context.alarm_id,
                "include_related": True,
                "include_historical_pattern": True,
            },
        )
        if not call.succeeded or not call.result:
            self._record_failure(context, call)
            return
        payload = call.result
        context.structured["recommendations"] = payload
        context.recommended_actions = payload.get("recommended_actions") or []
        context.likely_causes = payload.get("likely_causes") or []

    async def _step_compute_kpi(self, context: WorkflowContext) -> None:
        scope = self._scope_args(context)
        if not scope:
            return
        call = await self.mcp.call(
            "compute_kpi",
            {
                **scope,
                "calculation_type": "nuisance_alarm_score",
                "lookback_days": context.lookback_days,
            },
        )
        if call.succeeded and call.result:
            context.structured["kpi"] = call.result
        else:
            self._record_failure(context, call)

    # -- ticketing ----------------------------------------------------------
    async def _step_find_similar_tickets(self, context: WorkflowContext) -> None:
        arguments: dict[str, Any] = {"resolved_only": True, "limit": 5}
        if context.alarm_name:
            arguments["alarm_name"] = context.alarm_name
        if context.asset_id:
            arguments["asset_id"] = context.asset_id
        if context.asset_type:
            arguments["asset_type"] = context.asset_type
        if "alarm_name" not in arguments:
            # Without an alarm name the symptom is only in the wording
            # ("vibration"), so the request itself becomes the search text.
            arguments["query"] = context.message[:2000]

        call = await self.mcp.call("find_similar_tickets", arguments)
        if not call.succeeded or not call.result:
            self._record_failure(context, call)
            return
        payload = call.result
        context.similar_tickets = [_similar(row) for row in payload.get("results") or []]
        context.structured["similar_tickets"] = payload
        if payload.get("low_confidence"):
            context.note_degradation(
                "ticketing",
                "No historical ticket cleared the similarity threshold.",
                "No precedent is offered rather than a weak match presented as one.",
            )

    async def _step_list_tickets(self, context: WorkflowContext) -> None:
        asset_ids = context.correlated_asset_ids or ([context.asset_id] if context.asset_id else [])
        if not asset_ids:
            return
        call = await self.mcp.call(
            "list_tickets", {"asset_ids": asset_ids, "open_only": True, "page_size": 25}
        )
        if not call.succeeded or not call.result:
            self._record_failure(context, call)
            return
        payload = call.result
        context.open_linked_tickets = [_ticket_summary(row) for row in payload.get("tickets") or []]
        context.structured["open_linked_tickets"] = payload

    # -- local steps --------------------------------------------------------
    async def _step_retrieve_documents(self, context: WorkflowContext) -> None:
        """Document retrieval, scoped by what the MCP tools discovered.

        This is the join between the two halves of the system: the query is
        enriched with the alarm and asset the tools resolved, and the
        metadata filters come from the same place. Retrieval before the
        tool chain would be a separate demonstration, not one workflow.
        """
        parts = [context.message]
        if context.alarm_name:
            parts.append(context.alarm_name)
        if context.asset_name:
            parts.append(context.asset_name)
        for cause in context.likely_causes[:2]:
            parts.append(str(cause.get("cause", "")))
        query = " ".join(p for p in parts if p)

        try:
            result = self.retrieval.retrieve(
                query,
                top_k=self.settings.rag_top_k,
                asset_type=context.asset_type,
                alarm_name=context.alarm_name,
            )
        except Exception as exc:
            logger.exception("retrieval_failed")
            context.note_degradation(
                "rag",
                f"Document retrieval failed: {type(exc).__name__}. "
                "Has the index been built with `make ingest`?",
                "The answer rests on alarm data alone, without documented guidance.",
            )
            return

        context.retrieval = result
        if result.low_confidence:
            context.note_degradation(
                "rag",
                f"No document cleared the relevance threshold (best score {result.best_score}).",
                "No procedure is cited; the answer says so rather than guessing.",
            )
        if result.injection_attempts_neutralised:
            context.note_degradation(
                "rag",
                f"{result.injection_attempts_neutralised} retrieved passage(s) contained "
                "instruction-like content, which was neutralised.",
                "Those passages were used as evidence only.",
            )

    async def _step_draft_ticket(self, context: WorkflowContext) -> None:
        if not context.alarm_view:
            context.note_degradation(
                "tool",
                "No alarm was selected, so no incident could be drafted.",
                "Name an asset or site with an open alarm.",
            )
            return
        draft = build_ticket_draft(
            conversation_id=context.conversation_id,
            alarm=context.alarm_view,
            asset_metadata=context.structured.get("asset_metadata"),
            recommendations=context.recommended_actions,
            likely_causes=context.likely_causes,
            similar_tickets=context.similar_tickets,
            correlation=context.structured.get("correlation"),
            retrieval=context.retrieval,
            open_linked_tickets=context.open_linked_tickets,
        )
        context.structured["ticket_draft"] = draft

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _scope_args(context: WorkflowContext) -> dict[str, Any]:
        if context.asset_id:
            return {"asset_ids": [context.asset_id]}
        if context.unit:
            return {"unit": context.unit}
        if context.site:
            return {"site": context.site}
        return {}

    async def _synthesise(self, context: WorkflowContext) -> tuple[str, dict[str, Any]]:
        try:
            return await synthesise_answer(
                provider=self.provider,
                message=context.message,
                plan=context.plan,
                alarm=context.alarm_view,
                structured=context.structured,
                similar_tickets=context.similar_tickets,
                retrieval=context.retrieval,
                retrieval_service=self.retrieval,
                degraded=context.degraded,
            )
        except LlmUnavailableError as exc:
            context.note_degradation(
                "llm",
                f"Answer synthesis unavailable: {exc}.",
                "A structured summary is shown instead of a written narrative.",
            )
            from copilot.orchestration.synthesis import deterministic_summary

            return deterministic_summary(context), {"provider": "none", "degraded": True}


# --------------------------------------------------------------------------
# Projections
# --------------------------------------------------------------------------
def _ranked_to_view(row: dict[str, Any]) -> AlarmSummaryView:
    alarm = row["alarm"]
    return AlarmSummaryView(
        alarm_id=alarm["alarm_id"],
        alarm_name=alarm["alarm_name"],
        asset_id=alarm["asset_id"],
        asset_name=alarm["asset_name"],
        site=alarm["site"],
        unit=alarm["unit"],
        severity=alarm["severity"],
        status=alarm["status"],
        start_time=alarm["start_time"],
        priority_score=row.get("priority_score"),
        priority_band=row.get("priority_band"),
        priority_rationale=row.get("rationale"),
    )


def _detail_to_view(payload: dict[str, Any]) -> AlarmSummaryView:
    alarm = payload["alarm"]
    return AlarmSummaryView(
        alarm_id=alarm["alarm_id"],
        alarm_name=alarm["alarm_name"],
        asset_id=alarm["asset_id"],
        asset_name=alarm["asset_name"],
        site=alarm["site"],
        unit=alarm["unit"],
        severity=alarm["severity"],
        status=alarm["status"],
        start_time=alarm["start_time"],
        occurrences_last_90_days=payload.get("occurrences_last_90_days"),
        measured_value=payload.get("measured_value"),
        limit_value=payload.get("limit_value"),
        unit_of_measure=payload.get("unit_of_measure"),
    )


def _similar(row: dict[str, Any]) -> SimilarTicketSummary:
    ticket = row["ticket"]
    return SimilarTicketSummary(
        key=ticket["key"],
        title=ticket["title"],
        status=ticket["status"],
        priority=ticket["priority"],
        score=row["score"],
        matched_on=row["matched_on"],
        root_cause=ticket.get("root_cause"),
        resolution=ticket.get("resolution"),
        time_to_resolve_hours=ticket.get("time_to_resolve_hours"),
    )


def _ticket_summary(ticket: dict[str, Any]) -> SimilarTicketSummary:
    return SimilarTicketSummary(
        key=ticket["key"],
        title=ticket["title"],
        status=ticket["status"],
        priority=ticket["priority"],
        score=0.0,
        matched_on=["linked_asset"],
        root_cause=ticket.get("root_cause"),
        resolution=ticket.get("resolution"),
        time_to_resolve_hours=ticket.get("time_to_resolve_hours"),
    )


def _citations(result: RetrievalResult | None) -> list[EvidenceCitation]:
    if result is None:
        return []
    return [EvidenceCitation(**c.model_dump()) for c in result.citations]


def new_draft_id() -> str:
    return f"draft-{uuid.uuid4().hex[:12]}"

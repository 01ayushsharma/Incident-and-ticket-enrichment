"""Domain models for the copilot API.

The response model is deliberately wide. A copilot answer that is only
prose is not auditable, so every response carries the evidence it was built
from: the MCP execution trace, the document citations, the ticket draft if
one was produced, and the reasons for anything that degraded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------
class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(
        default=None, description="Omit to start a new conversation."
    )


class ApproveTicketRequest(BaseModel):
    """Human approval of a drafted ticket.

    The edited fields are sent back rather than a bare 'yes': the person
    approving is accountable for the content, so what they saw and possibly
    changed is what gets written.
    """

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    draft_id: str
    approved: bool
    title: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, min_length=1, max_length=20000)
    priority: str | None = Field(default=None, pattern="^P[1-4]$")
    assignee: str | None = None
    labels: list[str] | None = Field(default=None, max_length=20)


class FeedbackRequest(BaseModel):
    """A person's rating of one answer.

    Keyed by the answer's trace id rather than its text, so a thumbs-down
    can be joined straight to the logs, the plan and the MCP calls that
    produced the answer.
    """

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128)
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------
class PlanStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool: str
    why: str = ""
    optional: bool = False


class Plan(BaseModel):
    """What the copilot intends to do, before it does it."""

    model_config = ConfigDict(extra="ignore")

    intent: str
    reasoning: str = ""
    asset_hint: str | None = None
    site_hint: str | None = None
    alarm_hint: str | None = None
    lookback_days: int | None = None
    needs_documents: bool = True
    steps: list[PlanStep] = Field(default_factory=list)
    source: Literal["llm", "rule_based"] = "llm"
    degraded_reason: str | None = None


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------
class EvidenceCitation(BaseModel):
    """A document citation, as rendered in the GUI."""

    model_config = ConfigDict(extra="forbid")

    marker: str
    doc_id: str
    title: str
    heading: str
    doc_type: str
    source_path: str
    score: float
    excerpt: str


class SimilarTicketSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    status: str
    priority: str
    score: float
    matched_on: list[str]
    root_cause: str | None = None
    resolution: str | None = None
    time_to_resolve_hours: float | None = None


class AlarmSummaryView(BaseModel):
    """The alarm an incident is about, flattened for the GUI."""

    model_config = ConfigDict(extra="forbid")

    alarm_id: str
    alarm_name: str
    asset_id: str
    asset_name: str
    site: str
    unit: str
    severity: str
    status: str
    start_time: str
    priority_score: float | None = None
    priority_band: str | None = None
    priority_rationale: str | None = None
    occurrences_last_90_days: int | None = None
    measured_value: float | None = None
    limit_value: float | None = None
    unit_of_measure: str | None = None


class TicketDraft(BaseModel):
    """A proposed ticket, pending human approval. Never written as-is."""

    model_config = ConfigDict(extra="forbid")

    draft_id: str
    title: str
    description: str
    priority: str = "P3"
    asset_id: str | None = None
    asset_name: str | None = None
    site: str | None = None
    unit: str | None = None
    alarm_name: str | None = None
    labels: list[str] = Field(default_factory=list)
    assignee: str | None = None
    linked_alarm_ids: list[str] = Field(default_factory=list)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    similar_tickets: list[SimilarTicketSummary] = Field(default_factory=list)
    requires_approval: bool = True
    approval_reference: str = Field(description="Stable key making a repeated approval idempotent.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CreatedTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    status: str
    priority: str
    url_path: str
    created: bool = Field(description="False when an idempotent replay returned it.")


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------
class DegradationNotice(BaseModel):
    """Something did not work. Surfaced, never hidden."""

    model_config = ConfigDict(extra="forbid")

    component: Literal["llm", "mcp", "rag", "tool", "ticketing"]
    detail: str
    impact: str


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    request_id: str
    trace_id: str
    message: str = Field(description="The grounded natural-language answer.")
    intent: str
    plan: Plan

    alarm: AlarmSummaryView | None = None
    alarms: list[AlarmSummaryView] = Field(default_factory=list)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    similar_tickets: list[SimilarTicketSummary] = Field(default_factory=list)
    open_linked_tickets: list[SimilarTicketSummary] = Field(default_factory=list)
    structured: dict[str, Any] = Field(
        default_factory=dict, description="Tool payloads the GUI renders as panels."
    )

    ticket_draft: TicketDraft | None = None
    created_ticket: CreatedTicket | None = None

    mcp_trace: list[dict[str, Any]] = Field(default_factory=list)
    tools_discovered: int = 0
    low_confidence: bool = False
    degraded: list[DegradationNotice] = Field(default_factory=list)
    duration_ms: float = 0.0
    llm: dict[str, Any] = Field(default_factory=dict)


class AuditEntry(BaseModel):
    """One line of the audit trail the GUI shows."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    conversation_id: str
    trace_id: str
    actor: str
    action: str
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    service: str
    version: str
    mcp: dict[str, Any]
    rag: dict[str, Any]
    llm: dict[str, Any]

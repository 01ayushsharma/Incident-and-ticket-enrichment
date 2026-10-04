"""Typed contracts for the mock ticketing system."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from connectors.http_errors import ErrorDetail, ErrorResponse

__all__ = ["ErrorDetail", "ErrorResponse"]  # re-exported for the OpenAPI document


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


OPEN_STATUSES: frozenset[TicketStatus] = frozenset({TicketStatus.OPEN, TicketStatus.IN_PROGRESS})


class TicketPriority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Comment(BaseModel):
    comment_id: str
    author: str
    body: str
    created_at: datetime


class Ticket(BaseModel):
    key: str
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority

    asset_id: str | None = None
    asset_name: str | None = None
    asset_type: str | None = None
    site: str | None = None
    unit: str | None = None
    alarm_name: str | None = None
    alarm_type: str | None = None

    labels: list[str] = Field(default_factory=list)
    assignee: str | None = None
    reporter: str | None = None

    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None

    root_cause: str | None = None
    resolution: str | None = None
    time_to_resolve_hours: float | None = None

    comments: list[Comment] = Field(default_factory=list)
    linked_alarm_ids: list[str] = Field(default_factory=list)


class TicketCreate(BaseModel):
    """Payload for creating a ticket.

    ``confirmed`` is a deliberate second gate. The copilot already requires an
    explicit human approval before it calls this endpoint; requiring the flag
    here too means a mis-wired orchestrator or a stray MCP tool call cannot
    create a ticket by accident. Defence in depth for the one write operation
    in the system.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=1, max_length=20000)
    priority: TicketPriority = TicketPriority.P3
    status: TicketStatus = TicketStatus.OPEN

    asset_id: str | None = None
    asset_name: str | None = None
    site: str | None = None
    unit: str | None = None
    alarm_name: str | None = None

    labels: list[str] = Field(default_factory=list, max_length=20)
    assignee: str | None = None
    reporter: str = "alarm-copilot"
    linked_alarm_ids: list[str] = Field(default_factory=list, max_length=50)

    confirmed: bool = Field(
        default=False,
        description=(
            "Must be true. Write operations require explicit confirmation; "
            "the request is rejected with 422 otherwise."
        ),
    )


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, min_length=1, max_length=20000)
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    assignee: str | None = None
    labels: list[str] | None = Field(default=None, max_length=20)
    root_cause: str | None = None
    resolution: str | None = None
    linked_alarm_ids: list[str] | None = Field(default=None, max_length=50)
    confirmed: bool = Field(default=False, description="Must be true, as for creation.")


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=10000)
    author: str = "alarm-copilot"


class Pagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool


class TicketListResponse(BaseModel):
    data: list[Ticket]
    pagination: Pagination


class SimilarTicketRequest(BaseModel):
    """Find historical tickets resembling a situation.

    At least one of ``query``, ``alarm_name`` or ``asset_id`` must be given -
    an unconstrained similarity search returns noise, and the copilot always
    has at least the alarm name to hand.
    """

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=2000)
    alarm_name: str | None = None
    asset_id: str | None = None
    asset_type: str | None = None
    site: str | None = None
    unit: str | None = None
    statuses: list[TicketStatus] | None = None
    exclude_keys: list[str] = Field(default_factory=list, max_length=50)
    resolved_only: bool = Field(
        default=False,
        description="Restrict to tickets that carry a resolution, for 'how was this fixed'.",
    )
    limit: int = Field(default=5, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class SimilarTicket(BaseModel):
    ticket: Ticket
    score: float
    matched_on: list[str] = Field(
        description="Which signals contributed: text, alarm_name, asset, asset_type, unit, site."
    )


class SimilarTicketResponse(BaseModel):
    query: dict[str, Any]
    count: int
    results: list[SimilarTicket]
    low_confidence: bool = Field(
        description="True when the best score fell below the requested min_score."
    )


class TicketFieldsResponse(BaseModel):
    statuses: list[str]
    priorities: list[str]
    open_statuses: list[str]
    labels: list[str]
    assignees: list[str]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    dataset: dict[str, Any]

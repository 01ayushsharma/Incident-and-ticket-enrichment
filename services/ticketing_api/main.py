"""Mock ticketing API - application entry point.

A deliberately small ITSM-shaped service: search historical tickets, read
one, create one, update one, comment on one. It is the write target for the
copilot, and the only place in the stack where state changes.

Run it standalone with::

    uvicorn ticketing_api.main:app --port 8100
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, Depends, FastAPI, Header, Path, Query, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request

from connectors import tracing as trace
from connectors.http_errors import (
    ErrorResponse,
    NotFoundError,
    ValidationError,
    register_exception_handlers,
)
from connectors.observability import configure_logging, get_logger
from ticketing_api.config import get_settings
from ticketing_api.schemas import (
    CommentCreate,
    HealthResponse,
    SimilarTicketRequest,
    SimilarTicketResponse,
    Ticket,
    TicketCreate,
    TicketFieldsResponse,
    TicketListResponse,
    TicketPriority,
    TicketStatus,
    TicketUpdate,
)
from ticketing_api.security import require_bearer_token
from ticketing_api.store import get_store, reset_store

SERVICE_NAME = "ticketing-api-mock"
VERSION = "0.1.0"

logger = get_logger(__name__)


class TraceMiddleware(BaseHTTPMiddleware):
    """Bind the inbound trace context and emit one access log line."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        context = trace.from_headers(request.headers)
        token = trace.set_current(context)
        structlog.contextvars.bind_contextvars(**context.as_log_fields())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars(
                "trace_id", "request_id", "client_id", "metadata_tag"
            )
            trace.reset_current(token)

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers.update(context.response_headers())
        response.headers["x-response-time-ms"] = f"{duration_ms:.2f}"
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
            **context.as_log_fields(),
        )
        return response


health_router = APIRouter(tags=["health"])
router = APIRouter(tags=["tickets"], dependencies=[Depends(require_bearer_token)])


@health_router.get("/health", response_model=HealthResponse, summary="Liveness (unauthenticated)")
def health() -> HealthResponse:
    return HealthResponse(
        status="ok", service=SERVICE_NAME, version=VERSION, dataset=get_store().summary()
    )


@router.get("/tickets", response_model=TicketListResponse, summary="List and filter tickets")
def list_tickets(
    status: list[TicketStatus] | None = Query(None, description="Repeatable status filter."),
    priority: list[TicketPriority] | None = Query(None),
    asset_id: str | None = Query(None),
    asset_ids: list[str] | None = Query(
        None, description="Repeatable. Used to find tickets across correlated assets."
    ),
    site: str | None = Query(None),
    unit: str | None = Query(None),
    alarm_name: str | None = Query(None),
    label: str | None = Query(None),
    q: str | None = Query(None, max_length=500, description="Free-text substring filter."),
    open_only: bool = Query(False, description="Shorthand for status in (open, in_progress)."),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1),
    sort_by: str = Query("created_at", pattern="^(created_at|updated_at|priority|status|key)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
) -> TicketListResponse:
    settings = get_settings()
    size = page_size or settings.default_page_size
    if size > settings.max_page_size:
        raise ValidationError(
            f"page_size {size} exceeds the maximum of {settings.max_page_size}.",
            details={"max_page_size": settings.max_page_size},
        )
    data, pagination = get_store().list(
        status=status,
        priority=priority,
        asset_id=asset_id,
        asset_ids=asset_ids,
        site=site,
        unit=unit,
        alarm_name=alarm_name,
        label=label,
        query=q,
        open_only=open_only,
        page=page,
        page_size=size,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return TicketListResponse(data=data, pagination=pagination)


@router.post(
    "/tickets/search",
    response_model=SimilarTicketResponse,
    summary="Find historical tickets similar to a situation",
)
def search_similar(req: SimilarTicketRequest) -> SimilarTicketResponse:
    if not any((req.query, req.alarm_name, req.asset_id)):
        raise ValidationError(
            "Provide at least one of 'query', 'alarm_name' or 'asset_id'.",
            details={"required_any_of": ["query", "alarm_name", "asset_id"]},
        )
    results = get_store().find_similar(req)
    kept = [r for r in results if r.score >= req.min_score]
    best = results[0].score if results else 0.0
    return SimilarTicketResponse(
        query=req.model_dump(exclude_none=True, exclude_defaults=True),
        count=len(kept),
        results=kept,
        low_confidence=best < req.min_score or not kept,
    )


@router.get("/tickets/fields", response_model=TicketFieldsResponse, summary="Allowed field values")
def ticket_fields() -> TicketFieldsResponse:
    store = get_store()
    return TicketFieldsResponse(
        statuses=[s.value for s in TicketStatus],
        priorities=[p.value for p in TicketPriority],
        open_statuses=[TicketStatus.OPEN.value, TicketStatus.IN_PROGRESS.value],
        labels=store.distinct_labels(),
        assignees=store.distinct_assignees(),
    )


@router.get("/tickets/{key}", response_model=Ticket, summary="Read one ticket")
def get_ticket(key: str = Path(..., min_length=3, max_length=32)) -> Ticket:
    ticket = get_store().get(key)
    if ticket is None:
        raise NotFoundError(f"No ticket with key '{key}'.", details={"key": key})
    return ticket


@router.post(
    "/tickets",
    response_model=Ticket,
    status_code=201,
    summary="Create a ticket (requires explicit confirmation)",
)
def create_ticket(
    payload: TicketCreate,
    response: Response,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        description=(
            "Required. Replaying the same key returns the original ticket with 200 "
            "instead of creating a duplicate, which makes the caller's retries safe."
        ),
    ),
) -> Ticket:
    if not payload.confirmed:
        # The copilot gates this behind a human approval step; this is the
        # second, independent gate. See TicketCreate.confirmed.
        raise ValidationError(
            "Ticket creation requires explicit confirmation. Set 'confirmed' to true.",
            details={"field": "confirmed", "received": payload.confirmed},
        )
    ticket, created = get_store().create(payload, idempotency_key)
    if not created:
        # Idempotent replay: not a new resource, so not a 201.
        response.status_code = 200
        logger.info("ticket_create_replayed", ticket_key=ticket.key)
    else:
        logger.info(
            "ticket_created",
            ticket_key=ticket.key,
            asset_id=ticket.asset_id,
            priority=ticket.priority.value,
            linked_alarms=len(ticket.linked_alarm_ids),
        )
    return ticket


@router.patch("/tickets/{key}", response_model=Ticket, summary="Update a ticket")
def update_ticket(
    payload: TicketUpdate, key: str = Path(..., min_length=3, max_length=32)
) -> Ticket:
    if not payload.confirmed:
        raise ValidationError(
            "Ticket update requires explicit confirmation. Set 'confirmed' to true.",
            details={"field": "confirmed"},
        )
    ticket = get_store().update(key, payload)
    if ticket is None:
        raise NotFoundError(f"No ticket with key '{key}'.", details={"key": key})
    logger.info("ticket_updated", ticket_key=key, status=ticket.status.value)
    return ticket


@router.post("/tickets/{key}/comments", response_model=Ticket, summary="Append a comment")
def add_comment(
    payload: CommentCreate, key: str = Path(..., min_length=3, max_length=32)
) -> Ticket:
    ticket = get_store().add_comment(key, payload)
    if ticket is None:
        raise NotFoundError(f"No ticket with key '{key}'.", details={"key": key})
    return ticket


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(SERVICE_NAME)
    store = get_store()
    logger.info("service_started", **store.summary())
    yield
    logger.info("service_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Mock Ticketing API",
        version=VERSION,
        description=(
            "Candidate-built mock ticketing system. Authenticate with "
            "`Authorization: Bearer <TICKETING_API_TOKEN>`; `GET /health` is "
            "unauthenticated. Ticket creation and update require `confirmed: true`, "
            "and creation additionally requires an `Idempotency-Key` header so that "
            "a retried write cannot duplicate a ticket."
        ),
        lifespan=lifespan,
        responses={
            401: {"model": ErrorResponse, "description": "Missing or invalid bearer token"},
            404: {"model": ErrorResponse, "description": "Ticket not found"},
            422: {"model": ErrorResponse, "description": "Validation failed or not confirmed"},
        },
    )
    app.add_middleware(TraceMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(router)
    return app


app = create_app()


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    settings = get_settings()
    configure_logging(SERVICE_NAME)
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["app", "create_app", "main", "reset_store"]

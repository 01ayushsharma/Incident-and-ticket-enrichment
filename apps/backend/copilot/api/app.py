"""Copilot backend - FastAPI application.

Endpoints:

    GET  /health                       readiness of every dependency
    GET  /tools                        the discovered MCP tool catalog
    POST /chat                         run the combined MCP + RAG workflow
    POST /tickets/approve              the human approval gate for the write
    GET  /conversations/{id}           turns, drafts and created tickets
    GET  /conversations/{id}/audit     the audit trail

The write operation lives behind ``/tickets/approve`` and nowhere else.
``/chat`` can only ever produce a *draft*; no path through the chat endpoint
creates a ticket, which is the property the assignment's approval
requirement actually needs.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

import structlog
from fastapi import APIRouter, Depends, FastAPI, Path, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request

from connectors import tracing
from connectors.http_errors import (
    ErrorResponse,
    NotFoundError,
    ValidationError,
    register_exception_handlers,
)
from connectors.observability import configure_logging, get_logger
from copilot.config import CopilotSettings, get_settings
from copilot.llm.base import RetryingProvider
from copilot.llm.providers import build_provider
from copilot.mcp_client import McpClientConfig, McpToolClient, McpUnavailableError
from copilot.models import (
    ApproveTicketRequest,
    AuditEntry,
    ChatRequest,
    ChatResponse,
    CreatedTicket,
    FeedbackRequest,
    HealthResponse,
)
from copilot.orchestration.workflow import IncidentWorkflow
from copilot.state import ConversationStore
from rag.retrieval.service import RetrievalService

SERVICE_NAME = "incident-copilot-backend"
VERSION = "0.1.0"

logger = get_logger(__name__)


class TraceMiddleware(BaseHTTPMiddleware):
    """Establish the trace that flows through MCP into the source systems."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        context = tracing.from_headers(request.headers)
        if not context.client_id:
            # Name the hop when the caller did not. Without this the MCP
            # server and both source systems log a trace with no origin,
            # which is the first thing you want when reading one back.
            context = replace(context, client_id=SERVICE_NAME)
        token = tracing.set_current(context)
        structlog.contextvars.bind_contextvars(**context.as_log_fields())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars(
                "trace_id", "request_id", "client_id", "metadata_tag"
            )
            tracing.reset_current(token)

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


class Services:
    """Process-wide dependencies, built once at startup."""

    def __init__(self, settings: CopilotSettings) -> None:
        self.settings = settings
        self.conversations = ConversationStore(
            max_conversations=settings.max_conversations,
            max_turns=settings.max_history_turns,
        )
        self.retrieval = RetrievalService()
        self.provider = RetryingProvider(
            build_provider(
                settings.llm_provider,
                model=settings.llm_model,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout_seconds=settings.llm_timeout_seconds,
                max_output_tokens=settings.llm_max_output_tokens,
            ),
            max_retries=settings.llm_max_retries,
        )
        self.mcp = McpToolClient(
            McpClientConfig(
                transport=settings.mcp_transport,  # type: ignore[arg-type]
                url=settings.mcp_server_url,
                tool_timeout_seconds=settings.mcp_tool_timeout_seconds,
            )
        )
        self.mcp_error: str | None = None

    async def start(self) -> None:
        try:
            await self.mcp.connect()
        except McpUnavailableError as exc:
            # Start anyway: /health must be able to report *why* the copilot
            # is unusable, which it cannot do if startup crashes.
            self.mcp_error = str(exc)
            logger.error("mcp_connect_failed_at_startup", reason=str(exc))

    async def stop(self) -> None:
        await self.mcp.aclose()
        await self.provider.aclose()

    def workflow(self) -> IncidentWorkflow:
        return IncidentWorkflow(
            mcp=self.mcp,
            retrieval=self.retrieval,
            provider=self.provider,
            settings=self.settings,
        )


_services: Services | None = None


def get_services() -> Services:
    if _services is None:  # pragma: no cover - guarded by lifespan
        raise RuntimeError("Services are not initialised")
    return _services


def set_services(services: Services | None) -> None:
    """Install the service container. Tests use this to inject fakes."""
    global _services
    _services = services


router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(services: Services = Depends(get_services)) -> HealthResponse:
    """Readiness of every dependency, with enough detail to act on."""
    mcp_ok = services.mcp_error is None and bool(services.mcp.tools)
    try:
        indexed = services.retrieval.store.count()
    except Exception as exc:
        indexed = -1
        logger.warning("rag_health_probe_failed", error=str(exc)[:200])

    return HealthResponse(
        status="ok" if mcp_ok and indexed > 0 else "degraded",
        service=SERVICE_NAME,
        version=VERSION,
        mcp={
            "connected": mcp_ok,
            "server": services.mcp.server_name,
            "server_version": services.mcp.server_version,
            "transport": services.settings.mcp_transport,
            "url": services.settings.mcp_server_url,
            "tools": len(services.mcp.tools),
            "error": services.mcp_error,
        },
        rag={
            "indexed_chunks": indexed,
            "collection": services.retrieval.settings.vector_store_collection,
            "hint": None if indexed > 0 else "Run `make ingest` to build the index.",
        },
        llm=services.provider.describe(),
    )


@router.get("/tools", tags=["mcp"])
async def list_tools(services: Services = Depends(get_services)) -> dict[str, Any]:
    """The MCP tool catalog, for the GUI's tool-discovery panel."""
    tools = services.mcp.tools
    return {
        "server": services.mcp.server_name,
        "server_version": services.mcp.server_version,
        "transport": services.settings.mcp_transport,
        "count": len(tools),
        "write_tools": services.mcp.write_tools(),
        "tools": [
            {
                "name": tool.name,
                "title": tool.title,
                "description": tool.description,
                "read_only": tool.read_only,
                "destructive": tool.destructive,
                "arguments": tool.argument_names,
                "required": tool.required_arguments,
                "input_schema": tool.input_schema,
            }
            for tool in sorted(tools.values(), key=lambda t: t.name)
        ],
    }


@router.post("/chat", response_model=ChatResponse, tags=["copilot"])
async def chat(request: ChatRequest, services: Services = Depends(get_services)) -> ChatResponse:
    """Run the combined workflow. Produces drafts, never creates tickets."""
    if services.mcp_error is not None and not services.mcp.tools:
        raise ValidationError(
            "The copilot cannot reach its MCP server, so no source-system data is "
            "available. Check that the MCP server is running.",
            details={"mcp_error": services.mcp_error, "mcp_url": services.settings.mcp_server_url},
        )

    conversation = services.conversations.get_or_create(request.conversation_id)
    conversation.add_turn("user", request.message)
    trace = tracing.current()

    conversation.record(
        actor="user",
        action="message",
        detail=request.message[:500],
        trace_id=trace.trace_id,
    )

    response = await services.workflow().run(
        request.message,
        conversation_id=conversation.conversation_id,
        history=conversation.history[:-1],
    )
    conversation.add_turn("assistant", response.message)

    if response.ticket_draft is not None:
        conversation.drafts[response.ticket_draft.draft_id] = response.ticket_draft
        conversation.record(
            actor="copilot",
            action="ticket_drafted",
            detail=f"Drafted '{response.ticket_draft.title}' at "
            f"{response.ticket_draft.priority}; awaiting approval.",
            trace_id=trace.trace_id,
            metadata={
                "draft_id": response.ticket_draft.draft_id,
                "alarm_ids": response.ticket_draft.linked_alarm_ids,
                "citations": [c.doc_id for c in response.ticket_draft.citations],
            },
        )

    conversation.record(
        actor="copilot",
        action="answered",
        detail=f"intent={response.intent}, tools={len(response.mcp_trace)}, "
        f"citations={len(response.citations)}",
        trace_id=trace.trace_id,
        metadata={"degraded": [d.component for d in response.degraded]},
    )
    return response


@router.post("/tickets/approve", response_model=ChatResponse, tags=["copilot"])
async def approve_ticket(
    request: ApproveTicketRequest, services: Services = Depends(get_services)
) -> ChatResponse:
    """The approval gate. The only path that creates a ticket."""
    conversation = services.conversations.get(request.conversation_id)
    if conversation is None:
        raise NotFoundError(
            f"No conversation '{request.conversation_id}'.",
            details={"conversation_id": request.conversation_id},
        )
    draft = conversation.drafts.get(request.draft_id)
    if draft is None:
        raise NotFoundError(
            f"No draft '{request.draft_id}' in this conversation.",
            details={"draft_id": request.draft_id, "available": sorted(conversation.drafts)},
        )

    trace = tracing.current()

    if not request.approved:
        conversation.record(
            actor="user",
            action="ticket_rejected",
            detail=f"Declined draft {draft.draft_id} ('{draft.title}').",
            trace_id=trace.trace_id,
            metadata={"draft_id": draft.draft_id},
        )
        return ChatResponse(
            conversation_id=conversation.conversation_id,
            request_id=trace.request_id,
            trace_id=trace.trace_id,
            message="Understood - no ticket was created. The draft remains available "
            "if you change your mind.",
            intent="create_ticket",
            plan=_approval_plan(),
            ticket_draft=draft,
        )

    # The operator may have edited the draft; what they approved is what is
    # written, not what the copilot originally proposed.
    edited = draft.model_copy(
        update={
            k: v
            for k, v in {
                "title": request.title,
                "description": request.description,
                "priority": request.priority,
                "assignee": request.assignee,
                "labels": request.labels,
            }.items()
            if v is not None
        }
    )
    was_edited = edited.model_dump(exclude={"created_at"}) != draft.model_dump(
        exclude={"created_at"}
    )

    services.mcp.reset_trace()
    call = await services.mcp.call(
        "create_ticket",
        {
            "title": edited.title,
            "description": edited.description,
            "approved": True,
            "approval_reference": edited.approval_reference,
            "priority": edited.priority,
            "asset_id": edited.asset_id,
            "asset_name": edited.asset_name,
            "site": edited.site,
            "unit": edited.unit,
            "alarm_name": edited.alarm_name,
            "labels": edited.labels,
            "assignee": edited.assignee,
            "linked_alarm_ids": edited.linked_alarm_ids,
        },
    )

    if not call.succeeded or not call.result:
        conversation.record(
            actor="copilot",
            action="ticket_creation_failed",
            detail=call.error_message or "Unknown failure.",
            trace_id=trace.trace_id,
            metadata={"draft_id": draft.draft_id},
        )
        return ChatResponse(
            conversation_id=conversation.conversation_id,
            request_id=trace.request_id,
            trace_id=trace.trace_id,
            message=(
                "The ticket could not be created. Nothing was written, and the draft "
                f"is unchanged.\n\n**Reason.** {call.error_message}"
            ),
            intent="create_ticket",
            plan=_approval_plan(),
            ticket_draft=draft,
            mcp_trace=services.mcp.trace(),
            degraded=[
                {
                    "component": "ticketing",
                    "detail": call.error_message or "unknown",
                    "impact": "No ticket was created.",
                }
            ],
        )

    payload = call.result
    ticket = payload["ticket"]
    created = CreatedTicket(
        key=ticket["key"],
        title=ticket["title"],
        status=ticket["status"],
        priority=ticket["priority"],
        url_path=payload["url_path"],
        created=payload["created"],
    )
    conversation.created_tickets[draft.draft_id] = created.key
    conversation.record(
        actor="user",
        action="ticket_approved",
        detail=f"Approved draft {draft.draft_id}" + (" with edits" if was_edited else " unchanged"),
        trace_id=trace.trace_id,
        metadata={"draft_id": draft.draft_id, "edited": was_edited},
    )
    conversation.record(
        actor="copilot",
        action="ticket_created",
        detail=f"{created.key} created at {created.priority}."
        if created.created
        else f"{created.key} already existed; idempotent replay returned it.",
        trace_id=trace.trace_id,
        metadata={"ticket_key": created.key, "idempotent_replay": not created.created},
    )

    message = (
        f"Ticket **{created.key}** created at **{created.priority}**"
        if created.created
        else f"Ticket **{created.key}** already existed for this approval and was returned "
        "unchanged, so no duplicate was opened"
    )
    if was_edited:
        message += ". Your edits were applied."
    else:
        message += "."

    return ChatResponse(
        conversation_id=conversation.conversation_id,
        request_id=trace.request_id,
        trace_id=trace.trace_id,
        message=message,
        intent="create_ticket",
        plan=_approval_plan(),
        ticket_draft=edited,
        created_ticket=created,
        citations=edited.citations,
        similar_tickets=edited.similar_tickets,
        mcp_trace=services.mcp.trace(),
    )


@router.get("/conversations/{conversation_id}", tags=["copilot"])
async def get_conversation(
    conversation_id: str = Path(..., min_length=3, max_length=64),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    conversation = services.conversations.get(conversation_id)
    if conversation is None:
        raise NotFoundError(f"No conversation '{conversation_id}'.")
    return {
        "conversation_id": conversation.conversation_id,
        "created_at": conversation.created_at,
        "turns": [{"role": m.role, "content": m.content} for m in conversation.history],
        "drafts": [d.model_dump() for d in conversation.drafts.values()],
        "created_tickets": conversation.created_tickets,
        "audit_entries": len(conversation.audit),
    }


@router.get(
    "/conversations/{conversation_id}/audit",
    response_model=list[AuditEntry],
    tags=["copilot"],
)
async def get_audit(
    conversation_id: str = Path(..., min_length=3, max_length=64),
    services: Services = Depends(get_services),
) -> list[AuditEntry]:
    conversation = services.conversations.get(conversation_id)
    if conversation is None:
        raise NotFoundError(f"No conversation '{conversation_id}'.")
    return conversation.audit


@router.post(
    "/conversations/{conversation_id}/feedback",
    response_model=AuditEntry,
    status_code=201,
    tags=["copilot"],
)
async def post_feedback(
    request: FeedbackRequest,
    conversation_id: str = Path(..., min_length=3, max_length=64),
    services: Services = Depends(get_services),
) -> AuditEntry:
    """Record a rating of one answer in the conversation's audit trail."""
    conversation = services.conversations.get(conversation_id)
    if conversation is None:
        raise NotFoundError(f"No conversation '{conversation_id}'.")

    detail = f"Rated the answer {'helpful' if request.rating == 'up' else 'not helpful'}"
    if request.comment:
        detail += f": {request.comment[:500]}"
    return conversation.record(
        actor="user",
        action="feedback",
        detail=detail,
        # The answer's trace, so the rating sits next to what it rates.
        trace_id=request.trace_id,
        metadata={
            "rating": request.rating,
            "comment": request.comment,
            "request_trace_id": tracing.current().trace_id,
        },
    )


def _approval_plan():
    from copilot.models import Plan

    return Plan(
        intent="create_ticket",
        reasoning="Human approval decision; no planning required.",
        source="rule_based",
        steps=[],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(SERVICE_NAME)
    services = Services(settings)
    set_services(services)
    await services.start()
    logger.info(
        "service_started",
        llm_provider=services.provider.describe()["provider"],
        mcp_tools=len(services.mcp.tools),
        mcp_error=services.mcp_error,
    )
    yield
    await services.stop()
    set_services(None)
    logger.info("service_stopped")


def create_app(lifespan_enabled: bool = True) -> FastAPI:
    app = FastAPI(
        title="Incident and Ticket Enrichment Copilot",
        version=VERSION,
        description=(
            "Copilot backend. Reaches the Alarm Management and ticketing systems "
            "exclusively through the MCP server, and grounds its answers in a "
            "retrieved document corpus. Ticket creation requires explicit human "
            "approval via POST /tickets/approve."
        ),
        lifespan=lifespan if lifespan_enabled else None,
        responses={
            404: {"model": ErrorResponse, "description": "Not found"},
            422: {"model": ErrorResponse, "description": "Validation failed"},
        },
    )
    app.add_middleware(TraceMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # The Streamlit GUI is served from a different port in compose.
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    settings = get_settings()
    configure_logging(SERVICE_NAME)
    uvicorn.run(app, host=settings.backend_host, port=settings.backend_port, log_config=None)


if __name__ == "__main__":  # pragma: no cover
    main()

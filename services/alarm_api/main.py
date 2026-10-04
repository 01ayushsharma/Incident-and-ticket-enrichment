"""Alarm Management API simulator - application entry point.

Implements the contract defined by the Postman collections in ``postman/``.
Run it standalone with::

    uvicorn alarm_api.main:app --port 8000

The OpenAPI document is served at ``/openapi.json`` and the interactive docs
at ``/docs``; the MCP server's tool catalog is derived from that document.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from alarm_api.config import DATA_NOW, DATA_START, get_settings
from alarm_api.domain import store
from alarm_api.middleware import FaultInjectionMiddleware, TraceMiddleware
from alarm_api.routers import alarms, assets, calculations, feedback, recommendations
from alarm_api.schemas import ErrorResponse, HealthResponse
from connectors.http_errors import register_exception_handlers
from connectors.observability import configure_logging, get_logger

SERVICE_NAME = "alarm-api-simulator"
VERSION = "0.1.0"

logger = get_logger(__name__)

health_router = APIRouter(tags=["health"])


@health_router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness and dataset fingerprint (unauthenticated)",
)
def health() -> HealthResponse:
    """Unauthenticated by design - the Postman collection marks it ``noauth``
    and Docker Compose uses it as the service health check."""
    dataset = store.get_dataset()
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=VERSION,
        dataset=dataset.summary,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(SERVICE_NAME)
    # Build the dataset at startup rather than on the first request, so the
    # container's health check only passes once the service is truly ready.
    dataset = store.get_dataset()
    logger.info(
        "service_started",
        seed=settings.seed,
        assets=len(dataset.assets),
        alarms=len(dataset.alarms),
        window_start=DATA_START.isoformat(),
        window_end=DATA_NOW.isoformat(),
    )
    yield
    logger.info("service_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Alarm Management API Simulator",
        version=VERSION,
        description=(
            "Synthetic Alarm Management source system implementing the contract in "
            "postman/. Authenticate with `Authorization: Bearer <ALARM_API_TOKEN>`; "
            "`GET /health` is unauthenticated. Trace metadata is propagated via the "
            "`trace_id`, `x-client-id` and `x-metadata-tag` headers and echoed on "
            "every response."
        ),
        lifespan=lifespan,
        responses={
            400: {"model": ErrorResponse, "description": "Bad request"},
            401: {"model": ErrorResponse, "description": "Missing or invalid bearer token"},
            404: {"model": ErrorResponse, "description": "Resource not found"},
            422: {"model": ErrorResponse, "description": "Schema validation failed"},
            503: {"model": ErrorResponse, "description": "Upstream temporarily unavailable"},
        },
    )

    # Outermost middleware runs first: trace binding must wrap fault injection
    # so that an injected failure is still logged with its trace id.
    app.add_middleware(FaultInjectionMiddleware)
    app.add_middleware(TraceMiddleware)

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(assets.router)
    app.include_router(alarms.router)
    app.include_router(recommendations.router)
    app.include_router(calculations.router)
    app.include_router(feedback.router)
    return app


app = create_app()


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    settings = get_settings()
    configure_logging(SERVICE_NAME)
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":  # pragma: no cover
    main()

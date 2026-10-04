"""Shared pytest fixtures.

The simulator's dataset is deterministic but expensive enough to build that
rebuilding it per test would dominate the run. It is therefore built once per
session and reset only where a test genuinely mutates global state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alarm_api.config import reset_settings
from alarm_api.domain import analytics, store
from alarm_api.domain.seed import Dataset, build_dataset
from fastapi.testclient import TestClient

TEST_SEED = 20260501

# The window the Postman collections use.
POSTMAN_START = datetime(2026, 5, 1, tzinfo=UTC)
POSTMAN_END = datetime(2026, 7, 1, tzinfo=UTC)

AUTH_TOKEN = "demo-token"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}
TRACE_HEADERS = {
    **AUTH_HEADERS,
    "trace_id": "trace-pytest-001",
    "x-client-id": "pytest-client",
    "x-metadata-tag": "automated-test",
}


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    """The deterministic plant dataset, built once for the whole session."""
    return build_dataset(TEST_SEED)


@pytest.fixture
def time_range() -> dict[str, str]:
    """The Postman time window, as a JSON-ready ``time_range`` object."""
    return {
        "start_time": POSTMAN_START.isoformat().replace("+00:00", "Z"),
        "end_time": POSTMAN_END.isoformat().replace("+00:00", "Z"),
    }


@pytest.fixture(scope="session")
def alarm_app():
    """The simulator's FastAPI application, wired to the test dataset."""
    import os

    os.environ.setdefault("ALARM_API_TOKEN", AUTH_TOKEN)
    os.environ.setdefault("ALARM_API_SEED", str(TEST_SEED))
    reset_settings()
    store.reset_dataset()

    from alarm_api.main import create_app

    return create_app()


@pytest.fixture
def client(alarm_app) -> TestClient:
    """An authenticated-capable HTTP client for the simulator."""
    with TestClient(alarm_app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _clear_calculation_registry():
    """Calculations are process-global; keep tests independent of each other."""
    yield
    analytics.reset_calculations()


@pytest.fixture
def bfp101_id(dataset: Dataset) -> str:
    """Asset id of Boiler Feed Pump 101 - the acceptance scenario's subject."""
    asset = next(a for a in dataset.assets if a.asset_name == "Boiler Feed Pump 101")
    return asset.asset_id


# --------------------------------------------------------------------------
# Mock ticketing API
# --------------------------------------------------------------------------
TICKET_TOKEN = "demo-ticket-token"
TICKET_AUTH_HEADERS = {"Authorization": f"Bearer {TICKET_TOKEN}"}


@pytest.fixture
def ticketing_client():
    """A client for the ticketing API with a freshly loaded corpus.

    Not session-scoped: these tests create and mutate tickets, so each one
    gets a clean store rather than inheriting another test's writes.
    """
    import os

    from ticketing_api.config import reset_settings as reset_ticket_settings
    from ticketing_api.store import reset_store

    os.environ.setdefault("TICKETING_API_TOKEN", TICKET_TOKEN)
    reset_ticket_settings()
    reset_store()

    from ticketing_api.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    reset_store()


# --------------------------------------------------------------------------
# RAG index shared by the orchestration and end-to-end tests
# --------------------------------------------------------------------------
CORPUS = Path(__file__).resolve().parents[1] / "rag" / "documents"


@pytest.fixture(scope="session")
def indexed_retrieval(tmp_path_factory):
    """A RetrievalService over a throwaway index of the real corpus."""
    from rag.config import RagSettings
    from rag.ingestion.pipeline import ingest
    from rag.retrieval.service import RetrievalService
    from rag.retrieval.store import ChunkStore

    index_dir = tmp_path_factory.mktemp("copilot-rag-index")
    settings = RagSettings(
        document_path=str(CORPUS),
        vector_store_path=str(index_dir),
        vector_store_collection="copilot_test_corpus",
    )
    store = ChunkStore(settings.vector_store_path, settings.vector_store_collection)
    ingest(rebuild=True, settings=settings, store=store)
    return RetrievalService(store=store, settings=settings)


@pytest.fixture
async def harness(indexed_retrieval):
    """The full stack in process: copilot -> MCP -> both source systems."""
    from tests.harness import build_harness

    async with build_harness(retrieval=indexed_retrieval) as built:
        yield built

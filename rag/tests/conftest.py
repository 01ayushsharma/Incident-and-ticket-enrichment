"""Fixtures for the RAG tests.

The real corpus is indexed once per session into a temporary directory.
Building it costs around 15 seconds (the ONNX embedding model runs on CPU),
which is worth paying once to test against the documents that actually
ship rather than against a toy fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "rag" / "documents"
INJECTION_CORPUS = REPO_ROOT / "test-data" / "injection-corpus"


@pytest.fixture(scope="session")
def rag_settings(tmp_path_factory):
    """Settings pointed at a throwaway index over the real corpus."""
    from rag.config import RagSettings

    index_dir = tmp_path_factory.mktemp("rag-index")
    return RagSettings(
        document_path=str(CORPUS),
        vector_store_path=str(index_dir),
        vector_store_collection="test_corpus",
    )


@pytest.fixture(scope="session")
def ingestion_report(rag_settings):
    """Build the index once and hand back the report."""
    from rag.ingestion.pipeline import ingest
    from rag.retrieval.store import ChunkStore

    store = ChunkStore(rag_settings.vector_store_path, rag_settings.vector_store_collection)
    report = ingest(rebuild=True, settings=rag_settings, store=store)
    return report


@pytest.fixture(scope="session")
def chunk_store(rag_settings, ingestion_report):
    from rag.retrieval.store import ChunkStore

    store = ChunkStore(rag_settings.vector_store_path, rag_settings.vector_store_collection)
    store.ensure_loaded()
    return store


@pytest.fixture(scope="session")
def retrieval(rag_settings, chunk_store):
    from rag.retrieval.service import RetrievalService

    return RetrievalService(store=chunk_store, settings=rag_settings)


@pytest.fixture(scope="session")
def injection_retrieval(tmp_path_factory):
    """A separate index containing the tampered test document."""
    from rag.config import RagSettings
    from rag.ingestion.pipeline import ingest
    from rag.retrieval.service import RetrievalService
    from rag.retrieval.store import ChunkStore

    index_dir = tmp_path_factory.mktemp("rag-index-injection")
    settings = RagSettings(
        document_path=str(INJECTION_CORPUS),
        vector_store_path=str(index_dir),
        vector_store_collection="injection_corpus",
        min_score=0.0,
    )
    store = ChunkStore(settings.vector_store_path, settings.vector_store_collection)
    ingest(rebuild=True, settings=settings, store=store)
    return RetrievalService(store=store, settings=settings)

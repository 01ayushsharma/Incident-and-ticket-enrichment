"""The ingestion pipeline: discover, extract, chunk, embed, index."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import structlog

from rag.config import RagSettings, get_settings
from rag.ingestion.chunker import chunk_document
from rag.ingestion.loader import (
    UnsupportedDocumentError,
    discover_documents,
    load_document,
)
from rag.models import Chunk, IngestionReport
from rag.retrieval.store import ChunkStore, get_store

logger = structlog.get_logger(__name__)


def build_chunks(document_path: Path, settings: RagSettings) -> tuple[list[Chunk], list[str]]:
    """Load and chunk every document. Returns ``(chunks, skipped)``.

    A document that fails to load is skipped and reported rather than
    aborting the run: one malformed file should not prevent the rest of the
    corpus being indexed.
    """
    chunks: list[Chunk] = []
    skipped: list[str] = []

    # Report files sitting in the corpus directory that we cannot ingest.
    # Silently ignoring them is how a document goes missing from the index
    # without anyone noticing.
    ingestable = set(discover_documents(document_path))
    for path in sorted(p for p in document_path.rglob("*") if p.is_file()):
        if path not in ingestable:
            skipped.append(f"{path.name}: unsupported file type '{path.suffix}'")

    for path in sorted(ingestable):
        try:
            document = load_document(path)
        except UnsupportedDocumentError as exc:
            skipped.append(f"{path.name}: {exc}")
            logger.warning("document_skipped", path=path.name, reason=str(exc))
            continue
        except (OSError, UnicodeDecodeError) as exc:
            skipped.append(f"{path.name}: {exc}")
            logger.warning("document_unreadable", path=path.name, reason=str(exc))
            continue

        if not document.body.strip():
            skipped.append(f"{path.name}: empty after extraction")
            continue

        produced = chunk_document(
            document.body,
            document.metadata,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            min_chunk_chars=settings.min_chunk_chars,
        )
        chunks.extend(produced)
        logger.info(
            "document_chunked",
            doc_id=document.metadata.doc_id,
            path=path.name,
            chunks=len(produced),
        )

    return chunks, skipped


def ingest(
    *,
    rebuild: bool = False,
    settings: RagSettings | None = None,
    store: ChunkStore | None = None,
) -> IngestionReport:
    """Build (or rebuild) the retrieval index from the document corpus."""
    settings = settings or get_settings()
    store = store or get_store()
    started = time.perf_counter()

    document_path = Path(settings.document_path)
    if not document_path.exists():
        raise FileNotFoundError(
            f"Document path does not exist: {document_path}. "
            "Set DOCUMENT_PATH or create the directory."
        )

    if rebuild:
        logger.info("index_rebuild_requested", collection=settings.vector_store_collection)
        store.reset()

    chunks, skipped = build_chunks(document_path, settings)
    store.add(chunks)
    store.ensure_loaded()

    report = IngestionReport(
        documents=len({c.doc_id for c in chunks}),
        chunks=len(chunks),
        skipped=skipped,
        by_doc_type=dict(Counter(c.doc_type for c in chunks)),
        total_tokens_estimate=sum(c.token_estimate for c in chunks),
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        index_path=settings.vector_store_path,
        collection=settings.vector_store_collection,
    )
    logger.info("ingestion_completed", **report.model_dump(exclude={"skipped"}))
    return report

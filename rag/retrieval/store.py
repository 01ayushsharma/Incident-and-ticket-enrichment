"""Vector store and lexical index.

Dense retrieval uses ChromaDB with its default embedding function, which is
all-MiniLM-L6-v2 exported to ONNX - the same model the more common
sentence-transformers route would use, but without pulling in PyTorch. On
this corpus that is the difference between a ~90MB dependency and a ~2.5GB
one, which matters for the container image.

Lexical retrieval uses BM25 over the same chunk texts. It is rebuilt from
the store on load rather than persisted separately, so the two indexes
cannot drift apart.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

import structlog

from rag.models import Chunk

logger = structlog.get_logger(__name__)

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "on",
        "in",
        "at",
        "to",
        "for",
        "with",
        "from",
        "by",
        "is",
        "was",
        "were",
        "be",
        "been",
        "being",
        "it",
        "its",
        "as",
        "into",
        "this",
        "that",
        "these",
        "those",
        "if",
        "then",
        "than",
        "which",
        "who",
        "whom",
        "what",
        "when",
        "where",
        "how",
        "why",
        "do",
        "does",
        "did",
        "not",
        "no",
        "nor",
        "so",
        "such",
        "can",
        "could",
        "should",
        "would",
        "may",
        "might",
        "must",
    ]
)


def tokenise(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


class ChunkStore:
    """Persistent dense store plus an in-memory BM25 index over the same chunks."""

    def __init__(self, path: str, collection: str) -> None:
        self.path = path
        self.collection_name = collection
        self._lock = threading.RLock()
        self._client: Any = None
        self._collection: Any = None
        self._bm25: Any = None
        self._ordered_ids: list[str] = []
        self._documents: dict[str, dict[str, Any]] = {}

    # -- lifecycle ----------------------------------------------------------
    def _ensure_client(self) -> Any:
        if self._client is None:
            import chromadb
            from chromadb.config import Settings

            Path(self.path).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=self.path,
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
        return self._client

    def _ensure_collection(self) -> Any:
        if self._collection is None:
            client = self._ensure_client()
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def reset(self) -> None:
        """Drop and recreate the collection. Used by `ingest --rebuild`."""
        client = self._ensure_client()
        with self._lock:
            try:
                client.delete_collection(self.collection_name)
            except Exception:
                logger.debug("collection_absent", collection=self.collection_name)
            self._collection = None
            self._bm25 = None
            self._ordered_ids = []
            self._documents = {}
            self._ensure_collection()

    # -- writes -------------------------------------------------------------
    def add(self, chunks: list[Chunk], batch_size: int = 128) -> int:
        """Upsert chunks. Embedding happens inside Chroma."""
        if not chunks:
            return 0
        collection = self._ensure_collection()
        with self._lock:
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start : start + batch_size]
                collection.upsert(
                    ids=[c.chunk_id for c in batch],
                    documents=[c.text for c in batch],
                    metadatas=[c.as_chroma_metadata() for c in batch],
                )
            self._bm25 = None  # force a lexical rebuild on next query
        return len(chunks)

    # -- reads --------------------------------------------------------------
    def count(self) -> int:
        return self._ensure_collection().count()

    def _load_all(self) -> None:
        """Pull every chunk into memory to build the BM25 index.

        Viable because the corpus is small by design. A corpus large enough
        to make this impractical would want a search engine holding both
        indexes, which is noted in docs/known-limitations.md.
        """
        collection = self._ensure_collection()
        payload = collection.get(include=["documents", "metadatas"])
        ids = payload.get("ids") or []
        documents = payload.get("documents") or []
        metadatas = payload.get("metadatas") or []

        self._ordered_ids = list(ids)
        self._documents = {
            chunk_id: {"text": text, "metadata": metadata or {}}
            for chunk_id, text, metadata in zip(ids, documents, metadatas, strict=False)
        }

        from rank_bm25 import BM25Okapi

        corpus = [tokenise(self._documents[i]["text"]) for i in self._ordered_ids]
        self._bm25 = BM25Okapi(corpus) if any(corpus) else None

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._bm25 is None or not self._ordered_ids:
                self._load_all()

    def dense_search(
        self, query: str, k: int, where: dict[str, Any] | None = None
    ) -> list[tuple[str, float, str, dict[str, Any]]]:
        """Return ``(chunk_id, similarity, text, metadata)`` ranked by similarity."""
        collection = self._ensure_collection()
        total = collection.count()
        if total == 0:
            return []
        result = collection.query(
            query_texts=[query],
            n_results=min(k, total),
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        out: list[tuple[str, float, str, dict[str, Any]]] = []
        for chunk_id, text, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=False
        ):
            # Cosine distance in [0, 2]; convert to a similarity in [0, 1].
            similarity = max(0.0, 1.0 - float(distance))
            out.append((chunk_id, similarity, text, metadata or {}))
        return out

    # BM25 saturation constant. Mapping raw -> raw/(raw+K) gives an absolute
    # score in [0, 1) that is comparable across queries. Normalising against
    # the best hit instead would score the top result 1.0 for every query,
    # including one with no real match, which defeats low-confidence
    # detection entirely.
    BM25_SATURATION = 8.0

    def lexical_search(self, query: str, k: int) -> list[tuple[str, float, str, dict[str, Any]]]:
        """BM25 over the same chunks, mapped to an absolute [0, 1) score."""
        self.ensure_loaded()
        if self._bm25 is None or not self._ordered_ids:
            return []
        tokens = tokenise(query)
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        if not len(scores) or max(scores) <= 0:
            return []

        ranked = sorted(zip(self._ordered_ids, scores, strict=False), key=lambda kv: -kv[1])[:k]
        return [
            (
                chunk_id,
                float(score) / (float(score) + self.BM25_SATURATION),
                self._documents[chunk_id]["text"],
                self._documents[chunk_id]["metadata"],
            )
            for chunk_id, score in ranked
            if score > 0
        ]

    def get(self, chunk_id: str) -> dict[str, Any] | None:
        self.ensure_loaded()
        return self._documents.get(chunk_id)


_store: ChunkStore | None = None


def get_store() -> ChunkStore:
    global _store
    if _store is None:
        from rag.config import get_settings

        settings = get_settings()
        _store = ChunkStore(settings.vector_store_path, settings.vector_store_collection)
    return _store


def reset_store() -> None:
    global _store
    _store = None

"""Hybrid retrieval service.

Dense and lexical results are fused by weighted score rather than by
reciprocal rank. Rank fusion discards the *margin* between hits, and the
margin is exactly what the low-confidence decision needs: "the best match
scored 0.31 and the next 0.29" is a different situation from "0.84 and
0.22", and rank fusion makes them look identical.

Both retrievers are normalised to [0, 1] against their own best hit before
fusion, so the blend weight means what it says.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from rag.config import RagSettings, get_settings
from rag.models import Citation, RetrievalResult, RetrievedChunk
from rag.retrieval import sanitize
from rag.retrieval.store import ChunkStore, get_store

logger = structlog.get_logger(__name__)


class RetrievalService:
    def __init__(
        self, store: ChunkStore | None = None, settings: RagSettings | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or get_store()

    # ----------------------------------------------------------------- query
    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        doc_types: list[str] | None = None,
        asset_type: str | None = None,
        alarm_name: str | None = None,
        site: str | None = None,
        min_score: float | None = None,
    ) -> RetrievalResult:
        """Retrieve, fuse, filter, sanitise and build citations."""
        started = time.perf_counter()
        k = top_k or self.settings.top_k
        floor = self.settings.min_score if min_score is None else min_score
        candidates = max(k * self.settings.candidate_multiplier, k)

        if not query.strip():
            return RetrievalResult(
                query=query,
                chunks=[],
                citations=[],
                low_confidence=True,
                best_score=0.0,
                duration_ms=0.0,
            )

        # The dense side filters inside Chroma; the lexical side is filtered
        # after scoring, since BM25 here runs over the whole corpus in memory.
        where = self._build_where(doc_types)
        dense = self.store.dense_search(query, candidates, where)
        # BM25 runs over the whole corpus, so the same filter has to be
        # applied to its output or doc_type filtering leaks lexical hits.
        lexical = self.store.lexical_search(query, candidates)
        if doc_types:
            allowed = set(doc_types)
            lexical = [row for row in lexical if row[3].get("doc_type") in allowed]

        fused = self._fuse(dense, lexical)
        fused = self._apply_soft_filters(fused, asset_type, alarm_name, site)

        # `chunk_id` breaks ties explicitly. Without it the order of equally
        # scored chunks falls back to insertion order - dense hits first,
        # then lexical - which is an implementation detail that would shift
        # the moment either retriever's ordering changed.
        ranked = sorted(fused.values(), key=lambda c: (-c.score, c.chunk_id))
        total_candidates = len(ranked)
        kept = [c for c in ranked if c.score >= floor][:k]

        neutralised = 0
        for chunk in kept:
            cleaned = sanitize.sanitise(chunk.text)
            if cleaned.was_modified:
                neutralised += 1
                chunk.text = cleaned.text
                chunk.sanitised = True
                logger.warning(
                    "prompt_injection_neutralised",
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    findings=cleaned.findings,
                )

        best = ranked[0].score if ranked else 0.0
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        result = RetrievalResult(
            query=query,
            chunks=kept,
            citations=self._citations(kept),
            low_confidence=not kept or best < floor,
            best_score=round(best, 4),
            filters_applied={
                k_: v
                for k_, v in {
                    "doc_types": doc_types,
                    "asset_type": asset_type,
                    "alarm_name": alarm_name,
                    "site": site,
                    "min_score": floor,
                }.items()
                if v
            },
            injection_attempts_neutralised=neutralised,
            duration_ms=duration_ms,
            total_candidates=total_candidates,
        )
        logger.info(
            "retrieval_completed",
            query_length=len(query),
            returned=len(kept),
            candidates=total_candidates,
            best_score=result.best_score,
            low_confidence=result.low_confidence,
            neutralised=neutralised,
            duration_ms=duration_ms,
        )
        return result

    # --------------------------------------------------------------- helpers
    def _build_where(self, doc_types: list[str] | None) -> dict[str, Any] | None:
        if not doc_types:
            return None
        if len(doc_types) == 1:
            return {"doc_type": doc_types[0]}
        return {"$or": [{"doc_type": t} for t in doc_types]}

    def _fuse(
        self,
        dense: list[tuple[str, float, str, dict[str, Any]]],
        lexical: list[tuple[str, float, str, dict[str, Any]]],
    ) -> dict[str, RetrievedChunk]:
        weight_dense = self.settings.dense_weight
        weight_lexical = self.settings.lexical_weight
        merged: dict[str, RetrievedChunk] = {}

        for chunk_id, score, text, metadata in dense:
            merged[chunk_id] = self._to_chunk(
                chunk_id,
                text,
                metadata,
                dense_score=score,
                lexical_score=0.0,
                retrieved_by=["dense"],
            )
        for chunk_id, score, text, metadata in lexical:
            if chunk_id in merged:
                existing = merged[chunk_id]
                existing.lexical_score = score
                existing.retrieved_by.append("lexical")
            else:
                merged[chunk_id] = self._to_chunk(
                    chunk_id,
                    text,
                    metadata,
                    dense_score=0.0,
                    lexical_score=score,
                    retrieved_by=["lexical"],
                )

        for chunk in merged.values():
            chunk.score = round(
                weight_dense * chunk.dense_score + weight_lexical * chunk.lexical_score, 4
            )
        return merged

    @staticmethod
    def _to_chunk(
        chunk_id: str,
        text: str,
        metadata: dict[str, Any],
        *,
        dense_score: float,
        lexical_score: float,
        retrieved_by: list[str],
    ) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=chunk_id,
            doc_id=str(metadata.get("doc_id", "")),
            title=str(metadata.get("title", "")),
            doc_type=str(metadata.get("doc_type", "")),
            heading=str(metadata.get("heading", "")),
            text=text,
            score=0.0,
            dense_score=round(dense_score, 4),
            lexical_score=round(lexical_score, 4),
            retrieved_by=retrieved_by,
            source_path=str(metadata.get("source_path", "")),
        )

    def _apply_soft_filters(
        self,
        chunks: dict[str, RetrievedChunk],
        asset_type: str | None,
        alarm_name: str | None,
        site: str | None,
    ) -> dict[str, RetrievedChunk]:
        """Boost scope-matching chunks; drop scope-contradicting ones.

        A hard filter would discard the general guidance that carries no
        asset-type metadata, which is often the most useful document. So
        the rule is: a document that *declares* a scope and contradicts the
        query is dropped; one that declares nothing is kept unboosted.
        """
        if not any((asset_type, alarm_name, site)):
            return chunks

        kept: dict[str, RetrievedChunk] = {}
        for chunk_id, chunk in chunks.items():
            record = self.store.get(chunk_id)
            metadata = (record or {}).get("metadata", {})
            boost = 0.0
            drop = False

            for value, field in (
                (asset_type, "asset_types"),
                (alarm_name, "alarms"),
                (site, "sites"),
            ):
                if not value:
                    continue
                declared = [v for v in str(metadata.get(field, "")).split("|") if v]
                if not declared:
                    continue
                if value in declared:
                    boost += 0.08
                else:
                    drop = True

            if drop and boost == 0.0:
                continue
            chunk.score = round(min(1.0, chunk.score + boost), 4)
            kept[chunk_id] = chunk
        return kept

    @staticmethod
    def _citations(chunks: list[RetrievedChunk]) -> list[Citation]:
        return [
            Citation(
                marker=f"[{index}]",
                doc_id=chunk.doc_id,
                title=chunk.title,
                heading=chunk.heading,
                doc_type=chunk.doc_type,
                source_path=chunk.source_path,
                score=chunk.score,
                excerpt=_excerpt(strip_context_prefix(chunk.text, chunk.title, chunk.heading)),
            )
            for index, chunk in enumerate(chunks, start=1)
        ]

    # ------------------------------------------------------------- prompting
    def build_context_block(self, result: RetrievalResult) -> str:
        """Render retrieved chunks for a prompt, fenced as untrusted data."""
        if result.is_empty:
            return "No relevant documents were retrieved."
        nonce = sanitize.new_fence_nonce()
        parts = [sanitize.UNTRUSTED_CONTENT_PREAMBLE, ""]
        for citation, chunk in zip(result.citations, result.chunks, strict=True):
            header = f"{citation.marker} {chunk.title}"
            if chunk.heading:
                header += f" > {chunk.heading}"
            body = strip_context_prefix(chunk.text, chunk.title, chunk.heading)
            parts.append(sanitize.fence(f"{header}\n\n{body}", nonce, source=chunk.doc_id))
            parts.append("")
        return "\n".join(parts).strip()


def strip_context_prefix(text: str, title: str, heading: str) -> str:
    """Remove the 'Title > Heading' prefix the chunker prepends.

    The prefix is deliberately embedded and indexed - it measurably improves
    recall for topic-shaped queries - but it is noise once the citation
    header already states where the passage came from.
    """
    prefix = f"{title} > {heading}\n\n" if heading else ""
    if prefix and text.startswith(prefix):
        return text[len(prefix) :]
    return text


def _excerpt(text: str, limit: int = 400) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rsplit(" ", 1)[0] + " ..."


_service: RetrievalService | None = None


def get_service() -> RetrievalService:
    global _service
    if _service is None:
        _service = RetrievalService()
    return _service


def reset_service() -> None:
    global _service
    _service = None

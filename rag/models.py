"""Domain types for the RAG pipeline.

Chunks and citations are the contract between ingestion, retrieval and the
copilot. A citation must carry enough to be *checkable* by a human - the
document id, its title, the heading the text came from, and the text
itself - because an unverifiable citation is worse than none.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentMetadata(BaseModel):
    """Front-matter of a corpus document, plus derived fields."""

    model_config = ConfigDict(extra="allow")

    doc_id: str
    title: str
    doc_type: str = "reference"
    revision: int | str | None = None
    effective_date: str | None = None
    owner: str | None = None
    applies_to_asset_types: list[str] = Field(default_factory=list)
    applies_to_assets: list[str] = Field(default_factory=list)
    applies_to_alarms: list[str] = Field(default_factory=list)
    sites: list[str] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_path: str = ""


class Chunk(BaseModel):
    """One retrievable passage."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    doc_id: str
    title: str
    doc_type: str
    heading: str = Field(description="Heading path, e.g. 'Diagnostic sequence > Step 2'.")
    text: str
    chunk_index: int
    char_start: int
    char_end: int
    token_estimate: int
    metadata: DocumentMetadata

    def as_chroma_metadata(self) -> dict[str, str | int | float | bool]:
        """Flatten to the scalar-only metadata Chroma accepts.

        Lists are joined with '|' and matched with a substring filter at
        query time, which is enough for the filters this system needs and
        avoids a second store just to hold relationships.
        """
        meta = self.metadata
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "doc_type": self.doc_type,
            "heading": self.heading,
            "chunk_index": self.chunk_index,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "source_path": meta.source_path,
            "revision": str(meta.revision or ""),
            "effective_date": meta.effective_date or "",
            "owner": meta.owner or "",
            "asset_types": "|".join(meta.applies_to_asset_types),
            "assets": "|".join(meta.applies_to_assets),
            "alarms": "|".join(meta.applies_to_alarms),
            "sites": "|".join(meta.sites),
            "units": "|".join(meta.units),
            "tags": "|".join(meta.tags),
        }


class RetrievedChunk(BaseModel):
    """A chunk with its retrieval scores and provenance."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    doc_id: str
    title: str
    doc_type: str
    heading: str
    text: str
    score: float = Field(description="Fused score in [0, 1].")
    dense_score: float = 0.0
    lexical_score: float = 0.0
    retrieved_by: list[Literal["dense", "lexical"]] = Field(default_factory=list)
    source_path: str = ""
    sanitised: bool = Field(
        default=False,
        description="True when suspicious instruction-like content was neutralised.",
    )


class Citation(BaseModel):
    """What the GUI renders and what the answer must be traceable to."""

    model_config = ConfigDict(extra="forbid")

    marker: str = Field(description="Inline marker, e.g. '[1]'.")
    doc_id: str
    title: str
    heading: str
    doc_type: str
    source_path: str
    score: float
    excerpt: str = Field(description="The passage the claim rests on.")


class RetrievalResult(BaseModel):
    """The full outcome of one retrieval, including the negative cases."""

    model_config = ConfigDict(extra="forbid")

    query: str
    chunks: list[RetrievedChunk]
    citations: list[Citation]
    low_confidence: bool = Field(
        description="True when nothing cleared the score floor; do not answer from this."
    )
    best_score: float
    filters_applied: dict[str, Any] = Field(default_factory=dict)
    injection_attempts_neutralised: int = 0
    duration_ms: float = 0.0
    total_candidates: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.chunks


class IngestionReport(BaseModel):
    """Summary of an index build, printed by the CLI and asserted in tests."""

    model_config = ConfigDict(extra="forbid")

    documents: int
    chunks: int
    skipped: list[str] = Field(default_factory=list)
    by_doc_type: dict[str, int] = Field(default_factory=dict)
    total_tokens_estimate: int = 0
    duration_ms: float = 0.0
    index_path: str = ""
    collection: str = ""

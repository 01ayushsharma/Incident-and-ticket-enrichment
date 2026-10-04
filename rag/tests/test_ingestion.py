"""Ingestion tests: extraction, front matter, chunking and metadata capture."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag.ingestion.chunker import chunk_document, estimate_tokens
from rag.ingestion.loader import (
    UnsupportedDocumentError,
    discover_documents,
    load_document,
    parse_front_matter,
)
from rag.models import DocumentMetadata

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "rag" / "documents"


# --------------------------------------------------------------------------
# Front matter and loading
# --------------------------------------------------------------------------
def test_front_matter_is_separated_from_the_body():
    fields, body = parse_front_matter(
        "---\ndoc_id: X-1\ntitle: Example\ntags: [a, b]\n---\n\n# Heading\n\nText.\n"
    )
    assert fields["doc_id"] == "X-1"
    assert fields["tags"] == ["a", "b"]
    assert body.strip().startswith("# Heading")


def test_a_document_without_front_matter_still_loads():
    fields, body = parse_front_matter("# Just a heading\n\nSome text.\n")
    assert fields == {}
    assert body.startswith("# Just a heading")


def test_inline_lists_and_integers_are_typed():
    fields, _ = parse_front_matter(
        "---\nrevision: 7\nsites: [NorthPlant, SouthPlant]\nempty: []\n---\nbody\n"
    )
    assert fields["revision"] == 7
    assert fields["sites"] == ["NorthPlant", "SouthPlant"]
    assert fields["empty"] == []


def test_every_corpus_document_declares_the_metadata_retrieval_filters_on():
    """Retrieval filtering depends on this metadata, so it is a contract."""
    for path in discover_documents(CORPUS):
        document = load_document(path)
        meta = document.metadata
        assert meta.doc_id, f"{path.name} has no doc_id"
        assert meta.title, f"{path.name} has no title"
        assert meta.doc_type != "reference", f"{path.name} has no doc_type"
        assert meta.tags, f"{path.name} has no tags"
        assert meta.sites, f"{path.name} declares no sites"


def test_corpus_doc_ids_are_unique():
    ids = [load_document(p).metadata.doc_id for p in discover_documents(CORPUS)]
    assert len(ids) == len(set(ids)), "duplicate doc_id would collide chunk ids"


def test_unsupported_file_type_is_rejected_clearly(tmp_path):
    path = tmp_path / "diagram.xyz"
    path.write_text("content", encoding="utf-8")
    with pytest.raises(UnsupportedDocumentError, match="unsupported extension"):
        load_document(path)


def test_discovery_is_deterministic():
    assert discover_documents(CORPUS) == discover_documents(CORPUS)


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------
def _metadata(**overrides) -> DocumentMetadata:
    base = {"doc_id": "T-1", "title": "Test Document", "doc_type": "troubleshooting_guide"}
    base.update(overrides)
    return DocumentMetadata(**base)


def test_chunks_carry_their_heading_path():
    body = (
        "# Title\n\n"
        "## Section A\n\nParagraph about cooling water and seal flush behaviour here.\n\n"
        "### Step 1\n\nCheck the cooling water isolation valve position locally always.\n"
    )
    chunks = chunk_document(body, _metadata(), min_chunk_chars=10)
    headings = [c.heading for c in chunks]
    assert "Section A" in headings
    assert any(h == "Section A > Step 1" for h in headings)


def test_the_h1_is_not_repeated_in_the_heading_path():
    """The document title already states it; repeating it wastes context."""
    body = "# Document Title\n\n## Section\n\nEnough body text to survive the minimum.\n"
    chunks = chunk_document(body, _metadata(title="Document Title"), min_chunk_chars=10)
    assert all(not c.heading.startswith("Document Title") for c in chunks)


def test_chunk_text_is_prefixed_with_context_for_the_embedding():
    body = "# T\n\n## Cooling\n\nCheck the cooling water isolation valve position.\n"
    chunks = chunk_document(body, _metadata(title="Guide"), min_chunk_chars=10)
    assert chunks[0].text.startswith("Guide > Cooling")


def test_oversized_sections_are_split_with_overlap():
    paragraph = "This sentence describes a diagnostic step in some detail. " * 12
    body = f"# T\n\n## Long\n\n{paragraph}\n\n{paragraph}\n\n{paragraph}\n"
    chunks = chunk_document(body, _metadata(), chunk_size=400, chunk_overlap=80)
    assert len(chunks) > 1
    assert all(len(c.text) < 1200 for c in chunks)


def test_tiny_trailing_fragments_are_merged_not_emitted():
    body = "# T\n\n## Section\n\n" + ("Substantial content here. " * 20) + "\n\nok\n"
    chunks = chunk_document(body, _metadata(), min_chunk_chars=100)
    assert all(len(c.text) >= 50 for c in chunks)


def test_chunk_ids_are_stable_across_runs():
    """Re-ingestion must upsert rather than duplicate."""
    body = "# T\n\n## Section\n\nStable content that will not change between runs.\n"
    first = chunk_document(body, _metadata(), min_chunk_chars=10)
    second = chunk_document(body, _metadata(), min_chunk_chars=10)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_changed_content_produces_a_different_chunk_id():
    meta = _metadata()
    a = chunk_document(
        "# T\n\n## S\n\nOriginal body content for this section.\n", meta, min_chunk_chars=10
    )
    b = chunk_document(
        "# T\n\n## S\n\nRevised body content for this section.\n", meta, min_chunk_chars=10
    )
    assert a[0].chunk_id != b[0].chunk_id


def test_document_metadata_propagates_onto_every_chunk():
    meta = _metadata(
        applies_to_alarms=["High Vibration"],
        applies_to_asset_types=["pump"],
        sites=["NorthPlant"],
    )
    body = "# T\n\n## S\n\nSome content about vibration diagnosis on pumps here.\n"
    chunks = chunk_document(body, meta, min_chunk_chars=10)
    assert chunks
    for chunk in chunks:
        assert chunk.metadata.applies_to_alarms == ["High Vibration"]
        flat = chunk.as_chroma_metadata()
        assert flat["alarms"] == "High Vibration"
        assert flat["asset_types"] == "pump"
        assert isinstance(flat["chunk_index"], int)


def test_chroma_metadata_contains_only_scalars():
    """Chroma rejects list-valued metadata, so flattening is a hard contract."""
    meta = _metadata(applies_to_alarms=["A", "B"], tags=["x", "y"])
    body = "# T\n\n## S\n\nContent long enough to be retained as a chunk here.\n"
    chunk = chunk_document(body, meta, min_chunk_chars=10)[0]
    for key, value in chunk.as_chroma_metadata().items():
        assert isinstance(value, (str, int, float, bool)), f"{key} is {type(value)}"


def test_token_estimate_is_monotonic():
    assert estimate_tokens("word " * 100) > estimate_tokens("word " * 10)


def test_empty_document_produces_no_chunks():
    assert chunk_document("", _metadata()) == []


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------
def test_ingestion_indexes_the_whole_corpus(ingestion_report):
    assert ingestion_report.documents >= 15
    assert ingestion_report.chunks > 100
    assert ingestion_report.skipped == []
    assert ingestion_report.total_tokens_estimate > 0


def test_ingestion_covers_every_required_document_type(ingestion_report):
    """The assignment names the corpus types the solution must ingest."""
    required = {
        "troubleshooting_guide",
        "operating_procedure",
        "alarm_philosophy",
        "escalation_procedure",
        "resolution_notes",
        "safety_instruction",
        "maintenance_guide",
    }
    assert required <= set(ingestion_report.by_doc_type)


def test_reingesting_does_not_duplicate_chunks(rag_settings, chunk_store):
    """Stable chunk ids mean a second run upserts in place."""
    from rag.ingestion.pipeline import ingest

    before = chunk_store.count()
    ingest(rebuild=False, settings=rag_settings, store=chunk_store)
    assert chunk_store.count() == before


def test_a_missing_document_directory_fails_loudly(rag_settings):
    from rag.ingestion.pipeline import ingest

    broken = rag_settings.model_copy(update={"document_path": "/nonexistent/corpus"})
    with pytest.raises(FileNotFoundError, match="Document path does not exist"):
        ingest(settings=broken)


def test_unreadable_document_is_skipped_not_fatal(tmp_path, rag_settings):
    from rag.ingestion.pipeline import build_chunks

    (tmp_path / "good.md").write_text(
        "---\ndoc_id: G-1\ntitle: Good\n---\n\n## S\n\n" + ("Body text. " * 20),
        encoding="utf-8",
    )
    (tmp_path / "bad.xyz").write_text("nope", encoding="utf-8")

    chunks, skipped = build_chunks(tmp_path, rag_settings)
    assert chunks, "the readable document must still be indexed"
    assert len(skipped) == 1
    assert "bad.xyz" in skipped[0]

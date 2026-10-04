"""Document loading and text extraction.

Markdown with YAML front matter is the corpus format. PDFs are supported
too, because real support corpora are full of them and the assignment asks
for text extraction rather than for a convenient format.

Front matter is not decoration: the fields it carries (which alarms and
asset types a document applies to, which sites) become the retrieval
filters. A document without front matter still indexes, but it can only be
found by text, not by scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rag.models import DocumentMetadata

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_LIST_VALUE = re.compile(r"\A\[(.*)\]\Z", re.DOTALL)

SUPPORTED_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".pdf"})


@dataclass
class LoadedDocument:
    metadata: DocumentMetadata
    body: str
    path: Path


class UnsupportedDocumentError(ValueError):
    """Raised for a file type the loader cannot extract text from."""


def _parse_scalar(raw: str) -> str | int | list[str]:
    value = raw.strip()
    if match := _LIST_VALUE.match(value):
        inner = match.group(1).strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in inner.split(",") if item.strip()]
    value = value.strip("'\"")
    if value.isdigit():
        return int(value)
    return value


def parse_front_matter(text: str) -> tuple[dict[str, object], str]:
    """Split YAML-ish front matter from the body.

    A deliberately small parser rather than a YAML dependency: the corpus
    uses flat scalars and inline lists only, and constraining the format
    keeps a malformed document from failing the whole ingestion run.
    """
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text

    fields: dict[str, object] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, raw = stripped.partition(":")
        fields[key.strip()] = _parse_scalar(raw)
    return fields, text[match.end() :]


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise UnsupportedDocumentError(
            f"Cannot read {path.name}: install pypdf to ingest PDF documents."
        ) from exc
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def load_document(path: Path) -> LoadedDocument:
    """Read one file into text plus metadata."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedDocumentError(
            f"{path.name}: unsupported extension '{suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}."
        )

    fields: dict[str, object]
    if suffix == ".pdf":
        raw, fields = _extract_pdf(path), {}
    else:
        raw = path.read_text(encoding="utf-8")
        fields, raw = parse_front_matter(raw)

    metadata = DocumentMetadata(
        doc_id=str(fields.get("doc_id") or path.stem),
        title=str(fields.get("title") or _title_from_body(raw) or path.stem),
        doc_type=str(fields.get("doc_type") or "reference"),
        revision=fields.get("revision"),
        effective_date=_as_str(fields.get("effective_date")),
        owner=_as_str(fields.get("owner")),
        applies_to_asset_types=_as_list(fields.get("applies_to_asset_types")),
        applies_to_assets=_as_list(fields.get("applies_to_assets")),
        applies_to_alarms=_as_list(fields.get("applies_to_alarms")),
        sites=_as_list(fields.get("sites")),
        units=_as_list(fields.get("units")),
        tags=_as_list(fields.get("tags")),
        source_path=path.name,
    )
    return LoadedDocument(metadata=metadata, body=raw.strip(), path=path)


def _as_str(value: object) -> str | None:
    return None if value is None else str(value)


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _title_from_body(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def discover_documents(root: Path) -> list[Path]:
    """Every ingestable file under ``root``, in a stable order."""
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )

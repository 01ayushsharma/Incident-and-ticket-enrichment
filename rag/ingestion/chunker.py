"""Heading-aware chunking.

Why not fixed-size windows: these documents are procedures. A window that
splits "Step 3" from its heading produces a chunk that is retrievable but
useless, because the reader cannot tell what it is a step *of*. Splitting on
markdown headings first, and only then packing by size, keeps every chunk
attached to the heading path it belongs under - which is also what makes a
citation readable ("TG-201 > Diagnostic sequence > Step 2").

Oversized sections are split on paragraph boundaries with an overlap, so a
claim that straddles the split still appears whole in one of the pieces.
"""

from __future__ import annotations

import hashlib
import re

from rag.models import Chunk, DocumentMetadata

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)

# Rough characters-per-token for English prose. Only used for reporting and
# for budgeting context, never for correctness.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _chunk_id(doc_id: str, index: int, text: str) -> str:
    """Stable id: same document and same text give the same id.

    This makes re-ingestion idempotent - an unchanged document overwrites
    its own chunks rather than duplicating them.
    """
    digest = hashlib.sha1(f"{doc_id}|{index}|{text}".encode()).hexdigest()[:12]
    return f"{doc_id}:{index:03d}:{digest}"


def _sections(body: str) -> list[tuple[str, str, int]]:
    """Split into (heading_path, text, char_offset) on markdown headings."""
    matches = list(HEADING.finditer(body))
    if not matches:
        return [("", body, 0)]

    sections: list[tuple[str, str, int]] = []

    preamble = body[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble, 0))

    # Track the heading stack so a nested heading carries its parents.
    stack: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))
        # Skip the H1: it restates the document title, which every citation
        # already shows, and repeating it makes the path unreadable.
        path = " > ".join(h for lvl, h in stack if lvl > 1)

        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        text = body[start:end].strip()
        if text:
            sections.append((path, text, start))
    return sections


def _pack(text: str, size: int, overlap: int) -> list[tuple[str, int]]:
    """Split oversized text on paragraph boundaries with overlap."""
    if len(text) <= size:
        return [(text, 0)]

    paragraphs = re.split(r"\n\s*\n", text)
    pieces: list[tuple[str, int]] = []
    buffer: list[str] = []
    buffer_len = 0
    offset = 0
    cursor = 0

    for paragraph in paragraphs:
        candidate = len(paragraph) + 2
        if buffer and buffer_len + candidate > size:
            joined = "\n\n".join(buffer)
            pieces.append((joined, offset))
            # Carry the tail of this piece into the next one.
            tail = joined[-overlap:] if overlap else ""
            cursor += len(joined) + 2
            offset = max(0, cursor - len(tail))
            buffer = [tail, paragraph] if tail else [paragraph]
            buffer_len = len(tail) + candidate
        else:
            buffer.append(paragraph)
            buffer_len += candidate

    if buffer:
        pieces.append(("\n\n".join(buffer), offset))

    # A single paragraph longer than `size` survives the loop intact; split
    # it on sentence boundaries rather than emitting one huge chunk.
    expanded: list[tuple[str, int]] = []
    for piece, piece_offset in pieces:
        if len(piece) <= size * 1.5:
            expanded.append((piece, piece_offset))
            continue
        sentences = re.split(r"(?<=[.!?])\s+", piece)
        current: list[str] = []
        current_len = 0
        for sentence in sentences:
            if current and current_len + len(sentence) > size:
                expanded.append((" ".join(current), piece_offset))
                current, current_len = [sentence], len(sentence)
            else:
                current.append(sentence)
                current_len += len(sentence) + 1
        if current:
            expanded.append((" ".join(current), piece_offset))
    return expanded


def chunk_document(
    body: str,
    metadata: DocumentMetadata,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    min_chunk_chars: int = 80,
) -> list[Chunk]:
    """Turn one document body into retrievable chunks."""
    chunks: list[Chunk] = []
    index = 0

    for heading, text, section_offset in _sections(body):
        for piece, piece_offset in _pack(text, chunk_size, chunk_overlap):
            # An overlap tail can begin mid-sentence; drop the orphaned
            # punctuation so citations do not start with '. 5. ...'.
            cleaned = piece.strip().lstrip(".,;:!? ").strip()
            if len(cleaned) < min_chunk_chars:
                # Too short to carry meaning on its own; folding it into the
                # previous chunk keeps the heading context with the content.
                if chunks and heading == chunks[-1].heading:
                    previous = chunks[-1]
                    merged = f"{previous.text}\n\n{cleaned}"
                    chunks[-1] = previous.model_copy(
                        update={
                            "text": merged,
                            "char_end": previous.char_start + len(merged),
                            "token_estimate": estimate_tokens(merged),
                        }
                    )
                continue

            # Prefix the heading so the embedding sees what the passage is
            # about, not just its body text. This measurably improves recall
            # on queries phrased as a topic rather than as a sentence.
            embedded_text = f"{metadata.title} > {heading}\n\n{cleaned}" if heading else cleaned
            start = section_offset + piece_offset

            chunks.append(
                Chunk(
                    chunk_id=_chunk_id(metadata.doc_id, index, cleaned),
                    doc_id=metadata.doc_id,
                    title=metadata.title,
                    doc_type=metadata.doc_type,
                    heading=heading,
                    text=embedded_text,
                    chunk_index=index,
                    char_start=start,
                    char_end=start + len(cleaned),
                    token_estimate=estimate_tokens(embedded_text),
                    metadata=metadata,
                )
            )
            index += 1

    return chunks

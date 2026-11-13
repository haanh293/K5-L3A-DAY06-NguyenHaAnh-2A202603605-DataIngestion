"""Fixed-size and structure/paragraph-aware chunking strategies."""
from __future__ import annotations

import re

from .ingestion import _SECTION_HEADING_RE
from .models import Chunk, DocumentPage

_SENTENCE_END_RE = re.compile(r"[.?!:]$")


def fixed_size(page: DocumentPage, size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Split page text into overlapping fixed-size character windows."""
    if size <= 0:
        raise ValueError("size must be > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must satisfy 0 <= overlap < size")

    text = page.text
    if not text:
        return []

    chunks: list[Chunk] = []
    step = size - overlap
    start = 0
    idx = 1

    while start < len(text):
        end = min(start + size, len(text))
        piece = text[start:end].strip()
        if piece:
            meta = dict(page.metadata)
            meta.update(
                {
                    "chunk_strategy": "fixed_size",
                    "char_start": start,
                    "char_end": end,
                    "char_len": len(piece),
                }
            )
            chunks.append(
                Chunk(
                    chunk_id=f"{page.document_id}_p{page.page:02d}_c{idx:02d}",
                    document_id=page.document_id,
                    source=page.source,
                    page=page.page,
                    text=piece,
                    metadata=meta,
                )
            )
            idx += 1
        if end >= len(text):
            break
        start += step

    return chunks


def _split_into_paragraphs(text: str) -> list[tuple[str | None, str]]:
    """Group PDF lines into structural paragraphs and track heading transitions."""
    lines = text.splitlines()
    blocks: list[tuple[str | None, str]] = []
    buf: list[str] = []
    current_heading: str | None = None

    def flush() -> None:
        if buf:
            blocks.append((current_heading, "\n".join(buf).strip()))
            buf.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
            continue

        if _SECTION_HEADING_RE.match(stripped):
            flush()
            current_heading = stripped
            buf.append(stripped)
            continue

        buf.append(stripped)
        # Heuristic paragraph boundary for line-wrapped RFC PDFs:
        # short line ending with sentence-ending punctuation
        if len(stripped) < 68 and _SENTENCE_END_RE.search(stripped):
            flush()

    flush()
    return [(h, b) for h, b in blocks if b]


def _split_oversized_block(text: str, max_size: int) -> list[str]:
    """Split an oversized block at sentence or line boundaries within max_size."""
    if len(text) <= max_size:
        return [text]

    parts: list[str] = []
    sentences = re.split(r"(?<=[.?!])\s+", text)
    current = ""
    for sent in sentences:
        if len(sent) > max_size:
            if current:
                parts.append(current.strip())
                current = ""
            for i in range(0, len(sent), max_size):
                parts.append(sent[i : i + max_size].strip())
            continue

        candidate = f"{current} {sent}".strip() if current else sent
        if len(candidate) <= max_size:
            current = candidate
        else:
            if current:
                parts.append(current.strip())
            current = sent

    if current:
        parts.append(current.strip())
    return [p for p in parts if p]


def by_paragraph(page: DocumentPage, max_size: int = 900) -> list[Chunk]:
    """Group structural paragraphs within the same section up to max_size characters."""
    if max_size <= 0:
        raise ValueError("max_size must be > 0")
    if not page.text:
        return []

    blocks = _split_into_paragraphs(page.text)
    if not blocks:
        return []

    default_section = str(page.metadata.get("section", "general"))
    grouped: list[tuple[str, str]] = []
    cur_text = ""
    cur_section = default_section

    for heading, block in blocks:
        block_section = heading or cur_section
        for piece in _split_oversized_block(block, max_size):
            # Do not merge across a new section heading if buffer already has content
            if heading and cur_text and block_section != cur_section:
                grouped.append((cur_section, cur_text.strip()))
                cur_text = piece
                cur_section = block_section
                continue

            candidate = f"{cur_text}\n{piece}".strip() if cur_text else piece
            if len(candidate) <= max_size:
                cur_text = candidate
                cur_section = block_section
            else:
                if cur_text:
                    grouped.append((cur_section, cur_text.strip()))
                cur_text = piece
                cur_section = block_section

    if cur_text:
        grouped.append((cur_section, cur_text.strip()))

    chunks: list[Chunk] = []
    for idx, (sec, chunk_text) in enumerate(grouped, start=1):
        meta = dict(page.metadata)
        meta.update(
            {
                "section": sec,
                "chunk_strategy": "by_paragraph",
                "char_len": len(chunk_text),
            }
        )
        chunks.append(
            Chunk(
                chunk_id=f"{page.document_id}_p{page.page:02d}_c{idx:02d}",
                document_id=page.document_id,
                source=page.source,
                page=page.page,
                text=chunk_text,
                metadata=meta,
            )
        )

    return chunks

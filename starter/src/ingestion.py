"""Read and normalize source PDF documents while preserving source traceability."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .models import DocumentPage

_RFC_HEADER_RE = re.compile(
    r"^RFC\s+\d+\s+.*?(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}$"
)
_RFC_FOOTER_RE = re.compile(
    r"^(?:.*\[Page\s+\d+\]|(?:Fielding|Nottingham|Koster),\s+et\s+al\.\s+Standards\s+Track\s+Page\s+\d+)$"
)
_SECTION_HEADING_RE = re.compile(
    r"^(?:(\d+(?:\.\d+)*\.)|(Appendix\s+[A-Z]\.))\s+([A-Z0-9\"].{1,90})$"
)


def normalize_text(text: str) -> str:
    """Normalize Unicode (NFKC), remove RFC running headers/footers, and tidy whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            cleaned_lines.append("")
            continue
        if _RFC_HEADER_RE.match(line) or _RFC_FOOTER_RE.match(line):
            continue
        cleaned_lines.append(line)

    normalized = "\n".join(cleaned_lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def detect_section(text: str, fallback: str = "general") -> str:
    """Detect the first numbered section or appendix heading in text."""
    for line in text.splitlines():
        candidate = line.strip()
        m = _SECTION_HEADING_RE.match(candidate)
        if m:
            return candidate
    return fallback


def load_pdf(
    path: Path,
    document_id: str,
    source: str,
    valid_pages: list[int] | None = None,
    base_metadata: dict[str, Any] | None = None,
    ingestion_log: list[dict[str, Any]] | None = None,
) -> list[DocumentPage]:
    """Extract physical pages from a PDF, normalize text, and track excluded/empty pages."""
    if not path.exists():
        raise FileNotFoundError(f"Corpus PDF not found: {path}")

    reader = PdfReader(str(path))
    total_physical = len(reader.pages)
    valid_set = set(valid_pages) if valid_pages is not None else set(range(1, total_physical + 1))

    pages: list[DocumentPage] = []
    current_section = "Introduction"

    for page_num in range(1, total_physical + 1):
        raw_text = reader.pages[page_num - 1].extract_text() or ""
        norm_text = normalize_text(raw_text)

        if page_num not in valid_set:
            if ingestion_log is not None:
                ingestion_log.append(
                    {
                        "document_id": document_id,
                        "page": page_num,
                        "status": "excluded_by_manifest",
                        "raw_chars": len(raw_text),
                        "normalized_chars": len(norm_text),
                    }
                )
            continue

        if not norm_text:
            if ingestion_log is not None:
                ingestion_log.append(
                    {
                        "document_id": document_id,
                        "page": page_num,
                        "status": "empty_or_unreadable",
                        "raw_chars": len(raw_text),
                        "normalized_chars": 0,
                    }
                )
            continue

        current_section = detect_section(norm_text, fallback=current_section)
        meta = dict(base_metadata or {})
        meta.update(
            {
                "section": current_section,
                "physical_pages": total_physical,
                "char_count": len(norm_text),
            }
        )

        if ingestion_log is not None:
            ingestion_log.append(
                {
                    "document_id": document_id,
                    "page": page_num,
                    "status": "ingested",
                    "section": current_section,
                    "raw_chars": len(raw_text),
                    "normalized_chars": len(norm_text),
                }
            )

        pages.append(
            DocumentPage(
                document_id=document_id,
                source=source,
                page=page_num,
                text=norm_text,
                metadata=meta,
            )
        )

    return pages

"""Validate and extract text, keeping the page number for every chunk."""
from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf


class InvalidPDF(ValueError):
    """Input is not an eligible, text-extractable PDF."""


@dataclass(frozen=True)
class TextChunk:
    page: int
    ordinal: int
    content: str


def split_text(text: str, *, size: int, overlap: int) -> list[str]:
    """Character windows with overlap; prefer word boundaries when feasible."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    result: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            word_break = text.rfind(" ", start + int(size * 0.7), end)
            if word_break > start:
                end = word_break
        segment = text[start:end].strip()
        if segment:
            result.append(segment)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return result


def extract_pdf(data: bytes, *, max_pages: int, chunk_size: int, overlap: int) -> tuple[int, list[TextChunk]]:
    if not data.startswith(b"%PDF-"):
        raise InvalidPDF("Le contenu n'a pas une signature PDF valide.")
    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except (RuntimeError, ValueError, TypeError) as exc:
        raise InvalidPDF("PDF endommagé ou illisible.") from exc

    with pdf:
        if pdf.needs_pass:
            raise InvalidPDF("PDF protégé par mot de passe non pris en charge.")
        page_count = pdf.page_count
        if page_count < 1:
            raise InvalidPDF("Le PDF ne contient aucune page.")
        if page_count > max_pages:
            raise InvalidPDF(f"Ce PDF dépasse la limite de {max_pages} pages.")

        chunks: list[TextChunk] = []
        ordinal = 0
        for page_no, page in enumerate(pdf, start=1):
            text = page.get_text("text", sort=True)
            for section in split_text(text, size=chunk_size, overlap=overlap):
                chunks.append(TextChunk(page=page_no, ordinal=ordinal, content=section))
                ordinal += 1
        if not chunks:
            raise InvalidPDF("Aucun texte sélectionnable : PDF scanné ? L'OCR n'est pas inclus dans ce MVP.")
        return page_count, chunks

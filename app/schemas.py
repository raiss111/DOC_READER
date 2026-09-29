"""Public versioned API contracts, deliberately separated from SQLite rows."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: str
    filename: str
    sha256: str
    page_count: int
    chunk_count: int
    version: int
    uploaded_at: str


class DocumentList(BaseModel):
    total: int
    items: list[DocumentOut]


class QuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    document_ids: list[str] | None = Field(default=None, max_length=30)
    top_k: int = Field(default=4, ge=1, le=8)


class SourceOut(BaseModel):
    reference: int
    document_id: str
    filename: str
    page: int
    page_end: int | None = None  # end page when context crosses a PDF page boundary
    score: float
    excerpt: str


class AnswerOut(BaseModel):
    answer: str
    response_mode: str
    sources: list[SourceOut]
    warning: str | None = None

"""Versioned API contracts. V3 question and answer fields remain compatible."""
from __future__ import annotations

from typing import Literal
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
    document_ids: list[str] | None = Field(default=None, max_length=200)
    top_k: int = Field(default=4, ge=1, le=20)
    answer_style: Literal["synthese", "citation_exacte"] = "synthese"
    include_excerpts: bool = True


class SourceOut(BaseModel):
    reference: int
    document_id: str
    filename: str
    page: int
    page_end: int | None = None
    score: float
    excerpt: str | None = None


class AnswerOut(BaseModel):
    answer: str
    response_mode: str
    sources: list[SourceOut]
    warning: str | None = None


class ConversationIn(BaseModel):
    title: str = Field(default="Nouvelle conversation", min_length=1, max_length=120)
    document_ids: list[str] = Field(default_factory=list, max_length=200)


class ConversationTitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ConversationDocumentsIn(BaseModel):
    document_ids: list[str] = Field(default_factory=list, max_length=200)


class ConversationOut(BaseModel):
    id: str
    title: str
    document_ids: list[str]
    message_count: int
    created_at: str
    updated_at: str


class ConversationList(BaseModel):
    total: int
    items: list[ConversationOut]


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str
    response_mode: str | None = None
    sources: list[SourceOut] = Field(default_factory=list)
    created_at: str


class MessageList(BaseModel):
    total: int
    items: list[MessageOut]

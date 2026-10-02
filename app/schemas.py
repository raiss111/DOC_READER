"""Versioned API contracts.

V3/V4 fields remain compatible. V4.2 adds optional LLM-generation diagnostics so
clients can distinguish provider failures from responses rejected by citation
validation without exposing secrets or internal prompts.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


FallbackReason = Literal[
    "llm_disabled",
    "llm_not_configured",
    "llm_timeout",
    "llm_connection_error",
    "llm_provider_error",
    "llm_invalid_payload",
    "llm_empty_answer",
    "missing_citations",
    "invalid_citation_reference",
    "insufficient_evidence",
    "no_document",
]

GenerationStatus = Literal[
    "not_attempted",
    "success",
    "rejected",
    "unavailable",
    "error",
]


class GenerationOut(BaseModel):
    """Safe, user-visible diagnostics for the LLM generation attempt.

    ``rejected_answer`` contains only the model's generated answer when local
    validation rejects it. Raw provider payloads, headers, API keys and system
    prompts must never be placed here.
    """

    attempted: bool
    status: GenerationStatus
    provider: str | None = None
    model: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    error_type: str | None = None
    rejected_answer: str | None = None


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
    request_id: str | None = None
    fallback_reason: FallbackReason | None = None
    generation: GenerationOut | None = None


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

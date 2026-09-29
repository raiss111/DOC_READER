"""Versioned HTTP API: transactional PDF library, indexed retrieval and conversations."""
from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader

from .answering import Answerer
from .config import Settings
from .pdf_processing import InvalidPDF, extract_pdf
from .retrieval import Retriever, tokenize
from .schemas import (
    AnswerOut, ConversationDocumentsIn, ConversationIn, ConversationList,
    ConversationOut, ConversationTitleIn, DocumentList, DocumentOut,
    MessageList, QuestionIn,
)
from .store import DuplicateDocument, MissingDocuments, NotFound, Store

header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    files_dir = settings.storage_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    store = Store(settings.storage_dir / "metadata.sqlite3")
    retriever = Retriever(settings)
    answerer = Answerer(settings)

    app = FastAPI(
        title="PDF Intelligence API", version="4.0.0",
        description="Bibliothèque PDF (30 Mo, 1000 pages), index FTS5, questions multi-documents et conversations.",
    )
    app.state.store = store
    app.state.settings = settings

    # ---- Service du frontend (HTML / CSS / JS) ----
    static_dir = Path(__file__).resolve().parents[1] / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def serve_frontend() -> FileResponse:
        return FileResponse(static_dir / "index.html")
    # ------------------------------------------------

    router = APIRouter(prefix="/api/v1")

    def verify_api_key(provided: str | None = Depends(header_scheme)) -> None:
        if settings.app_api_key and (not provided or not secrets.compare_digest(provided, settings.app_api_key)):
            raise HTTPException(status_code=401, detail="Clé API absente ou incorrecte.")

    @router.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "retrieval_mode": settings.retrieval_mode,
                "llm_mode": settings.llm_mode, "index_mode": "sqlite_fts5" if settings.retrieval_mode == "lexical" else "semantic_exhaustive",
                "max_pdf_bytes": settings.max_pdf_bytes, "max_pages": settings.max_pages}

    protected = APIRouter(dependencies=[Depends(verify_api_key)])

    def duplicate_response(document_id: str) -> JSONResponse:
        return JSONResponse(status_code=409, content={
            "detail": "Ce document existe déjà dans la bibliothèque.",
            "existing_document_id": document_id,
        })

    def prepared_pdf(upload: UploadFile, *, replacing_id: str | None = None) -> tuple[dict, list[dict], bytes]:
        name = Path((upload.filename or "").replace("\\", "/")).name
        if not name or len(name) > 255 or any(ord(ch) < 32 for ch in name) or not name.lower().endswith(".pdf"):
            raise HTTPException(status_code=422, detail="Un nom de fichier .pdf est requis.")
        data = upload.file.read(settings.max_pdf_bytes + 1)
        if len(data) > settings.max_pdf_bytes:
            raise HTTPException(status_code=413, detail=f"PDF trop volumineux ({settings.max_pdf_bytes} octets maximum).")
        digest = hashlib.sha256(data).hexdigest()
        # A PUT with exactly the current bytes is a no-op, even if that PDF had
        # been duplicated by a legacy V1-V3 installation.
        if replacing_id is not None:
            current = store.get(replacing_id)
            if current and current["sha256"] == digest:
                return {"filename": current["filename"], "sha256": digest,
                        "page_count": current["page_count"]}, [], data
        # Cheap early check, then an authoritative in-transaction check inside Store.create/replace.
        already = store.find_by_sha(digest, excluded_id=replacing_id)
        if already:
            raise DuplicateDocument(already)
        try:
            pages, chunks = extract_pdf(data, max_pages=settings.max_pages,
                                         chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
        except InvalidPDF as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            indexed = retriever.prepare(chunks)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"filename": name, "sha256": digest, "page_count": pages}, indexed, data

    def store_new_file(data: bytes) -> Path:
        """Install an immutable staged PDF atomically; clean it on DB failure."""
        filename = uuid.uuid4().hex
        temporary = files_dir / f"{filename}.part"
        final = files_dir / f"{filename}.pdf"
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, final)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return final

    @protected.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED,
                    tags=["documents"], responses={409: {"description": "PDF déjà présent (SHA-256 identique)"}})
    def add_document(file: UploadFile = File(...)) -> dict | JSONResponse:
        try:
            try:
                record, chunks, data = prepared_pdf(file)
            except DuplicateDocument as exc:
                return duplicate_response(exc.existing_document_id)
            document_id = str(uuid.uuid4())
            new_path = store_new_file(data)
            try:
                return Store.public(store.create({**record, "id": document_id, "file_path": new_path}, chunks))
            except DuplicateDocument as exc:
                new_path.unlink(missing_ok=True)
                return duplicate_response(exc.existing_document_id)
            except Exception:
                new_path.unlink(missing_ok=True)
                raise
        finally:
            file.file.close()

    @protected.get("/documents", response_model=DocumentList, tags=["documents"])
    def list_documents(limit: int = Query(default=20, ge=1, le=100),
                       offset: int = Query(default=0, ge=0)) -> dict:
        total, items = store.list(limit, offset)
        return {"total": total, "items": items}

    @protected.get("/documents/{document_id}", response_model=DocumentOut, tags=["documents"])
    def get_document(document_id: str) -> dict:
        record = store.get(document_id)
        if not record:
            raise HTTPException(status_code=404, detail="Document introuvable.")
        return Store.public(record)

    @protected.put("/documents/{document_id}", response_model=DocumentOut, tags=["documents"],
                   responses={409: {"description": "Remplacement déjà présent sous un autre document"}})
    def replace_document(document_id: str, file: UploadFile = File(...)) -> dict | JSONResponse:
        try:
            existing = store.get(document_id)
            if not existing:
                raise HTTPException(status_code=404, detail="Document introuvable.")
            # Same bytes as the current document: idempotent no-op, version unchanged.
            data_hash = None
            try:
                record, chunks, data = prepared_pdf(file, replacing_id=document_id)
                data_hash = record["sha256"]
            except DuplicateDocument as exc:
                return duplicate_response(exc.existing_document_id)
            if data_hash == existing["sha256"]:
                return Store.public(existing)
            new_path = store_new_file(data)
            try:
                old_path = store.replace(document_id, {**record, "file_path": new_path}, chunks)
            except NotFound as exc:
                new_path.unlink(missing_ok=True)
                raise HTTPException(status_code=404, detail="Document introuvable.") from exc
            except DuplicateDocument as exc:
                new_path.unlink(missing_ok=True)
                return duplicate_response(exc.existing_document_id)
            except Exception:
                new_path.unlink(missing_ok=True)
                raise
            old_path.unlink(missing_ok=True)
            updated = store.get(document_id)
            assert updated is not None
            return Store.public(updated)
        finally:
            file.file.close()

    @protected.delete("/documents/{document_id}", status_code=204, tags=["documents"])
    def delete_document(document_id: str) -> None:
        try:
            former_path = store.delete(document_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail="Document introuvable.") from exc
        former_path.unlink(missing_ok=True)

    def answer_question(request: QuestionIn, document_ids: list[str] | None,
                        history: list[dict] | None = None) -> dict:
        question = request.question.strip()
        if len(question) < 3:
            raise HTTPException(status_code=422, detail="La question doit comporter au moins trois caractères.")
        ids = list(dict.fromkeys(document_ids)) if document_ids is not None else None
        if ids is not None:
            missing = store.missing_document_ids(ids)
            if missing:
                raise HTTPException(status_code=404, detail={"documents_introuvables": missing})
        # Short follow-up: include previous user question for retrieval, but answer the CURRENT one.
        retrieval_question = question
        if history and len(tokenize(question)) <= 5:
            previous = next((r["content"] for r in reversed(history) if r["role"] == "user"), None)
            if previous:
                retrieval_question = previous[:550] + " " + question
        try:
            if settings.retrieval_mode == "lexical":
                candidates = store.search_candidates(retrieval_question, ids, limit=max(300, request.top_k * 60))
            else:
                # Semantic mode remains exhaustive for recall (optional dependency, see README).
                candidates = store.all_chunks(ids)
            hits = retriever.search(retrieval_question, candidates, request.top_k)
            if hits:
                neighbors = store.neighboring_chunks(hits)
                hits = retriever.expand_context(hits, neighbors)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return answerer.answer(question, hits, answer_style=request.answer_style,
                               include_excerpts=request.include_excerpts, history=history)

    @protected.post("/questions", response_model=AnswerOut, response_model_exclude_none=True,
                    tags=["questions"])
    def ask_question(request: QuestionIn) -> dict:
        # Backward-compatible V1-V3: no document_ids means search entire library.
        return answer_question(request, request.document_ids)

    @protected.post("/conversations", response_model=ConversationOut, status_code=201,
                    tags=["conversations"])
    def create_conversation(request: ConversationIn) -> dict:
        ids = list(dict.fromkeys(request.document_ids))
        title = request.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="Le titre ne peut pas être vide.")
        try:
            return store.create_conversation(str(uuid.uuid4()), title, ids)
        except MissingDocuments as exc:
            raise HTTPException(status_code=404, detail={"documents_introuvables": exc.ids}) from exc

    @protected.get("/conversations", response_model=ConversationList, tags=["conversations"])
    def list_conversations(limit: int = Query(default=20, ge=1, le=100),
                           offset: int = Query(default=0, ge=0)) -> dict:
        total, rows = store.list_conversations(limit, offset)
        return {"total": total, "items": rows}

    @protected.get("/conversations/{conversation_id}", response_model=ConversationOut,
                   tags=["conversations"])
    def get_conversation(conversation_id: str) -> dict:
        row = store.get_conversation(conversation_id)
        if not row:
            raise HTTPException(status_code=404, detail="Conversation introuvable.")
        return row

    @protected.patch("/conversations/{conversation_id}", response_model=ConversationOut,
                     tags=["conversations"])
    def rename_conversation(conversation_id: str, request: ConversationTitleIn) -> dict:
        title = request.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="Le titre ne peut pas être vide.")
        try:
            return store.rename_conversation(conversation_id, title)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail="Conversation introuvable.") from exc

    @protected.put("/conversations/{conversation_id}/documents", response_model=ConversationOut,
                   tags=["conversations"])
    def set_conversation_documents(conversation_id: str, request: ConversationDocumentsIn) -> dict:
        ids = list(dict.fromkeys(request.document_ids))
        try:
            return store.set_conversation_documents(conversation_id, ids)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail="Conversation introuvable.") from exc
        except MissingDocuments as exc:
            raise HTTPException(status_code=404, detail={"documents_introuvables": exc.ids}) from exc

    @protected.get("/conversations/{conversation_id}/messages", response_model=MessageList,
                   response_model_exclude_none=True, tags=["conversations"])
    def list_messages(conversation_id: str, limit: int = Query(default=50, ge=1, le=100),
                      offset: int = Query(default=0, ge=0)) -> dict:
        try:
            total, messages = store.list_messages(conversation_id, limit, offset)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail="Conversation introuvable.") from exc
        return {"total": total, "items": messages}

    @protected.post("/conversations/{conversation_id}/questions", response_model=AnswerOut,
                    response_model_exclude_none=True, tags=["conversations"])
    def ask_in_conversation(conversation_id: str, request: QuestionIn) -> dict:
        conversation = store.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation introuvable.")
        available = conversation["document_ids"]
        if request.document_ids is not None:
            # Scoped overrides are allowed but may not silently search outside this conversation.
            ids = list(dict.fromkeys(request.document_ids))
            excluded = [id_ for id_ in ids if id_ not in available]
            if excluded:
                raise HTTPException(status_code=422, detail={"documents_hors_conversation": excluded})
        else:
            ids = available
        if not ids:
            raise HTTPException(status_code=422, detail="Associer au moins un document à la conversation.")
        history = store.message_history(conversation_id, limit=8)
        result = answer_question(request, ids, history)
        try:
            store.append_exchange(conversation_id, request.question.strip(), result)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail="Conversation supprimée pendant la requête.") from exc
        return result

    @protected.delete("/conversations/{conversation_id}", status_code=204, tags=["conversations"])
    def delete_conversation(conversation_id: str) -> None:
        try:
            store.delete_conversation(conversation_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail="Conversation introuvable.") from exc

    router.include_router(protected)
    app.include_router(router)
    return app


app = create_app()

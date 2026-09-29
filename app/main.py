"""HTTP adapters, authentication and file lifecycle orchestration."""
from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.security import APIKeyHeader

from .answering import Answerer
from .config import Settings
from .pdf_processing import InvalidPDF, extract_pdf
from .retrieval import Retriever
from .schemas import AnswerOut, DocumentList, DocumentOut, QuestionIn
from .store import NotFound, Store

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
        title="PDF Intelligence API", version="1.0.0",
        description="Importer, remplacer et supprimer des PDF textuels ; rechercher des preuves et poser des questions.",
    )
    app.state.store = store
    app.state.settings = settings
    router = APIRouter(prefix="/api/v1")

    def verify_api_key(provided: str | None = Depends(header_scheme)) -> None:
        if settings.app_api_key and (not provided or not secrets.compare_digest(provided, settings.app_api_key)):
            raise HTTPException(status_code=401, detail="Clé API absente ou incorrecte.")

    @router.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "retrieval_mode": settings.retrieval_mode, "llm_mode": settings.llm_mode}

    protected = APIRouter(dependencies=[Depends(verify_api_key)])

    def prepared_pdf(upload: UploadFile) -> tuple[dict, list[dict], bytes]:
        name = Path((upload.filename or "").replace("\\", "/")).name
        if not name or len(name) > 255 or any(ord(ch) < 32 for ch in name) or not name.lower().endswith(".pdf"):
            raise HTTPException(status_code=422, detail="Un nom de fichier .pdf est requis.")
        data = upload.file.read(settings.max_pdf_bytes + 1)
        if len(data) > settings.max_pdf_bytes:
            raise HTTPException(status_code=413, detail=f"PDF trop volumineux ({settings.max_pdf_bytes} octets maximum).")
        try:
            pages, chunks = extract_pdf(data, max_pages=settings.max_pages,
                                         chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
        except InvalidPDF as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            indexed = retriever.prepare(chunks)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"filename": name, "sha256": hashlib.sha256(data).hexdigest(), "page_count": pages}, indexed, data

    def store_new_file(data: bytes) -> Path:
        """Immutable opaque path, installed atomically before SQLite points to it."""
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
                    tags=["documents"])
    def add_document(file: UploadFile = File(...)) -> dict:
        try:
            record, chunks, data = prepared_pdf(file)
            document_id = str(uuid.uuid4())
            new_path = store_new_file(data)
            try:
                return Store.public(store.create({**record, "id": document_id, "file_path": new_path}, chunks))
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

    @protected.put("/documents/{document_id}", response_model=DocumentOut, tags=["documents"])
    def replace_document(document_id: str, file: UploadFile = File(...)) -> dict:
        try:
            if not store.get(document_id):
                raise HTTPException(status_code=404, detail="Document introuvable.")
            record, chunks, data = prepared_pdf(file)
            new_path = store_new_file(data)
            try:
                old_path = store.replace(document_id, {**record, "file_path": new_path}, chunks)
            except NotFound as exc:
                new_path.unlink(missing_ok=True)
                raise HTTPException(status_code=404, detail="Document introuvable.") from exc
            except Exception:
                new_path.unlink(missing_ok=True)
                raise
            old_path.unlink(missing_ok=True)
            return Store.public(store.get(document_id))
        finally:
            file.file.close()

    @protected.delete("/documents/{document_id}", status_code=204, tags=["documents"])
    def delete_document(document_id: str) -> None:
        try:
            former_path = store.delete(document_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail="Document introuvable.") from exc
        former_path.unlink(missing_ok=True)

    @protected.post("/questions", response_model=AnswerOut, tags=["questions"])
    def ask_question(request: QuestionIn) -> dict:
        question = request.question.strip()
        if len(question) < 3:
            raise HTTPException(status_code=422, detail="La question doit comporter au moins trois caractères.")
        document_ids = list(dict.fromkeys(request.document_ids)) if request.document_ids is not None else None
        if document_ids is not None:
            missing = [doc_id for doc_id in document_ids if not store.get(doc_id)]
            if missing:
                raise HTTPException(status_code=404, detail={"documents_introuvables": missing})
        chunks = store.all_chunks(document_ids)
        try:
            hits = retriever.search(question, chunks, request.top_k)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if settings.llm_mode == "openai_compatible":
            hits = retriever.expand_context(hits, chunks)
        return answerer.answer(question, hits)

    router.include_router(protected)
    app.include_router(router)
    return app


app = create_app()

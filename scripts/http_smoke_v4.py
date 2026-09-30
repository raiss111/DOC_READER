"""HTTP integration smoke for V4. Generates unique test PDFs, cleans only own resources.

Start the API in a separate terminal, then: python scripts/http_smoke_v4.py
"""
from __future__ import annotations

import os
import uuid

import httpx
import pymupdf
from dotenv import load_dotenv

load_dotenv()
base = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
headers = {"X-API-Key": os.getenv("APP_API_KEY", "")} if os.getenv("APP_API_KEY") else {}


def sample_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 60), text, fontsize=10)
    result = doc.tobytes()
    doc.close()
    return result

nonce = uuid.uuid4().hex[:10]
created: list[str] = []
conversation_id: str | None = None
with httpx.Client(base_url=base, headers=headers, timeout=90) as client:
    try:
        status = client.get("/api/v1/health")
        status.raise_for_status()
        assert status.json()["index_mode"] == "sqlite_fts5"
        print("GET /health: 200; index FTS5")
        texts = [f"Le paiement de la procedure {nonce} est fixe a dix dollars USD.",
                 f"Le paiement de la procedure {nonce} est fixe a vingt francs CDF."]
        binaries = [sample_pdf(t) for t in texts]
        for i, binary in enumerate(binaries):
            response = client.post("/api/v1/documents", files={"file": (f"smoke{i}.pdf", binary, "application/pdf")})
            response.raise_for_status()
            created.append(response.json()["id"])
        print("POST /documents: deux PDF distincts OK")
        duplicate = client.post("/api/v1/documents", files={"file": ("autre-nom.pdf", binaries[0], "application/pdf")})
        assert duplicate.status_code == 409 and duplicate.json()["existing_document_id"] == created[0]
        print("POST /documents: doublon renommé → 409 OK")
        conversation = client.post("/api/v1/conversations", json={
            "title": "Smoke V4", "document_ids": created})
        conversation.raise_for_status()
        conversation_id = conversation.json()["id"]
        print("POST /conversations: 201")
        answer = client.post(f"/api/v1/conversations/{conversation_id}/questions", json={
            "question": "Compare le paiement des deux procedures", "top_k": 2, "include_excerpts": False})
        answer.raise_for_status()
        assert {s["document_id"] for s in answer.json()["sources"]} == set(created)
        print("POST /conversations/{id}/questions: deux sources distinctes OK")
        history = client.get(f"/api/v1/conversations/{conversation_id}/messages")
        history.raise_for_status()
        assert history.json()["total"] == 2
        print("GET /messages: historique sauvegardé OK")
    finally:
        if conversation_id:
            assert client.delete(f"/api/v1/conversations/{conversation_id}").status_code == 204
        for doc_id in created:
            assert client.delete(f"/api/v1/documents/{doc_id}").status_code == 204
        print("Nettoyage des ressources créées par ce smoke: OK")
print("V4 LIVE HTTP SMOKE: PASSED")

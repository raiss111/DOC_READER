"""Non-destructive to existing user documents: creates/tests/deletes only its own new document.

Run with the API already started: python scripts/http_smoke.py
Optional: BASE_URL=http://127.0.0.1:8000 APP_API_KEY=your-key
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()
base = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
headers = {"X-API-Key": os.getenv("APP_API_KEY", "")} if os.getenv("APP_API_KEY") else {}
root = Path(__file__).resolve().parents[1]

with httpx.Client(base_url=base, headers=headers, timeout=60) as client:
    response = client.get("/api/v1/health")
    response.raise_for_status()
    print("Health:", response.json())
    source = (root / "examples" / "guide_procedures.pdf").read_bytes()
    replacement = (root / "examples" / "conditions_transport.pdf").read_bytes()
    doc_id = None
    try:
        response = client.post("/api/v1/documents", files={"file": ("smoke-guide.pdf", source, "application/pdf")})
        response.raise_for_status()
        doc = response.json()
        doc_id = doc["id"]
        print("Upload:", doc_id, "pages:", doc["page_count"])
        response = client.post("/api/v1/questions", json={"question": "Quel est le delai de declaration des marchandises ?", "document_ids": [doc_id]})
        response.raise_for_status()
        assert any("15 jours ouvrables" in src["excerpt"] for src in response.json()["sources"])
        print("Question + page/source: OK")
        response = client.put(f"/api/v1/documents/{doc_id}", files={"file": ("smoke-transport.pdf", replacement, "application/pdf")})
        response.raise_for_status()
        assert response.json()["version"] == 2
        response = client.post("/api/v1/questions", json={"question": "Quelle est la garantie du transport ?", "document_ids": [doc_id]})
        response.raise_for_status()
        assert any("30 jours calendaires" in src["excerpt"] for src in response.json()["sources"])
        response = client.post("/api/v1/questions", json={"question": "delai declaration", "document_ids": [doc_id]})
        response.raise_for_status()
        assert response.json()["response_mode"] == "no_evidence"
        print("Replacement + old index cleared: OK")
    finally:
        if doc_id:
            response = client.delete(f"/api/v1/documents/{doc_id}")
            response.raise_for_status()
            assert response.status_code == 204
            assert client.get(f"/api/v1/documents/{doc_id}").status_code == 404
            print("Deletion: OK")
print("LIVE HTTP SMOKE: PASSED")

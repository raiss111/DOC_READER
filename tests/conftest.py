from __future__ import annotations

import io

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(storage_dir=tmp_path / "application", chunk_size=300, chunk_overlap=40))
    with TestClient(app) as test_client:
        yield test_client


def pdf_bytes(*page_texts: str) -> bytes:
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=11)
    output = doc.tobytes()
    doc.close()
    return output


def upload(client: TestClient, filename: str, data: bytes, url="/api/v1/documents"):
    return client.post(url, files={"file": (filename, io.BytesIO(data), "application/pdf")})

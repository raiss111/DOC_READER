"""Regressions: repeated imports and definitions spanning two PDF pages."""
from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from conftest import pdf_bytes, upload


PREFIX = "/api/v1"


def test_four_identical_imports_no_longer_repeat_the_same_evidence(client):
    document = pdf_bytes("Le CSS est ecrit dans une feuille de style separee.")
    original = upload(client, "cours.pdf", document)
    assert original.status_code == 201
    for _ in range(3):
        duplicate = upload(client, "renamed.pdf", document)
        assert duplicate.status_code == 409
        assert duplicate.json()["existing_document_id"] == original.json()["id"]
    assert client.get(PREFIX + "/documents").json()["total"] == 1
    result = client.post(PREFIX + "/questions", json={
        "question": "Ou ecrit-on le CSS ?", "top_k": 4
    }).json()
    assert result["response_mode"] == "extractive"
    assert len(result["sources"]) == 1
    assert "feuille de style" in result["sources"][0]["excerpt"]
    assert client.get(PREFIX + "/documents").json()["total"] == 1


def test_llm_sees_definition_continued_on_next_page(tmp_path, monkeypatch):
    payloads = []

    def fake_post(self, url, **kwargs):
        payloads.append(kwargs["json"])
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "Une balise HTML delimite un element et utilise des chevrons; "
                       "elle peut etre ouvrante, fermante ou orpheline [1]. "
                       "Source : cours.pdf, section 2.1.1, pages 1-2 [1]."
        }}]}, request=httpx.Request("POST", url))

    pdf = pdf_bytes(
        "2.1.1 Elements, balises et attributs.\n"
        "HTML utilise des elements balises pour structurer une page web.\n"
        "Une balise ouvrante et une balise fermante encadrent un element.",
        "Les balises reprennent le nom des elements, entoure de chevrons.\n"
        "La balise fermante possede un slash devant son nom.\n"
        "Certains elements ont une balise orpheline : br cree un retour a la ligne.",
    )
    settings = Settings(storage_dir=tmp_path / "rag", chunk_size=950, chunk_overlap=150,
                        llm_mode="openai_compatible", llm_api_key="test-only")
    with TestClient(create_app(settings)) as client:
        added = upload(client, "cours.pdf", pdf)
        assert added.status_code == 201, added.text
        # Patch only outbound LLM calls: TestClient itself inherits from httpx.Client.
        original_post = httpx.Client.post

        def dispatch(self, url, **kwargs):
            if url == PREFIX + "/questions":
                return original_post(self, url, **kwargs)
            return fake_post(self, url, **kwargs)

        monkeypatch.setattr(httpx.Client, "post", dispatch)
        response = client.post(PREFIX + "/questions", json={
            "question": "C'est quoi une balise HTML ?", "top_k": 1
        })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["response_mode"] == "llm"
    assert result["sources"][0]["page"] == 1
    assert result["sources"][0]["page_end"] == 2
    assert "balise orpheline" in result["sources"][0]["excerpt"]
    assert "balise orpheline" in payloads[0]["messages"][1]["content"]
    assert "PAGES: 1-2" in payloads[0]["messages"][1]["content"]


def test_expansion_does_not_mix_documents():
    from app.retrieval import Retriever
    hits = [{"document_id": "A", "filename": "a.pdf", "page": 4,
             "ordinal": 9, "content": "balise ouvrante", "score": 1.0}]
    rows = hits + [
        {"document_id": "B", "filename": "b.pdf", "page": 5, "ordinal": 10,
         "content": "SECRET from other document"},
    ]
    enriched = Retriever(Settings()).expand_context(hits, rows)
    assert "SECRET" not in enriched[0]["context"]
    assert enriched[0]["page_end"] == 4

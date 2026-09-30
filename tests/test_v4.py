"""V4 contracts: deduplication, indexed search, migrations, conversations and scope."""
from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import httpx
import pymupdf
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.store import Store
from conftest import pdf_bytes, upload

P = "/api/v1"


def test_default_limits_and_document_hash_dedup(client):
    s = Settings()
    assert s.max_pdf_bytes == 30 * 1024 * 1024
    assert s.max_pages == 1000
    assert client.get(P + "/health").json()["index_mode"] == "sqlite_fts5"
    content = pdf_bytes("La nomenclature du transport est importante.")
    a = upload(client, "premier.pdf", content)
    assert a.status_code == 201
    b = upload(client, "autre_nom.pdf", content)
    assert b.status_code == 409
    assert b.json()["existing_document_id"] == a.json()["id"]
    assert client.get(P + "/documents").json()["total"] == 1
    assert len(list((client.app.state.settings.storage_dir / "files").glob("*.pdf"))) == 1
    # Identical bytes for the same resource are idempotent; no extra version or file.
    same = client.put(P + "/documents/" + a.json()["id"],
                      files={"file": ("renamed.pdf", io.BytesIO(content), "application/pdf")})
    assert same.status_code == 200 and same.json()["version"] == 1
    assert client.delete(P + "/documents/" + a.json()["id"]).status_code == 204
    assert upload(client, "reimport.pdf", content).status_code == 201


def test_replacing_with_another_document_fails_without_data_loss(client):
    old = upload(client, "old.pdf", pdf_bytes("Le montant ancien est de 90 dollars.")).json()
    other_binary = pdf_bytes("La facture porte sur 70 francs congolais.")
    other = upload(client, "other.pdf", other_binary).json()
    r = client.put(P + "/documents/" + old["id"],
                   files={"file": ("try.pdf", io.BytesIO(other_binary), "application/pdf")})
    assert r.status_code == 409 and r.json()["existing_document_id"] == other["id"]
    assert client.get(P + "/documents/" + old["id"]).json() == old
    assert client.post(P + "/questions", json={"question": "montant ancien"}).json()["sources"][0]["document_id"] == old["id"]


def test_fts5_is_used_in_lexical_mode_and_reindexed_after_replace_delete(client, monkeypatch):
    store = client.app.state.store

    def no_global_scan(*args, **kwargs):
        raise AssertionError("Lexical mode must NOT scan all chunks")

    monkeypatch.setattr(store, "all_chunks", no_global_scan)
    old = upload(client, "old.pdf", pdf_bytes("Le contrat mentionne le zèbre extraordinaire.")).json()
    initial = client.post(P + "/questions", json={"question": "zèbre extraordinaire", "top_k": 1}).json()
    assert initial["sources"][0]["document_id"] == old["id"]
    updated = client.put(P + "/documents/" + old["id"], files={"file": (
        "new.pdf", io.BytesIO(pdf_bytes("Le contrat mentionne le dauphin remarquable.")), "application/pdf")})
    assert updated.status_code == 200
    old_query = client.post(P + "/questions", json={"question": "zèbre extraordinaire"}).json()
    assert old_query["response_mode"] == "no_evidence"
    new_query = client.post(P + "/questions", json={"question": "dauphin remarquable"}).json()
    assert new_query["sources"][0]["document_id"] == old["id"]
    assert client.delete(P + "/documents/" + old["id"]).status_code == 204
    deleted = client.post(P + "/questions", json={"question": "dauphin remarquable"}).json()
    assert deleted["response_mode"] == "no_evidence"
    with store.connect() as db:
        db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('integrity-check')")


def test_multi_document_conversation_and_persistence(tmp_path):
    config = Settings(storage_dir=tmp_path / "v4", chunk_size=300, chunk_overlap=40)
    with TestClient(create_app(config)) as client:
        d1 = upload(client, "usd.pdf", pdf_bytes("Les paiements doivent etre realises en dollars USD.")).json()
        d2 = upload(client, "cdf.pdf", pdf_bytes("Les paiements doivent etre realises en francs CDF.")).json()
        c = client.post(P + "/conversations", json={
            "title": "Comparaison des paiements", "document_ids": [d1["id"], d2["id"]]})
        assert c.status_code == 201, c.text
        cid = c.json()["id"]
        assert c.json()["message_count"] == 0
        asked = client.post(P + f"/conversations/{cid}/questions", json={
            "question": "Compare les modalités de paiement selon les documents", "top_k": 2,
            "include_excerpts": False})
        assert asked.status_code == 200, asked.text
        refs = {source["document_id"] for source in asked.json()["sources"]}
        assert refs == {d1["id"], d2["id"]}
        assert all("excerpt" not in src for src in asked.json()["sources"])
        history = client.get(P + f"/conversations/{cid}/messages").json()
        assert history["total"] == 2
        assert [m["role"] for m in history["items"]] == ["user", "assistant"]
        assert "excerpt" not in history["items"][1]["sources"][0]
    # Both conversation and messages survive restart.
    with TestClient(create_app(config)) as restarted:
        assert restarted.get(P + f"/conversations/{cid}").json()["message_count"] == 2
        assert restarted.get(P + f"/conversations/{cid}/messages").json()["total"] == 2
        assert restarted.get(P + "/conversations").json()["total"] == 1
        renamed = restarted.patch(P + f"/conversations/{cid}", json={"title": "Dossier paiement"})
        assert renamed.status_code == 200 and renamed.json()["title"] == "Dossier paiement"
        assert restarted.delete(P + f"/conversations/{cid}").status_code == 204
        assert restarted.get(P + "/documents").json()["total"] == 2
        assert restarted.get(P + f"/conversations/{cid}").status_code == 404


def test_conversation_scopes_and_document_deletion(client):
    a = upload(client, "a.pdf", pdf_bytes("La clause alpha donne un taux de 10 pourcent.")).json()
    b = upload(client, "b.pdf", pdf_bytes("La clause beta donne un taux de 20 pourcent.")).json()
    c = client.post(P + "/conversations", json={"document_ids": [a["id"]]}).json()
    path = P + "/conversations/" + c["id"]
    out = client.post(path + "/questions", json={"question": "clause beta", "top_k": 2}).json()
    assert out["response_mode"] == "no_evidence"
    assert client.post(path + "/questions", json={
        "question": "clause beta", "document_ids": [b["id"]]}).status_code == 422
    assert client.put(path + "/documents", json={"document_ids": [a["id"], b["id"], b["id"]]}).json()["document_ids"] == [a["id"], b["id"]]
    assert client.post(path + "/questions", json={"question": "clause beta"}).json()["sources"][0]["document_id"] == b["id"]
    assert client.put(path + "/documents", json={"document_ids": ["not-present"]}).status_code == 404
    assert client.get(path).json()["document_ids"] == [a["id"], b["id"]]
    assert client.delete(P + "/documents/" + b["id"]).status_code == 204
    assert client.get(path).json()["document_ids"] == [a["id"]]
    assert client.get(path + "/messages").json()["total"] == 4
    assert client.post(path + "/questions", json={"question": "clause beta"}).json()["response_mode"] == "no_evidence"


def test_contextual_followup_sent_to_llm_and_not_leaked_between_chats(tmp_path, monkeypatch):
    settings = Settings(storage_dir=tmp_path / "chat", llm_mode="openai_compatible", llm_api_key="fake")
    captured = []
    original_post = httpx.Client.post

    def fake_post(self, url, **kwargs):
        if url.startswith(P):
            return original_post(self, url, **kwargs)
        captured.append(kwargs["json"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "Réponse sourcée [1]."}}]},
                              request=httpx.Request("POST", url))

    with TestClient(create_app(settings)) as client:
        pdf = upload(client, "html.pdf", pdf_bytes(
            "Une balise HTML ouvre et ferme un element. Exemple : p paragraphe."
        )).json()
        c1 = client.post(P + "/conversations", json={"document_ids": [pdf["id"]]}).json()["id"]
        c2 = client.post(P + "/conversations", json={"document_ids": [pdf["id"]]}).json()["id"]
        monkeypatch.setattr(httpx.Client, "post", fake_post)
        r1 = client.post(P + f"/conversations/{c1}/questions", json={"question": "Définis une balise HTML"})
        assert r1.status_code == 200 and r1.json()["response_mode"] == "llm"
        r2 = client.post(P + f"/conversations/{c1}/questions", json={"question": "Donne un exemple"})
        assert r2.status_code == 200 and r2.json()["sources"]
        assert "HISTORIQUE" in captured[-1]["messages"][1]["content"]
        assert "Définis une balise HTML" in captured[-1]["messages"][1]["content"]
        r3 = client.post(P + f"/conversations/{c2}/questions", json={"question": "Définis une balise HTML"})
        assert r3.status_code == 200
        assert "HISTORIQUE" not in captured[-1]["messages"][1]["content"]


def test_legacy_migration_preserves_duplicates_and_builds_index(tmp_path):
    folder = tmp_path / "old"
    folder.mkdir()
    db_path = folder / "metadata.sqlite3"
    # Actual V1 schema, with two old duplicates (migration must not delete either).
    with sqlite3.connect(db_path) as db:
        db.executescript("""
        CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT NOT NULL,
          file_path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, page_count INTEGER NOT NULL,
          chunk_count INTEGER NOT NULL, version INTEGER NOT NULL DEFAULT 1,
          uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE TABLE chunks (id INTEGER PRIMARY KEY,
          document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          page INTEGER NOT NULL, ordinal INTEGER NOT NULL, content TEXT NOT NULL,
          embedding_json TEXT);
        """)
        for i in (1, 2):
            db.execute("INSERT INTO documents(id,filename,file_path,sha256,page_count,chunk_count) "
                       "VALUES(?,?,?,?,1,1)", (f"old{i}", f"old{i}.pdf", str(folder / f"old{i}.pdf"), "samehash"))
            db.execute("INSERT INTO chunks(document_id,page,ordinal,content) VALUES(?,1,0,?)",
                       (f"old{i}", "Le projet originel comprend une documentation historique."))
        db.commit()
    store = Store(db_path)
    assert (folder / "metadata.sqlite3.pre_v4_backup.sqlite3").exists()
    with store.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
    assert len(store.search_candidates("documentation historique", None)) == 2
    assert store.find_by_sha("samehash") in {"old1", "old2"}
    # It also serves the old data via the V4 API without reimport.
    with TestClient(create_app(Settings(storage_dir=folder))) as client:
        result = client.post(P + "/questions", json={"question": "documentation historique"}).json()
        assert len(result["sources"]) == 1  # legacy duplicated evidence deduplicated
        assert result["response_mode"] == "extractive"


def test_limit_of_1000_pages(tmp_path):
    settings = Settings(storage_dir=tmp_path / "pages")
    doc = pymupdf.open()
    for _ in range(1000):
        doc.new_page()
    doc[0].insert_text((60, 60), "Cette premiere page contient des informations scientifiques.")
    good = doc.tobytes()
    doc.new_page()
    too_long = doc.tobytes()
    doc.close()
    with TestClient(create_app(settings)) as client:
        assert upload(client, "mille.pdf", good).status_code == 201
        response = upload(client, "mille-et-un.pdf", too_long)
        assert response.status_code == 422
        assert "1000" in response.json()["detail"]


def test_30_mib_limit_rejects_before_parsing(tmp_path):
    with TestClient(create_app(Settings(storage_dir=tmp_path / "big"))) as client:
        big = b"%PDF-" + b"X" * (30 * 1024 * 1024)
        result = upload(client, "too_big.pdf", big)
        assert result.status_code == 413
        assert client.get(P + "/documents").json()["total"] == 0


def test_same_hash_create_is_serialized_across_workers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from app.store import DuplicateDocument

    store = Store(tmp_path / "db.sqlite3")
    chunks = [{"page": 1, "ordinal": 0, "content": "Document unique en base."}]

    def create(i):
        try:
            store.create({"id": f"doc{i}", "filename": "same.pdf",
                          "file_path": tmp_path / f"doc{i}.pdf", "sha256": "duplicatehash",
                          "page_count": 1}, chunks)
            return "created"
        except DuplicateDocument:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, [1, 2]))
    assert sorted(results) == ["created", "duplicate"]
    assert store.list(10, 0)[0] == 1


def test_new_conversation_endpoints_require_shared_api_key(tmp_path):
    app = create_app(Settings(storage_dir=tmp_path / "auth", app_api_key="secret"))
    with TestClient(app) as client:
        assert client.get(P + "/conversations").status_code == 401
        assert client.post(P + "/conversations", json={"title": "Privé"}).status_code == 401
        assert client.post(P + "/conversations", json={"title": "Privé"},
                           headers={"X-API-Key": "secret"}).status_code == 201


def test_social_greeting_uses_llm_but_does_not_open_general_chat(tmp_path, monkeypatch):
    settings = Settings(storage_dir=tmp_path / "social", llm_mode="openai_compatible", llm_api_key="fake")
    original_post = httpx.Client.post
    outbound = []

    def fake_post(self, url, **kwargs):
        if url.startswith(P):
            return original_post(self, url, **kwargs)
        outbound.append(kwargs["json"])
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "Bonjour ! Je peux vous aider à comprendre les documents de cette conversation."
        }}]}, request=httpx.Request("POST", url))

    with TestClient(create_app(settings)) as client:
        cid = client.post(P + "/conversations", json={"title": "Vide"}).json()["id"]
        monkeypatch.setattr(httpx.Client, "post", fake_post)
        greeting = client.post(P + f"/conversations/{cid}/questions", json={"question": "Bonjour"})
        assert greeting.status_code == 200
        assert greeting.json()["response_mode"] == "llm_chat"
        assert greeting.json()["sources"] == []
        assert "documents" in outbound[-1]["messages"][0]["content"]
        # A substantive question still cannot escape the document scope.
        outside = client.post(P + f"/conversations/{cid}/questions", json={"question": "Quelle est la capitale du Japon ?"})
        assert outside.status_code == 422


def test_referential_followup_uses_previous_assistant_for_retrieval(tmp_path, monkeypatch):
    settings = Settings(storage_dir=tmp_path / "referential", llm_mode="openai_compatible", llm_api_key="fake")
    original_post = httpx.Client.post

    def fake_post(self, url, **kwargs):
        if url.startswith(P):
            return original_post(self, url, **kwargs)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "Les étapes comprennent la problématique, l'hypothèse et la délimitation [1]."
        }}]}, request=httpx.Request("POST", url))

    with TestClient(create_app(settings)) as client:
        pdf = upload(client, "methode.pdf", pdf_bytes(
            "La recherche scientifique comporte plusieurs étapes. La problématique est le point de départ. "
            "L'hypothèse joue un rôle central. La délimitation précise le champ de l'étude."
        )).json()
        cid = client.post(P + "/conversations", json={"document_ids": [pdf["id"]]}).json()["id"]
        store = client.app.state.store
        original_search = store.search_candidates
        queries = []

        def capture_search(question, document_ids, limit=300):
            queries.append(question)
            return original_search(question, document_ids, limit)

        monkeypatch.setattr(store, "search_candidates", capture_search)
        monkeypatch.setattr(httpx.Client, "post", fake_post)
        first = client.post(P + f"/conversations/{cid}/questions", json={
            "question": "Quelles sont les principales étapes de la recherche ?"
        })
        assert first.status_code == 200
        second = client.post(P + f"/conversations/{cid}/questions", json={
            "question": "Parmi ces étapes, lesquelles sont les plus importantes au début et pourquoi ?"
        })
        assert second.status_code == 200
        assert "problématique" in queries[-1].casefold()
        assert "hypothèse" in queries[-1].casefold()
        assert "délimitation" in queries[-1].casefold()


def test_priority_question_prefers_explicit_strength_wording():
    from app.retrieval import Retriever

    chunks = [
        {"document_id": "A", "filename": "a.pdf", "sha256": "a", "page": 1, "ordinal": 0,
         "content": "Les étapes importantes au début sont présentées dans ce chapitre.", "embedding_json": None},
        {"document_id": "A", "filename": "a.pdf", "sha256": "a", "page": 2, "ordinal": 4,
         "content": "La formulation du problème est une étape essentielle et le point de départ de la recherche.",
         "embedding_json": None},
    ]
    hits = Retriever(Settings()).search(
        "Quelles étapes sont les plus importantes au début ?", chunks, top_k=2
    )
    assert hits[0]["page"] == 2


def test_followup_detection_does_not_capture_standalone_definition():
    from app.retrieval import is_contextual_followup

    assert is_contextual_followup("Parmi ces étapes, lesquelles sont prioritaires ?") is True
    assert is_contextual_followup("Explique la quatrième.") is True
    assert is_contextual_followup("Qu'est-ce qu'une hypothèse ?") is False


def test_priority_detection_does_not_treat_ordinal_as_importance():
    from app.retrieval import _asks_for_priority

    assert _asks_for_priority("Quelles étapes sont les plus importantes au début ?") is True
    assert _asks_for_priority("Quel est le premier chapitre ?") is False

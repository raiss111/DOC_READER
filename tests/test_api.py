from __future__ import annotations

import io
from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from conftest import pdf_bytes, upload


PREFIX = "/api/v1"


def question(client, question, document_ids=None, top_k=4):
    data = {"question": question, "top_k": top_k}
    if document_ids is not None:
        data["document_ids"] = document_ids
    return client.post(f"{PREFIX}/questions", json=data)


def test_health_and_openapi(client):
    assert client.get(PREFIX + "/health").json()["status"] == "ok"
    schema = client.get("/openapi.json").json()
    assert "/api/v1/documents" in schema["paths"]
    assert "/api/v1/questions" in schema["paths"]


def test_upload_list_detail_and_question_with_source(client):
    response = upload(client, "procedures.pdf", pdf_bytes(
        "Le delai de declaration des marchandises est de 15 jours.",
        "Le transport doit respecter les consignes de securite.",
    ))
    assert response.status_code == 201, response.text
    doc = response.json()
    assert doc["page_count"] == 2
    assert doc["chunk_count"] == 2
    assert doc["version"] == 1
    assert len(doc["sha256"]) == 64
    listing = client.get(PREFIX + "/documents").json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == doc["id"]
    assert client.get(f"{PREFIX}/documents/{doc['id']}").json() == doc
    answer = question(client, "Quel est le delai de declaration ?").json()
    assert answer["response_mode"] == "extractive"
    assert "15 jours" in answer["answer"]
    assert answer["sources"][0]["page"] == 1
    assert answer["sources"][0]["document_id"] == doc["id"]
    assert "file_path" not in doc


def test_query_page_number_two(client):
    upload(client, "pages.pdf", pdf_bytes("La tarification est disponible.",
                                          "La garantie du transport est de trente jours."))
    answer = question(client, "Quelle est la garantie du transport ?").json()
    assert answer["sources"][0]["page"] == 2


def test_document_scope_and_top_k(client):
    a = upload(client, "alpha.pdf", pdf_bytes("Le paiement se fait en dollars.")).json()
    b = upload(client, "beta.pdf", pdf_bytes("Le paiement se fait en francs congolais.")).json()
    result = question(client, "Comment faire le paiement ?", [b["id"]], top_k=1).json()
    assert result["sources"][0]["document_id"] == b["id"]
    assert len(result["sources"]) == 1
    assert a["id"] != b["id"]


def test_no_evidence(client):
    upload(client, "a.pdf", pdf_bytes("Les informations portent sur la comptabilite."))
    result = question(client, "Quelle est la couleur des elephants ?").json()
    assert result["response_mode"] == "no_evidence"
    assert result["sources"] == []


def test_empty_library_returns_no_evidence(client):
    assert question(client, "Que dit le contrat ?").json()["response_mode"] == "no_evidence"


def test_replace_does_not_keep_old_index_or_binary(client):
    old = upload(client, "original.pdf", pdf_bytes("La livraison est prevue en janvier.")).json()
    old_file = Path(client.app.state.store.get(old["id"])["file_path"])
    new = pdf_bytes("La livraison est prevue en septembre.")
    updated = client.put(f"{PREFIX}/documents/{old['id']}",
                         files={"file": ("remplacement.pdf", io.BytesIO(new), "application/pdf")})
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["id"] == old["id"]
    assert updated.json()["filename"] == "remplacement.pdf"
    assert not old_file.exists()
    assert question(client, "septembre").json()["response_mode"] == "extractive"
    assert question(client, "janvier").json()["response_mode"] == "no_evidence"


def test_invalid_replace_preserves_old_document_and_index(client):
    old = upload(client, "original.pdf", pdf_bytes("Le montant est de 50 USD.")).json()
    response = client.put(f"{PREFIX}/documents/{old['id']}",
                          files={"file": ("bad.pdf", io.BytesIO(b"not a pdf"), "application/pdf")})
    assert response.status_code == 422
    assert client.get(f"{PREFIX}/documents/{old['id']}").json() == old
    assert "50 USD" in question(client, "Quel montant en USD ?").json()["answer"]


def test_delete_removes_document_index_and_binary(client):
    doc = upload(client, "to-delete.pdf", pdf_bytes("Le code est secret-123.")).json()
    stored_file = Path(client.app.state.store.get(doc["id"])["file_path"])
    assert stored_file.exists()
    assert client.delete(f"{PREFIX}/documents/{doc['id']}").status_code == 204
    assert not stored_file.exists()
    assert client.get(f"{PREFIX}/documents/{doc['id']}").status_code == 404
    assert question(client, "secret-123").json()["sources"] == []
    assert client.delete(f"{PREFIX}/documents/{doc['id']}").status_code == 404


def test_reject_non_pdf_extension_or_signature(client):
    assert upload(client, "fichier.txt", pdf_bytes("text" )).status_code == 422
    assert upload(client, "fichier.pdf", b"garbage").status_code == 422


def test_reject_scanned_or_blank_pdf(client):
    response = upload(client, "scan.pdf", pdf_bytes(""))
    assert response.status_code == 422
    assert "OCR" in response.json()["detail"]


def test_reject_encrypted_pdf(client):
    doc = pymupdf.open(stream=pdf_bytes("Informations privees."), filetype="pdf")
    encrypted = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="admin", user_pw="motdepasse")
    doc.close()
    assert upload(client, "private.pdf", encrypted).status_code == 422


def test_upload_limits(tmp_path):
    settings = Settings(storage_dir=tmp_path / "limited", max_pdf_bytes=2048, max_pages=1)
    with TestClient(create_app(settings)) as test_client:
        assert upload(test_client, "big.pdf", pdf_bytes("large PDF") + b"X" * 2500).status_code == 413
        assert upload(test_client, "two.pdf", pdf_bytes("first", "second")).status_code == 422


def test_authentication(tmp_path):
    app = create_app(Settings(storage_dir=tmp_path / "auth", app_api_key="test-secret"))
    with TestClient(app) as test_client:
        assert test_client.get(PREFIX + "/health").status_code == 200
        assert test_client.get(PREFIX + "/documents").status_code == 401
        assert test_client.get(PREFIX + "/documents", headers={"X-API-Key": "wrong"}).status_code == 401
        assert test_client.get(PREFIX + "/documents", headers={"X-API-Key": "test-secret"}).status_code == 200
        assert test_client.post(PREFIX + "/questions", json={"question": "Une question ?"}).status_code == 401


def test_validation_and_unknown_scopes(client):
    assert question(client, " ").status_code == 422
    assert question(client, "Une question ?", top_k=100).status_code == 422
    assert question(client, "Une question ?", ["unknown"]).status_code == 404
    assert client.get(PREFIX + "/documents?limit=0").status_code == 422


def test_safe_storage_name(client):
    response = upload(client, "../../evil.pdf", pdf_bytes("Les procedures locales."))
    assert response.status_code == 201
    doc = response.json()
    assert doc["filename"] == "evil.pdf"
    actual = client.app.state.store.get(doc["id"])
    assert Path(actual["file_path"]).parent == client.app.state.settings.storage_dir / "files"
    assert Path(actual["file_path"]).name != "evil.pdf"


def test_persistence_across_restart(tmp_path):
    settings = Settings(storage_dir=tmp_path / "persistent")
    with TestClient(create_app(settings)) as first:
        doc = upload(first, "p.pdf", pdf_bytes("Le bon de commande est obligatoire.")).json()
    with TestClient(create_app(settings)) as second:
        assert second.get(PREFIX + "/documents").json()["total"] == 1
        response = question(second, "Le bon de commande est-il obligatoire ?").json()
        assert response["sources"][0]["document_id"] == doc["id"]


def test_list_pagination(client):
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        assert upload(client, name, pdf_bytes("Information du dossier.")).status_code == 201
    response = client.get(PREFIX + "/documents?limit=2&offset=1").json()
    assert response["total"] == 3
    assert len(response["items"]) == 2


def test_valid_question_on_empty_selected_scope(client):
    upload(client, "a.pdf", pdf_bytes("Du texte simple."))
    assert question(client, "Du texte ?", []).json()["response_mode"] == "no_evidence"


def test_failed_replace_db_step_rolls_back_staged_file(client, monkeypatch):
    doc = upload(client, "stable.pdf", pdf_bytes("La valeur initiale est stable.")).json()
    store = client.app.state.store
    original = Path(store.get(doc["id"])["file_path"])
    initial_files = set(original.parent.iterdir())

    def fail_replace(*args, **kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(store, "replace", fail_replace)
    try:
        client.put(f"{PREFIX}/documents/{doc['id']}",
                   files={"file": ("new.pdf", io.BytesIO(pdf_bytes("Une autre valeur.")), "application/pdf")})
    except RuntimeError:
        pass
    else:
        raise AssertionError("The simulated failure should propagate in TestClient")
    assert set(original.parent.iterdir()) == initial_files
    assert client.get(f"{PREFIX}/documents/{doc['id']}").json() == doc
    assert "initiale" in question(client, "valeur initiale").json()["answer"]


def test_real_example_pdf_files(client):
    from pathlib import Path
    examples = Path(__file__).resolve().parents[1] / "examples"
    for sample in ("guide_procedures.pdf", "conditions_transport.pdf"):
        response = upload(client, sample, (examples / sample).read_bytes())
        assert response.status_code == 201, response.text
    report = question(client, "Quel est le delai de declaration des marchandises ?").json()
    assert "15 jours ouvrables" in report["sources"][0]["excerpt"]
    assert report["sources"][0]["page"] == 1
    warranty = question(client, "Quelle est la duree de la garantie de transport ?").json()
    assert "30 jours calendaires" in warranty["sources"][0]["excerpt"]
    assert warranty["sources"][0]["filename"] == "conditions_transport.pdf"

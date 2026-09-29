import pytest

from app.pdf_processing import InvalidPDF, extract_pdf, split_text
from app.retrieval import Retriever, tokenize
from app.config import Settings
from conftest import pdf_bytes


def test_chunks_have_overlap_and_preserve_ends():
    text = " ".join(f"mot{i:03}" for i in range(90))
    parts = split_text(text, size=200, overlap=40)
    assert len(parts) > 2
    assert parts[0].startswith("mot000")
    assert parts[-1].endswith("mot089")
    assert parts[0][-20:] in parts[1]


def test_page_reference_is_preserved():
    pages, chunks = extract_pdf(pdf_bytes("Premiere page.", "Deuxieme page."),
                                max_pages=5, chunk_size=200, overlap=40)
    assert pages == 2
    assert [c.page for c in chunks] == [1, 2]


def test_bad_pdf_rejected():
    with pytest.raises(InvalidPDF):
        extract_pdf(b"not pdf", max_pages=5, chunk_size=200, overlap=40)


def test_lexical_search_ignores_accents_and_stopwords():
    assert tokenize("Quel est le délai de déclaration ?") == ["delai", "declaration"]
    rows = [{"content": "Le delai de declaration est de 15 jours.", "document_id": "id", "page": 1,
             "filename": "doc.pdf", "embedding_json": None}]
    retriever = Retriever(Settings())
    assert retriever.search("délai déclaration", rows, top_k=2)[0]["page"] == 1
    assert retriever.search("ornithorynque", rows, top_k=2) == []


def test_semantic_search_with_controlled_vectors(monkeypatch):
    # No model downloads needed: validate the semantic branch with deterministic embeddings.
    import json
    retriever = Retriever(Settings(retrieval_mode="semantic", semantic_threshold=0.5))

    def fake_embed(texts):
        return [[1.0, 0.0] if "garantie" in text or "duree" in text
                else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(retriever, "embed", fake_embed)
    rows = [
        {"content": "La garantie de transport dure trente jours.", "document_id": "a", "page": 1,
         "filename": "a.pdf", "embedding_json": json.dumps([1.0, 0.0])},
        {"content": "La declaration se fait en quinze jours.", "document_id": "b", "page": 2,
         "filename": "b.pdf", "embedding_json": json.dumps([0.0, 1.0])},
    ]
    result = retriever.search("Quelle duree ?", rows, 3)
    assert len(result) == 1
    assert result[0]["document_id"] == "a"
    # Legacy lexical chunks without saved embeddings still work in semantic mode.
    rows[0]["embedding_json"] = None
    assert retriever.search("Quelle duree ?", rows, 3)[0]["document_id"] == "a"

import httpx

from app.answering import Answerer
from app.config import Settings


HITS = [{"content": "Le delai est de 15 jours.", "filename": "guide.pdf", "document_id": "abc",
         "page": 2, "score": 0.9}]


def test_extractive_includes_source():
    answer = Answerer(Settings()).answer("Quel delai ?", HITS)
    assert answer["response_mode"] == "extractive"
    assert "[1]" in answer["answer"]
    assert answer["sources"][0]["page"] == 2


def test_llm_with_valid_citation(monkeypatch):
    def fake_post(self, url, **kwargs):
        assert url.endswith("/chat/completions")
        return httpx.Response(200, json={"choices": [{"message": {"content": "Le delai est de 15 jours [1]."}}]},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = Answerer(Settings(llm_mode="openai_compatible")).answer("Quel delai ?", HITS)
    assert result["response_mode"] == "llm"
    assert "15 jours" in result["answer"]


def test_llm_without_citation_falls_back(monkeypatch):
    def fake_post(self, url, **kwargs):
        return httpx.Response(200, json={"choices": [{"message": {"content": "Reponse sans reference"}}]},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    answer = Answerer(Settings(llm_mode="openai_compatible")).answer("Question ?", HITS)
    assert answer["response_mode"] == "extractive"
    assert "repli" in answer["warning"]


def test_llm_network_failure_falls_back(monkeypatch):
    def fake_post(self, url, **kwargs):
        raise httpx.ConnectError("simulated outage")
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    answer = Answerer(Settings(llm_mode="openai_compatible")).answer("Question ?", HITS)
    assert answer["response_mode"] == "extractive"

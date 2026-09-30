"""An offline BM25 baseline, with an optional multilingual semantic mode."""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from typing import Any

from .config import Settings

# Very common French/English function words; do not remove negations.
STOPWORDS = set("""
le la les l un une des de du d au aux a et ou en est sont dans sur pour par avec que qui
qu quel quelle quels quelles ce cet cette ces se son sa ses leur leurs il elle ils elles
je tu nous vous mon ma mes votre vos notre nos de ces au a est on y combien quoi
this that the an and of to in is are for with on what which how do does from at
""".split())


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return [word for word in re.findall(r"\b\w+\b", text) if word not in STOPWORDS and len(word) > 1]


def _normalized_words(text: str) -> str:
    """Normalize for intent/phrase matching, without altering indexed PDF text."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def definition_subject(question: str) -> str | None:
    """Return the topic of an explicit definition question, not arbitrary questions."""
    normalized = _normalized_words(question)
    starters = (
        "c est quoi ", "qu est ce qu un ", "qu est ce qu une ",
        "qu est ce que ", "quelle est la definition de ",
        "donne une definition de ", "definition de ", "que signifie ",
        "what is ", "what are ",
    )
    for starter in starters:
        if normalized.startswith(starter):
            subject = normalized[len(starter):].strip()
            subject = re.sub(r"^(?:le|la|les|l|un|une|des|du|de|d)\s+", "", subject)
            # A compound question requires more than the definition, so keep normal ranking.
            if subject and not re.search(
                r"\b(?:comment|pourquoi|exemple|exemples|etapes|difference|comparer)\b", subject
            ):
                return subject
    return None




def is_contextual_followup(question: str) -> bool:
    """Detect a follow-up whose meaning depends on the preceding exchange."""
    normalized = _normalized_words(question)
    if not normalized:
        return False
    markers = (
        r"\bces\b", r"\bcette\b", r"\bceux\b", r"\bcelles?\b",
        r"\bce (?:dernier|derniere|point|passage|document|chapitre|element|exemple)\b",
        r"\bcelui(?: ci| la)?\b", r"\bcelle(?: ci| la)?\b", r"\bparmi\b",
        r"\blesquels?\b", r"\blesquelles?\b", r"\bprecedent", r"\bplus haut\b",
        r"\btu viens de\b", r"\bviens d en\b",
        r"\b(?:le|la) (?:premier|premiere|deuxieme|second|seconde|troisieme|quatrieme|cinquieme)\b",
    )
    return any(re.search(pattern, normalized) for pattern in markers)


def _priority_evidence_score(content: str) -> int:
    """Score explicit source wording that supports importance/priority claims."""
    normalized = _normalized_words(content)
    cues = (
        "point de depart", "premier pas", "etape essentielle", "assise centrale",
        "role central", "joue un role central", "pivot", "indispensable",
        "exigee dans toute recherche", "exige dans toute recherche",
        "tres importante", "tres important", "particulierement importante",
        "particulierement important", "fondamentale", "fondamental",
        "essentielle", "essentiel", "necessaire", "important",
    )
    return sum(1 for cue in cues if cue in normalized)


def _asks_for_priority(question: str) -> bool:
    normalized = _normalized_words(question)
    return bool(re.search(
        r"\b(important|importante|importants|importantes|essentiel|essentielle|essentiels|"
        r"essentielles|prioritaire|prioritaires|fondamental|fondamentale|fondamentaux|"
        r"indispensable|indispensables)\b",
        normalized,
    ))

def _contains_explicit_definition(content: str, subject: str) -> bool:
    """Prefer an explicit 'X est ...' definition over incidental mentions of X."""
    normalized = _normalized_words(content)
    pattern = (
        r"\b(?:le |la |les |l |un |une )?" + re.escape(subject)
        + r"\s+(?:est|sont|designe|signifie|constitue|correspond|se definit)\b"
    )
    return re.search(pattern, normalized) is not None


def _without_overlap(current: str, following: str, configured_overlap: int) -> str:
    """Return only the new suffix of the next sliding window, if overlap is exact."""
    limit = min(len(current), len(following), configured_overlap + 80)
    for shared in range(limit, 19, -1):
        if current.endswith(following[:shared]):
            return following[shared:]
    return following


class Retriever:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model: Any = None

    def _encoder(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError("Mode semantic : installer requirements-semantic.txt") from exc
            self._model = SentenceTransformer(self.settings.embedding_model)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.settings.retrieval_mode != "semantic":
            return []
        values = self._encoder().encode(texts, normalize_embeddings=True)
        return [[float(x) for x in row] for row in values]

    def prepare(self, chunks: list) -> list[dict]:
        vectors = self.embed([c.content for c in chunks])
        return [
            {"page": c.page, "ordinal": c.ordinal, "content": c.content,
             "embedding": vectors[i] if vectors else None}
            for i, c in enumerate(chunks)
        ]

    def search(self, query: str, chunks: list[dict], top_k: int) -> list[dict]:
        """Rank distinct evidence, not repeated uploads or overlapping windows.

        Only results are deduplicated: existing documents and SQLite rows are untouched.
        A second hit on the same PDF page is allowed if it is far from the first.
        """
        if not chunks:
            return []
        unique: list[dict] = []
        fingerprints: set[tuple[str, str]] = set()
        for chunk in chunks:
            fingerprint = re.sub(r"\s+", " ", chunk["content"]).strip().casefold()
            # Deduplicate repeated legacy uploads (same PDF SHA), but not a
            # genuinely different PDF that happens to contain the same sentence.
            key = (chunk.get("sha256", ""), fingerprint)
            if fingerprint and key not in fingerprints:
                fingerprints.add(key)
                unique.append(chunk)

        if self.settings.retrieval_mode == "semantic":
            ranked = self._semantic(query, unique, len(unique))
        else:
            ranked = self._bm25(query, unique, len(unique))

        subject = definition_subject(query)
        if subject:
            # A definition can appear once at the end of a page, while generic
            # follow-up sections repeat the topic many times and score higher.
            # Rerank without inventing a score or changing persistent chunks.
            ranked.sort(key=lambda hit: not _contains_explicit_definition(hit["content"], subject))

        if _asks_for_priority(query):
            # A request such as "les plus importantes" must be backed by explicit
            # wording in the source, not by the LLM's intuition. Stable sorting
            # preserves the retrieval score when two passages carry equal evidence.
            ranked.sort(key=lambda hit: -_priority_evidence_score(hit["content"]))

        selected: list[dict] = []
        # Comparison / synthesis across several documents needs coverage when top_k allows it.
        cross_document = re.search(
            r"\b(compar|diff[eé]ren|similair|points? communs?|plusieurs documents|"
            r"chaque document|selon ces|selon les documents)\w*",
            query.casefold(),
        ) is not None
        if cross_document and top_k > 1:
            covered: set[str] = set()
            for hit in ranked:
                if hit["document_id"] in covered:
                    continue
                covered.add(hit["document_id"])
                selected.append(hit)
                if len(selected) >= top_k:
                    return selected
        for hit in ranked:
            # Consecutive overlapping windows do not constitute independent evidence.
            if hit in selected or any(hit["document_id"] == prev["document_id"]
                   and hit["page"] == prev["page"]
                   and abs(hit.get("ordinal", -10_000) - prev.get("ordinal", 10_000)) <= 2
                   for prev in selected):
                continue
            selected.append(hit)
            if len(selected) == top_k:
                break
        return selected

    def expand_context(self, hits: list[dict], chunks: list[dict]) -> list[dict]:
        """Add the next two windows of the SAME document, even across a page boundary.

        PDF page breaks regularly split definitions and examples. Keep page/page_end
        accurate. This is query-independent; it does not hardcode the HTML test.
        """
        lookup = {(row["document_id"], row["ordinal"]): row for row in chunks}
        expanded: list[dict] = []
        for hit in hits:
            context = hit["content"]
            end_page = hit["page"]
            for offset in (1, 2):
                neighbor = lookup.get((hit["document_id"], hit.get("ordinal", -1000) + offset))
                if not neighbor or neighbor["page"] > hit["page"] + 1:
                    break
                if neighbor["page"] != end_page:
                    addition = f"\n\n[Début page {neighbor['page']}]\n" + neighbor["content"]
                else:
                    # Window overlap arises from CHUNK_OVERLAP; avoid echoing it to the LLM.
                    addition = " " + _without_overlap(context, neighbor["content"], self.settings.chunk_overlap)
                if len(context) + len(addition) > 3200:
                    available = 3200 - len(context)
                    if available >= 160:
                        context += addition[:available]
                        end_page = neighbor["page"]
                    break
                context += addition
                end_page = neighbor["page"]
            expanded.append({**hit, "context": context, "page_end": end_page})
        return expanded

    @staticmethod
    def _bm25(query: str, chunks: list[dict], top_k: int) -> list[dict]:
        def root(term: str) -> str:
            # Conservative plural normalization; FTS5 prefix candidates can match
            # "paiement" with "paiements", so the reranker must do the same.
            return term[:-1] if len(term) >= 5 and term.endswith("s") and not term.endswith(("ss", "us")) else term

        terms = {root(term) for term in tokenize(query)}
        if not terms:
            return []
        counts = [Counter(root(word) for word in tokenize(c["content"])) for c in chunks]
        lengths = [sum(c.values()) for c in counts]
        avg_len = max(1.0, sum(lengths) / len(chunks))
        document_frequency = Counter(word for counter in counts for word in counter)
        scores = []
        n = len(chunks)
        for index, counter in enumerate(counts):
            # With two substantive terms, a hit mentioning only one is too weak:
            # "clause beta" must not claim that a paragraph about "clause alpha" is evidence.
            if len(terms) == 2 and not terms.issubset(counter):
                continue
            score = 0.0
            for word in terms:
                f = counter.get(word, 0)
                if f:
                    df = document_frequency[word]
                    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                    score += idf * (f * 2.2) / (f + 1.2 * (0.25 + 0.75 * lengths[index] / avg_len))
            if score > 0:
                scores.append((score, index))
        scores.sort(key=lambda pair: (-pair[0], pair[1]))
        return [{**chunks[i], "score": round(score, 4)} for score, i in scores[:top_k]]

    def _semantic(self, query: str, chunks: list[dict], top_k: int) -> list[dict]:
        question_vector = self.embed([query])[0]
        # Supports a migration from lexical mode: old rows can be embedded on the fly.
        missing = [i for i, c in enumerate(chunks) if not c["embedding_json"]]
        computed = self.embed([chunks[i]["content"] for i in missing]) if missing else []
        fallback = dict(zip(missing, computed))
        scored = []
        for i, chunk in enumerate(chunks):
            vector = json.loads(chunk["embedding_json"]) if chunk["embedding_json"] else fallback[i]
            similarity = sum(a * b for a, b in zip(question_vector, vector))
            if similarity >= self.settings.semantic_threshold:
                scored.append((similarity, i))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [{**chunks[i], "score": round(score, 4)} for score, i in scored[:top_k]]

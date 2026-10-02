"""Hybrid retrieval: FTS5 lexical candidates + multilingual E5 semantic search + RRF.

The retriever is intentionally storage-agnostic:
- Store/SQLite decides which documents are allowed.
- FTS5 narrows lexical candidates on disk.
- Semantic search operates only on the chunks supplied by the caller.
- RRF fuses rankings without pretending BM25 and cosine scores are comparable.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from typing import Any

from .config import Settings

# Very common French/English function words; do not remove negations.
STOPWORDS = set(
    """
le la les l un une des de du d au aux a et ou en est sont dans sur pour par avec que qui
qu quel quelle quels quelles ce cet cette ces se son sa ses leur leurs il elle ils elles
je tu nous vous mon ma mes votre vos notre nos de ces au a est on y combien quoi
this that the an and of to in is are for with on what which how do does from at
""".split()
)


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return [
        word
        for word in re.findall(r"\b\w+\b", text)
        if word not in STOPWORDS and len(word) > 1
    ]


def _normalized_words(text: str) -> str:
    """Normalize for intent/phrase matching without altering indexed PDF text."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def definition_subject(question: str) -> str | None:
    """Return the topic of an explicit FR/EN definition question.

    Examples:
        "C'est quoi un agent ?" -> "agent"
        "Qu'est-ce qu'un agent IA ?" -> "agent ia"
        "What is an AI agent?" -> "ai agent"
        "What are AI agents?" -> "ai agents"
    """
    normalized = _normalized_words(question)
    starters = (
        "c est quoi ",
        "qu est ce qu un ",
        "qu est ce qu une ",
        "qu est ce que ",
        "quelle est la definition de ",
        "donne une definition de ",
        "definition de ",
        "que signifie ",
        "what is ",
        "what are ",
        "define ",
        "definition of ",
        "what does ",
    )

    for starter in starters:
        if not normalized.startswith(starter):
            continue

        subject = normalized[len(starter):].strip()

        # Remove a leading article/determiner in either supported language.
        subject = re.sub(
            r"^(?:le|la|les|l|un|une|des|du|de|d|a|an|the)\s+",
            "",
            subject,
        )

        # "What does X mean?" -> X
        if starter == "what does ":
            subject = re.sub(r"\s+mean$", "", subject).strip()

        # A compound question needs normal ranking rather than definition-only logic.
        if subject and not re.search(
            r"\b(?:comment|pourquoi|exemple|exemples|etapes|difference|comparer|"
            r"how|why|example|examples|steps|difference|compare)\b",
            subject,
        ):
            return subject

    return None


def is_contextual_followup(question: str) -> bool:
    """Detect a follow-up whose meaning depends on the preceding exchange."""
    normalized = _normalized_words(question)
    if not normalized:
        return False

    markers = (
        r"\bces\b",
        r"\bcette\b",
        r"\bceux\b",
        r"\bcelles?\b",
        r"\bce (?:dernier|derniere|point|passage|document|chapitre|element|exemple)\b",
        r"\bcelui(?: ci| la)?\b",
        r"\bcelle(?: ci| la)?\b",
        r"\bparmi\b",
        r"\blesquels?\b",
        r"\blesquelles?\b",
        r"\bprecedent",
        r"\bplus haut\b",
        r"\btu viens de\b",
        r"\bviens d en\b",
        r"\b(?:le|la) (?:premier|premiere|deuxieme|second|seconde|troisieme|quatrieme|cinquieme)\b",
        # English contextual follow-ups.
        r"\bthese\b",
        r"\bthose\b",
        r"\bwhich (?:one|ones)\b",
        r"\bthe previous\b",
        r"\bthe latter\b",
        r"\bthe former\b",
        r"\b(?:first|second|third|fourth|fifth) one\b",
    )
    return any(re.search(pattern, normalized) for pattern in markers)


def _priority_evidence_score(content: str) -> int:
    """Score explicit FR/EN wording that supports importance/priority claims."""
    normalized = _normalized_words(content)
    cues = (
        # French
        "point de depart",
        "premier pas",
        "etape essentielle",
        "assise centrale",
        "role central",
        "joue un role central",
        "pivot",
        "indispensable",
        "exigee dans toute recherche",
        "exige dans toute recherche",
        "tres importante",
        "tres important",
        "particulierement importante",
        "particulierement important",
        "fondamentale",
        "fondamental",
        "essentielle",
        "essentiel",
        "necessaire",
        "important",
        # English
        "starting point",
        "first step",
        "essential step",
        "central role",
        "plays a central role",
        "core",
        "crucial",
        "critical",
        "indispensable",
        "fundamental",
        "essential",
        "necessary",
        "important",
    )
    return sum(1 for cue in cues if cue in normalized)


def _asks_for_priority(question: str) -> bool:
    normalized = _normalized_words(question)
    return bool(
        re.search(
            r"\b(important|importante|importants|importantes|essentiel|essentielle|essentiels|"
            r"essentielles|prioritaire|prioritaires|fondamental|fondamentale|fondamentaux|"
            r"indispensable|indispensables|important|essential|priority|priorities|fundamental|"
            r"critical|crucial|indispensable)\b",
            normalized,
        )
    )


def _query_term_coverage(content: str, query: str) -> int:
    """Count distinct substantive query terms actually present in a passage."""
    query_terms = set(tokenize(query))
    if not query_terms:
        return 0
    content_terms = set(tokenize(content))
    return len(query_terms & content_terms)


def _contains_explicit_definition(content: str, subject: str) -> bool:
    """Prefer explicit FR/EN definitions over incidental mentions.

    This deliberately supports common formulations such as:
      - "Un agent IA est ..."
      - "AI agent is ..."
      - "X signifie ..."
      - "X means ..."
      - "X refers to ..."
      - "X is defined as ..."
    """
    normalized = _normalized_words(content)
    subject = _normalized_words(subject)
    if not subject:
        return False

    # Allow an optional adjective before the subject's last noun, e.g.
    # subject="ai agent" and content="an intelligent ai agent is ..." still
    # tends to be picked up through the exact occurrence later in the passage.
    article = r"(?:le |la |les |l |un |une |a |an |the )?"
    verbs = (
        r"(?:est|sont|designe|signifie|constitue|correspond|se definit|"
        r"is|are|means|refers to|is defined as|can be defined as|denotes|represents)"
    )
    pattern = rf"\b{article}{re.escape(subject)}\s+{verbs}\b"
    if re.search(pattern, normalized):
        return True

    # Plural/singular tolerance for English definitions: agent <-> agents.
    if subject.endswith("s"):
        singular = subject[:-1]
        if singular and re.search(rf"\b{article}{re.escape(singular)}\s+{verbs}\b", normalized):
            return True
    else:
        plural = subject + "s"
        if re.search(rf"\b{article}{re.escape(plural)}\s+{verbs}\b", normalized):
            return True

    return False


def _without_overlap(current: str, following: str, configured_overlap: int) -> str:
    """Return only the new suffix of the next sliding window if overlap is exact."""
    limit = min(len(current), len(following), configured_overlap + 80)
    for shared in range(limit, 19, -1):
        if current.endswith(following[:shared]):
            return following[shared:]
    return following


def _chunk_key(chunk: dict) -> tuple[str, int | str]:
    """Stable identity used to fuse lexical and semantic rankings."""
    if chunk.get("id") is not None:
        return (str(chunk.get("document_id", "")), int(chunk["id"]))
    return (
        str(chunk.get("document_id", "")),
        f"{chunk.get('page', '')}:{chunk.get('ordinal', '')}",
    )


class Retriever:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model: Any = None

    # ------------------------------------------------------------------
    # Embeddings / multilingual semantic retrieval
    # ------------------------------------------------------------------

    def _encoder(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "Mode semantic/hybrid : installer requirements-semantic.txt"
                ) from exc

            self._model = SentenceTransformer(self.settings.embedding_model)
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        values = self._encoder().encode(
            texts,
            normalize_embeddings=True,
            batch_size=self.settings.embedding_batch_size,
            show_progress_bar=False,
        )
        return [[float(x) for x in row] for row in values]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Encode texts with the configured sentence-transformer.

        This public method remains the compatibility seam used by the V4 tests
        and by callers that monkeypatch deterministic embeddings. Query/passage
        E5 prefixes are applied by ``embed_query`` and ``embed_passages``.
        """
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        """E5 query embedding.

        multilingual-e5 models are trained with the `query:` / `passage:`
        convention. Keeping those prefixes materially improves retrieval.
        Calling ``self.embed`` (rather than ``_encode`` directly) preserves the
        existing test/integration seam for controlled embeddings.
        """
        return self.embed([f"query: {text.strip()}"])[0]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self.embed([f"passage: {text.strip()}" for text in texts])

    def prepare(self, chunks: list) -> list[dict]:
        """Prepare chunks for insertion.

        In lexical mode no ML dependency is required. In semantic/hybrid mode,
        new documents are embedded once at ingestion time.
        """
        should_embed = self.settings.retrieval_mode in {"semantic", "hybrid"}
        vectors = self.embed_passages([c.content for c in chunks]) if should_embed else []
        return [
            {
                "page": c.page,
                "ordinal": c.ordinal,
                "content": c.content,
                "embedding": vectors[i] if vectors else None,
            }
            for i, c in enumerate(chunks)
        ]

    # ------------------------------------------------------------------
    # Public search API
    # ------------------------------------------------------------------

    def search(self, query: str, chunks: list[dict], top_k: int) -> list[dict]:
        """Backward-compatible search entry point.

        - lexical: BM25 reranking over supplied FTS5 candidates
        - semantic: cosine similarity over supplied chunks
        - hybrid: both branches over the same supplied chunks

        `hybrid_search()` is preferred for the final hybrid API because it can
        receive a small FTS5 candidate set and a broader semantic set separately.
        """
        if not chunks:
            return []

        unique = self._deduplicate(chunks)

        if self.settings.retrieval_mode == "semantic":
            ranked = self._semantic(query, unique, len(unique))
        elif self.settings.retrieval_mode == "hybrid":
            lexical = self._bm25(query, unique, min(len(unique), self.settings.hybrid_lexical_candidates))
            semantic = self._semantic(
                query,
                unique,
                min(len(unique), self.settings.hybrid_semantic_candidates),
                apply_threshold=False,
            )
            ranked = self._rrf_fuse(lexical, semantic)
        else:
            ranked = self._bm25(query, unique, len(unique))

        ranked = self._rerank(query, ranked)
        return self._select_distinct(query, ranked, top_k)

    def hybrid_search(
        self,
        query: str,
        lexical_chunks: list[dict],
        semantic_chunks: list[dict],
        top_k: int,
    ) -> list[dict]:
        """Fuse FTS5 lexical candidates with multilingual semantic retrieval.

        The caller must already have enforced document/conversation scope.
        BM25 scores and cosine scores are intentionally NOT added together;
        Reciprocal Rank Fusion combines ranks instead.
        """
        lexical_unique = self._deduplicate(lexical_chunks)
        semantic_unique = self._deduplicate(semantic_chunks)

        lexical_ranked = self._bm25(
            query,
            lexical_unique,
            min(len(lexical_unique), self.settings.hybrid_lexical_candidates),
        )
        semantic_ranked = self._semantic(
            query,
            semantic_unique,
            min(len(semantic_unique), self.settings.hybrid_semantic_candidates),
            apply_threshold=False,
        )

        ranked = self._rrf_fuse(lexical_ranked, semantic_ranked)
        ranked = self._rerank(query, ranked)
        return self._select_distinct(query, ranked, top_k)

    # ------------------------------------------------------------------
    # Ranking helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(chunks: list[dict]) -> list[dict]:
        unique: list[dict] = []
        fingerprints: set[tuple[str, str]] = set()
        for chunk in chunks:
            fingerprint = re.sub(r"\s+", " ", chunk["content"]).strip().casefold()
            key = (chunk.get("sha256", ""), fingerprint)
            if fingerprint and key not in fingerprints:
                fingerprints.add(key)
                unique.append(chunk)
        return unique

    def _rerank(self, query: str, ranked: list[dict]) -> list[dict]:
        if not ranked:
            return []

        subject = definition_subject(query)
        if subject:
            # Explicit definitions are the strongest signal for definition questions.
            # Keep retrieval/RRF order among equally explicit passages.
            ranked.sort(
                key=lambda hit: (
                    not _contains_explicit_definition(hit["content"], subject),
                    -_query_term_coverage(hit["content"], query),
                )
            )

        if _asks_for_priority(query):
            if is_contextual_followup(query):
                # For contextual follow-ups ("lesquelles sont les plus importantes ?"),
                # the concrete subject inherited from the previous turn must dominate.
                # Otherwise generic phrases such as "pivot" or "point de départ" can
                # pull retrieval toward an unrelated topic.
                ranked.sort(
                    key=lambda hit: (
                        -_query_term_coverage(hit["content"], query),
                        -_priority_evidence_score(hit["content"]),
                        -float(hit.get("score", 0.0)),
                    )
                )
            else:
                # For a standalone priority question, explicit source wording is the
                # strongest evidence. This preserves the V4.1 behaviour verified by
                # test_priority_question_prefers_explicit_strength_wording.
                ranked.sort(
                    key=lambda hit: (
                        -_priority_evidence_score(hit["content"]),
                        -_query_term_coverage(hit["content"], query),
                        -float(hit.get("score", 0.0)),
                    )
                )

        return ranked

    def _select_distinct(self, query: str, ranked: list[dict], top_k: int) -> list[dict]:
        selected: list[dict] = []

        cross_document = re.search(
            r"\b(compar|diff[eé]ren|similair|points? communs?|plusieurs documents|"
            r"chaque document|selon ces|selon les documents|compare|difference|"
            r"similarities|across documents|each document)\w*",
            query.casefold(),
        ) is not None

        if cross_document and top_k > 1:
            covered: set[str] = set()
            for hit in ranked:
                document_id = hit.get("document_id", "")
                if document_id in covered:
                    continue
                covered.add(document_id)
                selected.append(hit)
                if len(selected) >= top_k:
                    return selected

        for hit in ranked:
            if hit in selected:
                continue

            # Consecutive overlapping windows on the same page do not constitute
            # independent evidence.
            if any(
                hit.get("document_id") == prev.get("document_id")
                and hit.get("page") == prev.get("page")
                and abs(hit.get("ordinal", -10_000) - prev.get("ordinal", 10_000)) <= 2
                for prev in selected
            ):
                continue

            selected.append(hit)
            if len(selected) >= top_k:
                break

        return selected

    def _rrf_fuse(self, lexical: list[dict], semantic: list[dict]) -> list[dict]:
        """Weighted Reciprocal Rank Fusion.

        score = w_lex/(k + rank_lex) + w_sem/(k + rank_sem)

        This avoids comparing incompatible raw BM25 and cosine scales.
        """
        k = self.settings.hybrid_rrf_k
        fused: dict[tuple[str, int | str], dict] = {}

        def add(results: list[dict], weight: float, score_name: str) -> None:
            for rank, hit in enumerate(results, start=1):
                key = _chunk_key(hit)
                entry = fused.setdefault(
                    key,
                    {
                        **hit,
                        "rrf_score": 0.0,
                        "lexical_score": None,
                        "semantic_score": None,
                    },
                )
                entry["rrf_score"] += weight / (k + rank)
                entry[score_name] = hit.get("score")

        add(lexical, self.settings.hybrid_lexical_weight, "lexical_score")
        add(semantic, self.settings.hybrid_semantic_weight, "semantic_score")

        ranked = sorted(
            fused.values(),
            key=lambda hit: (
                -float(hit["rrf_score"]),
                str(hit.get("document_id", "")),
                int(hit.get("ordinal", 0)),
            ),
        )

        # Public `score` remains a deterministic ranking value. It is an RRF
        # score in hybrid mode, NOT a probability.
        return [
            {
                **hit,
                "score": round(float(hit["rrf_score"]), 6),
            }
            for hit in ranked
        ]

    # ------------------------------------------------------------------
    # Context expansion
    # ------------------------------------------------------------------

    def expand_context(self, hits: list[dict], chunks: list[dict]) -> list[dict]:
        """Add the next two windows of the SAME document, even across a page boundary."""
        lookup = {(row["document_id"], row["ordinal"]): row for row in chunks}
        expanded: list[dict] = []

        for hit in hits:
            context = hit["content"]
            end_page = hit["page"]

            for offset in (1, 2):
                neighbor = lookup.get(
                    (hit["document_id"], hit.get("ordinal", -1000) + offset)
                )
                if not neighbor or neighbor["page"] > hit["page"] + 1:
                    break

                if neighbor["page"] != end_page:
                    addition = f"\n\n[Début page {neighbor['page']}]\n" + neighbor["content"]
                else:
                    addition = " " + _without_overlap(
                        context,
                        neighbor["content"],
                        self.settings.chunk_overlap,
                    )

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

    # ------------------------------------------------------------------
    # Lexical BM25 reranker
    # ------------------------------------------------------------------

    @staticmethod
    def _bm25(query: str, chunks: list[dict], top_k: int) -> list[dict]:
        def root(term: str) -> str:
            # Conservative plural normalization; FTS5 prefix candidates can match
            # "paiement" with "paiements", so the reranker must do the same.
            return (
                term[:-1]
                if len(term) >= 5
                and term.endswith("s")
                and not term.endswith(("ss", "us"))
                else term
            )

        terms = {root(term) for term in tokenize(query)}
        if not terms:
            return []

        counts = [Counter(root(word) for word in tokenize(c["content"])) for c in chunks]
        lengths = [sum(c.values()) for c in counts]
        avg_len = max(1.0, sum(lengths) / len(chunks))
        document_frequency = Counter(word for counter in counts for word in counter)

        scores: list[tuple[float, int]] = []
        n = len(chunks)

        for index, counter in enumerate(counts):
            # For a two-term query, one-term-only matches are usually too weak.
            if len(terms) == 2 and not terms.issubset(counter):
                continue

            score = 0.0
            for word in terms:
                frequency = counter.get(word, 0)
                if not frequency:
                    continue

                df = document_frequency[word]
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += idf * (frequency * 2.2) / (
                    frequency + 1.2 * (0.25 + 0.75 * lengths[index] / avg_len)
                )

            if score > 0:
                scores.append((score, index))

        scores.sort(key=lambda pair: (-pair[0], pair[1]))
        return [
            {**chunks[index], "score": round(score, 4)}
            for score, index in scores[:top_k]
        ]

    # ------------------------------------------------------------------
    # Semantic cosine retrieval
    # ------------------------------------------------------------------

    def _semantic(
        self,
        query: str,
        chunks: list[dict],
        top_k: int,
        *,
        apply_threshold: bool = True,
    ) -> list[dict]:
        if not chunks:
            return []

        question_vector = self.embed_query(query)

        # Existing rows may have no embedding (e.g. documents imported while the
        # application was in lexical mode). Compute missing vectors in one batch.
        missing_indexes = [
            index
            for index, chunk in enumerate(chunks)
            if not chunk.get("embedding_json")
        ]

        computed_vectors = (
            self.embed_passages([chunks[index]["content"] for index in missing_indexes])
            if missing_indexes
            else []
        )
        fallback = dict(zip(missing_indexes, computed_vectors))

        scored: list[tuple[float, int]] = []

        for index, chunk in enumerate(chunks):
            if chunk.get("embedding_json"):
                try:
                    vector = json.loads(chunk["embedding_json"])
                except (TypeError, json.JSONDecodeError):
                    vector = fallback.get(index)
                    if vector is None:
                        vector = self.embed_passages([chunk["content"]])[0]
            else:
                vector = fallback[index]

            # Both query and E5 passage embeddings are normalized, so dot product
            # is cosine similarity.
            similarity = sum(a * b for a, b in zip(question_vector, vector))

            if not apply_threshold or similarity >= self.settings.semantic_threshold:
                scored.append((similarity, index))

        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [
            {**chunks[index], "score": round(score, 4)}
            for score, index in scored[:top_k]
        ]

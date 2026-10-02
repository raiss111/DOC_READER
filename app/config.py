"""Environment-based configuration. No credentials belong in source control."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    storage_dir: Path = Path("./data")
    app_api_key: str = ""

    # ---------------------------------------------------------
    # PDF ingestion
    # ---------------------------------------------------------
    max_pdf_bytes: int = 30 * 1024 * 1024
    max_pages: int = 1000
    chunk_size: int = 950
    chunk_overlap: int = 150

    # ---------------------------------------------------------
    # Retrieval
    # ---------------------------------------------------------

    # IMPORTANT:
    # Ne mets PAS encore RETRIEVAL_MODE=hybrid dans .env.
    # On l'activera seulement après migration de retrieval.py,
    # store.py et main.py.
    retrieval_mode: str = "lexical"  # lexical | semantic | hybrid

    # Modèle multilingue dédié au semantic retrieval.
    #
    # Il permettra notamment :
    #   cérémonies ≈ événements
    #   rôle ≈ fonction
    #   agent IA ≈ autonomous entity
    #
    # retrieval.py ajoutera automatiquement les préfixes
    # "query:" et "passage:" requis par E5.
    embedding_model: str = "intfloat/multilingual-e5-small"

    # Nombre de textes encodés simultanément.
    # 32 est raisonnable sur CPU et évite une consommation mémoire excessive.
    embedding_batch_size: int = 32

    # Seuil utilisé principalement en mode semantic pur.
    #
    # En mode hybrid, ce score ne sera PAS utilisé comme score final :
    # FTS5 et cosine similarity seront fusionnés avec RRF.
    semantic_threshold: float = 0.30

    # ---------------------------------------------------------
    # Hybrid retrieval
    # FTS5 lexical + multilingual semantic + RRF
    # ---------------------------------------------------------

    # Constante classique du Reciprocal Rank Fusion.
    hybrid_rrf_k: int = 60

    # Poids initiaux volontairement équilibrés.
    # On les ajustera uniquement si les tests de régression
    # montrent qu'un côté domine anormalement l'autre.
    hybrid_lexical_weight: float = 1.0
    hybrid_semantic_weight: float = 1.0

    # Nombre maximum de candidats fournis par chaque moteur
    # avant la fusion RRF.
    hybrid_lexical_candidates: int = 80
    hybrid_semantic_candidates: int = 80

    # ---------------------------------------------------------
    # LLM
    # ---------------------------------------------------------

    llm_mode: str = "extractive"  # extractive | openai_compatible
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen/qwen3.8-27b"
    llm_timeout_seconds: float = 25.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            storage_dir=Path(
                os.getenv("STORAGE_DIR", "./data")
            ).expanduser().resolve(),

            app_api_key=os.getenv("APP_API_KEY", ""),

            max_pdf_bytes=int(
                os.getenv(
                    "MAX_PDF_BYTES",
                    str(30 * 1024 * 1024),
                )
            ),

            max_pages=int(
                os.getenv("MAX_PAGES", "1000")
            ),

            chunk_size=int(
                os.getenv("CHUNK_SIZE", "950")
            ),

            chunk_overlap=int(
                os.getenv("CHUNK_OVERLAP", "150")
            ),

            retrieval_mode=os.getenv(
                "RETRIEVAL_MODE",
                "lexical",
            ).strip().lower(),

            embedding_model=os.getenv(
                "EMBEDDING_MODEL",
                "intfloat/multilingual-e5-small",
            ).strip(),

            embedding_batch_size=int(
                os.getenv(
                    "EMBEDDING_BATCH_SIZE",
                    "32",
                )
            ),

            semantic_threshold=float(
                os.getenv(
                    "SEMANTIC_THRESHOLD",
                    "0.30",
                )
            ),

            hybrid_rrf_k=int(
                os.getenv(
                    "HYBRID_RRF_K",
                    "60",
                )
            ),

            hybrid_lexical_weight=float(
                os.getenv(
                    "HYBRID_LEXICAL_WEIGHT",
                    "1.0",
                )
            ),

            hybrid_semantic_weight=float(
                os.getenv(
                    "HYBRID_SEMANTIC_WEIGHT",
                    "1.0",
                )
            ),

            hybrid_lexical_candidates=int(
                os.getenv(
                    "HYBRID_LEXICAL_CANDIDATES",
                    "80",
                )
            ),

            hybrid_semantic_candidates=int(
                os.getenv(
                    "HYBRID_SEMANTIC_CANDIDATES",
                    "80",
                )
            ),

            llm_mode=os.getenv(
                "LLM_MODE",
                "extractive",
            ).strip().lower(),

            llm_base_url=os.getenv(
                "LLM_BASE_URL",
                "https://api.groq.com/openai/v1",
            ).strip(),

            llm_api_key=os.getenv(
                "LLM_API_KEY",
                "",
            ),

            llm_model=os.getenv(
                "LLM_MODEL",
                "qwen/qwen3.8-27b",
            ).strip(),

            llm_timeout_seconds=float(
                os.getenv(
                    "LLM_TIMEOUT_SECONDS",
                    "25",
                )
            ),
        )

    def validate(self) -> None:
        if self.retrieval_mode not in {
            "lexical",
            "semantic",
            "hybrid",
        }:
            raise ValueError(
                "RETRIEVAL_MODE must be lexical, semantic or hybrid"
            )

        if self.llm_mode not in {
            "extractive",
            "openai_compatible",
        }:
            raise ValueError(
                "LLM_MODE must be extractive or openai_compatible"
            )

        if (
            not 200 <= self.chunk_size <= 5000
            or not 0 <= self.chunk_overlap < self.chunk_size
        ):
            raise ValueError(
                "Set 200 <= CHUNK_SIZE <= 5000 and "
                "0 <= CHUNK_OVERLAP < CHUNK_SIZE"
            )

        if (
            self.max_pdf_bytes < 1024
            or self.max_pages < 1
        ):
            raise ValueError(
                "Upload limits must be positive and reasonable"
            )

        if not self.embedding_model:
            raise ValueError(
                "EMBEDDING_MODEL must not be empty"
            )

        if not 1 <= self.embedding_batch_size <= 512:
            raise ValueError(
                "EMBEDDING_BATCH_SIZE must be between 1 and 512"
            )

        if not 0.0 <= self.semantic_threshold <= 1.0:
            raise ValueError(
                "SEMANTIC_THRESHOLD must be between 0 and 1"
            )

        if self.hybrid_rrf_k < 1:
            raise ValueError(
                "HYBRID_RRF_K must be >= 1"
            )

        if (
            self.hybrid_lexical_weight <= 0
            or self.hybrid_semantic_weight <= 0
        ):
            raise ValueError(
                "Hybrid retrieval weights must be > 0"
            )

        if not 1 <= self.hybrid_lexical_candidates <= 1000:
            raise ValueError(
                "HYBRID_LEXICAL_CANDIDATES must be between 1 and 1000"
            )

        if not 1 <= self.hybrid_semantic_candidates <= 1000:
            raise ValueError(
                "HYBRID_SEMANTIC_CANDIDATES must be between 1 and 1000"
            )

        if self.llm_timeout_seconds <= 0:
            raise ValueError(
                "LLM_TIMEOUT_SECONDS must be > 0"
            )

        if (
            self.llm_mode == "openai_compatible"
            and not self.llm_base_url.startswith(
                (
                    "https://",
                    "http://localhost:",
                    "http://127.0.0.1:",
                )
            )
        ):
            raise ValueError(
                "LLM_BASE_URL must use HTTPS, "
                "or localhost for a local model"
            )
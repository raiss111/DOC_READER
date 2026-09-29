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
    max_pdf_bytes: int = 10 * 1024 * 1024
    max_pages: int = 200
    chunk_size: int = 950
    chunk_overlap: int = 150
    retrieval_mode: str = "lexical"  # lexical (offline) or semantic (optional ML extra)
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    semantic_threshold: float = 0.38
    llm_mode: str = "extractive"  # extractive (offline) or openai_compatible
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"  # override with a currently supported model
    llm_timeout_seconds: float = 25.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            storage_dir=Path(os.getenv("STORAGE_DIR", "./data")).expanduser().resolve(),
            app_api_key=os.getenv("APP_API_KEY", ""),
            max_pdf_bytes=int(os.getenv("MAX_PDF_BYTES", str(10 * 1024 * 1024))),
            max_pages=int(os.getenv("MAX_PAGES", "200")),
            chunk_size=int(os.getenv("CHUNK_SIZE", "950")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "150")),
            retrieval_mode=os.getenv("RETRIEVAL_MODE", "lexical").strip().lower(),
            embedding_model=os.getenv("EMBEDDING_MODEL", cls.embedding_model),
            semantic_threshold=float(os.getenv("SEMANTIC_THRESHOLD", "0.38")),
            llm_mode=os.getenv("LLM_MODE", "extractive").strip().lower(),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "25")),
        )

    def validate(self) -> None:
        if self.retrieval_mode not in {"lexical", "semantic"}:
            raise ValueError("RETRIEVAL_MODE must be lexical or semantic")
        if self.llm_mode not in {"extractive", "openai_compatible"}:
            raise ValueError("LLM_MODE must be extractive or openai_compatible")
        if not 200 <= self.chunk_size <= 5000 or not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("Set 200 <= CHUNK_SIZE <= 5000 and 0 <= CHUNK_OVERLAP < CHUNK_SIZE")
        if self.max_pdf_bytes < 1024 or self.max_pages < 1:
            raise ValueError("Upload limits must be positive and reasonable")
        if not 0 <= self.semantic_threshold <= 1:
            raise ValueError("SEMANTIC_THRESHOLD must be between 0 and 1")
        if self.llm_mode == "openai_compatible" and not self.llm_base_url.startswith(("https://", "http://localhost:", "http://127.0.0.1:")):
            raise ValueError("LLM_BASE_URL must use HTTPS, or localhost for a local model")

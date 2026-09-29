"""SQLite is the source of truth; binary files have opaque, versioned names."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class NotFound(Exception):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 30000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    sha256 TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    page INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding_json TEXT
                );
                CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id, ordinal);
            """)

    @staticmethod
    def public(row: sqlite3.Row | dict) -> dict:
        return {key: row[key] for key in (
            "id", "filename", "sha256", "page_count", "chunk_count", "version", "uploaded_at"
        )}

    @staticmethod
    def insert_chunks(db: sqlite3.Connection, document_id: str, chunks: list[dict]) -> None:
        db.executemany(
            "INSERT INTO chunks(document_id, page, ordinal, content, embedding_json) VALUES (?,?,?,?,?)",
            [(document_id, c["page"], c["ordinal"], c["content"],
              json.dumps(c["embedding"]) if c.get("embedding") is not None else None) for c in chunks],
        )

    def create(self, record: dict, chunks: list[dict]) -> dict:
        with self.connect() as db:
            db.execute(
                "INSERT INTO documents(id,filename,file_path,sha256,page_count,chunk_count) VALUES(?,?,?,?,?,?)",
                (record["id"], record["filename"], str(record["file_path"]), record["sha256"],
                 record["page_count"], len(chunks)),
            )
            self.insert_chunks(db, record["id"], chunks)
        return self.get(record["id"])

    def get(self, document_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            return dict(row) if row else None

    def list(self, limit: int, offset: int) -> tuple[int, list[dict]]:
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            rows = db.execute(
                "SELECT * FROM documents ORDER BY uploaded_at DESC, id DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            return total, [self.public(row) for row in rows]

    def replace(self, document_id: str, record: dict, chunks: list[dict]) -> Path:
        """Atomic DB switch to new file. Caller has already safely staged the new PDF."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT file_path FROM documents WHERE id = ?", (document_id,)).fetchone()
            if not old:
                raise NotFound()
            db.execute(
                "UPDATE documents SET filename=?, file_path=?, sha256=?, page_count=?, "
                "chunk_count=?, version=version+1, uploaded_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (record["filename"], str(record["file_path"]), record["sha256"], record["page_count"],
                 len(chunks), document_id),
            )
            db.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            self.insert_chunks(db, document_id, chunks)
            return Path(old["file_path"])

    def delete(self, document_id: str) -> Path:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT file_path FROM documents WHERE id = ?", (document_id,)).fetchone()
            if not row:
                raise NotFound()
            db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            return Path(row["file_path"])

    def all_chunks(self, document_ids: list[str] | None = None) -> list[dict]:
        query = (
            "SELECT c.id,c.document_id,c.page,c.ordinal,c.content,c.embedding_json,d.filename "
            "FROM chunks c JOIN documents d ON d.id=c.document_id"
        )
        params: list[str] = []
        if document_ids is not None:
            if not document_ids:
                return []
            query += " WHERE c.document_id IN (" + ",".join("?" for _ in document_ids) + ")"
            params = document_ids
        query += " ORDER BY c.document_id, c.ordinal"
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

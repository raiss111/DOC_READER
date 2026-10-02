"""SQLite source of truth, transactional document lifecycle and FTS5 indexing.

Schema v4 upgrades existing V1/V2/V3 databases in place; pre-upgrade DB is backed up.
V4.2 adds a model-aware embedding cache in a separate table without altering
existing document, chunk, conversation or message data.
Existing duplicate documents are *not* silently removed, but new duplicates are forbidden.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class NotFound(Exception):
    pass


class DuplicateDocument(Exception):
    def __init__(self, existing_document_id: str):
        self.existing_document_id = existing_document_id
        super().__init__(f"Document déjà présent : {existing_document_id}")


class MissingDocuments(Exception):
    def __init__(self, ids: list[str]):
        self.ids = ids
        super().__init__(f"Documents introuvables : {ids}")


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # sqlite3.backup handles an existing WAL database properly, unlike copying only .sqlite3.
        if self.path.is_file():
            with sqlite3.connect(self.path) as original:
                version = original.execute("PRAGMA user_version").fetchone()[0]
                if version < 4:
                    backup_path = self.path.with_name(self.path.name + ".pre_v4_backup.sqlite3")
                    if not backup_path.exists():
                        with sqlite3.connect(backup_path) as backup:
                            original.backup(backup)
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
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 4:
                raise RuntimeError(f"Base SQLite plus récente que l'application (version {version}).")
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
                CREATE INDEX IF NOT EXISTS documents_sha256_idx ON documents(sha256);
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    page INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding_json TEXT
                );
                CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id, ordinal);
                CREATE TABLE IF NOT EXISTS chunk_embeddings (
                    chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    PRIMARY KEY(chunk_id, model)
                );
                CREATE INDEX IF NOT EXISTS chunk_embeddings_model_idx
                    ON chunk_embeddings(model, chunk_id);
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS conversation_documents (
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    PRIMARY KEY(conversation_id, document_id)
                );
                CREATE INDEX IF NOT EXISTS conversation_documents_document_idx
                    ON conversation_documents(document_id);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    response_mode TEXT,
                    sources_json TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS messages_conversation_idx ON messages(conversation_id, id);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    content, content='chunks', content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                );
                CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_fts_update AFTER UPDATE OF content ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
                END;
            """)
            if version < 4:
                # Backfill all existing V1-V3 chunks; do not touch PDF files or their IDs.
                db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
                db.execute("PRAGMA user_version = 4")

    @staticmethod
    def public(row: sqlite3.Row | dict) -> dict:
        return {key: row[key] for key in (
            "id", "filename", "sha256", "page_count", "chunk_count", "version", "uploaded_at"
        )}

    @staticmethod
    def insert_chunks(
        db: sqlite3.Connection,
        document_id: str,
        chunks: list[dict],
        *,
        embedding_model: str | None = None,
    ) -> None:
        """Insert chunks and optionally persist model-aware embeddings.

        ``chunks.embedding_json`` is retained as a backward-compatible mirror for
        the existing V4 semantic path. V4.2's hybrid path uses ``chunk_embeddings``
        so vectors produced by different models are never silently mixed.
        """
        db.executemany(
            "INSERT INTO chunks(document_id, page, ordinal, content, embedding_json) VALUES (?,?,?,?,?)",
            [(document_id, c["page"], c["ordinal"], c["content"],
              json.dumps(c["embedding"]) if c.get("embedding") is not None else None) for c in chunks],
        )

        if embedding_model:
            vectors_by_ordinal = {
                c["ordinal"]: c["embedding"]
                for c in chunks
                if c.get("embedding") is not None
            }
            if vectors_by_ordinal:
                rows = db.execute(
                    "SELECT id,ordinal FROM chunks WHERE document_id=?",
                    (document_id,),
                ).fetchall()
                payload = [
                    (row["id"], embedding_model, json.dumps(vectors_by_ordinal[row["ordinal"]]))
                    for row in rows
                    if row["ordinal"] in vectors_by_ordinal
                ]
                if payload:
                    db.executemany(
                        "INSERT INTO chunk_embeddings(chunk_id,model,embedding_json) VALUES(?,?,?) "
                        "ON CONFLICT(chunk_id,model) DO UPDATE SET "
                        "embedding_json=excluded.embedding_json, "
                        "created_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                        payload,
                    )

        # FTS5 is updated atomically by database triggers.

    @staticmethod
    def _existing_hash(db: sqlite3.Connection, sha256: str, excluded_id: str | None = None) -> str | None:
        if excluded_id is None:
            row = db.execute("SELECT id FROM documents WHERE sha256=? ORDER BY uploaded_at,id LIMIT 1",
                             (sha256,)).fetchone()
        else:
            row = db.execute("SELECT id FROM documents WHERE sha256=? AND id<>? "
                             "ORDER BY uploaded_at,id LIMIT 1", (sha256, excluded_id)).fetchone()
        return row["id"] if row else None

    def find_by_sha(self, sha256: str, excluded_id: str | None = None) -> str | None:
        with self.connect() as db:
            return self._existing_hash(db, sha256, excluded_id)

    def create(
        self, record: dict, chunks: list[dict], *, embedding_model: str | None = None
    ) -> dict:
        with self.connect() as db:
            # Writer lock + check prevents two concurrent API imports of the same SHA.
            db.execute("BEGIN IMMEDIATE")
            existing = self._existing_hash(db, record["sha256"])
            if existing:
                raise DuplicateDocument(existing)
            db.execute(
                "INSERT INTO documents(id,filename,file_path,sha256,page_count,chunk_count) VALUES(?,?,?,?,?,?)",
                (record["id"], record["filename"], str(record["file_path"]), record["sha256"],
                 record["page_count"], len(chunks)),
            )
            self.insert_chunks(db, record["id"], chunks, embedding_model=embedding_model)
        return self.get(record["id"])

    def get(self, document_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            return dict(row) if row else None

    def list(self, limit: int, offset: int) -> tuple[int, list[dict]]:
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            rows = db.execute(
                "SELECT * FROM documents ORDER BY uploaded_at DESC, id DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            return total, [self.public(row) for row in rows]

    def replace(
        self, document_id: str, record: dict, chunks: list[dict], *,
        embedding_model: str | None = None,
    ) -> Path:
        """Atomic DB switch to staged PDF + atomic FTS update; old file deleted by caller."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT file_path FROM documents WHERE id=?", (document_id,)).fetchone()
            if not old:
                raise NotFound()
            existing = self._existing_hash(db, record["sha256"], document_id)
            if existing:
                raise DuplicateDocument(existing)
            db.execute(
                "UPDATE documents SET filename=?, file_path=?, sha256=?, page_count=?, "
                "chunk_count=?, version=version+1, uploaded_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (record["filename"], str(record["file_path"]), record["sha256"], record["page_count"],
                 len(chunks), document_id),
            )
            db.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
            self.insert_chunks(db, document_id, chunks, embedding_model=embedding_model)
            return Path(old["file_path"])

    def delete(self, document_id: str) -> Path:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT file_path FROM documents WHERE id=?", (document_id,)).fetchone()
            if not row:
                raise NotFound()
            db.execute("DELETE FROM documents WHERE id=?", (document_id,))
            # Foreign keys delete conversation-document bindings; FTS triggers remove chunks.
            return Path(row["file_path"])

    @staticmethod
    def _chunk_query_where(document_ids: list[str] | None) -> tuple[str, list[str]]:
        if document_ids is None:
            return "", []
        if not document_ids:
            return " AND 0", []
        return " AND c.document_id IN (" + ",".join("?" for _ in document_ids) + ")", document_ids

    def search_candidates(self, question: str, document_ids: list[str] | None, limit: int = 300) -> list[dict]:
        """FTS5 narrows lexical candidates on-disk; only those rows are reranked in Python."""
        # Local import avoids module-level circular dependency (retrieval imports Settings).
        from .retrieval import tokenize
        import re
        terms = list(dict.fromkeys(t for t in tokenize(question) if re.fullmatch(r"[a-z0-9_]+", t)))[:24]
        if not terms or document_ids == []:
            return []
        match = " OR ".join('"' + term + '"*' for term in terms)
        clause, params = self._chunk_query_where(document_ids)
        with self.connect() as db:
            rows = db.execute(
                "SELECT c.id,c.document_id,c.page,c.ordinal,c.content,c.embedding_json,d.filename,d.sha256, "
                "bm25(chunks_fts) AS fts_score FROM chunks_fts "
                "JOIN chunks c ON c.id=chunks_fts.rowid "
                "JOIN documents d ON d.id=c.document_id "
                "WHERE chunks_fts MATCH ?" + clause + " ORDER BY bm25(chunks_fts) LIMIT ?",
                [match, *params, limit],
            ).fetchall()
            return [dict(row) for row in rows]

    def neighboring_chunks(self, hits: list[dict], forward: int = 2) -> list[dict]:
        """Fetch a few same-document next windows for selected hits; never load whole corpus."""
        if not hits:
            return []
        seen: set[tuple[str, int]] = set()
        conditions: list[str] = []
        args: list[str | int] = []
        for hit in hits:
            key = (hit["document_id"], hit["ordinal"])
            if key in seen:
                continue
            seen.add(key)
            conditions.append("(c.document_id=? AND c.ordinal BETWEEN ? AND ?)")
            args.extend([*key, hit["ordinal"] + forward])
        with self.connect() as db:
            rows = db.execute(
                "SELECT c.id,c.document_id,c.page,c.ordinal,c.content,c.embedding_json,d.filename,d.sha256 "
                "FROM chunks c JOIN documents d ON d.id=c.document_id WHERE " + " OR ".join(conditions),
                args,
            ).fetchall()
            return [dict(row) for row in rows]

    def all_chunks(self, document_ids: list[str] | None = None) -> list[dict]:
        """Legacy exhaustive path retained for optional exact semantic search only."""
        query = (
            "SELECT c.id,c.document_id,c.page,c.ordinal,c.content,c.embedding_json,d.filename,d.sha256 "
            "FROM chunks c JOIN documents d ON d.id=c.document_id"
        )
        params: list[str] = []
        if document_ids is not None:
            if not document_ids:
                return []
            query += " WHERE c.document_id IN (" + ",".join("?" for _ in document_ids) + ")"
            params = document_ids
        query += " ORDER BY c.document_id,c.ordinal"
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def semantic_chunks(
        self,
        document_ids: list[str] | None,
        embedding_model: str,
    ) -> list[dict]:
        """Return scoped chunks with embeddings only from the requested model.

        Old/unknown vectors are intentionally exposed as ``None`` so the caller
        can recompute them with the current multilingual model. This prevents
        mixing vector spaces when EMBEDDING_MODEL changes.
        """
        if document_ids == []:
            return []

        clause, params = self._chunk_query_where(document_ids)
        with self.connect() as db:
            rows = db.execute(
                "SELECT c.id,c.document_id,c.page,c.ordinal,c.content,ce.embedding_json,"
                "d.filename,d.sha256 FROM chunks c "
                "JOIN documents d ON d.id=c.document_id "
                "LEFT JOIN chunk_embeddings ce ON ce.chunk_id=c.id AND ce.model=? "
                "WHERE 1=1" + clause + " ORDER BY c.document_id,c.ordinal",
                [embedding_model, *params],
            ).fetchall()
            return [dict(row) for row in rows]

    def save_embeddings(
        self,
        embeddings: list[tuple[int, list[float]]],
        embedding_model: str,
    ) -> None:
        """Persist computed embeddings transactionally for later hybrid queries.

        Embeddings are derived/cache data. Source PDF text remains in ``chunks``.
        Re-running this method for the same chunk/model is idempotent.
        """
        if not embeddings:
            return
        if not embedding_model:
            raise ValueError("embedding_model must not be empty")

        payload = [
            (chunk_id, embedding_model, json.dumps(vector))
            for chunk_id, vector in embeddings
        ]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "INSERT INTO chunk_embeddings(chunk_id,model,embedding_json) VALUES(?,?,?) "
                "ON CONFLICT(chunk_id,model) DO UPDATE SET "
                "embedding_json=excluded.embedding_json, "
                "created_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                payload,
            )

    def embedding_status(
        self,
        document_ids: list[str] | None,
        embedding_model: str,
    ) -> dict:
        """Return cache coverage for diagnostics without exposing vector data."""
        if document_ids == []:
            return {"total": 0, "ready": 0, "missing": 0, "model": embedding_model}

        clause, params = self._chunk_query_where(document_ids)
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS total, COUNT(ce.chunk_id) AS ready "
                "FROM chunks c LEFT JOIN chunk_embeddings ce "
                "ON ce.chunk_id=c.id AND ce.model=? WHERE 1=1" + clause,
                [embedding_model, *params],
            ).fetchone()
            total = int(row["total"])
            ready = int(row["ready"])
            return {
                "total": total,
                "ready": ready,
                "missing": total - ready,
                "model": embedding_model,
            }

    def missing_document_ids(self, ids: list[str]) -> list[str]:
        if not ids:
            return []
        with self.connect() as db:
            placeholders = ",".join("?" for _ in ids)
            found = {r[0] for r in db.execute(
                f"SELECT id FROM documents WHERE id IN ({placeholders})", ids)}
            return [id_ for id_ in ids if id_ not in found]

    @staticmethod
    def _conversation(db: sqlite3.Connection, conversation_id: str) -> dict | None:
        row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not row:
            return None
        ids = [r[0] for r in db.execute("SELECT document_id FROM conversation_documents "
                                        "WHERE conversation_id=? ORDER BY rowid", (conversation_id,))]
        count = db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?", (conversation_id,)).fetchone()[0]
        return {**dict(row), "document_ids": ids, "message_count": count}

    @staticmethod
    def _verify_document_ids(db: sqlite3.Connection, ids: list[str]) -> None:
        if not ids:
            return
        found = {r[0] for r in db.execute(
            "SELECT id FROM documents WHERE id IN (" + ",".join("?" for _ in ids) + ")", ids)}
        missing = [id_ for id_ in ids if id_ not in found]
        if missing:
            raise MissingDocuments(missing)

    def create_conversation(self, conversation_id: str, title: str, document_ids: list[str]) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._verify_document_ids(db, document_ids)
            db.execute("INSERT INTO conversations(id,title) VALUES(?,?)", (conversation_id, title))
            db.executemany("INSERT INTO conversation_documents(conversation_id,document_id) VALUES(?,?)",
                           [(conversation_id, id_) for id_ in document_ids])
            result = self._conversation(db, conversation_id)
            assert result is not None
            return result

    def get_conversation(self, conversation_id: str) -> dict | None:
        with self.connect() as db:
            return self._conversation(db, conversation_id)

    def list_conversations(self, limit: int, offset: int) -> tuple[int, list[dict]]:
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            ids = [r[0] for r in db.execute(
                "SELECT id FROM conversations ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
                (limit, offset))]
            return total, [self._conversation(db, conv_id) for conv_id in ids]

    def set_conversation_documents(self, conversation_id: str, document_ids: list[str]) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone():
                raise NotFound()
            self._verify_document_ids(db, document_ids)
            db.execute("DELETE FROM conversation_documents WHERE conversation_id=?", (conversation_id,))
            db.executemany("INSERT INTO conversation_documents(conversation_id,document_id) VALUES(?,?)",
                           [(conversation_id, id_) for id_ in document_ids])
            db.execute("UPDATE conversations SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                       (conversation_id,))
            result = self._conversation(db, conversation_id)
            assert result is not None
            return result

    def rename_conversation(self, conversation_id: str, title: str) -> dict:
        with self.connect() as db:
            cursor = db.execute("UPDATE conversations SET title=?, "
                                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                                (title, conversation_id))
            if cursor.rowcount != 1:
                raise NotFound()
            result = self._conversation(db, conversation_id)
            assert result is not None
            return result

    def delete_conversation(self, conversation_id: str) -> None:
        with self.connect() as db:
            if db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,)).rowcount != 1:
                raise NotFound()

    @staticmethod
    def _message(row: sqlite3.Row) -> dict:
        return {**dict(row), "sources": json.loads(row["sources_json"] or "[]")}

    def message_history(self, conversation_id: str, limit: int = 8) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
                              (conversation_id, limit)).fetchall()
            return [self._message(r) for r in reversed(rows)]

    def list_messages(self, conversation_id: str, limit: int, offset: int) -> tuple[int, list[dict]]:
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone():
                raise NotFound()
            total = db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?",
                               (conversation_id,)).fetchone()[0]
            rows = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id LIMIT ? OFFSET ?",
                              (conversation_id, limit, offset)).fetchall()
            return total, [self._message(r) for r in rows]

    def append_exchange(self, conversation_id: str, question: str, result: dict) -> None:
        """Save user + assistant as one transaction; no half exchanges."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone():
                raise NotFound()
            db.execute("INSERT INTO messages(conversation_id,role,content) VALUES(?,'user',?)",
                       (conversation_id, question))
            db.execute("INSERT INTO messages(conversation_id,role,content,response_mode,sources_json) "
                       "VALUES(?,'assistant',?,?,?)",
                       (conversation_id, result["answer"], result["response_mode"],
                        json.dumps([{k: v for k, v in source.items() if k != "excerpt"}
                                    for source in result["sources"]], ensure_ascii=False)))
            db.execute("UPDATE conversations SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                       (conversation_id,))

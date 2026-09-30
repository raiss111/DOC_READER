"""Rebuild FTS5 after an index incident; never modify PDF binaries or document rows."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.store import Store

store = Store(Settings.from_env().storage_dir / "metadata.sqlite3")
with store.connect() as db:
    db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('integrity-check')")
    documents = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
print(f"Index FTS5 reconstruit et vérifié. Documents : {documents} ; passages : {chunks}.")

"""Report unreferenced/missing PDF binaries without deleting any data. Run while server is stopped."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
root = Path(os.getenv("STORAGE_DIR", "./data")).resolve()
db_path = root / "metadata.sqlite3"
if not db_path.exists():
    raise SystemExit(f"No database at {db_path}")
with sqlite3.connect(db_path) as db:
    referenced = {Path(row[0]).resolve() for row in db.execute("SELECT file_path FROM documents")}
actual = {p.resolve() for p in (root / "files").glob("*.pdf")}
print(f"Documents indexed: {len(referenced)}")
print(f"PDF files: {len(actual)}")
for path in sorted(actual - referenced):
    print("ORPHAN (review before manual deletion):", path)
for path in sorted(referenced - actual):
    print("MISSING referenced file:", path)
for path in sorted((root / "files").glob("*.part")):
    print("STALE POSSIBLE .part (review):", path)
print("Audit finished, no changes made.")

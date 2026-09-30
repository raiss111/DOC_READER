"""Create a consistent offline storage backup without printing/exporting API secrets.

Run with Uvicorn stopped, from the project's root, before installing a new version:
    python scripts/backup_storage.py --destination ../BACKUP_DOC_READER_BEFORE_V4
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv()
parser = argparse.ArgumentParser(description="Backup SQLite and PDF binaries (server must be stopped).")
parser.add_argument("--destination", type=Path, required=True)
args = parser.parse_args()
root = Path(os.getenv("STORAGE_DIR", "./data")).expanduser().resolve()
destination = args.destination.expanduser().resolve()
if not root.is_dir() or not (root / "metadata.sqlite3").is_file():
    raise SystemExit(f"Base de données introuvable dans {root}")
if destination == root or root in destination.parents:
    raise SystemExit("Choisir un dossier de sauvegarde EN DEHORS de STORAGE_DIR.")
if destination.exists():
    raise SystemExit("Le dossier de sauvegarde existe déjà : choisir un autre nom pour éviter tout écrasement.")
# Parent mkdir + exclusive new destination; no destructive operations on source.
destination.mkdir(parents=True)
with sqlite3.connect(root / "metadata.sqlite3") as source:
    with sqlite3.connect(destination / "metadata.sqlite3") as backup:
        source.backup(backup)
if (root / "files").is_dir():
    shutil.copytree(root / "files", destination / "files")
print("Sauvegarde SQLite + PDF créée dans :", destination)
print("Le fichier .env (avec votre clé) n'a PAS été inclus. Conservez-le séparément et en sécurité.")

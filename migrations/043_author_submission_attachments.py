"""Add a private attachment ledger to a disposable database."""
import sqlite3
import tempfile
from pathlib import Path

MIGRATION_ID = "043_author_submission_attachments"


def migrate(path):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError("Only a disposable temporary database may be migrated")
    with sqlite3.connect(path.as_uri() + "?mode=rw", uri=True) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id=?", ("042_author_submission_linkage",)).fetchone():
            raise RuntimeError("Linkage migration required")
        db.execute("""CREATE TABLE IF NOT EXISTS author_submission_attachments (
            id TEXT PRIMARY KEY,
            draft_id TEXT NOT NULL REFERENCES author_submission_drafts(id),
            kind TEXT NOT NULL CHECK(kind IN ('cover_letter', 'supplementary')),
            filename TEXT NOT NULL,
            media_type TEXT NOT NULL,
            size INTEGER NOT NULL CHECK(size > 0),
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL,
            supersedes TEXT REFERENCES author_submission_attachments(id),
            removed_at TEXT
        )""")
        expected = {"id", "draft_id", "kind", "filename", "media_type", "size", "sha256", "created_at", "supersedes", "removed_at"}
        table_info = list(db.execute("PRAGMA table_info(author_submission_attachments)"))
        columns = {row[1] for row in table_info}
        keys = list(db.execute("PRAGMA foreign_key_list(author_submission_attachments)"))
        if columns != expected or not any(row[1] == "id" and row[5] == 1 for row in table_info) or not any(row[2:5] == ("author_submission_drafts", "draft_id", "id") for row in keys) or not any(row[2:5] == ("author_submission_attachments", "supersedes", "id") for row in keys):
            raise RuntimeError("Conflicting author submission attachment schema")
        db.execute("INSERT OR IGNORE INTO schema_migrations VALUES (?, datetime('now'))", (MIGRATION_ID,))
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key violation")
        db.commit()

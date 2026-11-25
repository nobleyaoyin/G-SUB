"""Isolated-only additive rehearsal for private, pre-manuscript drafts."""
from pathlib import Path
import sqlite3
import tempfile

MIGRATION_ID = "041_author_submission_drafts"


def migrate(path):
    path = Path(path).resolve(strict=True)
    # This migration is not authorized to alter persistent project databases.
    if not path.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError("Only a disposable temporary database may be migrated")
    with sqlite3.connect(path.as_uri() + "?mode=rw", uri=True) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS author_submission_drafts (
            id TEXT PRIMARY KEY,
            author_id INTEGER NOT NULL REFERENCES users(user_id),
            request_id TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
            current_step INTEGER NOT NULL DEFAULT 1 CHECK (current_step BETWEEN 1 AND 10),
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(author_id, request_id)
        )""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(author_submission_drafts)")}
        expected = {"id", "author_id", "request_id", "revision", "current_step", "payload", "created_at", "updated_at"}
        foreign_keys = list(db.execute("PRAGMA foreign_key_list(author_submission_drafts)"))
        indexes = list(db.execute("PRAGMA index_list(author_submission_drafts)"))
        unique_columns = [tuple(row[2] for row in db.execute(f'PRAGMA index_info("{index[1]}")')) for index in indexes if index[2]]
        if columns != expected or not any(row[2:5] == ("users", "author_id", "user_id") for row in foreign_keys) or ("author_id", "request_id") not in unique_columns:
            raise RuntimeError("Conflicting author submission draft schema")
        db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (migration_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO schema_migrations VALUES (?, datetime('now'))", (MIGRATION_ID,))
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key violation")
        db.commit()

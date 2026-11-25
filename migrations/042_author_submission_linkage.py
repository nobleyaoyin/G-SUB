"""Rehearse additive draft/manuscript links on disposable databases only."""
import sqlite3
import tempfile
from pathlib import Path

MIGRATION_ID = "042_author_submission_linkage"


def migrate(path):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError("Only a disposable temporary database may be migrated")
    with sqlite3.connect(path.as_uri() + "?mode=rw", uri=True) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id=?", ("041_author_submission_drafts",)).fetchone():
            raise RuntimeError("Draft migration required")
        db.execute("""CREATE TABLE IF NOT EXISTS author_submission_links (
            draft_id TEXT PRIMARY KEY REFERENCES author_submission_drafts(id),
            manuscript_id INTEGER NOT NULL UNIQUE REFERENCES manuscripts(manuscript_id),
            created_at TEXT NOT NULL
        )""")
        table_info = list(db.execute("PRAGMA table_info(author_submission_links)"))
        columns = {row[1] for row in table_info}
        keys = list(db.execute("PRAGMA foreign_key_list(author_submission_links)"))
        indexes = list(db.execute("PRAGMA index_list(author_submission_links)"))
        unique_columns = [tuple(row[2] for row in db.execute(f'PRAGMA index_info("{index[1]}")')) for index in indexes if index[2]]
        if columns != {"draft_id", "manuscript_id", "created_at"} or not any(row[1] == "draft_id" and row[5] == 1 for row in table_info) or not any(row[2:5] == ("author_submission_drafts", "draft_id", "id") for row in keys) or not any(row[2:5] == ("manuscripts", "manuscript_id", "manuscript_id") for row in keys) or ("manuscript_id",) not in unique_columns:
            raise RuntimeError("Conflicting author submission linkage schema")
        db.execute("INSERT OR IGNORE INTO schema_migrations VALUES (?, datetime('now'))", (MIGRATION_ID,))
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key violation")
        db.commit()

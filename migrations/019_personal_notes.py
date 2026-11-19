"""Add private, manuscript-scoped personal notes."""

import argparse
import sqlite3
from pathlib import Path

MIGRATION_ID = "019_personal_notes"

DDL = {
    "personal_notes": """
        CREATE TABLE personal_notes (
            note_id INTEGER PRIMARY KEY AUTOINCREMENT,
            manuscript_id INTEGER NOT NULL
                REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
            user_id INTEGER NOT NULL
                REFERENCES users(user_id) ON DELETE RESTRICT,
            content TEXT NOT NULL
                CHECK (length(trim(content)) BETWEEN 1 AND 10000),
            created_at TEXT NOT NULL DEFAULT
                (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT
                (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """,
    "ix_personal_notes_owner":
        """
        CREATE INDEX ix_personal_notes_owner
        ON personal_notes(user_id, manuscript_id, created_at, note_id)
        """,
}


def normalize(sql):
    return " ".join(sql.strip().rstrip(";").lower().split())


def migrate(database_path):
    path = Path(database_path).resolve(strict=True)

    if not path.is_file():
        raise ValueError("An existing SQLite database is required")

    db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)

    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")

        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        if not {"users", "manuscripts", "schema_migrations"}.issubset(tables):
            raise RuntimeError("Required database tables are missing")

        applied = {
            row[0] for row in db.execute(
                "SELECT migration_id FROM schema_migrations"
            )
        }

        if "018_general_comments" not in applied:
            raise RuntimeError("Migration 018 is required")

        names = set(DDL)
        placeholders = ",".join("?" for _ in names)

        existing = {
            row[0] for row in db.execute(
                f"SELECT name FROM sqlite_master WHERE name IN ({placeholders})",
                tuple(names),
            )
        }

        if MIGRATION_ID not in applied:
            if existing:
                raise RuntimeError("Conflicting or partially created Notes schema")

            for sql in DDL.values():
                db.execute(sql)

            db.execute(
                """
                INSERT INTO schema_migrations (migration_id, applied_at)
                VALUES (?, datetime('now'))
                """,
                (MIGRATION_ID,),
            )

        for name, expected in DDL.items():
            row = db.execute(
                "SELECT type, sql FROM sqlite_master WHERE name=?",
                (name,),
            ).fetchone()

            expected_type = "table" if name == "personal_notes" else "index"

            if (
                row is None
                or row[0] != expected_type
                or normalize(row[1]) != normalize(expected)
            ):
                raise RuntimeError(f"Incompatible Notes schema: {name}")

        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key violation")

        db.commit()
        print("PASS: Migration 019 verified.")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    migrate(parser.parse_args().database)

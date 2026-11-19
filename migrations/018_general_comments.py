"""Add staff-visible general comments to existing manuscript records."""

import argparse
import sqlite3
from pathlib import Path


MIGRATION_ID = "018_general_comments"

DDL = {
    "general_comments": """
        CREATE TABLE general_comments (
            comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            manuscript_id INTEGER NOT NULL
                REFERENCES manuscripts(manuscript_id)
                ON DELETE RESTRICT,
            user_id INTEGER NOT NULL
                REFERENCES users(user_id)
                ON DELETE RESTRICT,
            content TEXT NOT NULL
                CHECK (length(trim(content)) BETWEEN 1 AND 10000),
            visibility TEXT NOT NULL DEFAULT 'staff'
                CHECK (visibility = 'staff'),
            created_at TEXT NOT NULL DEFAULT
                (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """,
    "ix_general_comments_manuscript":
        """
        CREATE INDEX ix_general_comments_manuscript
        ON general_comments(manuscript_id, created_at, comment_id)
        """,
    "ix_general_comments_user":
        """
        CREATE INDEX ix_general_comments_user
        ON general_comments(user_id)
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

        required_tables = {
            "users",
            "manuscripts",
            "schema_migrations",
        }

        existing_tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        if not required_tables.issubset(existing_tables):
            raise RuntimeError("Required database tables are missing")

        applied = {
            row[0]
            for row in db.execute(
                "SELECT migration_id FROM schema_migrations"
            )
        }

        if "017_ai_prescreening" not in applied:
            raise RuntimeError("Migration 017 is required")

        expected_names = set(DDL)

        existing_objects = {
            row[0]
            for row in db.execute(
                """
                SELECT name FROM sqlite_master
                WHERE name IN (?, ?, ?)
                """,
                tuple(expected_names),
            )
        }

        if MIGRATION_ID not in applied:
            if existing_objects:
                raise RuntimeError(
                    "Conflicting or partially created General Comments schema"
                )

            for sql in DDL.values():
                db.execute(sql)

            db.execute(
                """
                INSERT INTO schema_migrations
                    (migration_id, applied_at)
                VALUES (?, datetime('now'))
                """,
                (MIGRATION_ID,),
            )

        for name, expected_sql in DDL.items():
            row = db.execute(
                "SELECT type, sql FROM sqlite_master WHERE name=?",
                (name,),
            ).fetchone()

            expected_type = (
                "table" if name == "general_comments" else "index"
            )

            if (
                row is None
                or row[0] != expected_type
                or normalize(row[1]) != normalize(expected_sql)
            ):
                raise RuntimeError(
                    f"Incompatible General Comments schema: {name}"
                )

        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key violation")

        db.commit()
        print("PASS: Migration 018 verified.")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    migrate(parser.parse_args().database)

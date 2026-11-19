"""Explicit AI pre-screening schema migration for an existing SQLite database."""

import argparse
from pathlib import Path
import sqlite3


MIGRATION_ID = "017_ai_prescreening"

DDL = {
    "manuscript_submission_snapshots": """
        CREATE TABLE manuscript_submission_snapshots (
            snapshot_id TEXT PRIMARY KEY NOT NULL,
            manuscript_id INTEGER NOT NULL
                REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
            submitted_by INTEGER NOT NULL
                REFERENCES users(user_id) ON DELETE RESTRICT,
            submission_kind TEXT NOT NULL
                CHECK (submission_kind IN (
                    'initial', 'initial_revision', 'peer_revision'
                )),
            review_round INTEGER NOT NULL CHECK (review_round > 0),
            submission_sequence INTEGER NOT NULL
                CHECK (submission_sequence > 0),
            file_ref TEXT NOT NULL,
            file_sha256 TEXT NOT NULL CHECK (length(file_sha256) = 64),
            file_format TEXT NOT NULL
                CHECK (file_format IN ('txt', 'docx', 'pdf', 'doc')),
            online_version_id TEXT,
            submitted_at TEXT NOT NULL,
            UNIQUE (manuscript_id, submission_sequence)
        )
    """,
    "ai_prescreening_jobs": """
        CREATE TABLE ai_prescreening_jobs (
            job_id TEXT PRIMARY KEY NOT NULL,
            snapshot_id TEXT NOT NULL UNIQUE
                REFERENCES manuscript_submission_snapshots(snapshot_id)
                ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending', 'processing', 'retry_wait',
                    'completed', 'failed', 'unsupported'
                )),
            attempt_count INTEGER NOT NULL DEFAULT 0
                CHECK (attempt_count >= 0),
            max_attempts INTEGER NOT NULL DEFAULT 3
                CHECK (max_attempts > 0),
            lease_token TEXT,
            lease_until TEXT,
            next_attempt_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (job_id, snapshot_id),
            CHECK (
                (status = 'processing'
                    AND lease_token IS NOT NULL
                    AND lease_until IS NOT NULL)
                OR
                (status <> 'processing'
                    AND lease_token IS NULL
                    AND lease_until IS NULL)
            )
        )
    """,
    "ai_prescreening_reports": """
        CREATE TABLE ai_prescreening_reports (
            report_id TEXT PRIMARY KEY NOT NULL,
            snapshot_id TEXT NOT NULL UNIQUE
                REFERENCES manuscript_submission_snapshots(snapshot_id)
                ON DELETE RESTRICT,
            job_id TEXT NOT NULL UNIQUE
                REFERENCES ai_prescreening_jobs(job_id)
                ON DELETE RESTRICT,
            engine TEXT NOT NULL,
            findings_json TEXT NOT NULL CHECK (json_valid(findings_json)),
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id, snapshot_id)
                REFERENCES ai_prescreening_jobs(job_id, snapshot_id)
                ON DELETE RESTRICT
        )
    """,
}

TRIGGERS = {
    "ai_snapshots_no_update": """
        CREATE TRIGGER ai_snapshots_no_update
        BEFORE UPDATE ON manuscript_submission_snapshots
        BEGIN SELECT RAISE(ABORT, 'immutable submission snapshot'); END
    """,
    "ai_snapshots_no_delete": """
        CREATE TRIGGER ai_snapshots_no_delete
        BEFORE DELETE ON manuscript_submission_snapshots
        BEGIN SELECT RAISE(ABORT, 'immutable submission snapshot'); END
    """,
    "ai_reports_no_update": """
        CREATE TRIGGER ai_reports_no_update
        BEFORE UPDATE ON ai_prescreening_reports
        BEGIN SELECT RAISE(ABORT, 'immutable AI report'); END
    """,
    "ai_reports_no_delete": """
        CREATE TRIGGER ai_reports_no_delete
        BEFORE DELETE ON ai_prescreening_reports
        BEGIN SELECT RAISE(ABORT, 'immutable AI report'); END
    """,
}


def normalize(sql):
    return " ".join(sql.strip().rstrip(";").lower().split())


def migrate(database_path):
    path = Path(database_path).resolve(strict=True)

    if not path.is_file():
        raise ValueError("An existing SQLite database file is required")

    db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)

    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")

        prerequisites = {
            "users": {"user_id"},
            "manuscripts": {"manuscript_id", "author_id", "review_round"},
            "schema_migrations": {"migration_id", "applied_at"},
        }

        for table, required_columns in prerequisites.items():
            row = db.execute(
                "SELECT type FROM sqlite_master WHERE name=?",
                (table,),
            ).fetchone()

            if row is None or row[0] != "table":
                raise RuntimeError(f"Missing prerequisite table: {table}")

            columns = {
                item[1]
                for item in db.execute(f"PRAGMA table_info({table})")
            }

            if not required_columns.issubset(columns):
                raise RuntimeError(f"Incompatible prerequisite table: {table}")

        applied = {
            row[0]
            for row in db.execute(
                "SELECT migration_id FROM schema_migrations"
            )
        }

        if "014_online_document_versions" not in applied:
            raise RuntimeError("Migration 014 is required")

        expected = {
            **{name: ("table", sql) for name, sql in DDL.items()},
            **{name: ("trigger", sql) for name, sql in TRIGGERS.items()},
        }

        if MIGRATION_ID not in applied:
            for name in expected:
                existing = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name=?",
                    (name,),
                ).fetchone()

                if existing:
                    raise RuntimeError(
                        f"Conflicting or partial AI schema: {name}"
                    )

            for sql in DDL.values():
                db.execute(sql)

            for sql in TRIGGERS.values():
                db.execute(sql)

            db.execute(
                "INSERT INTO schema_migrations VALUES (?, datetime('now'))",
                (MIGRATION_ID,),
            )

        for name, (kind, sql) in expected.items():
            row = db.execute(
                "SELECT type, sql FROM sqlite_master WHERE name=?",
                (name,),
            ).fetchone()

            if (
                row is None
                or row[0] != kind
                or normalize(row[1]) != normalize(sql)
            ):
                raise RuntimeError(f"Incompatible AI schema: {name}")

        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key violation")

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "database",
        help="Explicit path to an existing SQLite database",
    )
    migrate(parser.parse_args().database)

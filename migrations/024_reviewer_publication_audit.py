"""Append-only candidate artifact publication evidence on an explicit DB."""
import argparse
from importlib import import_module
from pathlib import Path
import sqlite3

MIGRATION_ID = '024_reviewer_publication_audit'
normalize = import_module('migrations.022_eic_prospective_proof').normalize
DDL = {
    'reviewer_publication_audit': '''CREATE TABLE reviewer_publication_audit (
        artifact_id TEXT PRIMARY KEY REFERENCES reviewer_artifacts(artifact_id),
        actor_id INTEGER NOT NULL REFERENCES users(user_id),
        manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id),
        review_round INTEGER NOT NULL CHECK(review_round>0),
        artifact_version INTEGER NOT NULL CHECK(artifact_version>0),
        artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64 AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'),
        source_proof_id TEXT NOT NULL REFERENCES eic_prospective_proofs(proof_id),
        occurred_at TEXT NOT NULL,
        result TEXT NOT NULL CHECK(result IN ('published','reaffirmed'))
    )''',
    'reviewer_publication_audit_check': '''CREATE TRIGGER reviewer_publication_audit_check BEFORE INSERT ON reviewer_publication_audit
        WHEN NOT EXISTS (SELECT 1 FROM reviewer_artifacts a JOIN reviewer_candidate_reservations r ON r.candidate_id=a.storage_id
            WHERE a.artifact_id=NEW.artifact_id AND a.status='approved' AND a.manuscript_id=NEW.manuscript_id
            AND a.review_round=NEW.review_round AND a.artifact_revision=NEW.artifact_version
            AND a.artifact_sha256=NEW.artifact_sha256 AND r.proof_id=NEW.source_proof_id
            AND EXISTS (SELECT 1 FROM users u WHERE u.user_id=NEW.actor_id AND u.role='eic'))
        BEGIN SELECT RAISE(ABORT,'publication evidence mismatch'); END''',
    'reviewer_publication_audit_no_update': "CREATE TRIGGER reviewer_publication_audit_no_update BEFORE UPDATE ON reviewer_publication_audit BEGIN SELECT RAISE(ABORT,'publication audit is immutable'); END",
    'reviewer_publication_audit_no_delete': "CREATE TRIGGER reviewer_publication_audit_no_delete BEFORE DELETE ON reviewer_publication_audit BEGIN SELECT RAISE(ABORT,'publication audit is immutable'); END",
}


def validate_schema(db):
    for name, expected in DDL.items():
        row = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        if not row or normalize(row[0]) != normalize(expected):
            raise RuntimeError('Publication audit schema unavailable')
    extra = db.execute("SELECT name FROM sqlite_master WHERE tbl_name='reviewer_publication_audit' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
    if any(row[0] not in DDL for row in extra):
        raise RuntimeError('Unexpected publication audit schema object')


def migrate(database_path):
    path = Path(database_path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Existing SQLite database required')
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', ('023_reviewer_candidate_intake',)).fetchone():
            raise RuntimeError('Required migration unavailable')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)).fetchone():
            if {r[0] for r in db.execute('SELECT name FROM sqlite_master')}.intersection(DDL):
                raise RuntimeError('Conflicting or partial publication audit schema')
            for sql in DDL.values():
                db.execute(sql)
            db.execute("INSERT INTO schema_migrations (migration_id,applied_at) VALUES (?,datetime('now'))", (MIGRATION_ID,))
        validate_schema(db)
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key violation')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('database')
    migrate(parser.parse_args().database)

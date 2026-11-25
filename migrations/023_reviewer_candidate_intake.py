"""Add private candidate intake; run only against an explicitly supplied DB."""
import argparse
from importlib import import_module
from pathlib import Path
import sqlite3

MIGRATION_ID = '023_reviewer_candidate_intake'
normalize = import_module('migrations.022_eic_prospective_proof').normalize

DDL = {
    'reviewer_candidate_reservations': '''CREATE TABLE reviewer_candidate_reservations (
        candidate_id TEXT PRIMARY KEY CHECK(length(candidate_id)=32 AND candidate_id NOT GLOB '*[^0-9a-f]*'),
        manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id),
        review_round INTEGER NOT NULL CHECK(review_round>0),
        source_id INTEGER NOT NULL REFERENCES review_round_files(round_file_id),
        proof_id TEXT NOT NULL REFERENCES eic_prospective_proofs(proof_id),
        source_evidence_id TEXT NOT NULL REFERENCES source_provenance_evidence(evidence_id),
        artifact_version INTEGER NOT NULL CHECK(artifact_version>0),
        sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
        byte_size INTEGER NOT NULL CHECK(byte_size BETWEEN 1 AND 10485760),
        format TEXT NOT NULL CHECK(format IN ('pdf','docx','doc','txt')),
        prepared_by INTEGER NOT NULL REFERENCES users(user_id),
        reserved_at TEXT NOT NULL,
        UNIQUE(manuscript_id,review_round,artifact_version)
    )''',
    'reviewer_candidate_publications': '''CREATE TABLE reviewer_candidate_publications (
        candidate_id TEXT PRIMARY KEY REFERENCES reviewer_candidate_reservations(candidate_id),
        stored_at TEXT NOT NULL
    )''',
    'reviewer_candidate_verifications': '''CREATE TABLE reviewer_candidate_verifications (
        candidate_id TEXT PRIMARY KEY REFERENCES reviewer_candidate_publications(candidate_id),
        verifier_id INTEGER NOT NULL REFERENCES users(user_id),
        verified_at TEXT NOT NULL,
        checklist TEXT NOT NULL CHECK(checklist='reviewer_anonymity_v1:1111111111'),
        sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
        artifact_version INTEGER NOT NULL CHECK(artifact_version>0)
    )''',
    'reviewer_candidate_approvals': '''CREATE TABLE reviewer_candidate_approvals (
        candidate_id TEXT PRIMARY KEY REFERENCES reviewer_candidate_verifications(candidate_id),
        approver_id INTEGER NOT NULL REFERENCES users(user_id),
        approved_at TEXT NOT NULL,
        sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
        artifact_version INTEGER NOT NULL CHECK(artifact_version>0)
    )''',
    'reviewer_candidate_withdrawals': '''CREATE TABLE reviewer_candidate_withdrawals (
        candidate_id TEXT PRIMARY KEY REFERENCES reviewer_candidate_approvals(candidate_id),
        actor_id INTEGER NOT NULL REFERENCES users(user_id),
        withdrawn_at TEXT NOT NULL
    )''',
    'candidate_verification_match': '''CREATE TRIGGER candidate_verification_match BEFORE INSERT ON reviewer_candidate_verifications
      WHEN NOT EXISTS (SELECT 1 FROM reviewer_candidate_reservations r WHERE r.candidate_id=NEW.candidate_id AND r.sha256=NEW.sha256 AND r.artifact_version=NEW.artifact_version)
      BEGIN SELECT RAISE(ABORT,'candidate verification mismatch'); END''',
    'candidate_approval_match': '''CREATE TRIGGER candidate_approval_match BEFORE INSERT ON reviewer_candidate_approvals
      WHEN NOT EXISTS (SELECT 1 FROM reviewer_candidate_verifications v WHERE v.candidate_id=NEW.candidate_id AND v.sha256=NEW.sha256 AND v.artifact_version=NEW.artifact_version)
      BEGIN SELECT RAISE(ABORT,'candidate approval mismatch'); END''',
}
for table in ('reviewer_candidate_reservations', 'reviewer_candidate_publications', 'reviewer_candidate_verifications', 'reviewer_candidate_approvals', 'reviewer_candidate_withdrawals'):
    for operation in ('UPDATE', 'DELETE'):
        name = f'{table}_no_{operation.lower()}'
        DDL[name] = f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable candidate history'); END"


def validate_schema(db):
    for name, expected in DDL.items():
        row = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        if not row or normalize(row[0]) != normalize(expected):
            raise RuntimeError('Candidate schema unavailable or incompatible')
    extra = db.execute("SELECT name FROM sqlite_master WHERE tbl_name IN ('reviewer_candidate_reservations','reviewer_candidate_publications','reviewer_candidate_verifications','reviewer_candidate_approvals','reviewer_candidate_withdrawals') AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
    if any(row[0] not in DDL for row in extra):
        raise RuntimeError('Unexpected candidate schema object')


def migrate(database_path):
    path = Path(database_path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Existing SQLite database required')
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        for required in ('013_artifact_evidence', '022_eic_prospective_proof'):
            if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (required,)).fetchone():
                raise RuntimeError('Required migration unavailable')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)).fetchone():
            if {r[0] for r in db.execute('SELECT name FROM sqlite_master')}.intersection(DDL):
                raise RuntimeError('Conflicting or partial candidate schema')
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

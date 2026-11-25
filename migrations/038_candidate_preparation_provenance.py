"""Immutable prospective candidate preparation evidence; never migrate Main here."""
try:
    from migrations._target_safety import checked_database_target
except ModuleNotFoundError as exc:
    if exc.name != 'migrations':
        raise
    from _target_safety import checked_database_target
from pathlib import Path
import sqlite3
from importlib import import_module

MIGRATION_ID = '038_candidate_preparation_provenance'
normalize = import_module('migrations.022_eic_prospective_proof').normalize
DDL = {
    'candidate_preparation_events': '''CREATE TABLE candidate_preparation_events (
        candidate_id TEXT PRIMARY KEY REFERENCES reviewer_candidate_reservations(candidate_id),
        manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id),
        review_round INTEGER NOT NULL CHECK(review_round>0),
        source_id INTEGER NOT NULL REFERENCES review_round_files(round_file_id),
        source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
        input_sha256 TEXT NOT NULL CHECK(length(input_sha256)=64 AND input_sha256 NOT GLOB '*[^0-9a-f]*'),
        prepared_sha256 TEXT NOT NULL CHECK(length(prepared_sha256)=64 AND prepared_sha256 NOT GLOB '*[^0-9a-f]*'),
        method TEXT NOT NULL CHECK(method='docx-v1'),
        actor_id INTEGER NOT NULL REFERENCES users(user_id),
        processed_at TEXT NOT NULL,
        result TEXT NOT NULL CHECK(result='prepared'),
        verification_status TEXT NOT NULL CHECK(verification_status='unverified'),
        human_review_status TEXT NOT NULL CHECK(human_review_status='pending')
    )''',
    'candidate_preparation_binding': '''CREATE TRIGGER candidate_preparation_binding BEFORE INSERT ON candidate_preparation_events
      WHEN NOT EXISTS (SELECT 1 FROM reviewer_candidate_reservations r
        JOIN eic_prospective_proofs p ON p.proof_id=r.proof_id
        JOIN eic_proof_reservations s ON s.storage_id=p.storage_id
        WHERE r.candidate_id=NEW.candidate_id AND r.manuscript_id=NEW.manuscript_id
          AND r.review_round=NEW.review_round AND r.source_id=NEW.source_id
          AND r.sha256=NEW.prepared_sha256 AND r.prepared_by=NEW.actor_id
          AND r.format='docx' AND s.source_id=NEW.source_id AND s.sha256=NEW.source_sha256)
      BEGIN SELECT RAISE(ABORT,'candidate preparation binding mismatch'); END''',
    'candidate_preparation_no_update': '''CREATE TRIGGER candidate_preparation_no_update BEFORE UPDATE ON candidate_preparation_events
      BEGIN SELECT RAISE(ABORT,'immutable candidate preparation'); END''',
    'candidate_preparation_no_delete': '''CREATE TRIGGER candidate_preparation_no_delete BEFORE DELETE ON candidate_preparation_events
      BEGIN SELECT RAISE(ABORT,'immutable candidate preparation'); END''',
    'candidate_review_rejections': '''CREATE TABLE candidate_review_rejections (
        candidate_id TEXT PRIMARY KEY REFERENCES reviewer_candidate_publications(candidate_id),
        reviewer_id INTEGER NOT NULL REFERENCES users(user_id),
        reviewed_at TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        artifact_version INTEGER NOT NULL CHECK(artifact_version>0),
        result TEXT NOT NULL CHECK(result='rejected'),
        reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000)
    )''',
    'candidate_rejection_binding': '''CREATE TRIGGER candidate_rejection_binding BEFORE INSERT ON candidate_review_rejections
      WHEN NOT EXISTS (SELECT 1 FROM reviewer_candidate_reservations r WHERE r.candidate_id=NEW.candidate_id
          AND r.sha256=NEW.sha256 AND r.artifact_version=NEW.artifact_version)
        OR EXISTS (SELECT 1 FROM reviewer_candidate_approvals a WHERE a.candidate_id=NEW.candidate_id)
      BEGIN SELECT RAISE(ABORT,'candidate rejection mismatch'); END''',
    'candidate_rejection_no_update': '''CREATE TRIGGER candidate_rejection_no_update BEFORE UPDATE ON candidate_review_rejections
      BEGIN SELECT RAISE(ABORT,'immutable candidate rejection'); END''',
    'candidate_rejection_no_delete': '''CREATE TRIGGER candidate_rejection_no_delete BEFORE DELETE ON candidate_review_rejections
      BEGIN SELECT RAISE(ABORT,'immutable candidate rejection'); END''',
    'candidate_filename_verifications': '''CREATE TABLE candidate_filename_verifications (
        candidate_id TEXT PRIMARY KEY REFERENCES reviewer_candidate_publications(candidate_id),
        verifier_id INTEGER NOT NULL REFERENCES users(user_id), verified_at TEXT NOT NULL,
        sha256 TEXT NOT NULL, artifact_version INTEGER NOT NULL CHECK(artifact_version>0)
    )''',
    'candidate_filename_binding': '''CREATE TRIGGER candidate_filename_binding BEFORE INSERT ON candidate_filename_verifications
      WHEN NOT EXISTS (SELECT 1 FROM reviewer_candidate_reservations r WHERE r.candidate_id=NEW.candidate_id
        AND r.sha256=NEW.sha256 AND r.artifact_version=NEW.artifact_version)
      BEGIN SELECT RAISE(ABORT,'candidate filename verification mismatch'); END''',
    'candidate_filename_no_update': '''CREATE TRIGGER candidate_filename_no_update BEFORE UPDATE ON candidate_filename_verifications
      BEGIN SELECT RAISE(ABORT,'immutable filename verification'); END''',
    'candidate_filename_no_delete': '''CREATE TRIGGER candidate_filename_no_delete BEFORE DELETE ON candidate_filename_verifications
      BEGIN SELECT RAISE(ABORT,'immutable filename verification'); END''',
}


def validate_schema(db):
    for name, sql in DDL.items():
        row = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        if not row or normalize(row[0]) != normalize(sql):
            raise RuntimeError('Candidate preparation schema unavailable')
    extras = db.execute("SELECT name FROM sqlite_master WHERE tbl_name IN ('candidate_preparation_events','candidate_review_rejections','candidate_filename_verifications') AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
    if any(row[0] not in DDL for row in extras):
        raise RuntimeError('Unexpected candidate preparation schema object')


def migrate(database_path):
    path = checked_database_target(database_path)
    if path == (Path(__file__).resolve().parents[1] / 'manuscript.db').resolve():
        raise ValueError('Persistent project database is not permitted')
    if not path.is_file():
        raise ValueError('Existing SQLite database required')
    with sqlite3.connect(path.as_uri()+'?mode=rw', uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', ('023_reviewer_candidate_intake',)).fetchone():
            raise RuntimeError('Candidate intake migration required')
        applied = db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)).fetchone()
        if not applied:
            if any(db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (name,)).fetchone() for name in DDL):
                raise RuntimeError('Conflicting preparation schema')
            for sql in DDL.values(): db.execute(sql)
            db.execute("INSERT INTO schema_migrations (migration_id,applied_at) VALUES (?,datetime('now'))", (MIGRATION_ID,))
        validate_schema(db)
        if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key violation')
        db.commit()

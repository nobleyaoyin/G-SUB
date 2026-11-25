"""Add prospective EIC attestations; run only against an explicitly supplied DB."""
import argparse
import sqlite3
from pathlib import Path

MIGRATION_ID = '022_eic_prospective_proof'
DDL = {
    'eic_proof_reservations': '''CREATE TABLE eic_proof_reservations (
        storage_id TEXT PRIMARY KEY CHECK(length(storage_id)=32 AND storage_id NOT GLOB '*[^0-9a-f]*'),
        manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
        review_round INTEGER NOT NULL CHECK(review_round>0),
        source_id INTEGER NOT NULL REFERENCES review_round_files(round_file_id) ON DELETE RESTRICT,
        actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        policy_revision INTEGER NOT NULL CHECK(policy_revision>0),
        policy_event_id TEXT NOT NULL,
        sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
        byte_size INTEGER NOT NULL CHECK(byte_size BETWEEN 1 AND 10485760),
        format TEXT NOT NULL CHECK(format IN ('pdf','docx','doc','txt')),
        reserved_at TEXT NOT NULL
    )''',
    'eic_prospective_proofs': '''CREATE TABLE eic_prospective_proofs (
        proof_id TEXT PRIMARY KEY CHECK(length(proof_id)=32 AND proof_id NOT GLOB '*[^0-9a-f]*'),
        storage_id TEXT NOT NULL UNIQUE REFERENCES eic_proof_reservations(storage_id) ON DELETE RESTRICT,
        source_id INTEGER NOT NULL UNIQUE REFERENCES review_round_files(round_file_id) ON DELETE RESTRICT,
        checklist TEXT NOT NULL CHECK(checklist='eic_anonymization_v1'),
        key_id TEXT NOT NULL CHECK(length(key_id) BETWEEN 1 AND 64),
        signature TEXT NOT NULL CHECK(length(signature)=64 AND signature NOT GLOB '*[^0-9a-f]*'),
        approved_at TEXT NOT NULL
    )''',
    'eic_proof_revocations': '''CREATE TABLE eic_proof_revocations (
        proof_id TEXT PRIMARY KEY REFERENCES eic_prospective_proofs(proof_id) ON DELETE RESTRICT,
        actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1000),
        revoked_at TEXT NOT NULL
    )''',
    'eic_proofs_source_check': '''CREATE TRIGGER eic_proofs_source_check BEFORE INSERT ON eic_prospective_proofs
      WHEN NOT EXISTS (SELECT 1 FROM eic_proof_reservations r WHERE r.storage_id=NEW.storage_id AND r.source_id=NEW.source_id)
      BEGIN SELECT RAISE(ABORT,'source mismatch'); END''',
}
for table in ('eic_proof_reservations', 'eic_prospective_proofs', 'eic_proof_revocations'):
    for operation in ('UPDATE', 'DELETE'):
        name = f'{table}_no_{operation.lower()}'
        DDL[name] = f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable proof history'); END"


def normalize(sql):
    return ' '.join((sql or '').strip().rstrip(';').lower().split())


def validate_schema(db):
    for name, expected in DDL.items():
        row = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        if not row or normalize(row[0]) != normalize(expected):
            raise RuntimeError('Incompatible EIC proof schema')
    extras = db.execute("SELECT name FROM sqlite_master WHERE tbl_name IN ('eic_proof_reservations','eic_prospective_proofs','eic_proof_revocations') AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
    if any(row[0] not in DDL for row in extras):
        raise RuntimeError('Unexpected EIC proof schema object')


def migrate(database_path):
    path = Path(database_path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Existing SQLite database required')
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        for required in ('001_reviewer_file_bindings', '011_blind_review_policy', '019_personal_notes'):
            if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (required,)).fetchone():
                raise RuntimeError('Required migration unavailable')
        applied = db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)).fetchone()
        if not applied:
            objects = {r[0] for r in db.execute('SELECT name FROM sqlite_master')}
            if objects.intersection(DDL):
                raise RuntimeError('Conflicting or partial proof schema')
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

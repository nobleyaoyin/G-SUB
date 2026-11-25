"""Add immutable prospective policy-to-source grant evidence on an explicit DB."""
import argparse
from pathlib import Path
import sqlite3

MIGRATION_ID='027_source_grant_provenance'
DDL={
    'controlled_source_grant_provenance': '''CREATE TABLE controlled_source_grant_provenance (
        grant_id TEXT PRIMARY KEY REFERENCES distribution_grants(grant_id) ON DELETE RESTRICT,
        policy_id TEXT NOT NULL REFERENCES controlled_source_policies(policy_id) ON DELETE RESTRICT,
        manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
        policy_version INTEGER NOT NULL CHECK(policy_version>0),
        source_kind TEXT NOT NULL CHECK(source_kind='current_author_manuscript'),
        source_ref TEXT NOT NULL CHECK(length(source_ref)>0),
        source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
        recipient_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        invitation_kind TEXT NOT NULL CHECK(invitation_kind IN ('initial','final')),
        invitation_id INTEGER NOT NULL CHECK(invitation_id>0),
        intent_id TEXT REFERENCES automatic_distribution_intents(intent_id) ON DELETE RESTRICT,
        actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        authorized_at TEXT NOT NULL
    )''',
    'controlled_source_provenance_validate': '''CREATE TRIGGER controlled_source_provenance_validate
        BEFORE INSERT ON controlled_source_grant_provenance BEGIN
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controlled_source_policies p
            JOIN manuscripts m ON m.manuscript_id=p.manuscript_id
            JOIN distribution_grants g ON g.grant_id=NEW.grant_id
            JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id
            WHERE p.policy_id=NEW.policy_id AND p.mode='manual' AND NEW.intent_id IS NULL
              AND p.manuscript_id=NEW.manuscript_id AND p.version=NEW.policy_version
              AND p.source_kind=NEW.source_kind AND p.source_ref=NEW.source_ref AND m.file_path=NEW.source_ref
              AND p.source_sha256=NEW.source_sha256 AND p.invitation_kind=NEW.invitation_kind
              AND g.manuscript_id=NEW.manuscript_id AND g.recipient_id=NEW.recipient_id
              AND g.actor_id=NEW.actor_id AND g.mode='manual' AND a.manuscript_id=NEW.manuscript_id
              AND a.kind='editor_source' AND a.sha256=NEW.source_sha256
              AND ((NEW.invitation_kind='initial' AND g.initial_invitation_id=NEW.invitation_id)
                OR (NEW.invitation_kind='final' AND g.final_invitation_id=NEW.invitation_id))
              AND NOT EXISTS(SELECT 1 FROM controlled_source_policy_revocations r WHERE r.policy_id=p.policy_id)
              AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=g.grant_id))
            THEN RAISE(ABORT,'Source provenance mismatch') END;
    END''',
    'controlled_source_provenance_no_update': "CREATE TRIGGER controlled_source_provenance_no_update BEFORE UPDATE ON controlled_source_grant_provenance BEGIN SELECT RAISE(ABORT,'immutable source provenance'); END",
    'controlled_source_provenance_no_delete': "CREATE TRIGGER controlled_source_provenance_no_delete BEFORE DELETE ON controlled_source_grant_provenance BEGIN SELECT RAISE(ABORT,'immutable source provenance'); END",
}


def normalize(sql): return ' '.join(sql.strip().rstrip(';').lower().split())


def migrate(database_path):
    path=Path(database_path).resolve(strict=True)
    if not path.is_file(): raise ValueError('Existing SQLite database required')
    db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='026_controlled_source_policy'").fetchone(): raise RuntimeError('Migration 026 required')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone():
            if {row[0] for row in db.execute('SELECT name FROM sqlite_master')}.intersection(DDL): raise RuntimeError('Conflicting or partial provenance schema')
            for sql in DDL.values(): db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",(MIGRATION_ID,))
        for name,expected in DDL.items():
            row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
            if not row or normalize(row[0])!=normalize(expected): raise RuntimeError('Incompatible provenance schema: '+name)
        if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key violation')
        db.commit()
    except Exception:
        db.rollback();raise
    finally: db.close()


def downgrade_empty(database_path):
    path=Path(database_path).resolve(strict=True);db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone(): raise RuntimeError('Migration not installed')
        if db.execute('SELECT 1 FROM controlled_source_grant_provenance LIMIT 1').fetchone(): raise RuntimeError('Source provenance must be retained')
        db.execute('DROP TABLE controlled_source_grant_provenance');db.execute('DELETE FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,));db.commit()
    except Exception:
        db.rollback();raise
    finally: db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('database');parser.add_argument('--downgrade-empty',action='store_true');args=parser.parse_args()
    (downgrade_empty if args.downgrade_empty else migrate)(args.database)

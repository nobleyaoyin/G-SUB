"""Add prospective source policies; no policy is activated by migration."""
import argparse
from pathlib import Path
import sqlite3

MIGRATION_ID = '026_controlled_source_policy'
DDL = {
    'controlled_source_policies': '''CREATE TABLE controlled_source_policies (
        policy_id TEXT PRIMARY KEY,
        manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
        invitation_kind TEXT NOT NULL CHECK(invitation_kind IN ('initial','final')),
        mode TEXT NOT NULL CHECK(mode IN ('manual','automatic')),
        source_kind TEXT NOT NULL CHECK(source_kind='current_author_manuscript'),
        source_ref TEXT NOT NULL CHECK(length(source_ref)>0),
        source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
        version INTEGER NOT NULL CHECK(version>0),
        actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        authorized_at TEXT NOT NULL,
        UNIQUE(manuscript_id,invitation_kind,version)
    )''',
    'controlled_source_policy_revocations': '''CREATE TABLE controlled_source_policy_revocations (
        policy_id TEXT PRIMARY KEY REFERENCES controlled_source_policies(policy_id) ON DELETE RESTRICT,
        actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000),
        revoked_at TEXT NOT NULL
    )''',
    'controlled_source_policy_actor': '''CREATE TRIGGER controlled_source_policy_actor BEFORE INSERT ON controlled_source_policies BEGIN
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.actor_id AND role='eic') THEN RAISE(ABORT,'EIC required') END;
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM manuscripts WHERE manuscript_id=NEW.manuscript_id AND status!='draft') THEN RAISE(ABORT,'Manuscript unavailable') END;
        SELECT CASE WHEN EXISTS(SELECT 1 FROM controlled_source_policies p WHERE p.manuscript_id=NEW.manuscript_id AND p.invitation_kind=NEW.invitation_kind AND NOT EXISTS(SELECT 1 FROM controlled_source_policy_revocations r WHERE r.policy_id=p.policy_id)) THEN RAISE(ABORT,'Active policy exists') END;
        SELECT CASE WHEN NEW.version != 1 + COALESCE((SELECT MAX(version) FROM controlled_source_policies p WHERE p.manuscript_id=NEW.manuscript_id AND p.invitation_kind=NEW.invitation_kind),0) THEN RAISE(ABORT,'Invalid policy version') END;
    END''',
    'controlled_source_revocation_actor': '''CREATE TRIGGER controlled_source_revocation_actor BEFORE INSERT ON controlled_source_policy_revocations BEGIN
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.actor_id AND role='eic') THEN RAISE(ABORT,'EIC required') END;
    END''',
}
for table in ('controlled_source_policies','controlled_source_policy_revocations'):
    for operation in ('UPDATE','DELETE'):
        name = f'{table}_no_{operation.lower()}'
        DDL[name] = f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable policy evidence'); END"


def normalize(sql):
    return ' '.join(sql.strip().rstrip(';').lower().split())


def migrate(database_path):
    path = Path(database_path).resolve(strict=True)
    if not path.is_file(): raise ValueError('Existing SQLite database required')
    db = sqlite3.connect(path.as_uri()+'?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='025_automatic_distribution'").fetchone(): raise RuntimeError('Migration 025 required')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone():
            if {row[0] for row in db.execute('SELECT name FROM sqlite_master')}.intersection(DDL): raise RuntimeError('Conflicting or partial controlled policy schema')
            for sql in DDL.values(): db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",(MIGRATION_ID,))
        for name, sql in DDL.items():
            row = db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
            if not row or normalize(row[0]) != normalize(sql): raise RuntimeError('Incompatible controlled policy schema: '+name)
        if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key violation')
        db.commit()
    except Exception:
        db.rollback(); raise
    finally: db.close()


def downgrade_empty(database_path):
    path = Path(database_path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone(): raise RuntimeError('Migration not installed')
        if db.execute('SELECT 1 FROM controlled_source_policies LIMIT 1').fetchone(): raise RuntimeError('Policy history must be retained')
        db.execute('DROP TABLE controlled_source_policy_revocations'); db.execute('DROP TABLE controlled_source_policies')
        db.execute('DELETE FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)); db.commit()
    except Exception:
        db.rollback(); raise
    finally: db.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('database'); parser.add_argument('--downgrade-empty',action='store_true'); args=parser.parse_args()
    (downgrade_empty if args.downgrade_empty else migrate)(args.database)

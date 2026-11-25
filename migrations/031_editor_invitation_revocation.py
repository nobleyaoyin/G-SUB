"""Append-only editor invitation revocation; explicit migration only."""
import sqlite3
from pathlib import Path

MIGRATION_ID='031_editor_invitation_revocation'
DDL={
 'editor_invitation_revocations': '''CREATE TABLE editor_invitation_revocations (
    invitation_kind TEXT NOT NULL CHECK(invitation_kind IN ('initial','final')),
    invitation_id INTEGER NOT NULL,
    manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
    recipient_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000),
    revoked_at TEXT NOT NULL,
    PRIMARY KEY(invitation_kind,invitation_id)
 )''',
 'editor_invitation_revocations_validate': '''CREATE TRIGGER editor_invitation_revocations_validate BEFORE INSERT ON editor_invitation_revocations BEGIN
    SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.actor_id AND role='eic') THEN RAISE(ABORT,'EIC required') END;
    SELECT CASE WHEN NEW.invitation_kind='initial' AND NOT EXISTS(SELECT 1 FROM initial_editor_invitations WHERE invitation_id=NEW.invitation_id AND manuscript_id=NEW.manuscript_id AND editor_id=NEW.recipient_id AND status IN ('pending','accepted')) THEN RAISE(ABORT,'Invitation unavailable') END;
    SELECT CASE WHEN NEW.invitation_kind='final' AND NOT EXISTS(SELECT 1 FROM final_editor_invitations WHERE invitation_id=NEW.invitation_id AND manuscript_id=NEW.manuscript_id AND editor_id=NEW.recipient_id AND status IN ('pending','accepted')) THEN RAISE(ABORT,'Invitation unavailable') END;
 END''',
 'editor_invitation_revocations_no_update': "CREATE TRIGGER editor_invitation_revocations_no_update BEFORE UPDATE ON editor_invitation_revocations BEGIN SELECT RAISE(ABORT,'immutable invitation revocation'); END",
 'editor_invitation_revocations_no_delete': "CREATE TRIGGER editor_invitation_revocations_no_delete BEFORE DELETE ON editor_invitation_revocations BEGIN SELECT RAISE(ABORT,'immutable invitation revocation'); END",
}
def normalize(sql):return ' '.join(sql.strip().rstrip(';').lower().split())
def migrate(database):
    path=Path(database).resolve(strict=True)
    with sqlite3.connect(path.as_uri()+'?mode=rw',uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='030_automatic_processing'").fetchone():raise RuntimeError('Migration 030 required')
        applied=db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone()
        if not applied:
            if any(db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone() for name in DDL):raise RuntimeError('Partial revocation schema')
            for sql in DDL.values():db.execute(sql)
            db.execute("INSERT INTO schema_migrations(migration_id,applied_at) VALUES(?,datetime('now'))",(MIGRATION_ID,))
        for name,sql in DDL.items():
            row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
            if not row or normalize(row[0])!=normalize(sql):raise RuntimeError('Incompatible revocation schema')
        if db.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('Foreign key violation')
        db.commit()
def downgrade_empty(database):
    with sqlite3.connect(Path(database).resolve(strict=True).as_uri()+'?mode=rw',uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM editor_invitation_revocations LIMIT 1').fetchone():raise RuntimeError('Revocation history must be retained')
        db.execute('DROP TABLE editor_invitation_revocations')
        db.execute('DELETE FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,));db.commit()

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Explicit editor invitation revocation schema migration')
    parser.add_argument('database');parser.add_argument('--downgrade-empty',action='store_true')
    args=parser.parse_args()
    (downgrade_empty if args.downgrade_empty else migrate)(args.database)

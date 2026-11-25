"""Bind sample Initial Editing objects to their real editing submissions."""
try:
    from migrations._target_safety import checked_database_target
except ModuleNotFoundError as exc:
    if exc.name != 'migrations':
        raise
    from _target_safety import checked_database_target
from pathlib import Path
import sqlite3

MIGRATION_ID = '036_sample_initial_editing'
DDL = {
    'sample_initial_artifacts': '''CREATE TABLE sample_initial_artifacts (
        submission_id INTEGER PRIMARY KEY REFERENCES initial_editing_submissions(submission_id),
        manuscript_id INTEGER NOT NULL REFERENCES sample_manuscripts(manuscript_id),
        editor_id INTEGER NOT NULL REFERENCES users(user_id),
        version_id TEXT NOT NULL UNIQUE,
        storage_identity TEXT NOT NULL UNIQUE,
        sha256 TEXT NOT NULL,
        byte_size INTEGER NOT NULL CHECK(byte_size > 0 AND byte_size <= 10485760),
        file_format TEXT NOT NULL CHECK(file_format IN ('pdf','docx','doc','txt')),
        created_at TEXT NOT NULL)''',
    'sample_initial_artifact_binding': '''CREATE TRIGGER sample_initial_artifact_binding BEFORE INSERT ON sample_initial_artifacts
        WHEN NEW.storage_identity != ('sample:v1/initial_editing/' || NEW.manuscript_id || '/' || NEW.version_id || '.' || NEW.file_format)
          OR NOT EXISTS(SELECT 1 FROM initial_editing_submissions s JOIN manuscripts m ON m.manuscript_id=s.manuscript_id
            JOIN initial_editor_invitations i ON i.manuscript_id=s.manuscript_id AND i.editor_id=s.editor_id
            WHERE s.submission_id=NEW.submission_id AND s.manuscript_id=NEW.manuscript_id
            AND s.editor_id=NEW.editor_id AND s.file_path=NEW.storage_identity
            AND s.status='pending_author' AND m.status='initial_editing' AND i.status='accepted')
        BEGIN SELECT RAISE(ABORT,'invalid initial artifact binding'); END''',
    'sample_initial_no_update': '''CREATE TRIGGER sample_initial_no_update BEFORE UPDATE ON sample_initial_artifacts
        BEGIN SELECT RAISE(ABORT,'immutable sample initial artifact'); END''',
    'sample_initial_no_delete': '''CREATE TRIGGER sample_initial_no_delete BEFORE DELETE ON sample_initial_artifacts
        BEGIN SELECT RAISE(ABORT,'immutable sample initial artifact'); END''',
}


def normalize(sql):
    return ' '.join(sql.strip().rstrip(';').lower().split())


def migrate(database, *, authorize_main=False):
    path = checked_database_target(database)
    if path == (Path(__file__).resolve().parents[1] / 'manuscript.db').resolve() and not authorize_main:
        raise ValueError('Persistent Main database is not permitted')
    with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='035_sample_document_storage'").fetchone():
            raise RuntimeError('Migration 035 required')
        installed = db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)).fetchone()
        if not installed:
            if any(db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (name,)).fetchone() for name in DDL):
                raise RuntimeError('Partial sample initial artifact schema')
            for sql in DDL.values(): db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))", (MIGRATION_ID,))
        for name, expected in DDL.items():
            row = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if not row or not row[0] or normalize(row[0]) != normalize(expected):
                raise RuntimeError('Incompatible sample initial artifact schema')
        if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key violation')
        db.commit()


def downgrade_empty(database):
    path = checked_database_target(database)
    if path == (Path(__file__).resolve().parents[1] / 'manuscript.db').resolve():
        raise ValueError('Persistent Main database is not permitted')
    with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM sample_initial_artifacts LIMIT 1').fetchone():
            raise RuntimeError('Sample initial artifact history must be retained')
        for name in ('sample_initial_artifact_binding','sample_initial_no_update','sample_initial_no_delete'):
            db.execute('DROP TRIGGER ' + name)
        db.execute('DROP TABLE sample_initial_artifacts')
        db.execute('DELETE FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)); db.commit()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('database')
    parser.add_argument('--downgrade-empty', action='store_true')
    parser.add_argument('--authorize-main', action='store_true', help='Explicitly authorize migration of Main (never permits downgrade)')
    args = parser.parse_args()
    if args.downgrade_empty:
        if args.authorize_main: parser.error('--authorize-main cannot be used for downgrade')
        downgrade_empty(args.database)
    else:
        migrate(args.database, authorize_main=args.authorize_main)

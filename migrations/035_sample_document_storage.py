"""Add an operator-provisioned sample registry and immutable document ledger."""
try:
    from migrations._target_safety import checked_database_target
except ModuleNotFoundError as exc:
    if exc.name != 'migrations':
        raise
    from _target_safety import checked_database_target
from pathlib import Path
import sqlite3

MIGRATION_ID = '035_sample_document_storage'
DDL = {
    'sample_manuscripts': '''CREATE TABLE sample_manuscripts (
        manuscript_id INTEGER PRIMARY KEY REFERENCES manuscripts(manuscript_id),
        registered_at TEXT NOT NULL)''',
    'sample_document_versions': '''CREATE TABLE sample_document_versions (
        version_id TEXT PRIMARY KEY,
        manuscript_id INTEGER NOT NULL REFERENCES sample_manuscripts(manuscript_id),
        storage_identity TEXT NOT NULL UNIQUE,
        sha256 TEXT NOT NULL,
        byte_size INTEGER NOT NULL CHECK(byte_size > 0 AND byte_size <= 10485760),
        file_format TEXT NOT NULL CHECK(file_format IN ('pdf','docx','doc','txt')),
        review_round INTEGER NOT NULL CHECK(review_round > 0),
        uploaded_by INTEGER NOT NULL REFERENCES users(user_id),
        created_at TEXT NOT NULL)''',
    'sample_registry_insert_check': '''CREATE TRIGGER sample_registry_insert_check BEFORE INSERT ON sample_manuscripts
        WHEN NOT EXISTS(SELECT 1 FROM manuscripts m WHERE m.manuscript_id=NEW.manuscript_id AND m.status='draft' AND m.file_path IS NULL)
        BEGIN SELECT RAISE(ABORT,'sample registration requires an empty draft'); END''',
    'sample_versions_insert_check': '''CREATE TRIGGER sample_versions_insert_check BEFORE INSERT ON sample_document_versions
        WHEN NEW.storage_identity != ('sample:v1/manuscripts/' || NEW.manuscript_id || '/' || NEW.version_id || '.' || NEW.file_format)
          OR NOT EXISTS(SELECT 1 FROM manuscripts m WHERE m.manuscript_id=NEW.manuscript_id AND m.author_id=NEW.uploaded_by AND m.status IN ('draft','revision_required','initial_revision_required'))
        BEGIN SELECT RAISE(ABORT,'invalid sample document binding'); END''',
    'sample_versions_no_update': '''CREATE TRIGGER sample_versions_no_update BEFORE UPDATE ON sample_document_versions
        BEGIN SELECT RAISE(ABORT,'immutable sample version'); END''',
    'sample_versions_no_delete': '''CREATE TRIGGER sample_versions_no_delete BEFORE DELETE ON sample_document_versions
        BEGIN SELECT RAISE(ABORT,'immutable sample version'); END''',
    'sample_registry_no_update': '''CREATE TRIGGER sample_registry_no_update BEFORE UPDATE ON sample_manuscripts
        BEGIN SELECT RAISE(ABORT,'immutable sample registry'); END''',
    'sample_registry_no_delete': '''CREATE TRIGGER sample_registry_no_delete BEFORE DELETE ON sample_manuscripts
        BEGIN SELECT RAISE(ABORT,'immutable sample registry'); END''',
}


def normalize(sql):
    return ' '.join(sql.strip().rstrip(';').lower().split())


def migrate(database, *, authorize_main=False):
    path = checked_database_target(database)
    if path == (Path(__file__).resolve().parents[1] / 'manuscript.db').resolve() and not authorize_main:
        raise ValueError('Persistent Main database is not permitted')
    with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM schema_migrations LIMIT 1').fetchone():
            raise RuntimeError('Existing migrations required')
        installed = db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)).fetchone()
        if not installed:
            if any(db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (name,)).fetchone() for name in DDL):
                raise RuntimeError('Partial sample storage schema')
            for sql in DDL.values():
                db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))", (MIGRATION_ID,))
        for name, sql in DDL.items():
            row = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if not row or not row[0] or normalize(row[0]) != normalize(sql):
                raise RuntimeError('Incompatible sample storage schema')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key violation')
        db.commit()


def downgrade_empty(database):
    path = checked_database_target(database)
    if path == (Path(__file__).resolve().parents[1] / 'manuscript.db').resolve():
        raise ValueError('Persistent Main database is not permitted')
    with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM sample_manuscripts LIMIT 1').fetchone() or db.execute('SELECT 1 FROM sample_document_versions LIMIT 1').fetchone():
            raise RuntimeError('Sample storage history must be retained')
        for name in ('sample_versions_no_update', 'sample_versions_no_delete', 'sample_registry_no_update', 'sample_registry_no_delete', 'sample_registry_insert_check', 'sample_versions_insert_check'):
            db.execute('DROP TRIGGER ' + name)
        db.execute('DROP TABLE sample_document_versions')
        db.execute('DROP TABLE sample_manuscripts')
        db.execute('DELETE FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,))
        db.commit()


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

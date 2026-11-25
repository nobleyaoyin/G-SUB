"""Add owner-visible original upload names to a disposable database."""
import sqlite3
import tempfile
from pathlib import Path

MIGRATION_ID = '044_manuscript_upload_names'


def migrate(path):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError('Only a disposable temporary database may be migrated')
    with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='043_author_submission_attachments'").fetchone():
            raise RuntimeError('Attachment migration required')
        db.execute('''CREATE TABLE IF NOT EXISTS manuscript_upload_names (
            manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id),
            storage_name TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            PRIMARY KEY (manuscript_id, storage_name)
        )''')
        info = list(db.execute('PRAGMA table_info(manuscript_upload_names)'))
        columns = {row[1] for row in info}
        primary = sorted((row[5], row[1]) for row in info if row[5])
        keys = list(db.execute('PRAGMA foreign_key_list(manuscript_upload_names)'))
        if columns != {'manuscript_id', 'storage_name', 'original_filename'} or primary != [(1, 'manuscript_id'), (2, 'storage_name')] or not any(row[2:5] == ('manuscripts', 'manuscript_id', 'manuscript_id') for row in keys):
            raise RuntimeError('Conflicting manuscript upload name schema')
        db.execute('INSERT OR IGNORE INTO schema_migrations VALUES (?, datetime(\'now\'))', (MIGRATION_ID,))
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key violation')
        db.commit()

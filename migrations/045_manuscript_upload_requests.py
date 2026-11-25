"""Add a request ledger for manuscript uploads on disposable databases."""
import sqlite3
import tempfile
from pathlib import Path

MIGRATION_ID = '045_manuscript_upload_requests'


def migrate(path):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError('Only a disposable temporary database may be migrated')
    with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='044_manuscript_upload_names'").fetchone():
            raise RuntimeError('Upload name migration required')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='manuscript_upload_names'").fetchone():
            raise RuntimeError('Upload name schema unavailable')
        db.execute('''CREATE TABLE IF NOT EXISTS manuscript_upload_requests (
            request_id TEXT PRIMARY KEY,
            manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id),
            author_id INTEGER NOT NULL REFERENCES users(user_id),
            storage_name TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            size INTEGER NOT NULL CHECK(size > 0),
            sha256 TEXT NOT NULL,
            UNIQUE(manuscript_id, storage_name)
        )''')
        info = list(db.execute('PRAGMA table_info(manuscript_upload_requests)'))
        columns = {row[1] for row in info}
        keys = list(db.execute('PRAGMA foreign_key_list(manuscript_upload_requests)'))
        indexes = list(db.execute('PRAGMA index_list(manuscript_upload_requests)'))
        unique = [tuple(row[2] for row in db.execute(f'PRAGMA index_info("{item[1]}")')) for item in indexes if item[2]]
        if columns != {'request_id', 'manuscript_id', 'author_id', 'storage_name', 'original_filename', 'size', 'sha256'} or not any(row[1]=='request_id' and row[5]==1 for row in info) or not any(row[2:5]==('manuscripts','manuscript_id','manuscript_id') for row in keys) or not any(row[2:5]==('users','author_id','user_id') for row in keys) or ('manuscript_id','storage_name') not in unique:
            raise RuntimeError('Conflicting upload request schema')
        db.execute('''CREATE TABLE IF NOT EXISTS manuscript_submission_requests (
            request_id TEXT PRIMARY KEY,
            manuscript_id INTEGER NOT NULL UNIQUE REFERENCES manuscripts(manuscript_id),
            author_id INTEGER NOT NULL REFERENCES users(user_id)
        )''')
        info = list(db.execute('PRAGMA table_info(manuscript_submission_requests)'))
        keys = list(db.execute('PRAGMA foreign_key_list(manuscript_submission_requests)'))
        indexes = list(db.execute('PRAGMA index_list(manuscript_submission_requests)'))
        unique = [tuple(row[2] for row in db.execute(f'PRAGMA index_info("{item[1]}")')) for item in indexes if item[2]]
        if {row[1] for row in info} != {'request_id', 'manuscript_id', 'author_id'} or not any(row[1]=='request_id' and row[5]==1 for row in info) or not any(row[2:5]==('manuscripts','manuscript_id','manuscript_id') for row in keys) or not any(row[2:5]==('users','author_id','user_id') for row in keys) or ('manuscript_id',) not in unique:
            raise RuntimeError('Conflicting submission request schema')
        db.execute('INSERT OR IGNORE INTO schema_migrations VALUES (?, datetime(\'now\'))', (MIGRATION_ID,))
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key violation')
        db.commit()

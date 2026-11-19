"""Explicitly add ONLYOFFICE session and callback state to an existing SQLite file."""
import argparse
from pathlib import Path
import sqlite3

ID = '016_onlyoffice_sessions'
DDL = (
    '''CREATE TABLE onlyoffice_sessions (session_id TEXT PRIMARY KEY, manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id), actor_id INTEGER NOT NULL REFERENCES users(user_id), stage TEXT NOT NULL CHECK(stage IN ('author','initial','final')), source_ref TEXT NOT NULL, source_sha256 TEXT NOT NULL, scope_key TEXT NOT NULL, head_id TEXT, global_head_id TEXT, expires_at INTEGER NOT NULL, closed INTEGER NOT NULL DEFAULT 0 CHECK(closed IN (0,1)), revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)))''',
    '''CREATE TABLE onlyoffice_callbacks (session_id TEXT NOT NULL REFERENCES onlyoffice_sessions(session_id), event_hash TEXT NOT NULL, status INTEGER NOT NULL, digest TEXT, url_hash TEXT, PRIMARY KEY(session_id,event_hash))''',
    '''CREATE TRIGGER onlyoffice_callbacks_no_update BEFORE UPDATE ON onlyoffice_callbacks BEGIN SELECT RAISE(ABORT,'immutable callback'); END''',
    '''CREATE TRIGGER onlyoffice_callbacks_no_delete BEFORE DELETE ON onlyoffice_callbacks BEGIN SELECT RAISE(ABORT,'immutable callback'); END''',
)


def migrate(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file(): raise ValueError('An existing database file is required')
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='014_online_document_versions'").fetchone():
            raise RuntimeError('Migration 014 is required')
        names = ('onlyoffice_sessions', 'onlyoffice_callbacks', 'onlyoffice_callbacks_no_update', 'onlyoffice_callbacks_no_delete')
        existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name IN (?,?,?,?)", names)}
        applied = db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (ID,)).fetchone()
        if not applied:
            if existing: raise RuntimeError('Conflicting or partial schema')
            for sql in DDL: db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?, datetime('now'))", (ID,))
        for name, expected in zip(names, DDL):
            row = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            normalize = lambda value: ' '.join(value.strip().rstrip(';').lower().split())
            if not row or normalize(row[0]) != normalize(expected): raise RuntimeError('Incompatible ONLYOFFICE schema')
        if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key violation')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database')
    migrate(parser.parse_args().database)

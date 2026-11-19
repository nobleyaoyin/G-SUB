"""Explicitly add immutable online TXT version metadata to an existing SQLite file."""
import argparse
from pathlib import Path
import re
import sqlite3

MIGRATION_ID = '014_online_document_versions'
DDL = """CREATE TABLE online_document_versions (
    version_id TEXT PRIMARY KEY NOT NULL,
    manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
    actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    stage TEXT NOT NULL CHECK (stage IN ('author', 'initial', 'final')),
    scope_key TEXT NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    source_ref TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
    file_ref TEXT NOT NULL UNIQUE,
    file_sha256 TEXT NOT NULL CHECK (length(file_sha256) = 64),
    saved_at TEXT NOT NULL,
    change_note TEXT CHECK (change_note IS NULL OR length(change_note) <= 500),
    UNIQUE (manuscript_id, actor_id, stage, scope_key, version_number)
)"""
TRIGGERS = {
    'online_versions_no_update': "CREATE TRIGGER online_versions_no_update BEFORE UPDATE ON online_document_versions BEGIN SELECT RAISE(ABORT, 'immutable version'); END",
    'online_versions_no_delete': "CREATE TRIGGER online_versions_no_delete BEFORE DELETE ON online_document_versions BEGIN SELECT RAISE(ABORT, 'immutable version'); END",
}

def normalize(value):
    return re.sub(r'\s+', ' ', value.strip().rstrip(';')).lower()

def migrate(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('An existing database file is required')
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        objects = {row[0]: (row[1], row[2]) for row in db.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','trigger','view')")}
        for table, fields in {'users': {'user_id'}, 'manuscripts': {'manuscript_id', 'author_id'}, 'schema_migrations': {'migration_id', 'applied_at'}}.items():
            if objects.get(table, (None,))[0] != 'table' or not fields.issubset({r[1] for r in db.execute(f'PRAGMA table_info({table})')}):
                raise RuntimeError('Missing or incompatible prerequisite schema')
        ledger = {r[0] for r in db.execute('SELECT migration_id FROM schema_migrations')}
        if not {'001_reviewer_file_bindings', '002_reviewer_invitations', '003_two_reviewer_policy', '004_author_agreements', '005_final_editor_workflow', '006_formatter_publication'}.issubset(ledger):
            raise RuntimeError('Migrations 001–006 are required')
        expected = {'online_document_versions': ('table', DDL), **{k: ('trigger', v) for k, v in TRIGGERS.items()}}
        if MIGRATION_ID not in ledger:
            if any(name in objects for name in expected):
                raise RuntimeError('Conflicting or partial version schema')
            db.execute(DDL)
            for sql in TRIGGERS.values(): db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?, datetime('now'))", (MIGRATION_ID,))
        for name, (kind, sql) in expected.items():
            row = db.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if not row or row[0] != kind or normalize(row[1]) != normalize(sql):
                raise RuntimeError('Incompatible version schema')
        if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key violation')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', help='Explicit path to an existing SQLite database')
    migrate(parser.parse_args().database)

"""Explicit additive Google OIDC identity and one-time transaction schema."""
import argparse
from pathlib import Path
import re
import sqlite3

MIGRATION_ID = '015_google_oidc'
DDL = {
    'google_identities': '''CREATE TABLE google_identities (
        subject TEXT PRIMARY KEY NOT NULL,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE RESTRICT,
        linked_at INTEGER NOT NULL CHECK(linked_at > 0)
    )''',
    'google_oauth_transactions': '''CREATE TABLE google_oauth_transactions (
        state_hash TEXT PRIMARY KEY NOT NULL,
        browser_hash TEXT NOT NULL,
        nonce TEXT NOT NULL,
        verifier TEXT NOT NULL,
        link_user_id INTEGER REFERENCES users(user_id) ON DELETE RESTRICT,
        expires_at INTEGER NOT NULL
    )''',
    'google_oauth_handoffs': '''CREATE TABLE google_oauth_handoffs (
        receipt_hash TEXT PRIMARY KEY NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        expires_at INTEGER NOT NULL
    )''',
}

def normalize(value): return re.sub(r'\s+', ' ', value.strip().rstrip(';')).lower()

def migrate(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file(): raise ValueError('Existing SQLite file required')
    db = sqlite3.connect(path.as_uri()+'?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
        objects = {r[0]: (r[1], r[2]) for r in db.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view')")}
        for name, cols in {'users': {'user_id','email','role'}, 'schema_migrations': {'migration_id','applied_at'}}.items():
            if objects.get(name, (None,))[0] != 'table' or not cols.issubset({r[1] for r in db.execute(f'PRAGMA table_info({name})')}):
                raise RuntimeError('Missing prerequisite schema')
        ledger = {r[0] for r in db.execute('SELECT migration_id FROM schema_migrations')}
        if not {'001_reviewer_file_bindings','002_reviewer_invitations','003_two_reviewer_policy','004_author_agreements','005_final_editor_workflow','006_formatter_publication'}.issubset(ledger): raise RuntimeError('Migrations 001–006 required')
        if MIGRATION_ID not in ledger:
            if any(name in objects for name in DDL): raise RuntimeError('Conflicting or partial Google schema')
            for sql in DDL.values(): db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))", (MIGRATION_ID,))
        for name, sql in DDL.items():
            row = db.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if not row or row[0] != 'table' or normalize(row[1]) != normalize(sql): raise RuntimeError('Incompatible Google schema')
        if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key violation')
        db.commit()
    except Exception:
        db.rollback(); raise
    finally: db.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('database'); migrate(parser.parse_args().database)

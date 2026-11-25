"""Atomic submission-schema candidate, restricted to disposable rehearsal databases.

Not an authorization or operator tool for persistent databases. Deploy only after
separately reviewed production tooling and explicit authorization exist.
"""
from pathlib import Path
import re
import sqlite3
import tempfile

MIGRATION_ID = '046_main_submission_schema'
PRIOR_IDS = ('041_author_submission_drafts', '042_author_submission_linkage',
             '043_author_submission_attachments', '044_manuscript_upload_names',
             '045_manuscript_upload_requests')
TABLES = {
    'author_submission_drafts': '''CREATE TABLE author_submission_drafts (
        id TEXT PRIMARY KEY, author_id INTEGER NOT NULL REFERENCES users(user_id),
        request_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
        current_step INTEGER NOT NULL DEFAULT 1 CHECK (current_step BETWEEN 1 AND 10),
        payload TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(author_id, request_id))''',
    'author_submission_links': '''CREATE TABLE author_submission_links (
        draft_id TEXT PRIMARY KEY REFERENCES author_submission_drafts(id),
        manuscript_id INTEGER NOT NULL UNIQUE REFERENCES manuscripts(manuscript_id), created_at TEXT NOT NULL)''',
    'author_submission_attachments': '''CREATE TABLE author_submission_attachments (
        id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES author_submission_drafts(id),
        kind TEXT NOT NULL CHECK(kind IN ('cover_letter', 'supplementary')), filename TEXT NOT NULL,
        media_type TEXT NOT NULL, size INTEGER NOT NULL CHECK(size > 0), sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL, supersedes TEXT REFERENCES author_submission_attachments(id), removed_at TEXT)''',
    'manuscript_upload_names': '''CREATE TABLE manuscript_upload_names (
        manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id), storage_name TEXT NOT NULL,
        original_filename TEXT NOT NULL, PRIMARY KEY (manuscript_id, storage_name))''',
    'manuscript_upload_requests': '''CREATE TABLE manuscript_upload_requests (
        request_id TEXT PRIMARY KEY, manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id),
        author_id INTEGER NOT NULL REFERENCES users(user_id), storage_name TEXT NOT NULL,
        original_filename TEXT NOT NULL, size INTEGER NOT NULL CHECK(size > 0), sha256 TEXT NOT NULL,
        UNIQUE(manuscript_id, storage_name))''',
    'manuscript_submission_requests': '''CREATE TABLE manuscript_submission_requests (
        request_id TEXT PRIMARY KEY, manuscript_id INTEGER NOT NULL UNIQUE REFERENCES manuscripts(manuscript_id),
        author_id INTEGER NOT NULL REFERENCES users(user_id))''',
}


def _normal(sql):
    # Compare tokens, not whitespace-stripped text: token boundaries, literal
    # values, and quoted identifiers must never collapse into different SQL.
    # Unknown syntax fails closed rather than guessing at SQL equivalence.
    result = []
    pos = 0
    while pos < len(sql):
        char = sql[pos]
        if char.isspace():
            pos += 1
        elif char in "'\"`[":
            closing = ']' if char == '[' else char
            end = pos + 1
            while end < len(sql):
                if sql[end] == closing:
                    if closing != ']' and end + 1 < len(sql) and sql[end + 1] == closing:
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            else:
                raise ValueError('Unterminated SQL quote')
            result.append(('quoted', sql[pos:end]))
            pos = end
        elif char.isascii() and (char.isalpha() or char == '_'):
            match = re.match(r'[A-Za-z_][A-Za-z_0-9$]*', sql[pos:])
            result.append(('word', match.group().lower()))
            pos += len(match.group())
        elif char.isascii() and char.isdigit():
            match = re.match(r'[0-9]+', sql[pos:])
            result.append(('number', match.group()))
            pos += len(match.group())
        elif sql[pos:pos + 2] in ('>=', '<=', '!=', '<>', '==', '||', '<<', '>>'):
            result.append(('operator', sql[pos:pos + 2]))
            pos += 2
        elif char in '(),.=<>+-*/%':
            if sql[pos:pos + 2] in ('--', '/*'):
                raise ValueError('SQL comments are not supported')
            result.append(('symbol', char))
            pos += 1
        else:
            raise ValueError('Unsupported SQL token')
    return tuple(result)


def migrate(path, *, _after_create=None):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError('Only a disposable temporary database may be migrated')
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('A standalone disposable database file is required')
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Database integrity check failed')
        for table, column in (('users', 'user_id'), ('manuscripts', 'manuscript_id'),
                              ('schema_migrations', 'migration_id'), ('schema_migrations', 'applied_at')):
            if column not in {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}:
                raise RuntimeError('Required base schema is unavailable')
        present = {name: db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() for name in TABLES}
        ledger = {row[0] for row in db.execute('SELECT migration_id FROM schema_migrations')}
        ids = set(PRIOR_IDS + (MIGRATION_ID,))
        if any(present.values()):
            if not all(present.values()) or not ids.issubset(ledger):
                raise RuntimeError('Partial submission schema requires manual investigation')
            if any(_normal(present[name][0]) != _normal(sql) for name, sql in TABLES.items()):
                raise RuntimeError('Conflicting submission schema')
            db.rollback()
            return 'already applied'
        if ids & ledger:
            raise RuntimeError('Submission migration ledger conflicts with schema')
        for index, (name, sql) in enumerate(TABLES.items()):
            db.execute(sql)
            if _after_create is not None:
                _after_create(index, name)
        for migration_id in PRIOR_IDS + (MIGRATION_ID,):
            db.execute("INSERT INTO schema_migrations (migration_id, applied_at) VALUES (?, datetime('now'))", (migration_id,))
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key violation')
        db.commit()
        return 'applied'
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()

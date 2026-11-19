"""Add optional self-reported profiles; requires an explicit existing SQLite path."""
import argparse
from importlib import import_module
from pathlib import Path
import re
import sqlite3

MIGRATION_ID = '010_reviewer_profiles'
PREREQUISITES = ('001_reviewer_file_bindings', '002_reviewer_invitations', '003_two_reviewer_policy', '004_author_agreements', '005_final_editor_workflow', '006_formatter_publication')
DDL = """CREATE TABLE reviewer_profiles (
    user_id INTEGER NOT NULL PRIMARY KEY REFERENCES users(user_id) ON DELETE RESTRICT,
    professional_title TEXT CHECK (professional_title IS NULL OR length(professional_title) BETWEEN 1 AND 100),
    institution TEXT CHECK (institution IS NULL OR length(institution) BETWEEN 1 AND 200),
    department TEXT CHECK (department IS NULL OR length(department) BETWEEN 1 AND 150),
    research_areas TEXT NOT NULL CHECK (length(research_areas) <= 4096 AND json_valid(research_areas) AND json_type(research_areas) = 'array'),
    expertise TEXT NOT NULL CHECK (length(expertise) <= 4096 AND json_valid(expertise) AND json_type(expertise) = 'array'),
    updated_at TEXT NOT NULL CHECK (length(updated_at) = 27),
    provenance TEXT NOT NULL CHECK (provenance = 'self_reported')
)"""


def normalize(sql):
    parts = re.split(r"('(?:''|[^'])*')", sql.strip().rstrip(';'))
    return ''.join(part if i % 2 else re.sub(r'\s+', ' ', part.lower()) for i, part in enumerate(parts)).strip()


def migrate(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file(): raise ValueError('Database must be an existing file')
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        objects = {name: (kind, sql) for name, kind, sql in db.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view','index','trigger')")}
        if objects.get('schema_migrations', (None,))[0] != 'table' or objects.get('users', (None,))[0] != 'table': raise RuntimeError('Missing prerequisite tables')
        if {row[1] for row in db.execute('PRAGMA table_info(schema_migrations)')} != {'migration_id', 'applied_at'}: raise RuntimeError('Invalid ledger')
        if not {'user_id', 'role', 'name', 'email'}.issubset({row[1] for row in db.execute('PRAGMA table_info(users)')}): raise RuntimeError('Invalid users schema')
        ledger = {row[0] for row in db.execute('SELECT migration_id FROM schema_migrations')}
        if not set(PREREQUISITES).issubset(ledger): raise RuntimeError('Migrations 001–006 are required')
        for name in PREREQUISITES:
            declared = import_module('migrations.' + name).DDL
            if isinstance(declared, str):
                declared = {{'002_reviewer_invitations': 'reviewer_invitations', '003_two_reviewer_policy': 'manuscript_review_policies', '004_author_agreements': 'author_agreements'}[name]: declared}
            for obj, expected in declared.items():
                actual = objects.get(obj)
                kind = 'index' if expected.strip().lower().startswith(('create index', 'create unique index')) else 'table'
                if not actual or actual[0] != kind or not actual[1] or normalize(actual[1]) != normalize(expected):
                    raise RuntimeError('Incompatible prerequisite schema')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Integrity check failed')
        if MIGRATION_ID not in ledger:
            if 'reviewer_profiles' in objects: raise RuntimeError('Conflicting reviewer profile object')
            db.execute(DDL)
            db.execute("INSERT INTO schema_migrations VALUES (?, datetime('now'))", (MIGRATION_ID,))
        actual = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='reviewer_profiles'").fetchone()
        if not actual or normalize(actual[0]) != normalize(DDL): raise RuntimeError('Reviewer profile schema mismatch')
        if db.execute("SELECT 1 FROM sqlite_master WHERE tbl_name='reviewer_profiles' AND type IN ('trigger','index') AND sql IS NOT NULL").fetchone(): raise RuntimeError('Unexpected reviewer profile schema objects')
        if db.execute('PRAGMA foreign_key_check').fetchone() or db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]: raise RuntimeError('Integrity check failed')
        db.commit()
    except Exception:
        db.rollback(); raise
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', help='Explicit existing SQLite database path')
    migrate(parser.parse_args().database)

"""Add disconnected blind-policy persistence; requires an explicit SQLite path."""
import argparse
from importlib import import_module
from pathlib import Path
import sqlite3

MIGRATION_ID = '011_blind_review_policy'
PREREQUISITES = import_module('migrations.010_reviewer_profiles').PREREQUISITES
normalize = import_module('migrations.010_reviewer_profiles').normalize

DDL = {
    'blind_policy_events': """CREATE TABLE blind_policy_events (
        event_id TEXT NOT NULL PRIMARY KEY,
        manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision >= 1),
        mode TEXT NOT NULL CHECK(mode IN ('single_blind','double_blind')),
        action TEXT NOT NULL CHECK(action IN ('selected','changed','locked')),
        actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        occurred_at TEXT NOT NULL CHECK(length(occurred_at)=27),
        invitation_id INTEGER REFERENCES reviewer_invitations(assignment_id) ON DELETE RESTRICT,
        CHECK((action='locked' AND invitation_id IS NOT NULL) OR (action<>'locked' AND invitation_id IS NULL)),
        CHECK((revision=1 AND action='selected') OR (revision>1 AND action IN ('changed','locked'))),
        UNIQUE(manuscript_id, revision),
        UNIQUE(event_id, manuscript_id, revision, mode)
    )""",
    'blind_policies': """CREATE TABLE blind_policies (
        manuscript_id INTEGER NOT NULL PRIMARY KEY REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
        mode TEXT NOT NULL CHECK(mode IN ('single_blind','double_blind')),
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision >= 1),
        selected_by INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        selected_at TEXT NOT NULL CHECK(length(selected_at)=27),
        updated_by INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        updated_at TEXT NOT NULL CHECK(length(updated_at)=27),
        locked_at TEXT CHECK(locked_at IS NULL OR length(locked_at)=27),
        lock_invitation_id INTEGER REFERENCES reviewer_invitations(assignment_id) ON DELETE RESTRICT,
        last_event_id TEXT NOT NULL,
        CHECK((locked_at IS NULL AND lock_invitation_id IS NULL) OR (locked_at IS NOT NULL AND lock_invitation_id IS NOT NULL)),
        FOREIGN KEY(last_event_id, manuscript_id, revision, mode) REFERENCES blind_policy_events(event_id, manuscript_id, revision, mode) ON DELETE RESTRICT
    )""",
    'ix_blind_events_actor_time': 'CREATE INDEX ix_blind_events_actor_time ON blind_policy_events(actor_id, occurred_at)',
    'blind_events_no_update': "CREATE TRIGGER blind_events_no_update BEFORE UPDATE ON blind_policy_events BEGIN SELECT RAISE(ABORT, 'blind policy events are append-only'); END",
    'blind_events_no_delete': "CREATE TRIGGER blind_events_no_delete BEFORE DELETE ON blind_policy_events BEGIN SELECT RAISE(ABORT, 'blind policy events are append-only'); END",
    'blind_events_invitation_match': """CREATE TRIGGER blind_events_invitation_match BEFORE INSERT ON blind_policy_events
        WHEN NEW.invitation_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM reviewer_invitations i JOIN review_assignments a ON a.assignment_id=i.assignment_id
            WHERE i.assignment_id=NEW.invitation_id AND a.manuscript_id=NEW.manuscript_id)
        BEGIN SELECT RAISE(ABORT, 'invitation manuscript mismatch'); END""",
}


def validate_schema(db):
    objects = {name: (kind, sql) for name, kind, sql in db.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view','index','trigger')")}
    for name, expected in DDL.items():
        kind = 'trigger' if expected.startswith('CREATE TRIGGER') else 'index' if expected.startswith('CREATE INDEX') else 'table'
        actual = objects.get(name)
        if not actual or actual[0] != kind or not actual[1] or normalize(actual[1]) != normalize(expected):
            raise RuntimeError('Blind policy schema unavailable or incompatible')
    extra = db.execute("SELECT name FROM sqlite_master WHERE tbl_name IN ('blind_policies','blind_policy_events') AND type IN ('trigger','index') AND sql IS NOT NULL").fetchall()
    if any(row[0] not in DDL for row in extra):
        raise RuntimeError('Blind policy schema unavailable or incompatible')


def migrate(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file(): raise ValueError('Database must be an existing file')
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        objects = {name: (kind, sql) for name, kind, sql in db.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view','index','trigger')")}
        if objects.get('schema_migrations', (None,))[0] != 'table' or {r[1] for r in db.execute('PRAGMA table_info(schema_migrations)')} != {'migration_id', 'applied_at'}:
            raise RuntimeError('Missing or incompatible migration ledger')
        ledger = {r[0] for r in db.execute('SELECT migration_id FROM schema_migrations')}
        if not set(PREREQUISITES).issubset(ledger): raise RuntimeError('Migrations 001–006 required')
        for name in PREREQUISITES:
            declared = import_module('migrations.' + name).DDL
            if isinstance(declared, str):
                declared = {{'002_reviewer_invitations': 'reviewer_invitations', '003_two_reviewer_policy': 'manuscript_review_policies', '004_author_agreements': 'author_agreements'}[name]: declared}
            for obj, expected in declared.items():
                actual = objects.get(obj)
                if not actual or not actual[1] or normalize(actual[1]) != normalize(expected): raise RuntimeError('Incompatible prerequisite schema')
        if '010_reviewer_profiles' in ledger:
            actual = objects.get('reviewer_profiles')
            expected = import_module('migrations.010_reviewer_profiles').DDL
            if not actual or actual[0] != 'table' or not actual[1] or normalize(actual[1]) != normalize(expected): raise RuntimeError('Incompatible optional profile schema')
        if not {'manuscript_id', 'author_id'}.issubset({r[1] for r in db.execute('PRAGMA table_info(manuscripts)')}) or not {'user_id', 'role'}.issubset({r[1] for r in db.execute('PRAGMA table_info(users)')}): raise RuntimeError('Incompatible base schema')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Integrity check failed')
        if MIGRATION_ID not in ledger:
            if any(name in objects for name in DDL): raise RuntimeError('Conflicting or partial blind policy schema')
            for sql in DDL.values(): db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?, datetime('now'))", (MIGRATION_ID,))
        validate_schema(db)
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

"""Real blind-policy store checks in disposable SQLite; no migrations or files."""
import ast
from pathlib import Path
import sqlite3

import pytest

from app.database import engine as configured_engine
from app import blind_policy_store as store


def _declared_policy_ddl():
    # Read the declared schema as data: do not run the migration entry point.
    source = (Path(__file__).resolve().parents[1] / 'migrations' / '011_blind_review_policy.py').read_text()
    tree = ast.parse(source)
    declaration = next(node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'DDL' for target in node.targets))
    return ast.literal_eval(declaration.value)


@pytest.fixture
def policy_db(monkeypatch):
    def reject_configured(*args, **kwargs):
        raise AssertionError('Configured application database connection is forbidden')
    monkeypatch.setattr(configured_engine, 'connect', reject_configured)
    monkeypatch.setattr(configured_engine, 'raw_connection', reject_configured)
    connect = sqlite3.connect
    def memory_only(database, *args, **kwargs):
        if database != ':memory:' or kwargs.get('uri', False):
            raise AssertionError('Only a fresh in-memory SQLite database is allowed')
        return connect(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', memory_only)
    db = sqlite3.connect(':memory:')
    db.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) else sqlite3.SQLITE_OK)
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
        CREATE TABLE schema_migrations (migration_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE users (user_id INTEGER PRIMARY KEY, role TEXT NOT NULL);
        CREATE TABLE manuscripts (manuscript_id INTEGER PRIMARY KEY);
        CREATE TABLE review_assignments (assignment_id INTEGER PRIMARY KEY,
            manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id),
            reviewer_id INTEGER NOT NULL REFERENCES users(user_id));
        CREATE TABLE reviewer_invitations (assignment_id INTEGER PRIMARY KEY
            REFERENCES review_assignments(assignment_id), status TEXT NOT NULL);
    ''')
    for ddl in _declared_policy_ddl().values():
        db.execute(ddl)
    db.execute('INSERT INTO schema_migrations VALUES (?, ?)', ('011_blind_review_policy', 'synthetic'))
    db.executemany('INSERT INTO users VALUES (?, ?)', [(1, 'eic'), (2, 'reviewer'), (3, 'author')])
    db.executemany('INSERT INTO manuscripts VALUES (?)', [(1,), (2,)])
    db.commit()
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert db.execute('PRAGMA database_list').fetchall() == [(0, 'main', '')]
    try:
        yield db
    finally:
        db.close()


def select_policy(db, mode='single_blind'):
    store.begin_write(db)
    result = store.select_mode(db, 1, mode, 1)
    db.commit()
    return result


def invite(db, manuscript_id=1, assignment_id=10):
    db.execute('INSERT INTO review_assignments VALUES (?, ?, ?)', (assignment_id, manuscript_id, 2))
    db.execute('INSERT INTO reviewer_invitations VALUES (?, ?)', (assignment_id, 'accepted'))
    db.commit()


def test_guards_reject_configured_and_file_databases(policy_db):
    with pytest.raises(AssertionError, match='configured|Configured'):
        configured_engine.connect()
    with pytest.raises(AssertionError, match='configured|Configured'):
        configured_engine.raw_connection()
    with pytest.raises(AssertionError, match='in-memory'):
        sqlite3.connect('manuscript.db')
    with pytest.raises(sqlite3.DatabaseError):
        policy_db.execute("ATTACH DATABASE ':memory:' AS other")


def test_missing_policy_returns_none(policy_db):
    assert store.read_policy(policy_db, 1) is None
    assert policy_db.execute('SELECT count(*) FROM blind_policy_events').fetchone()[0] == 0


@pytest.mark.parametrize('mode', ['single_blind', 'double_blind'])
def test_valid_selected_policy_has_unlocked_synthetic_history(policy_db, mode):
    policy = select_policy(policy_db, mode)
    assert policy['mode'] == mode and policy['revision'] == 1 and policy['locked_at'] is None
    assert store.read_policy(policy_db, 1) == policy
    assert policy_db.execute('SELECT revision, mode, action, invitation_id FROM blind_policy_events').fetchall() == [(1, mode, 'selected', None)]
    assert policy_db.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('mode', ['single_blind', 'double_blind'])
def test_valid_locked_policy_uses_real_synthetic_invitation(policy_db, mode):
    select_policy(policy_db, mode)
    invite(policy_db)
    store.begin_write(policy_db)
    locked = store.lock_mode(policy_db, 1, 10, 1, 1)
    policy_db.commit()
    assert locked['mode'] == mode and locked['revision'] == 2 and locked['locked_at']
    assert locked['lock_invitation_id'] == 10
    assert store.read_policy(policy_db, 1) == locked
    assert policy_db.execute('SELECT revision, action, invitation_id FROM blind_policy_events ORDER BY revision').fetchall() == [(1, 'selected', None), (2, 'locked', 10)]
    assert policy_db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_invalid_mode_is_rejected_without_history(policy_db):
    store.begin_write(policy_db)
    with pytest.raises(store.PolicyError, match='Invalid review mode'):
        store.select_mode(policy_db, 1, 'invalid', 1)
    policy_db.rollback()
    assert store.read_policy(policy_db, 1) is None
    assert policy_db.execute('SELECT count(*) FROM blind_policy_events').fetchone()[0] == 0


def test_database_constraint_rejects_invalid_policy_event_mode(policy_db):
    with pytest.raises(sqlite3.IntegrityError):
        policy_db.execute('INSERT INTO blind_policy_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                          ('synthetic', 1, 1, 'invalid', 'selected', 1, '2026-01-02T03:04:05.000000Z', None))
    policy_db.rollback()
    assert store.read_policy(policy_db, 1) is None


def test_inconsistent_policy_history_is_rejected(policy_db):
    select_policy(policy_db)
    policy_db.execute('BEGIN')
    policy_db.execute('PRAGMA defer_foreign_keys=ON')
    policy_db.execute('UPDATE blind_policies SET revision=2 WHERE manuscript_id=1')
    with pytest.raises(store.PolicyError, match='Inconsistent policy history'):
        store.read_policy(policy_db, 1)
    policy_db.rollback()
    assert store.read_policy(policy_db, 1)['revision'] == 1


@pytest.mark.parametrize('statement', ["UPDATE blind_policy_events SET mode='double_blind'", 'DELETE FROM blind_policy_events'])
def test_policy_events_are_append_only(policy_db, statement):
    select_policy(policy_db)
    with pytest.raises(sqlite3.IntegrityError, match='append-only'):
        policy_db.execute(statement)
    policy_db.rollback()
    assert store.read_policy(policy_db, 1)['revision'] == 1


def test_missing_schema_ledger_fails_closed(policy_db):
    policy_db.execute('DELETE FROM schema_migrations WHERE migration_id=?', ('011_blind_review_policy',))
    policy_db.commit()
    with pytest.raises(store.SchemaUnavailable):
        store.read_policy(policy_db, 1)


def test_missing_append_only_trigger_fails_schema_validation(policy_db):
    policy_db.execute('DROP TRIGGER blind_events_no_update')
    with pytest.raises(store.SchemaUnavailable):
        store.read_policy(policy_db, 1)


def test_wrong_manuscript_invitation_cannot_lock_policy(policy_db):
    select_policy(policy_db)
    invite(policy_db, manuscript_id=2)
    store.begin_write(policy_db)
    with pytest.raises(store.PolicyError, match='Invitation does not match manuscript'):
        store.lock_mode(policy_db, 1, 10, 1, 1)
    policy_db.rollback()
    assert store.read_policy(policy_db, 1)['locked_at'] is None
    assert policy_db.execute('SELECT count(*) FROM blind_policy_events').fetchone()[0] == 1

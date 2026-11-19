"""Disconnected SQLite persistence, not authentication or active blind review.

Callers own the transaction and must use BEGIN IMMEDIATE for writes. Future
routes must bind the actor to verified authentication and authorize EIC access
inside the same transaction. IDs alone do not establish authority.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import import_module
import sqlite3
from uuid import uuid4

schema = import_module('migrations.011_blind_review_policy')
MODES = frozenset(('single_blind', 'double_blind'))


class PolicyError(ValueError):
    pass


class SchemaUnavailable(PolicyError):
    pass


def begin_write(db):
    if db.in_transaction: raise PolicyError('A fresh write transaction is required')
    if not db.execute('PRAGMA foreign_keys').fetchone()[0]: raise PolicyError('Foreign keys must be enabled')
    db.execute('BEGIN IMMEDIATE')


def _schema(db):
    try:
        if not db.execute('PRAGMA foreign_keys').fetchone()[0]: raise SchemaUnavailable('Foreign keys must be enabled')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (schema.MIGRATION_ID,)).fetchone(): raise SchemaUnavailable('Blind policy schema unavailable')
        schema.validate_schema(db)
    except (sqlite3.DatabaseError, RuntimeError) as error:
        raise SchemaUnavailable('Blind policy schema unavailable or incompatible') from error


def _id(value):
    if type(value) is not int or value < 1: raise PolicyError('Invalid identifier')
    return value


def _timestamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def read_policy(db, manuscript_id):
    _schema(db); _id(manuscript_id)
    row = db.execute('SELECT manuscript_id,mode,revision,selected_by,selected_at,updated_by,updated_at,locked_at,lock_invitation_id,last_event_id FROM blind_policies WHERE manuscript_id=?', (manuscript_id,)).fetchone()
    events = db.execute('SELECT event_id,revision,mode,action,actor_id,occurred_at,invitation_id FROM blind_policy_events WHERE manuscript_id=? ORDER BY revision', (manuscript_id,)).fetchall()
    if row is None:
        if events: raise PolicyError('Inconsistent policy history')
        return None
    if len(events) != row[2]: raise PolicyError('Inconsistent policy history')
    prev_mode = None
    for n, event in enumerate(events, 1):
        eid, revision, mode, action, actor, at, invitation = event
        if revision != n or mode not in MODES or (n == 1 and action != 'selected') or (n > 1 and action not in ('changed', 'locked')) or (action == 'changed' and mode == prev_mode) or (action == 'locked' and (mode != prev_mode or n != len(events))):
            raise PolicyError('Inconsistent policy history')
        prev_mode = mode
    first, last = events[0], events[-1]
    if (row[1], row[2], row[3], row[4], row[5], row[6], row[9]) != (last[2], last[1], first[4], first[5], last[4], last[5], last[0]): raise PolicyError('Inconsistent policy history')
    if (row[7], row[8]) != ((last[5], last[6]) if last[3] == 'locked' else (None, None)): raise PolicyError('Inconsistent policy history')
    return dict(zip(('manuscript_id','mode','revision','selected_by','selected_at','updated_by','updated_at','locked_at','lock_invitation_id','last_event_id'), row))


@contextmanager
def _write(db):
    if not db.in_transaction: raise PolicyError('Caller must begin a write transaction')
    _schema(db)
    db.execute('SAVEPOINT blind_policy_operation')
    try:
        yield
        db.execute('RELEASE SAVEPOINT blind_policy_operation')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT blind_policy_operation')
        db.execute('RELEASE SAVEPOINT blind_policy_operation')
        raise


def _actor(db, actor_id):
    _id(actor_id)
    if not db.execute("SELECT 1 FROM users WHERE user_id=? AND role='eic'", (actor_id,)).fetchone(): raise PolicyError('EIC actor required')


def _event(db, manuscript_id, revision, mode, action, actor_id, invitation_id=None):
    event_id, at = str(uuid4()), _timestamp()
    db.execute('INSERT INTO blind_policy_events VALUES (?,?,?,?,?,?,?,?)', (event_id, manuscript_id, revision, mode, action, actor_id, at, invitation_id))
    return event_id, at


def select_mode(db, manuscript_id, mode, actor_id):
    with _write(db):
        _id(manuscript_id); _actor(db, actor_id)
        if mode not in MODES: raise PolicyError('Invalid review mode')
        if not db.execute('SELECT 1 FROM manuscripts WHERE manuscript_id=?', (manuscript_id,)).fetchone(): raise PolicyError('Manuscript unavailable')
        if read_policy(db, manuscript_id) is not None: raise PolicyError('Policy already selected')
        if db.execute('SELECT 1 FROM review_assignments WHERE manuscript_id=? LIMIT 1', (manuscript_id,)).fetchone(): raise PolicyError('Existing review assignments require legacy policy review')
        eid, at = _event(db, manuscript_id, 1, mode, 'selected', actor_id)
        db.execute('INSERT INTO blind_policies VALUES (?,?,?,?,?,?,?,?,?,?)', (manuscript_id, mode, 1, actor_id, at, actor_id, at, None, None, eid))
        return read_policy(db, manuscript_id)


def change_mode(db, manuscript_id, mode, actor_id, expected_revision):
    with _write(db):
        _id(manuscript_id); _id(expected_revision); _actor(db, actor_id)
        if mode not in MODES: raise PolicyError('Invalid review mode')
        old = read_policy(db, manuscript_id)
        if not old or old['revision'] != expected_revision or old['locked_at'] is not None: raise PolicyError('Policy unavailable, locked or stale')
        if old['mode'] == mode: raise PolicyError('Mode is unchanged')
        if db.execute('SELECT 1 FROM review_assignments WHERE manuscript_id=? LIMIT 1', (manuscript_id,)).fetchone(): raise PolicyError('Existing review assignments prevent changes')
        eid, at = _event(db, manuscript_id, expected_revision + 1, mode, 'changed', actor_id)
        result = db.execute('UPDATE blind_policies SET mode=?,revision=?,updated_by=?,updated_at=?,last_event_id=? WHERE manuscript_id=? AND revision=? AND locked_at IS NULL', (mode, expected_revision+1, actor_id, at, eid, manuscript_id, expected_revision))
        if result.rowcount != 1: raise PolicyError('Policy unavailable, locked or stale')
        return read_policy(db, manuscript_id)


def lock_mode(db, manuscript_id, invitation_id, actor_id, expected_revision, *, assignment_actor=False):
    with _write(db):
        _id(manuscript_id); _id(invitation_id); _id(expected_revision)
        if assignment_actor:
            _id(actor_id)
            if not db.execute("SELECT 1 FROM users u JOIN review_assignments a ON a.assigned_by=u.user_id JOIN reviewer_invitations i ON i.assignment_id=a.assignment_id WHERE u.user_id=? AND u.role IN ('editor','eic') AND a.manuscript_id=? AND i.assignment_id=?", (actor_id, manuscript_id, invitation_id)).fetchone():
                raise PolicyError('Authorized invitation actor required')
        else:
            _actor(db, actor_id)
        old = read_policy(db, manuscript_id)
        if not old or old['revision'] != expected_revision or old['locked_at'] is not None: raise PolicyError('Policy unavailable, locked or stale')
        if not db.execute('SELECT 1 FROM reviewer_invitations i JOIN review_assignments a ON a.assignment_id=i.assignment_id WHERE i.assignment_id=? AND a.manuscript_id=?', (invitation_id, manuscript_id)).fetchone(): raise PolicyError('Invitation does not match manuscript')
        eid, at = _event(db, manuscript_id, expected_revision+1, old['mode'], 'locked', actor_id, invitation_id)
        result = db.execute('UPDATE blind_policies SET revision=?,updated_by=?,updated_at=?,locked_at=?,lock_invitation_id=?,last_event_id=? WHERE manuscript_id=? AND revision=? AND locked_at IS NULL', (expected_revision+1, actor_id, at, at, invitation_id, eid, manuscript_id, expected_revision))
        if result.rowcount != 1: raise PolicyError('Policy unavailable, locked or stale')
        return read_policy(db, manuscript_id)

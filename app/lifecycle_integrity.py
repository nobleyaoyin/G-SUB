"""Read-only integrity checks for already lifecycle-protected artifact operations.

This module does not enroll accounts, authenticate a request, or define an
administrator authority. Callers must separately authenticate their principal.
"""
from datetime import datetime
from importlib import import_module
import sqlite3
from sqlalchemy.exc import SQLAlchemyError

from app import lifecycle_prototype

schema = import_module('migrations.009_account_invitation_lifecycle')


class LifecycleIntegrityError(ValueError):
    """A lifecycle identity or its recorded history is unavailable."""


def active_actor(raw, user_id, role, *, require_transaction=True):
    """Validate 009 schema and the complete existing chain; return generation.

    The caller must hold its authorization transaction and authenticate the
    principal independently. No record is created or modified here.
    """
    try:
        if not isinstance(raw, sqlite3.Connection) or (require_transaction and not raw.in_transaction):
            raise ValueError('Active SQLite authorization transaction required')
        if type(user_id) is not int or user_id <= 0 or role not in ('eic', 'reviewer'):
            raise ValueError('Invalid lifecycle identity')
        if raw.execute('PRAGMA foreign_keys').fetchone() != (1,):
            raise ValueError('Foreign keys unavailable')
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (schema.MIGRATION_ID,)).fetchone():
            raise ValueError('Lifecycle migration unavailable')
        schema._validate_own_schema(schema._objects(raw))
        if raw.execute('SELECT role FROM users WHERE user_id=?', (user_id,)).fetchone() != (role,):
            raise ValueError('Role unavailable')
        state = lifecycle_prototype._state(raw, user_id)
        if state is None or state.state != 'active':
            raise ValueError('Active lifecycle unavailable')
        events = raw.execute('''SELECT e.sequence,e.from_state,e.to_state,e.reason_code,e.occurred_at,
                u.user_id FROM account_lifecycle_events e LEFT JOIN users u ON u.user_id=e.actor_user_id
                WHERE e.user_id=? ORDER BY e.sequence''', (user_id,)).fetchall()
        for sequence, before, after, reason, stamp, actor in events:
            expected = 'initial_enrollment' if sequence == 1 else (
                'administrative_disable' if (before, after) == ('active', 'disabled') else 'administrative_reactivation')
            if reason != expected or actor is None or not isinstance(stamp, str):
                raise ValueError('Lifecycle event unavailable')
            parsed = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%S.%fZ')
            if parsed.strftime('%Y-%m-%dT%H:%M:%S.%fZ') != stamp:
                raise ValueError('Invalid lifecycle timestamp')
        return state.generation
    except (sqlite3.Error, RuntimeError, ValueError, TypeError, lifecycle_prototype.PolicyError) as exc:
        raise LifecycleIntegrityError('Lifecycle integrity unavailable') from exc


def login_generation(db, user):
    """Bind a newly authenticated EIC session when a valid active chain exists.

    An absent or invalid chain does not alter legacy login; it yields no
    protected capability. Protected requests always revalidate in a transaction.
    """
    if user.role != 'eic':
        return None
    try:
        conn = db.connection()
        if conn.dialect.name != 'sqlite':
            return None
        return active_actor(conn.connection.driver_connection, user.user_id, 'eic', require_transaction=False)
    except (LifecycleIntegrityError, RuntimeError, SQLAlchemyError):
        return None

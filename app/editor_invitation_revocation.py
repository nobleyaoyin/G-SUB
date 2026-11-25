"""Fail closed on damaged Editor invitation revocation evidence."""
from importlib import import_module
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError


def effective_status(db,kind,invitation):
    """Project revocation separately without changing the historical response."""
    if kind not in ('initial','final') or invitation is None:
        raise HTTPException(503,'Invitation authorization unavailable')
    if is_revoked(db,kind,invitation.invitation_id):return 'revoked'
    return invitation.status


def is_revoked(db,kind,invitation_id):
    try:
        conn=db.connection()
        if conn.dialect.name!='sqlite':raise HTTPException(503,'Invitation authorization unavailable')
        raw=conn.connection.driver_connection
        return is_revoked_raw(raw,kind,invitation_id)
    except HTTPException:raise
    except (SQLAlchemyError,KeyError):raise HTTPException(503,'Invitation authorization unavailable') from None


def is_revoked_raw(raw,kind,invitation_id):
    import sqlite3
    module=import_module('migrations.031_editor_invitation_revocation')
    try:
        if not raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone():
            if raw.execute("SELECT 1 FROM sqlite_master WHERE name='editor_invitation_revocations'").fetchone():raise HTTPException(503,'Invitation authorization unavailable')
            return False
        installed=raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(module.MIGRATION_ID,)).fetchone()
        existing=raw.execute("SELECT 1 FROM sqlite_master WHERE name='editor_invitation_revocations'").fetchone()
        if not installed and not existing:return False
        if not installed or not existing:raise HTTPException(503,'Invitation authorization unavailable')
        for name,expected in module.DDL.items():
            row=raw.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
            if not row or not row[0] or module.normalize(row[0])!=module.normalize(expected):raise HTTPException(503,'Invitation authorization unavailable')
        return bool(raw.execute('SELECT 1 FROM editor_invitation_revocations WHERE invitation_kind=? AND invitation_id=?',(kind,invitation_id)).fetchone())
    except sqlite3.Error:raise HTTPException(503,'Invitation authorization unavailable') from None

"""Caller-transaction-owned, append-only online document version ledger."""
import hashlib
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

def digest(data):
    return hashlib.sha256(data).hexdigest()

def require_schema(db):
    try:
        row = db.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='014_online_document_versions'")).first()
        cols = {r[1] for r in db.connection().exec_driver_sql('PRAGMA table_info(online_document_versions)')}
        if not row or cols != {'version_id','manuscript_id','actor_id','stage','scope_key','version_number','source_ref','source_sha256','file_ref','file_sha256','saved_at','change_note'}:
            raise HTTPException(503, 'Online version history unavailable; migration 014 is required')
    except SQLAlchemyError:
        raise HTTPException(503, 'Online version history unavailable; migration 014 is required') from None

def history(db, manuscript_id, actor_id, stage, scope=None):
    require_schema(db)
    sql = 'SELECT * FROM online_document_versions WHERE manuscript_id=:mid AND actor_id=:actor AND stage=:stage'
    params = {'mid': manuscript_id, 'actor': actor_id, 'stage': stage}
    if scope is not None:
        sql += ' AND scope_key=:scope'
        params['scope'] = scope
    return db.execute(text(sql + ' ORDER BY saved_at, version_number'), params).mappings().all()

def record(db, manuscript_id, actor_id, stage, scope, source_ref, source_bytes, file_ref, content, note=None):
    rows = history(db, manuscript_id, actor_id, stage, scope)
    values = {'id': uuid4().hex, 'mid': manuscript_id, 'actor': actor_id, 'stage': stage, 'scope': scope,
              'number': max((row['version_number'] for row in rows), default=0)+1,
              'source': source_ref, 'source_hash': digest(source_bytes), 'file': file_ref, 'file_hash': digest(content),
              'saved': datetime.now(timezone.utc).isoformat(), 'note': note}
    db.execute(text('''INSERT INTO online_document_versions
        (version_id, manuscript_id, actor_id, stage, scope_key, version_number, source_ref, source_sha256, file_ref, file_sha256, saved_at, change_note)
        VALUES (:id,:mid,:actor,:stage,:scope,:number,:source,:source_hash,:file,:file_hash,:saved,:note)'''), values)
    return values

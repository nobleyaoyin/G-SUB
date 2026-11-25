"""Sample Final Editing and Formatting bytes; caller owns authorization."""
from datetime import datetime, timezone
from importlib import import_module
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.sample_storage import SampleStorage, SampleStorageError


def require_schema(db):
    migration = import_module('migrations.037_sample_final_formatting')
    conn = db.connection()
    if not conn.execute(text('SELECT 1 FROM schema_migrations WHERE migration_id=:id'), {'id':migration.MIGRATION_ID}).first():
        raise HTTPException(503, 'Sample stage storage unavailable')
    for name, expected in migration.DDL.items():
        row = conn.execute(text('SELECT sql FROM sqlite_master WHERE name=:name'), {'name':name}).first()
        if not row or not row[0] or migration.normalize(row[0]) != migration.normalize(expected):
            raise HTTPException(503, 'Sample stage storage unavailable')


def write(db, kind, manuscript_id, extension, content):
    if kind not in ('final_editing', 'formatting'):
        raise HTTPException(503, 'Sample stage storage unavailable')
    require_schema(db)
    version, fmt = uuid4().hex, extension.lstrip('.')
    identity = f'sample:v1/{kind}/{manuscript_id}/{version}.{fmt}'
    try:
        digest = SampleStorage.for_development().write_new(identity, content)
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(503, 'Sample stage storage unavailable') from None
    return {'kind':kind, 'version':version, 'identity':identity, 'sha':digest, 'size':len(content), 'format':fmt}


def bind(db, submission, actor_id, artifact):
    db.execute(text('''INSERT INTO sample_stage_artifacts
      (kind,submission_id,manuscript_id,actor_id,version_id,storage_identity,sha256,byte_size,file_format,created_at)
      VALUES (:kind,:sid,:mid,:actor,:version,:identity,:sha,:size,:format,:created)'''),
      {'sid':submission.submission_id, 'mid':submission.manuscript_id, 'actor':actor_id,
       **artifact, 'created':datetime.now(timezone.utc).isoformat()})


def read(db, kind, submission):
    if kind not in ('final_editing', 'formatting'):
        raise HTTPException(409, 'Document unavailable')
    require_schema(db)
    row = db.execute(text('SELECT * FROM sample_stage_artifacts WHERE kind=:kind AND submission_id=:sid AND manuscript_id=:mid'),
        {'kind':kind, 'sid':submission.submission_id, 'mid':submission.manuscript_id}).mappings().first()
    if (not row or not re.fullmatch(r'[0-9a-f]{32}', row['version_id'] or '')
            or row['file_format'] not in {'pdf','docx','doc','txt'}
            or row['storage_identity'] != f"sample:v1/{kind}/{submission.manuscript_id}/{row['version_id']}.{row['file_format']}"
            or row['storage_identity'] != submission.file_path
            or (kind == 'final_editing' and row['actor_id'] != submission.editor_id)
            or (kind == 'formatting' and row['sha256'] != submission.sha256)):
        raise HTTPException(409, 'Document unavailable')
    try:
        data = SampleStorage.for_development().read(row['storage_identity'], digest=row['sha256'])
        if len(data) != row['byte_size']:
            raise SampleStorageError('Size mismatch')
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(409, 'Document unavailable') from None
    return row, data

"""Immutable Initial Editing sample artifacts; callers enforce authorization."""
from datetime import datetime, timezone
from importlib import import_module
from uuid import uuid4
import re

from fastapi import HTTPException
from sqlalchemy import text

from app.sample_storage import SampleStorage, SampleStorageError


def require_schema(db):
    migration = import_module('migrations.036_sample_initial_editing')
    conn = db.connection()
    row = conn.execute(text('SELECT 1 FROM schema_migrations WHERE migration_id=:id'), {'id':migration.MIGRATION_ID}).first()
    if not row:
        raise HTTPException(503, 'Sample initial editing storage unavailable')
    for name, expected in migration.DDL.items():
        actual = conn.execute(text('SELECT sql FROM sqlite_master WHERE name=:name'), {'name':name}).first()
        if not actual or not actual[0] or migration.normalize(actual[0]) != migration.normalize(expected):
            raise HTTPException(503, 'Sample initial editing storage unavailable')


def write(db, manuscript_id, extension, content):
    require_schema(db)
    version = uuid4().hex
    fmt = extension.lstrip('.')
    identity = f'sample:v1/initial_editing/{manuscript_id}/{version}.{fmt}'
    try:
        digest = SampleStorage.for_development().write_new(identity, content)
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(503, 'Sample initial editing storage unavailable') from None
    return {'version':version, 'identity':identity, 'sha':digest, 'size':len(content), 'format':fmt}


def bind(db, submission, artifact):
    db.execute(text('''INSERT INTO sample_initial_artifacts
      (submission_id,manuscript_id,editor_id,version_id,storage_identity,sha256,byte_size,file_format,created_at)
      VALUES (:sid,:mid,:editor,:version,:identity,:sha,:size,:format,:created)'''),
      {'sid':submission.submission_id, 'mid':submission.manuscript_id, 'editor':submission.editor_id,
       **artifact, 'created':datetime.now(timezone.utc).isoformat()})


def read(db, submission):
    require_schema(db)
    row = db.execute(text('SELECT * FROM sample_initial_artifacts WHERE submission_id=:sid AND manuscript_id=:mid AND editor_id=:editor'),
        {'sid':submission.submission_id, 'mid':submission.manuscript_id, 'editor':submission.editor_id}).mappings().first()
    if (not row or not re.fullmatch(r'[0-9a-f]{32}', row['version_id'] or '')
            or row['file_format'] not in {'pdf','docx','doc','txt'}
            or row['storage_identity'] != f"sample:v1/initial_editing/{submission.manuscript_id}/{row['version_id']}.{row['file_format']}"
            or row['storage_identity'] != submission.file_path):
        raise HTTPException(409, 'Initial editing document unavailable')
    try:
        data = SampleStorage.for_development().read(row['storage_identity'], digest=row['sha256'])
        if len(data) != row['byte_size']:
            raise SampleStorageError('Size mismatch')
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(409, 'Initial editing document unavailable') from None
    return row, data

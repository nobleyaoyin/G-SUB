"""Trusted ledger operations for registered development-sample manuscripts.

Registration is operator-controlled; no application endpoint accepts a root,
storage identity or registration request from a client.
"""
from importlib import import_module
from datetime import datetime, timezone
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.sample_storage import SampleStorage, SampleStorageError

RESERVED_SAMPLE_MANUSCRIPT = 1000000001


def _schema(db):
    migration = import_module('migrations.035_sample_document_storage')
    conn = db.connection()
    objects = set(inspect(conn).get_table_names())
    names = {'sample_manuscripts', 'sample_document_versions'}
    if 'schema_migrations' not in objects:
        if objects & names:
            raise HTTPException(503, 'Sample document storage unavailable')
        return False
    present = conn.execute(text('SELECT 1 FROM schema_migrations WHERE migration_id=:id'), {'id': migration.MIGRATION_ID}).first()
    if not present:
        if objects & names:
            raise HTTPException(503, 'Sample document storage unavailable')
        return False
    for name, expected in migration.DDL.items():
        row = conn.execute(text('SELECT sql FROM sqlite_master WHERE name=:name'), {'name': name}).first()
        if not row or not row[0] or migration.normalize(row[0]) != migration.normalize(expected):
            raise HTTPException(503, 'Sample document storage unavailable')
    return True


def registered(db, manuscript_id):
    ready = _schema(db)
    if not ready:
        if manuscript_id == RESERVED_SAMPLE_MANUSCRIPT:
            raise HTTPException(503, 'Sample document storage is not provisioned')
        return False
    row = db.execute(text('SELECT 1 FROM sample_manuscripts WHERE manuscript_id=:mid'), {'mid': manuscript_id}).first()
    if not row and manuscript_id == RESERVED_SAMPLE_MANUSCRIPT:
        raise HTTPException(503, 'Sample document storage is not provisioned')
    return bool(row)


def versions(db, manuscript_id):
    rows = db.execute(text('''SELECT version_id,storage_identity,sha256,byte_size,file_format,review_round,created_at
        FROM sample_document_versions WHERE manuscript_id=:mid ORDER BY created_at,version_id'''), {'mid': manuscript_id}).mappings().all()
    for row in rows:
        if (not re.fullmatch(r'[0-9a-f]{32}', row['version_id'] or '')
                or row['file_format'] not in {'pdf', 'docx', 'doc', 'txt'}
                or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'] or '')
                or row['storage_identity'] != f"sample:v1/manuscripts/{manuscript_id}/{row['version_id']}.{row['file_format']}"):
            raise HTTPException(503, 'Sample document history unavailable')
    return rows


def read_version(db, manuscript_id, version_id):
    if not re.fullmatch(r'[0-9a-f]{32}', version_id):
        raise HTTPException(404, 'Document unavailable')
    row = db.execute(text('''SELECT version_id,storage_identity,sha256,byte_size,file_format,review_round,created_at
        FROM sample_document_versions WHERE manuscript_id=:mid AND version_id=:version'''),
        {'mid': manuscript_id, 'version': version_id}).mappings().first()
    if not row or row['storage_identity'] != f"sample:v1/manuscripts/{manuscript_id}/{version_id}.{row['file_format']}":
        raise HTTPException(404, 'Document unavailable')
    try:
        content = SampleStorage.for_development().read(row['storage_identity'], digest=row['sha256'])
        if len(content) != row['byte_size']:
            raise SampleStorageError('Size mismatch')
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(409, 'Document unavailable') from None
    return row, content


def current(db, manuscript):
    ref = manuscript.file_path or ''
    return read_identity(db, manuscript.manuscript_id, ref)


def read_identity(db, manuscript_id, ref):
    if not isinstance(ref, str) or not ref.startswith(f'sample:v1/manuscripts/{manuscript_id}/'):
        raise HTTPException(409, 'Document unavailable')
    match = re.fullmatch(r'sample:v1/manuscripts/[1-9][0-9]*/([0-9a-f]{32})\.(pdf|docx|doc|txt)', ref)
    if not match:
        raise HTTPException(409, 'Document unavailable')
    row, content = read_version(db, manuscript_id, match.group(1))
    if row['storage_identity'] != ref:
        raise HTTPException(409, 'Document unavailable')
    return row, content


def submission_file(db, manuscript, review_round):
    """Return verified immutable evidence for a sample submission transaction."""
    from app.ai_submission import SubmissionFile
    from app.routers.manuscripts import validate_manuscript_file
    row, content = current(db, manuscript)
    if row['review_round'] != review_round:
        raise HTTPException(409, 'Sample document belongs to a different review round')
    validate_manuscript_file('submission.' + row['file_format'], content, historical=True)
    return SubmissionFile(file_ref=row['storage_identity'], file_sha256=row['sha256'], file_format=row['file_format'])


def record_submission(db, manuscript, actor, kind, review_round):
    from app.ai_submission import create_submission_snapshot_job
    from app.submission_snapshot_history import snapshot_rows
    if 'manuscript_submission_snapshots' not in inspect(db.connection()).get_table_names():
        raise HTTPException(503, 'Sample submission history unavailable')
    snapshot_rows(db, manuscript)  # Verify migration and immutable triggers.
    evidence = submission_file(db, manuscript, review_round)
    create_submission_snapshot_job(db, manuscript_id=manuscript.manuscript_id,
        submitted_by=actor.user_id, submission_kind=kind, review_round=review_round,
        submission_file=evidence, queue_ai=False)


def publish(db, manuscript, actor, round_number, extension, content, *, online_source=None, change_note=None):
    version = uuid4().hex
    file_format = extension.lstrip('.')
    identity = f'sample:v1/manuscripts/{manuscript.manuscript_id}/{version}.{file_format}'
    try:
        digest = SampleStorage.for_development().write_new(identity, content)
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(503, 'Sample document storage unavailable') from None
    # If the transaction fails or its outcome is unknown, retain the immutable
    # object: deleting it could destroy a committed version after a lost ack.
    previous = manuscript.file_path
    try:
        db.execute(text('''INSERT INTO sample_document_versions
            (version_id,manuscript_id,storage_identity,sha256,byte_size,file_format,review_round,uploaded_by,created_at)
            VALUES (:id,:mid,:identity,:sha,:size,:format,:round,:actor,:created_at)'''),
            {'id': version, 'mid': manuscript.manuscript_id, 'identity': identity, 'sha': digest,
             'size': len(content), 'format': file_format, 'round': round_number, 'actor': actor.user_id,
             'created_at': datetime.now(timezone.utc).isoformat()})
        result = db.execute(text('''UPDATE manuscripts SET file_path=:identity WHERE manuscript_id=:mid
            AND author_id=:actor AND status=:status AND file_path IS :previous'''),
            {'identity': identity, 'mid': manuscript.manuscript_id, 'actor': actor.user_id,
             'status': manuscript.status, 'previous': previous})
        if result.rowcount != 1:
            raise HTTPException(409, 'Manuscript changed; retry the upload')
        if online_source is not None:
            from app import online_versions
            online_versions.record(db, manuscript.manuscript_id, actor.user_id, 'author', 'author',
                previous, online_source, identity, content, change_note)
        db.commit()
        db.refresh(manuscript)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(503, 'Sample upload outcome unavailable') from None
    return version

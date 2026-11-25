"""Read existing immutable submission snapshots without exposing storage references."""
from importlib import import_module
import hashlib
import re
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import guard_demo_path
from app.controlled_source_authorization import read_bounded_source


def snapshot_rows(db, manuscript):
    """Return verified-schema evidence scoped to the manuscript's current owner."""
    try:
        conn = db.connection()
        tables = set(inspect(conn).get_table_names())
        if 'schema_migrations' not in tables:
            return []
        installed = bool(conn.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='017_ai_prescreening'")).first())
        present = 'manuscript_submission_snapshots' in tables
        if not installed and not present:
            return []
        if not installed or not present:
            raise HTTPException(503, 'Submission history unavailable')
        migration = import_module('migrations.017_ai_prescreening')
        objects = {'manuscript_submission_snapshots': migration.DDL['manuscript_submission_snapshots'],
                   'ai_snapshots_no_update': migration.TRIGGERS['ai_snapshots_no_update'],
                   'ai_snapshots_no_delete': migration.TRIGGERS['ai_snapshots_no_delete']}
        for name, expected in objects.items():
            row = conn.execute(text('SELECT sql FROM sqlite_master WHERE name=:name'), {'name':name}).first()
            if not row or not row[0] or migration.normalize(row[0]) != migration.normalize(expected):
                raise HTTPException(503, 'Submission history unavailable')
        return conn.execute(text('''SELECT snapshot_id, submission_kind, review_round, submission_sequence,
            file_ref, file_sha256, file_format, submitted_at FROM manuscript_submission_snapshots
            WHERE manuscript_id=:mid AND submitted_by=:author ORDER BY submission_sequence'''),
            {'mid':manuscript.manuscript_id, 'author':manuscript.author_id}).mappings().all()
    except HTTPException:
        raise
    except (SQLAlchemyError, ValueError, TypeError):
        raise HTTPException(503, 'Submission history unavailable') from None


def read_snapshot(db, manuscript, snapshot_id, base_dir, extensions, maximum):
    """Verify the stored digest on the exact bounded bytes returned to the caller."""
    if not re.fullmatch(r'[0-9a-f]{32}', snapshot_id):
        raise HTTPException(404, 'Document unavailable')
    row = next((item for item in snapshot_rows(db, manuscript) if item['snapshot_id'] == snapshot_id), None)
    if row is None:
        raise HTTPException(404, 'Document unavailable')
    try:
        if isinstance(row['file_ref'], str) and row['file_ref'].startswith('sample:v1/'):
            from app import sample_documents
            if not sample_documents.registered(db, manuscript.manuscript_id):
                raise HTTPException(409, 'Document unavailable')
            match = re.fullmatch(r'sample:v1/manuscripts/[1-9][0-9]*/([0-9a-f]{32})\.(pdf|docx|doc|txt)', row['file_ref'])
            if not match:
                raise HTTPException(409, 'Document unavailable')
            version, content = sample_documents.read_version(db, manuscript.manuscript_id, match.group(1))
            extension = '.' + row['file_format']
            if (version['storage_identity'] != row['file_ref'] or version['sha256'] != row['file_sha256']
                    or version['file_format'] != row['file_format'] or extension not in extensions or len(content) > maximum):
                raise HTTPException(409, 'Document unavailable')
            return content, extension
        ref = Path(row['file_ref'])
        path = guard_demo_path(ref if ref.is_absolute() else base_dir / ref)
        root = guard_demo_path(base_dir / 'uploads' / 'manuscripts' / str(manuscript.manuscript_id)).resolve()
        extension = path.suffix.lower()
        if (not root.is_relative_to(base_dir.resolve()) or path.parent.resolve() != root or extension not in extensions or
                extension != '.' + row['file_format'] or not re.fullmatch(r'[0-9a-f]{64}', row['file_sha256'])):
            raise HTTPException(409, 'Document unavailable')
        content = read_bounded_source(path, maximum)
        if hashlib.sha256(content).hexdigest() != row['file_sha256']:
            raise HTTPException(409, 'Document integrity unavailable')
        return content, extension
    except HTTPException:
        raise
    except (OSError, ValueError, TypeError, RuntimeError):
        raise HTTPException(409, 'Document unavailable') from None

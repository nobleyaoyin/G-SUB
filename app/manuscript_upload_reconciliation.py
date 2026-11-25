"""Conservative, read-only evidence for manuscript upload reconciliation.

This service intentionally does not delete or move files. Legacy version
history is directory-based, so absence from a request ledger is not evidence
that a file is disposable. Callers must supply a fresh isolated session and
an explicit storage root; the function is not exposed through an HTTP route.
"""
import hashlib
import os
import stat
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.controlled_source_authorization import read_bounded_source
from app.routers.manuscripts import (
    ALLOWED_MANUSCRIPT_EXTENSIONS,
    MAX_MANUSCRIPT_FILE_SIZE,
    _begin_author_submission,
    _require_upload_request_schema,
)


def inspect_manuscript_uploads(db, storage_root, manuscript_id):
    """Return non-destructive evidence; never classify unknown files as safe.

    BEGIN IMMEDIATE excludes other SQLite writers while records are examined.
    Legacy uploads may write files before acquiring their database write lock,
    so every unrecorded filesystem entry remains indeterminate, even under
    that lock. No file contents, original names, or paths are returned.
    """
    root = Path(storage_root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError('An explicit, non-symlink storage root is required')
    if not isinstance(manuscript_id, int) or isinstance(manuscript_id, bool) or manuscript_id <= 0:
        raise ValueError('Invalid manuscript identifier')
    root = root.resolve(strict=True)
    directory = root / 'uploads' / 'manuscripts' / str(manuscript_id)
    _begin_author_submission(db)
    try:
        _require_upload_request_schema(db)
        manuscript = db.execute(text('SELECT file_path FROM manuscripts WHERE manuscript_id=:id'), {'id': manuscript_id}).mappings().first()
        if manuscript is None:
            raise HTTPException(404, 'Manuscript not found.')
        recorded = db.execute(text('SELECT request_id, storage_name, size, sha256 FROM manuscript_upload_requests WHERE manuscript_id=:id ORDER BY request_id'), {'id': manuscript_id}).mappings().all()
        named = set(db.execute(text('SELECT storage_name FROM manuscript_upload_names WHERE manuscript_id=:id'), {'id': manuscript_id}).scalars())
        if directory.is_symlink():
            raise HTTPException(409, 'Manuscript storage is unavailable.')
        if directory.exists() and (not directory.is_dir() or not directory.resolve().is_relative_to(root)):
            raise HTTPException(409, 'Manuscript storage is unavailable.')
        files = {}
        unsafe = 0
        if directory.is_dir():
            for entry in os.scandir(directory):
                try:
                    if entry.is_symlink() or not stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
                        unsafe += 1
                    elif Path(entry.name).suffix.lower() in ALLOWED_MANUSCRIPT_EXTENSIONS:
                        files[entry.name] = Path(entry.path)
                except OSError:
                    unsafe += 1
        results = []
        for row in recorded:
            name = row['storage_name']
            if not isinstance(name, str) or Path(name).name != name:
                raise HTTPException(503, 'Upload evidence is inconsistent.')
            state = 'missing'
            if name in files:
                try:
                    content = read_bounded_source(files[name], MAX_MANUSCRIPT_FILE_SIZE)
                    state = 'verified' if len(content) == row['size'] and hashlib.sha256(content).hexdigest() == row['sha256'] else 'integrity_mismatch'
                except HTTPException:
                    state = 'unavailable'
            results.append({'request_id': row['request_id'], 'state': state})
        current_path = manuscript['file_path']
        current_name = Path(current_path).name if current_path else None
        expected_current = str(Path('uploads') / 'manuscripts' / str(manuscript_id) / current_name) if current_name else None
        if current_path and str(current_path) != expected_current:
            current_state = 'external_or_legacy_reference'
        elif current_name is None:
            current_state = 'none'
        elif current_name not in files:
            current_state = 'missing'
        else:
            current_state = 'present'
        known_names = {row['storage_name'] for row in recorded} | named
        unknown = sorted(hashlib.sha256(name.encode()).hexdigest() for name in files if name not in known_names and name != current_name)
        missing_named = sum(name not in files for name in named)
        return {'recorded': results, 'current': current_state, 'missing_named_versions': missing_named,
                'indeterminate_versions': unknown, 'unsafe_entries': unsafe, 'cleanup_available': False}
    except SQLAlchemyError:
        raise HTTPException(503, 'Upload evidence is unavailable.') from None
    finally:
        db.rollback()

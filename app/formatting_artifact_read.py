"""Verified bytes for an independently authorized formatting artifact."""
import hashlib
from fastapi import HTTPException
from app.config import guard_demo_path
from app.controlled_source_authorization import read_bounded_source


def read_formatting_artifact(submission, manuscript_id, base_dir, allowed_extensions, maximum_size, *, db=None):
    """Return exactly the bytes whose recorded digest was checked, without exposing paths."""
    from app import sample_documents
    if db is not None and sample_documents.registered(db, manuscript_id):
        from app import sample_stage_artifacts
        row, content = sample_stage_artifacts.read(db, 'formatting', submission)
        extension = '.' + row['file_format']
        if extension not in allowed_extensions or len(content) > maximum_size:
            raise HTTPException(409, 'Document unavailable')
        return content, extension
    if isinstance(submission.file_path, str) and submission.file_path.startswith('sample:v1/'):
        raise HTTPException(409, 'Document unavailable')
    root = guard_demo_path(base_dir / 'uploads' / 'formatting' / str(manuscript_id)).resolve()
    path = guard_demo_path(base_dir / submission.file_path).resolve()
    extension = path.suffix.lower()
    if path.parent != root or extension not in allowed_extensions:
        raise HTTPException(404, 'Document unavailable')
    content = read_bounded_source(path, maximum_size)
    if hashlib.sha256(content).hexdigest() != submission.sha256:
        raise HTTPException(409, 'Document integrity unavailable')
    return content, extension

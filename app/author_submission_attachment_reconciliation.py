"""Read-only reconciliation; never deletes or changes attachment files."""
from uuid import UUID

from sqlalchemy import text

from app.routers.author_submission_attachments import _directory
from app.routers.manuscripts import _begin_author_submission


def reconcile(db):
    """Return ledger/file differences while excluding active SQLite writers.

    Caller must have a fresh session. Results are administrative evidence only;
    do not delete candidates automatically or expose this function via HTTP.
    """
    directory = _directory()
    _begin_author_submission(db)
    try:
        recorded = set(db.execute(text("SELECT id FROM author_submission_attachments")).scalars().all())
        present = set()
        for path in directory.iterdir():
            try:
                if path.is_symlink() or not path.is_file() or str(UUID(path.name)) != path.name:
                    continue
            except ValueError:
                continue
            present.add(path.name)
        return {"unrecorded_file_ids": sorted(present - recorded), "missing_file_ids": sorted(recorded - present)}
    finally:
        db.rollback()

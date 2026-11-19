"""Validation and resolution of immutable review-round file references."""
from pathlib import Path
from dataclasses import dataclass
import hashlib
import os
import stat
from app.config import DATA_ROOT, guard_demo_path

from fastapi import HTTPException
from sqlalchemy import select

from app.models import InitialEditingSubmission, PreReviewConfirmation, ReviewAssignmentFile, ReviewRoundFile
from app.reviewer_invitations import may_review
from app.routers.manuscripts import ALLOWED_MANUSCRIPT_EXTENSIONS, MAX_MANUSCRIPT_FILE_SIZE, validate_manuscript_file

BASE_DIR = DATA_ROOT


def _round_location(record, manuscript, db):
    if record.manuscript_id != manuscript.manuscript_id:
        raise HTTPException(409, "Review file is unavailable")
    if record.review_round == 1 and record.source_kind == "initial_editing":
        confirmation = db.get(PreReviewConfirmation, record.confirmation_id)
        submission = db.get(InitialEditingSubmission, confirmation.submission_id) if confirmation else None
        if not (confirmation and submission and confirmation.manuscript_id == manuscript.manuscript_id
                and confirmation.author_id == manuscript.author_id and confirmation.decision == "confirm"
                and submission.manuscript_id == manuscript.manuscript_id and submission.status == "eic_approved"
                and confirmation.file_path == submission.file_path == record.file_path):
            raise HTTPException(409, "Review file is unavailable")
        root = BASE_DIR / "uploads" / "initial_editing" / str(manuscript.manuscript_id)
        allowed = set(ALLOWED_MANUSCRIPT_EXTENSIONS)
    elif record.review_round > 1 and record.source_kind == "author_revision" and record.confirmation_id is None:
        root = BASE_DIR / "uploads" / "manuscripts" / str(manuscript.manuscript_id)
        allowed = set(ALLOWED_MANUSCRIPT_EXTENSIONS)
    else:
        raise HTTPException(409, "Review file is unavailable")
    path = guard_demo_path(BASE_DIR / record.file_path)
    guard_demo_path(root)
    return root, path, allowed


def validate_round_file(record, manuscript, db):
    root, path, allowed = _round_location(record, manuscript, db)
    path = path.resolve()
    if path.parent != root.resolve() or path.suffix.lower() not in allowed or not path.is_file():
        raise HTTPException(409, "Review file is unavailable")
    try:
        with path.open("rb") as file:
            content = file.read(MAX_MANUSCRIPT_FILE_SIZE + 1)
        validate_manuscript_file(path.name, content, historical=True)
    except (OSError, HTTPException):
        raise HTTPException(409, "Review file is unavailable")
    return path


def _assignment_record(db, assignment, manuscript):
    binding = db.get(ReviewAssignmentFile, assignment.assignment_id)
    record = db.get(ReviewRoundFile, binding.round_file_id) if binding else None
    if not record or not may_review(db, assignment) or assignment.status not in ("assigned", "completed") or record.review_round != assignment.review_round:
        raise HTTPException(409, "Review file is unavailable; contact the editorial team")
    return record


def resolve_assignment_file(db, assignment, manuscript):
    return validate_round_file(_assignment_record(db, assignment, manuscript), manuscript, db)


@dataclass(frozen=True)
class ReviewFileSnapshot:
    content: bytes
    extension: str
    sha256: str


def snapshot_assignment_file(db, assignment, manuscript):
    """Read and validate one bounded descriptor-backed immutable byte snapshot."""
    record = _assignment_record(db, assignment, manuscript)
    return snapshot_round_file(db, record, manuscript)


def snapshot_round_file(db, record, manuscript):
    """Snapshot a previously authorized round record; caller owns authorization."""
    root, path, allowed = _round_location(record, manuscript, db)
    try:
        if not all(hasattr(os, flag) for flag in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK')) or os.open not in os.supports_dir_fd:
            raise OSError('Secure descriptor opening unavailable')
        base = Path(os.path.abspath(BASE_DIR))
        path = Path(os.path.abspath(path))
        root = Path(os.path.abspath(root))
        relative = path.relative_to(base)
        if path.parent != root or '..' in Path(record.file_path).parts or path.suffix.lower() not in allowed:
            raise OSError('Invalid review file path')
        parts = base.parts[1:] + relative.parts
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(base.anchor, flags)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, flags, dir_fd=directory)
                os.close(directory)
                directory = next_fd
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > MAX_MANUSCRIPT_FILE_SIZE:
                    raise OSError('Invalid review file')
                chunks = []
                remaining = MAX_MANUSCRIPT_FILE_SIZE + 1
                while remaining:
                    chunk = os.read(fd, min(remaining, 65536))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                content = b''.join(chunks)
                after = os.fstat(fd)
                if (len(content) != before.st_size or len(content) > MAX_MANUSCRIPT_FILE_SIZE or
                    (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                    raise OSError('Review file changed while reading')
            finally:
                os.close(fd)
        finally:
            os.close(directory)
        validate_manuscript_file(path.name, content, historical=True)
        return ReviewFileSnapshot(content, path.suffix.lower(), hashlib.sha256(content).hexdigest())
    except (OSError, ValueError, HTTPException):
        raise HTTPException(409, 'Review file unavailable') from None


def get_or_create_round_one(db, manuscript):
    record = db.scalar(select(ReviewRoundFile).where(ReviewRoundFile.manuscript_id == manuscript.manuscript_id, ReviewRoundFile.review_round == 1))
    if record:
        validate_round_file(record, manuscript, db)
        return record
    confirmations = db.scalars(select(PreReviewConfirmation).join(InitialEditingSubmission, PreReviewConfirmation.submission_id == InitialEditingSubmission.submission_id).where(
        PreReviewConfirmation.manuscript_id == manuscript.manuscript_id,
        PreReviewConfirmation.author_id == manuscript.author_id,
        PreReviewConfirmation.decision == "confirm",
        InitialEditingSubmission.manuscript_id == manuscript.manuscript_id,
        InitialEditingSubmission.status == "eic_approved",
    )).all()
    if len(confirmations) != 1:
        raise HTTPException(409, "A unique confirmed review file is required")
    confirmation = confirmations[0]
    record = ReviewRoundFile(manuscript_id=manuscript.manuscript_id, review_round=1, source_kind="initial_editing", confirmation_id=confirmation.confirmation_id, file_path=confirmation.file_path)
    validate_round_file(record, manuscript, db)
    db.add(record)
    db.flush()
    return record

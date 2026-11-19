"""Prepare manuscript submission snapshots and queue advisory AI jobs.

Database writes participate in the caller's submission transaction.
This module does not execute AI analysis or commit transactions.
"""

from dataclasses import dataclass
import hashlib
import os
import stat
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


MAX_FILE_SIZE = 10 * 1024 * 1024
SUPPORTED_FORMATS = {"txt", "docx", "pdf", "doc"}


@dataclass(frozen=True)
class SubmissionFile:
    file_ref: str
    file_sha256: str
    file_format: str


def prepare_submission_file(
    stored_path: str,
    *,
    resolve_path,
) -> SubmissionFile:
    """Validate and hash the actual file selected for formal submission."""
    if not stored_path:
        raise ValueError("Submission file reference is missing")

    path = resolve_path(stored_path)

    if not isinstance(path, Path):
        raise TypeError("File resolver must return pathlib.Path")

    file_format = path.suffix.lower().lstrip(".")
    if file_format not in SUPPORTED_FORMATS:
        raise ValueError("Unsupported manuscript file format")

    # Reject a symbolic link at the final path component.
    # Parent directories must still be checked by the trusted resolver.
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("Secure no-follow file opening is unavailable")

    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK

    fd = os.open(path, flags)

    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())

        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Submission file is not a regular file")

        if before.st_size == 0:
            raise ValueError("Submission file is empty")

        if before.st_size > MAX_FILE_SIZE:
            raise ValueError("Submission file exceeds size limit")

        digest = hashlib.sha256()
        total = 0

        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break

            total += len(chunk)

            if total > MAX_FILE_SIZE:
                raise ValueError("Submission file exceeds size limit")

            digest.update(chunk)

        after = os.fstat(handle.fileno())

        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or total != after.st_size
        ):
            raise ValueError("Submission file changed during reading")

    if total == 0:
        raise ValueError("Submission file is empty")

    return SubmissionFile(
        file_ref=stored_path,
        file_sha256=digest.hexdigest(),
        file_format=file_format,
    )


def create_submission_snapshot_job(
    db,
    *,
    manuscript_id: int,
    submitted_by: int,
    submission_kind: str,
    review_round: int,
    submission_file: SubmissionFile,
    online_version_id: str | None = None,
) -> tuple[str, str]:
    """Insert one immutable snapshot and pending job without committing.

    Caller must already hold a SQLite BEGIN IMMEDIATE transaction.
    """

    if submission_kind not in {
        "initial",
        "initial_revision",
        "peer_revision",
    }:
        raise ValueError("Invalid submission kind")

    if review_round <= 0:
        raise ValueError("Invalid review round")

    if manuscript_id <= 0 or submitted_by <= 0:
        raise ValueError("Invalid manuscript or author ID")

    connection = db.connection()

    if connection.dialect.name != "sqlite":
        raise RuntimeError("SQLite transaction required")

    raw_connection = connection.connection.driver_connection

    if not raw_connection.in_transaction:
        raise RuntimeError("Active submission transaction required")

    sequence = db.execute(
        text(
            "SELECT COALESCE(MAX(submission_sequence), 0) + 1 "
            "FROM manuscript_submission_snapshots "
            "WHERE manuscript_id = :mid"
        ),
        {"mid": manuscript_id},
    ).scalar_one()

    snapshot_id = uuid4().hex
    job_id = uuid4().hex
    timestamp = datetime.now(timezone.utc).isoformat()

    db.execute(
        text(
            "INSERT INTO manuscript_submission_snapshots "
            "(snapshot_id, manuscript_id, submitted_by, "
            "submission_kind, review_round, submission_sequence, "
            "file_ref, file_sha256, file_format, "
            "online_version_id, submitted_at) "
            "VALUES (:snapshot_id, :manuscript_id, :submitted_by, "
            ":submission_kind, :review_round, :sequence, "
            ":file_ref, :file_sha256, :file_format, "
            ":online_version_id, :submitted_at)"
        ),
        {
            "snapshot_id": snapshot_id,
            "manuscript_id": manuscript_id,
            "submitted_by": submitted_by,
            "submission_kind": submission_kind,
            "review_round": review_round,
            "sequence": sequence,
            "file_ref": submission_file.file_ref,
            "file_sha256": submission_file.file_sha256,
            "file_format": submission_file.file_format,
            "online_version_id": online_version_id,
            "submitted_at": timestamp,
        },
    )

    db.execute(
        text(
            "INSERT INTO ai_prescreening_jobs "
            "(job_id, snapshot_id, status, "
            "attempt_count, max_attempts, created_at, updated_at) "
            "VALUES (:job_id, :snapshot_id, 'pending', "
            "0, 3, :created_at, :updated_at)"
        ),
        {
            "job_id": job_id,
            "snapshot_id": snapshot_id,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )

    return snapshot_id, job_id



def try_create_submission_job(
    db,
    *,
    enabled: bool,
    manuscript_id: int,
    submitted_by: int,
    submission_kind: str,
    review_round: int,
    stored_path: str,
    resolve_path,
    online_version_id: str | None = None,
) -> str:
    """Queue advisory prescreening within an existing submission transaction.

Return 'disabled' when the feature is off, or 'pending' after
creating the snapshot and job. Never commit the session.
When enabled, database failures propagate to the caller."""
    if not enabled:
        return "disabled"

    connection = db.connection()

    if connection.dialect.name != "sqlite":
        raise RuntimeError("SQLite submission transaction required")

    raw_connection = connection.connection.driver_connection

    if not raw_connection.in_transaction:
        raise RuntimeError("Active submission transaction required")

    submission_file = prepare_submission_file(
        stored_path,
        resolve_path=resolve_path,
    )

    try:
        with db.begin_nested():
            create_submission_snapshot_job(
                db,
                manuscript_id=manuscript_id,
                submitted_by=submitted_by,
                submission_kind=submission_kind,
                review_round=review_round,
                submission_file=submission_file,
                online_version_id=online_version_id,
            )
    except IntegrityError:
        # Do not suppress unexpected database integrity violations.
        # The SAVEPOINT rolls back AI writes; the caller owns the
        # surrounding submission transaction and its rollback.
        raise

    return "pending"

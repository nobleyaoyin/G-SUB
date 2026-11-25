"""Private draft attachments; configured explicitly and never reviewer-facing."""
import hashlib
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.filename_headers import normalize_upload_filename
from app.models import User
from app.config import PROJECT_ROOT
from app.reviewer_artifact_storage import StorageError, _open_private_directory
from app.routers.users import require_role
from app.routers.manuscripts import _begin_author_submission, validate_manuscript_file

router = APIRouter(prefix="/author/submission-drafts", tags=["author submission attachments"])


def _open_attachment_directory(directory):
    """Pin a private, non-public store directory without following symlinks."""
    try:
        project = PROJECT_ROOT.resolve(strict=True)
        if directory == project or directory.is_relative_to(project) or project.is_relative_to(directory):
            raise ValueError('Private attachment store overlaps the application')
        return _open_private_directory(directory)
    except (OSError, ValueError, StorageError):
        raise HTTPException(503, "Attachments are not available.") from None


def _directory():
    root = os.environ.get("GSUB_SUBMISSION_ATTACHMENT_ROOT")
    directory = Path(root) if root else None
    if directory is None or not directory.is_absolute():
        raise HTTPException(503, "Attachments are not available.")
    fd = _open_attachment_directory(directory)
    os.close(fd)
    return directory


def _policy():
    formats = os.environ.get("GSUB_SUBMISSION_ATTACHMENT_FORMATS")
    maximum = os.environ.get("GSUB_SUBMISSION_ATTACHMENT_MAX_BYTES")
    try:
        size = int(maximum or "")
    except ValueError:
        raise HTTPException(503, "Attachments are not configured.")
    extensions = {item.strip().lower().lstrip(".") for item in (formats or "").split(",") if item.strip()}
    # Reuse the existing content validator and its technical 10 MiB ceiling.
    if not extensions or not extensions <= {"pdf", "docx", "doc", "txt"} or not 0 < size <= 10 * 1024 * 1024:
        raise HTTPException(503, "Attachments are not configured.")
    return _directory(), extensions, size


def _draft(db, draft_id, author_id, writable=False):
    try:
        row = db.execute(text("SELECT d.id, l.manuscript_id, m.status FROM author_submission_drafts d LEFT JOIN author_submission_links l ON l.draft_id=d.id LEFT JOIN manuscripts m ON m.manuscript_id=l.manuscript_id WHERE d.id=:id AND d.author_id=:author"), {"id": str(draft_id), "author": author_id}).mappings().first()
    except OperationalError:
        raise HTTPException(503, "Attachments are not available yet.")
    if row is None:
        raise HTTPException(404, "Draft not found.")
    if row["manuscript_id"] is not None and row["status"] is None:
        raise HTTPException(503, "Attachments are not available yet.")
    if writable and row["status"] is not None and row["status"] != "draft":
        raise HTTPException(409, "Attachments cannot be changed after submission.")


def _attachment(db, draft_id, attachment_id):
    try:
        row = db.execute(text("SELECT id, kind, filename, media_type, size, sha256, created_at, supersedes, removed_at FROM author_submission_attachments WHERE draft_id=:draft AND id=:id"), {"draft": str(draft_id), "id": str(attachment_id)}).mappings().first()
    except OperationalError:
        raise HTTPException(503, "Attachments are not available yet.")
    if row is None:
        raise HTTPException(404, "Attachment not found.")
    return row


@router.get("/{draft_id}/attachments")
def list_attachments(draft_id: UUID, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("author"))):
    response.headers["Cache-Control"] = "no-store"
    _draft(db, draft_id, user.user_id)
    try:
        rows = db.execute(text("SELECT id, kind, filename, media_type, size, created_at, supersedes, removed_at FROM author_submission_attachments WHERE draft_id=:draft ORDER BY created_at, id"), {"draft": str(draft_id)}).mappings().all()
    except OperationalError:
        raise HTTPException(503, "Attachments are not available yet.")
    return [dict(row) for row in rows]


@router.post("/{draft_id}/attachments", status_code=201)
async def upload_attachment(draft_id: UUID, response: Response, kind: str = Form(...), file: UploadFile = File(...), replaces: UUID | None = Form(None), request_id: UUID | None = Form(None), db: Session = Depends(get_db), user: User = Depends(require_role("author"))):
    response.headers["Cache-Control"] = "no-store"
    if kind not in {"cover_letter", "supplementary"}:
        raise HTTPException(422, "Choose a valid attachment type.")
    _draft(db, draft_id, user.user_id, writable=True)
    directory, formats, maximum = _policy()
    try:
        filename = normalize_upload_filename(file.filename)
    except ValueError:
        raise HTTPException(400, 'Choose a file with a valid filename.') from None
    if not filename or len(filename) > 255 or any(ord(char) < 32 for char in filename) or Path(filename).suffix.lower().lstrip(".") not in formats:
        raise HTTPException(400, "This file format is not supported.")
    content = await file.read(maximum + 1)
    if len(content) > maximum:
        raise HTTPException(413, "This file is too large.")
    _, media_type = validate_manuscript_file(filename, content)
    attachment_id = str(request_id or uuid4())
    digest = hashlib.sha256(content).hexdigest()
    created_file = False
    commit_attempted = False
    directory_fd = _open_attachment_directory(directory)
    try:
        _begin_author_submission(db)
        try:
            _draft(db, draft_id, user.user_id, writable=True)
            if request_id:
                existing = db.execute(text("SELECT draft_id, kind, filename, size, sha256, supersedes FROM author_submission_attachments WHERE id=:id"), {"id": attachment_id}).mappings().first()
                if existing:
                    try:
                        matching_name = normalize_upload_filename(existing['filename']) == filename
                    except ValueError:
                        matching_name = False
                    if existing["draft_id"] != str(draft_id) or existing["kind"] != kind or not matching_name or existing["size"] != len(content) or existing["sha256"] != digest or existing["supersedes"] != (str(replaces) if replaces else None):
                        raise HTTPException(409, "This upload request conflicts with an existing attachment.")
                    row = dict(_attachment(db, draft_id, attachment_id))
                    db.rollback()
                    response.status_code = 200
                    return row
            if replaces:
                previous = _attachment(db, draft_id, replaces)
                if previous["kind"] != kind or previous["removed_at"]:
                    raise HTTPException(409, "This attachment cannot be replaced.")
            elif kind == "cover_letter" and db.execute(text("SELECT 1 FROM author_submission_attachments WHERE draft_id=:draft AND kind='cover_letter' AND removed_at IS NULL"), {"draft": str(draft_id)}).first():
                raise HTTPException(409, "Replace the existing cover letter instead.")
            fd = os.open(attachment_id, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            created_file = True
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
            now = datetime.now(timezone.utc).isoformat()
            if replaces:
                db.execute(text("UPDATE author_submission_attachments SET removed_at=:now WHERE id=:id AND draft_id=:draft"), {"now": now, "id": str(replaces), "draft": str(draft_id)})
            db.execute(text("INSERT INTO author_submission_attachments (id,draft_id,kind,filename,media_type,size,sha256,created_at,supersedes) VALUES (:id,:draft,:kind,:filename,:media,:size,:digest,:created,:previous)"), {"id": attachment_id, "draft": str(draft_id), "kind": kind, "filename": filename, "media": media_type, "size": len(content), "digest": digest, "created": now, "previous": str(replaces) if replaces else None})
            commit_attempted = True
            db.commit()
        except Exception as exc:
            db.rollback()
            if created_file and not commit_attempted:
                try:
                    os.unlink(attachment_id, dir_fd=directory_fd)
                except OSError:
                    pass  # Reconciliation can report any leftover unrecorded file.
            if isinstance(exc, (OperationalError, OSError)):
                raise HTTPException(503, "Attachments are not available yet.")
            raise
        return dict(_attachment(db, draft_id, attachment_id))
    finally:
        os.close(directory_fd)


@router.get("/{draft_id}/attachments/{attachment_id}")
def download_attachment(draft_id: UUID, attachment_id: UUID, db: Session = Depends(get_db), user: User = Depends(require_role("author"))):
    _draft(db, draft_id, user.user_id)
    row = _attachment(db, draft_id, attachment_id)
    directory = _directory()
    directory_fd = _open_attachment_directory(directory)
    try:
        fd = os.open(str(attachment_id), os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=directory_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                raise OSError("not a file")
            content = stream.read(10 * 1024 * 1024 + 1)
    except OSError:
        raise HTTPException(404, "Attachment is unavailable.")
    finally:
        os.close(directory_fd)
    if len(content) != row["size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
        raise HTTPException(409, "Attachment is unavailable.")
    from app.filename_headers import content_disposition
    extension = Path(row['filename']).suffix.lower()
    fallback = 'attachment' + (extension if extension in ('.pdf', '.docx', '.doc', '.txt') else '.bin')
    return Response(content, media_type=row["media_type"], headers={"Cache-Control": "no-store", "Content-Disposition": content_disposition(row['filename'], fallback)})


@router.delete("/{draft_id}/attachments/{attachment_id}", status_code=204)
def remove_attachment(draft_id: UUID, attachment_id: UUID, db: Session = Depends(get_db), user: User = Depends(require_role("author"))):
    _begin_author_submission(db)
    try:
        _draft(db, draft_id, user.user_id, writable=True)
        row = _attachment(db, draft_id, attachment_id)
        if row["removed_at"] is None:
            db.execute(text("UPDATE author_submission_attachments SET removed_at=:now WHERE id=:id AND draft_id=:draft"), {"now": datetime.now(timezone.utc).isoformat(), "id": str(attachment_id), "draft": str(draft_id)})
        db.commit()
    except Exception as exc:
        db.rollback()
        if isinstance(exc, OperationalError):
            raise HTTPException(503, "Attachments are not available yet.")
        raise
    return Response(status_code=204, headers={"Cache-Control": "no-store"})

"""Fail-closed integration checks for manuscripts linked to private drafts."""
import hashlib
import json
import os
import stat
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.submission_type_config import available_submission_types
from app.author_submission_policy import submission_policy, validate_authors


def _field_error(step, field, message):
    raise HTTPException(422, detail={"code": "submission_validation", "errors": [{"step": step, "field": field, "message": message}]})


def linked_draft(db, manuscript_id):
    try:
        present = db.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='author_submission_links'")).first()
        if not present:
            ledger = db.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'")).first()
            if ledger and db.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='042_author_submission_linkage'")).first():
                raise HTTPException(503, "Submission information is unavailable.")
            return None
        row = db.execute(text("SELECT d.id, d.author_id, d.payload, d.revision FROM author_submission_links l LEFT JOIN author_submission_drafts d ON d.id=l.draft_id WHERE l.manuscript_id=:id"), {"id": manuscript_id}).mappings().first()
        if row is not None and row["id"] is None:
            raise HTTPException(503, "Submission information is unavailable.")
        return row
    except SQLAlchemyError:
        raise HTTPException(503, "Submission information is unavailable.")


def validate_linked_submission(db, manuscript, expected_revision=None):
    row = linked_draft(db, manuscript.manuscript_id)
    if row is None:
        return
    if expected_revision is None:
        raise HTTPException(428, "Reload the submission and provide its saved revision.")
    if expected_revision != row["revision"]:
        raise HTTPException(409, "This submission changed. Reload before submitting.")
    if row["author_id"] != manuscript.author_id:
        raise HTTPException(409, "Submission information is inconsistent.")
    try:
        payload = json.loads(row["payload"])
    except (ValueError, TypeError):
        raise HTTPException(503, "Submission information is unavailable.")
    if not isinstance(payload, dict) or not isinstance(payload.get("title"), str) or not isinstance(payload.get("abstract"), str) or payload["title"].strip() != manuscript.title or payload["abstract"].strip() != manuscript.abstract:
        raise HTTPException(409, "Submission information changed. Reload before submitting.")
    if payload.get("submission_type") not in available_submission_types():
        _field_error(2, "submission_type", "Choose an available submission type.")
    policy = submission_policy()
    author_errors = validate_authors(payload, policy)
    if author_errors:
        raise HTTPException(422, detail={"code": "submission_validation", "errors": author_errors})
    keywords = payload.get("keywords") or []
    if not isinstance(keywords, list) or (policy["keywords_required"] and not keywords) or any(not isinstance(k, str) or not k.strip() for k in keywords):
        _field_error(6, "keywords", "Add at least one keyword.")
    if len({keyword.strip().casefold() for keyword in keywords}) != len(keywords):
        _field_error(6, "keywords", "Remove duplicate keywords.")
    try:
        attachments = db.execute(text("SELECT id, kind, size, sha256 FROM author_submission_attachments WHERE draft_id=:draft AND removed_at IS NULL"), {"draft": row["id"]}).mappings().all()
        supplementary = db.execute(text("SELECT 1 FROM author_submission_attachments WHERE draft_id=:draft AND kind='supplementary' AND removed_at IS NULL LIMIT 1"), {"draft": row["id"]}).first()
    except SQLAlchemyError:
        raise HTTPException(503, "Submission attachments are unavailable.")
    if policy["cover_letter_required"] and not (isinstance(payload.get("cover_letter"), str) and payload["cover_letter"].strip()) and not any(item["kind"] == "cover_letter" for item in attachments):
        raise HTTPException(422, detail={"code": "submission_validation", "errors": [{"step": 9, "field": "cover_letter", "message": "Add a cover letter."}]})
    info = payload.get("manuscript_information") or {}
    if isinstance(info, dict) and info.get("has_supplementary_files") is True and not supplementary:
        _field_error(10, "supplementary_files", "Add the supplementary files or update your selection.")
    if attachments:
        from app.routers.author_submission_attachments import _directory, _open_attachment_directory
        directory_fd = _open_attachment_directory(_directory())
        try:
            for attachment in attachments:
                try:
                    name = str(UUID(attachment["id"]))
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=directory_fd)
                    with os.fdopen(fd, "rb") as stream:
                        info = os.fstat(stream.fileno())
                        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                                or stat.S_IMODE(info.st_mode) & 0o077):
                            raise OSError("not a private file")
                        content = stream.read(10 * 1024 * 1024 + 1)
                    if len(content) != attachment["size"] or hashlib.sha256(content).hexdigest() != attachment["sha256"]:
                        raise OSError("integrity mismatch")
                except (OSError, ValueError, TypeError):
                    raise HTTPException(409, "A submission attachment is unavailable. Check your files before submitting.")
        finally:
            os.close(directory_fd)

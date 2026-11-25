"""Owner-only storage for incomplete submissions, separate from reviewer DTOs.

This foundation does not submit manuscripts or change the existing wizard.
"""
import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.routers.users import require_role
from app.submission_type_config import available_submission_types
from app.author_submission_errors import SubmissionValidationRoute

router = APIRouter(prefix="/author/submission-drafts", tags=["author submission drafts"], route_class=SubmissionValidationRoute)
logger = logging.getLogger(__name__)


class CreateDraft(BaseModel):
    request_id: UUID


class LinkDraft(BaseModel):
    revision: int = Field(ge=0)


class DraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Institution(DraftModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = None
    department: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None


class SubmissionPerson(DraftModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prefix: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    orcid: str | None = None
    institutions: list[Institution] | None = None


class SubmissionFunding(DraftModel):
    has_funding: bool | None = None
    name: str | None = None
    award_number: str | None = None


class SubmissionInformation(DraftModel):
    figures: int | None = Field(default=None, ge=0, strict=True)
    tables: int | None = Field(default=None, ge=0, strict=True)
    words: int | None = Field(default=None, ge=0, strict=True)
    previously_submitted: bool | None = None
    has_supplementary_files: bool | None = None


class SubmissionPayload(DraftModel):
    submission_type: str | None = None
    title: str | None = None
    running_head: str | None = None
    abstract: str | None = None
    keywords: list[str] | None = None
    corresponding_author: SubmissionPerson | None = None
    corresponding_author_position: int | None = Field(default=None, ge=0, strict=True)
    coauthors: list[SubmissionPerson] | None = None
    cover_letter: str | None = None
    funding: SubmissionFunding | None = None
    manuscript_information: SubmissionInformation | None = None


class UpdateDraft(BaseModel):
    revision: int = Field(ge=0)
    current_step: int = Field(ge=1, le=10)
    payload: SubmissionPayload


def _read(db, author_id, draft_id):
    try:
        return db.execute(text("SELECT id, revision, current_step, payload, created_at, updated_at FROM author_submission_drafts WHERE id=:id AND author_id=:author"), {"id": str(draft_id), "author": author_id}).mappings().first()
    except OperationalError as exc:
        logger.error("Submission draft lookup failed: %s", exc.orig)
        raise HTTPException(503, "Submission drafts are not available yet.")


def _view(row):
    payload = json.loads(row["payload"])
    corresponding = payload.get("corresponding_author")
    coauthors = payload.get("coauthors") or []
    position = payload.get("corresponding_author_position")
    ordered = None
    if isinstance(corresponding, dict) and isinstance(coauthors, list) and type(position) is int and 0 <= position <= len(coauthors):
        ordered = [{**person, "is_corresponding": False} for person in coauthors]
        ordered.insert(position, {**corresponding, "is_corresponding": True})
    return {**dict(row), "payload": payload, "ordered_authors": ordered}


@router.get("/configuration")
def configuration(response: Response, user: User = Depends(require_role("author"))):
    response.headers["Cache-Control"] = "no-store"
    return {"submission_types": available_submission_types()}


@router.get("/requirements")
def requirements(response: Response, user: User = Depends(require_role("author"))):
    from app.author_submission_policy import submission_policy
    response.headers["Cache-Control"] = "no-store"
    return submission_policy()


@router.post("", status_code=201)
def create_draft(data: CreateDraft, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("author"))):
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc).isoformat()
    draft_id = str(uuid4())
    try:
        db.execute(text("INSERT INTO author_submission_drafts (id, author_id, request_id, created_at, updated_at) VALUES (:id, :author, :request, :now, :now)"), {"id": draft_id, "author": user.user_id, "request": str(data.request_id), "now": now})
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.execute(text("SELECT id FROM author_submission_drafts WHERE author_id=:author AND request_id=:request"), {"author": user.user_id, "request": str(data.request_id)}).first()
        if row is None:
            raise HTTPException(409, "Could not create the draft.")
        draft_id = row.id
        response.status_code = 200
    except OperationalError as exc:
        db.rollback()
        logger.error("Submission draft creation failed: %s", exc.orig)
        raise HTTPException(503, "Submission drafts are not available yet.")
    return _view(_read(db, user.user_id, draft_id))


@router.get("")
def list_drafts(response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("author"))):
    response.headers["Cache-Control"] = "no-store"
    try:
        rows = db.execute(text("SELECT id, revision, current_step, payload, created_at, updated_at FROM author_submission_drafts WHERE author_id=:author ORDER BY updated_at DESC, id"), {"author": user.user_id}).mappings().all()
    except OperationalError as exc:
        logger.error("Submission draft listing failed: %s", exc.orig)
        raise HTTPException(503, "Submission drafts are not available yet.")
    return [_view(row) for row in rows]


@router.get("/{draft_id}")
def get_draft(draft_id: UUID, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("author"))):
    response.headers["Cache-Control"] = "no-store"
    row = _read(db, user.user_id, draft_id)
    if row is None:
        raise HTTPException(404, "Draft not found.")
    return _view(row)


@router.post("/{draft_id}/link")
def link_manuscript(draft_id: UUID, data: LinkDraft, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("author"))):
    from app.author_submission_linkage import link_draft
    response.headers["Cache-Control"] = "no-store"
    return {"manuscript_id": link_draft(db, draft_id, user.user_id, data.revision)}


@router.put("/{draft_id}")
def update_draft(draft_id: UUID, data: UpdateDraft, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("author"))):
    response.headers["Cache-Control"] = "no-store"
    from app.routers.manuscripts import _begin_author_submission
    from app.schemas import ManuscriptCreate
    _begin_author_submission(db)
    current = _read(db, user.user_id, draft_id)
    if current is None:
        raise HTTPException(404, "Draft not found.")
    if current["revision"] != data.revision:
        raise HTTPException(409, "This draft has changed. Reload it before saving.")
    linked = None
    try:
        has_links = db.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='author_submission_links'")).first()
        if has_links:
            linked = db.execute(text("SELECT l.manuscript_id, m.status, m.author_id, m.title, m.abstract FROM author_submission_links l LEFT JOIN manuscripts m ON m.manuscript_id=l.manuscript_id WHERE l.draft_id=:id"), {"id": str(draft_id)}).mappings().first()
            if linked and linked["status"] is None:
                raise HTTPException(503, "Submission drafts are not available yet.")
            if linked and linked["status"] != "draft":
                raise HTTPException(409, "This submission can no longer be edited.")
            if linked and linked["author_id"] != user.user_id:
                raise HTTPException(409, "Submission information is inconsistent.")
    except OperationalError:
        raise HTTPException(503, "Submission drafts are not available yet.")
    selected = data.payload.submission_type
    previous = json.loads(current["payload"]).get("submission_type")
    # Preserve an existing value if an administrator later retires it. A new
    # selection must be configured; final submission must revalidate it.
    if selected is not None and selected != previous and selected not in available_submission_types():
        raise HTTPException(422, detail={"code": "submission_validation", "errors": [{"step": 2, "field": "submission_type", "message": "Choose an available submission type."}]})
    if linked:
        old = json.loads(current["payload"])
        if not isinstance(old.get("title"), str) or not isinstance(old.get("abstract"), str) or old["title"].strip() != linked["title"] or old["abstract"].strip() != linked["abstract"]:
            raise HTTPException(409, "Submission information changed. Reload before saving.")
        try:
            fields = ManuscriptCreate(title=data.payload.title, abstract=data.payload.abstract)
        except ValidationError:
            raise HTTPException(422, "Title and abstract are required for this draft.")
    try:
        payload = json.dumps(data.payload.model_dump(exclude_unset=True), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        raise HTTPException(422, "Draft information is invalid.")
    if len(payload.encode("utf-8")) > 1024 * 1024:
        raise HTTPException(413, "Draft information is too large.")
    try:
        result = db.execute(text("UPDATE author_submission_drafts SET payload=:payload, current_step=:step, revision=revision+1, updated_at=:now WHERE id=:id AND author_id=:author AND revision=:revision"), {"payload": payload, "step": data.current_step, "now": datetime.now(timezone.utc).isoformat(), "id": str(draft_id), "author": user.user_id, "revision": data.revision})
        if not result.rowcount:
            row = _read(db, user.user_id, draft_id)
            db.rollback()
            raise HTTPException(409 if row else 404, "This draft has changed. Reload it before saving." if row else "Draft not found.")
        if linked:
            result = db.execute(text("UPDATE manuscripts SET title=:title, abstract=:abstract WHERE manuscript_id=:id AND author_id=:author AND status='draft' AND title=:old_title AND abstract=:old_abstract"), {"title": fields.title, "abstract": fields.abstract, "id": linked["manuscript_id"], "author": user.user_id, "old_title": linked["title"], "old_abstract": linked["abstract"]})
            if result.rowcount != 1:
                db.rollback()
                raise HTTPException(409, "Submission information changed. Reload before saving.")
        db.commit()
    except OperationalError:
        db.rollback()
        raise HTTPException(503, "Submission drafts are not available yet.")
    return _view(_read(db, user.user_id, draft_id))


def _merge_partial(existing, changes):
    result = dict(existing)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_partial(result[key], value)
        else:
            result[key] = value
    return result


@router.patch("/{draft_id}")
def patch_draft(draft_id: UUID, data: UpdateDraft, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("author"))):
    current = _read(db, user.user_id, draft_id)
    if current is None:
        raise HTTPException(404, "Draft not found.")
    if current["revision"] != data.revision:
        raise HTTPException(409, "This draft has changed. Reload it before saving.")
    merged = _merge_partial(json.loads(current["payload"]), data.payload.model_dump(exclude_unset=True))
    replacement = UpdateDraft(revision=data.revision, current_step=data.current_step, payload=SubmissionPayload.model_validate(merged))
    return update_draft(draft_id, replacement, response, db, user)

"""Transactional linkage from a private draft to an ordinary manuscript."""
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.models import Manuscript
from app.schemas import ManuscriptCreate
from app.routers.manuscripts import _begin_author_submission


def link_draft(db, draft_id, author_id, expected_revision=None):
    """Create one ordinary manuscript draft atomically, without submitting it.

    The caller must not have begun a transaction.
    """
    _begin_author_submission(db)
    try:
        row = db.execute(text("SELECT payload, revision FROM author_submission_drafts WHERE id=:id AND author_id=:author"), {"id": str(draft_id), "author": author_id}).mappings().first()
        if row is None:
            raise HTTPException(404, "Draft not found.")
        if expected_revision is not None and row["revision"] != expected_revision:
            raise HTTPException(409, "This draft has changed. Reload before continuing.")
        linked = db.execute(text("SELECT manuscript_id FROM author_submission_links WHERE draft_id=:id"), {"id": str(draft_id)}).scalar_one_or_none()
        if linked is not None:
            db.rollback()
            return linked
        payload = json.loads(row["payload"])
        try:
            fields = ManuscriptCreate(title=payload.get("title"), abstract=payload.get("abstract"))
        except ValidationError as error:
            fields = []
            for item in error.errors():
                name = item['loc'][0]
                fields.append({'step': 3 if name == 'title' else 4, 'field': name, 'message': 'Enter a valid title.' if name == 'title' else 'Enter an abstract.'})
            raise HTTPException(422, detail={'code': 'submission_validation', 'errors': fields})
        manuscript = Manuscript(title=fields.title, abstract=fields.abstract, author_id=author_id, status="draft", review_round=1)
        db.add(manuscript)
        db.flush()
        db.execute(text("INSERT INTO author_submission_links (draft_id, manuscript_id, created_at) VALUES (:draft, :manuscript, :created)"), {"draft": str(draft_id), "manuscript": manuscript.manuscript_id, "created": datetime.now(timezone.utc).isoformat()})
        db.commit()
        return manuscript.manuscript_id
    except OperationalError:
        db.rollback()
        raise HTTPException(503, "Submission drafts are not available yet.")
    except Exception:
        db.rollback()
        raise

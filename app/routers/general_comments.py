"""Staff-only manuscript general comments."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User,
    Manuscript,
    GeneralComment,
    InitialEditorInvitation,
    FinalEditorInvitation,
    FormatterInvitation,
)
from app.routers.users import get_current_user


router = APIRouter(
    prefix="/manuscripts",
    tags=["General Comments"],
)


class GeneralCommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class GeneralCommentResponse(BaseModel):
    comment_id: int
    manuscript_id: int
    user_id: int
    author_name: str
    content: str
    visibility: Literal["staff"]
    created_at: datetime


def _has_accepted_invitation(db, model, user_column, manuscript_id, user_id):
    statement = (
        select(model.invitation_id)
        .where(
            model.manuscript_id == manuscript_id,
            user_column == user_id,
            model.status == "accepted",
        )
        .limit(1)
    )
    return db.scalar(statement) is not None


def _require_staff_access(db: Session, manuscript_id: int, user: User):
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(status_code=404, detail="Manuscript not found")

    # EIC can access staff comments across manuscripts.
    if user.role in {"eic", "chief_editor", "editor_in_chief"}:
        return manuscript

    # Initial Editor.
    if user.role == "editor" and _has_accepted_invitation(
        db,
        InitialEditorInvitation,
        InitialEditorInvitation.editor_id,
        manuscript_id,
        user.user_id,
    ):
        return manuscript

    # Final Editor.
    if user.role == "editor" and _has_accepted_invitation(
        db,
        FinalEditorInvitation,
        FinalEditorInvitation.editor_id,
        manuscript_id,
        user.user_id,
    ):
        return manuscript

    # Formatter. Some workflows use an editor account for formatting.
    if user.role in {"formatter", "editor"} and _has_accepted_invitation(
        db,
        FormatterInvitation,
        FormatterInvitation.formatter_id,
        manuscript_id,
        user.user_id,
    ):
        return manuscript

    raise HTTPException(
        status_code=403,
        detail="You are not authorized to access staff comments for this manuscript",
    )


def _serialize(comment: GeneralComment, author_name: str):
    return GeneralCommentResponse(
        comment_id=comment.comment_id,
        manuscript_id=comment.manuscript_id,
        user_id=comment.user_id,
        author_name=author_name,
        content=comment.content,
        visibility="staff",
        created_at=comment.created_at,
    )


@router.get(
    "/{manuscript_id}/general-comments",
    response_model=list[GeneralCommentResponse],
)
def get_general_comments(
    manuscript_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_staff_access(db, manuscript_id, current_user)

    rows = db.execute(
        select(GeneralComment, User.name)
        .join(User, User.user_id == GeneralComment.user_id)
        .where(
            GeneralComment.manuscript_id == manuscript_id,
            GeneralComment.visibility == "staff",
        )
        .order_by(
            GeneralComment.created_at.asc(),
            GeneralComment.comment_id.asc(),
        )
    ).all()

    return [_serialize(comment, name) for comment, name in rows]


@router.post(
    "/{manuscript_id}/general-comments",
    response_model=GeneralCommentResponse,
    status_code=201,
)
def create_general_comment(
    manuscript_id: int,
    payload: GeneralCommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_staff_access(db, manuscript_id, current_user)

    content = payload.content.strip()

    if not content:
        raise HTTPException(
            status_code=422,
            detail="Comment cannot be empty",
        )

    comment = GeneralComment(
        manuscript_id=manuscript_id,
        user_id=current_user.user_id,
        content=content,
        visibility="staff",
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    return _serialize(comment, current_user.name)

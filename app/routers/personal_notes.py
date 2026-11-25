"""Private manuscript notes for individual staff and authors."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User,
    Manuscript,
    PersonalNote,
    InitialEditorInvitation,
    FinalEditorInvitation,
    FormatterInvitation,
)
from app.routers.users import get_current_user
from app.editor_invitation_revocation import effective_status


router = APIRouter(
    prefix="/manuscripts",
    tags=["Personal Notes"],
)


class NoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class NoteUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class NoteResponse(BaseModel):
    note_id: int
    manuscript_id: int
    user_id: int
    content: str
    created_at: datetime
    updated_at: datetime


def require_manuscript_access(db, manuscript_id, user):
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None or (manuscript.status == "draft" and
            (user.role != "author" or manuscript.author_id != user.user_id)):
        raise HTTPException(404, "Manuscript not found")

    if user.role in {"eic", "chief_editor", "editor_in_chief"}:
        return manuscript

    if user.role == "author" and manuscript.author_id == user.user_id:
        return manuscript

    invitations = []

    if user.role == "editor":
        invitations = [
            (InitialEditorInvitation, InitialEditorInvitation.editor_id),
            (FinalEditorInvitation, FinalEditorInvitation.editor_id),
            (FormatterInvitation, FormatterInvitation.formatter_id),
        ]
    elif user.role == "formatter":
        invitations = [
            (FormatterInvitation, FormatterInvitation.formatter_id),
        ]

    for model, column in invitations:
        found = db.scalars(
            select(model).where(
                model.manuscript_id == manuscript_id,
                column == user.user_id,
                model.status == "accepted",
            )
        )
        for invitation in found:
            if model is InitialEditorInvitation:
                if effective_status(db, 'initial', invitation) != 'accepted':continue
            elif model is FinalEditorInvitation:
                if effective_status(db, 'final', invitation) != 'accepted':continue
            return manuscript

    raise HTTPException(403, "Manuscript access denied")


def get_owned_note(db, manuscript_id, note_id, user):
    note = db.scalar(
        select(PersonalNote).where(
            PersonalNote.note_id == note_id,
            PersonalNote.manuscript_id == manuscript_id,
            PersonalNote.user_id == user.user_id,
        )
    )

    if note is None:
        raise HTTPException(404, "Personal note not found")

    return note


def serialize(note):
    return NoteResponse(
        note_id=note.note_id,
        manuscript_id=note.manuscript_id,
        user_id=note.user_id,
        content=note.content,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.get("/{manuscript_id}/notes", response_model=list[NoteResponse])
def list_notes(
    manuscript_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_manuscript_access(db, manuscript_id, current_user)

    notes = db.scalars(
        select(PersonalNote).where(
            PersonalNote.manuscript_id == manuscript_id,
            PersonalNote.user_id == current_user.user_id,
        ).order_by(
            PersonalNote.created_at.desc(),
            PersonalNote.note_id.desc(),
        )
    ).all()

    return [serialize(note) for note in notes]


@router.post(
    "/{manuscript_id}/notes",
    response_model=NoteResponse,
    status_code=201,
)
def create_note(
    manuscript_id: int,
    payload: NoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_manuscript_access(db, manuscript_id, current_user)

    content = payload.content.strip()

    if not content:
        raise HTTPException(422, "Note cannot be empty")

    note = PersonalNote(
        manuscript_id=manuscript_id,
        user_id=current_user.user_id,
        content=content,
    )

    db.add(note)
    db.commit()
    db.refresh(note)

    return serialize(note)


@router.put(
    "/{manuscript_id}/notes/{note_id}",
    response_model=NoteResponse,
)
def update_note(
    manuscript_id: int,
    note_id: int,
    payload: NoteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_manuscript_access(db, manuscript_id, current_user)

    note = get_owned_note(db, manuscript_id, note_id, current_user)

    content = payload.content.strip()

    if not content:
        raise HTTPException(422, "Note cannot be empty")

    note.content = content
    note.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(note)

    return serialize(note)


@router.delete("/{manuscript_id}/notes/{note_id}")
def delete_note(
    manuscript_id: int,
    note_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_manuscript_access(db, manuscript_id, current_user)

    note = get_owned_note(db, manuscript_id, note_id, current_user)

    db.delete(note)
    db.commit()

    return {"deleted": True}

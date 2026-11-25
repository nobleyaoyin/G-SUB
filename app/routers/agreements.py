"""Prospective author responses to the post-acceptance prototype agreement."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthorAgreement, EICDecision, InitialEditorInvitation, Manuscript, Notification, ReviewAssignment, User
from app.routers.manuscripts import can_access_manuscript
from app.routers.users import require_role
from app.agreement_content import snapshot_status

router = APIRouter(prefix='/agreements', tags=['Author agreements'])


class AgreementResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['accept', 'decline']
    agreement_version: str = Field(min_length=1, max_length=40)


def serialize_agreement(agreement):
    if agreement is None:
        return None
    return {'agreement_id': agreement.agreement_id, 'manuscript_id': agreement.manuscript_id,
            'agreement_version': agreement.agreement_version, 'agreement_text': agreement.agreement_text,
            'template_status': snapshot_status(agreement.agreement_version, agreement.agreement_text),
            'status': agreement.status, 'created_at': agreement.created_at, 'responded_at': agreement.responded_at}


def _saved_response(db, agreement_id, user_id, version, status):
    """Reconcile an identical retry against freshly read, authorized state."""
    saved = db.get(AuthorAgreement, agreement_id)
    current = db.get(Manuscript, saved.manuscript_id) if saved else None
    decision = db.get(EICDecision, saved.decision_id) if saved else None
    if (saved and current and decision and saved.author_id == user_id and current.author_id == user_id
            and decision.manuscript_id == current.manuscript_id and decision.decision == 'accept'
            and decision.review_round == current.review_round and saved.agreement_version == version
            and saved.status == status):
        return {'agreement_id': agreement_id, 'manuscript_id': current.manuscript_id,
                'agreement_version': saved.agreement_version, 'status': saved.status,
                'responded_at': saved.responded_at, 'manuscript_status': current.status}
    return None


@router.get('/my')
def my_agreements(current_user: User = Depends(require_role('author')), db: Session = Depends(get_db)):
    results = db.execute(select(AuthorAgreement, Manuscript).join(Manuscript, Manuscript.manuscript_id == AuthorAgreement.manuscript_id).where(
        Manuscript.author_id == current_user.user_id, AuthorAgreement.author_id == current_user.user_id,
    ).order_by(AuthorAgreement.agreement_id.desc())).all()
    return [{**serialize_agreement(agreement), 'manuscript_title': manuscript.title, 'manuscript_status': manuscript.status}
            for agreement, manuscript in results]


@router.get('/manuscripts/{manuscript_id}')
def get_manuscript_agreement(manuscript_id: int, current_user: User = Depends(require_role('author', 'editor', 'eic')), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if manuscript is None or not can_access_manuscript(db, manuscript, current_user):
        raise HTTPException(status_code=404, detail='Manuscript not found')
    agreement = db.scalar(select(AuthorAgreement).where(AuthorAgreement.manuscript_id == manuscript_id).order_by(AuthorAgreement.agreement_id.desc()).limit(1))
    return serialize_agreement(agreement)


@router.post('/{agreement_id}/respond')
def respond_agreement(agreement_id: int, response: AgreementResponse, current_user: User = Depends(require_role('author')), db: Session = Depends(get_db)):
    agreement = db.get(AuthorAgreement, agreement_id)
    if agreement is None:
        raise HTTPException(status_code=404, detail='Agreement not found')
    manuscript = db.get(Manuscript, agreement.manuscript_id)
    if manuscript is None:
        raise HTTPException(status_code=404, detail='Manuscript not found')
    if manuscript.author_id != current_user.user_id or agreement.author_id != current_user.user_id:
        raise HTTPException(status_code=403, detail='Only the manuscript author may respond')
    decision = db.get(EICDecision, agreement.decision_id)
    if not (decision and decision.manuscript_id == manuscript.manuscript_id and decision.decision == 'accept'
            and decision.review_round == manuscript.review_round):
        raise HTTPException(status_code=409, detail='A current EIC acceptance is required')
    if response.agreement_version != agreement.agreement_version:
        raise HTTPException(status_code=409, detail='Agreement version changed; refresh before responding')
    new_status = 'accepted' if response.decision == 'accept' else 'declined'
    if agreement.status != 'pending':
        if agreement.status != new_status:
            raise HTTPException(status_code=409, detail='Agreement has already been answered')
        return {'agreement_id': agreement_id, 'manuscript_id': manuscript.manuscript_id,
                'agreement_version': agreement.agreement_version, 'status': agreement.status,
                'responded_at': agreement.responded_at, 'manuscript_status': manuscript.status}
    if manuscript.status != 'awaiting_author_agreement':
        db.rollback()
        replay = _saved_response(db, agreement_id, current_user.user_id, response.agreement_version, new_status)
        if replay is not None:return replay
        raise HTTPException(status_code=409, detail='Manuscript is not awaiting an agreement response')
    now = datetime.now(timezone.utc)
    changed = db.execute(update(AuthorAgreement).where(
        AuthorAgreement.agreement_id == agreement_id, AuthorAgreement.status == 'pending',
        AuthorAgreement.agreement_version == response.agreement_version,
    ).values(status=new_status, responded_at=now))
    if changed.rowcount != 1:
        db.rollback()
        replay = _saved_response(db, agreement_id, current_user.user_id, response.agreement_version, new_status)
        if replay is not None:return replay
        raise HTTPException(status_code=409, detail='Agreement has already been answered')
    manuscript.status = 'final_editing' if new_status == 'accepted' else 'author_agreement_declined'
    recipients = {decision.eic_id}
    recipients.update(db.scalars(select(InitialEditorInvitation.editor_id).where(
        InitialEditorInvitation.manuscript_id == manuscript.manuscript_id,
        InitialEditorInvitation.status == 'accepted')).all())
    recipients.update(db.scalars(select(ReviewAssignment.assigned_by).where(
        ReviewAssignment.manuscript_id == manuscript.manuscript_id)).all())
    for user_id in recipients:
        user = db.get(User, user_id)
        if user and user.role in ('editor', 'eic'):
            db.add(Notification(user_id=user_id, manuscript_id=manuscript.manuscript_id,
                                notification_type='author_agreement_response',
                                message=f'Author {new_status} the prototype agreement for manuscript #{manuscript.manuscript_id}.', is_read=False))
    db.commit()
    db.refresh(agreement)
    return {'agreement_id': agreement_id, 'manuscript_id': manuscript.manuscript_id,
            'agreement_version': response.agreement_version, 'status': new_status,
            'responded_at': agreement.responded_at, 'manuscript_status': manuscript.status}

"""Prospective final editor invitation and final PDF review workflow."""
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (AuthorAgreement, EICDecision, FinalEditorInvitation, FinalEditingSubmission,
                        FinalEditingSubmissionInvitation, Manuscript, Notification, User)
from app.routers.users import require_role

router=APIRouter(prefix='/final-workflow',tags=['Final editing workflow'])

class Invite(BaseModel):
    manuscript_id:int=Field(gt=0)
    editor_id:int=Field(gt=0)

class Respond(BaseModel):
    decision:Literal['accept','decline']

class ReviewData(BaseModel):
    decision:Literal['approve','request_revision']
    comments:str=Field(min_length=1,max_length=5000)
    @field_validator('comments')
    @classmethod
    def nonblank(cls,value):
        value=value.strip()
        if not value:raise ValueError('Comments cannot be blank')
        return value

def latest_agreement(db,mid):
    return db.scalar(select(AuthorAgreement).where(AuthorAgreement.manuscript_id==mid).order_by(AuthorAgreement.agreement_id.desc()).limit(1))

def accepted_current_agreement(db, manuscript):
    agreement=latest_agreement(db, manuscript.manuscript_id)
    if (not agreement or agreement.status!='accepted' or not agreement.responded_at
            or agreement.author_id!=manuscript.author_id or not agreement.agreement_version
            or not agreement.agreement_version.strip() or not agreement.agreement_text
            or not agreement.agreement_text.strip()):return False
    decision=db.get(EICDecision,agreement.decision_id)
    return bool(decision and decision.manuscript_id==manuscript.manuscript_id and decision.decision=='accept' and decision.review_round==manuscript.review_round)

def preview_eligible(db, manuscript, invitation):
    from app.editor_invitation_revocation import effective_status
    status=effective_status(db,'final',invitation)
    if manuscript.status == 'draft': return False
    if status == 'accepted': return True
    if status != 'pending' or manuscript.status != 'final_editing': return False
    agreement = latest_agreement(db, manuscript.manuscript_id)
    return bool(agreement and agreement.status == 'accepted')

def summary_invitation(db,inv):
    from app.editor_invitation_revocation import effective_status
    person=db.get(User,inv.editor_id)
    return {'invitation_id':inv.invitation_id,'manuscript_id':inv.manuscript_id,'editor_id':inv.editor_id,'editor':person.name if person else 'Unknown','status':effective_status(db,'final',inv),'original_status':inv.status,'invited_at':inv.invited_at,'responded_at':inv.responded_at}

def submissions(db,mid):
    rows=db.execute(select(FinalEditingSubmission,FinalEditingSubmissionInvitation).join(FinalEditingSubmissionInvitation,FinalEditingSubmissionInvitation.submission_id==FinalEditingSubmission.submission_id).where(FinalEditingSubmission.manuscript_id==mid).order_by(FinalEditingSubmission.submission_id.desc())).all()
    return [{'submission_id':s.submission_id,'invitation_id':link.invitation_id,'editor_id':s.editor_id,'status':s.status,'comments':s.comments,'eic_comments':s.eic_comments,'author_comments':s.author_comments,'created_at':s.created_at} for s,link in rows]

@router.post('/invite',status_code=201)
def invite(data:Invite,current_user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    m=db.get(Manuscript,data.manuscript_id)
    if not m:raise HTTPException(404,'Manuscript not found')
    if m.status!='final_editing' or not accepted_current_agreement(db,m):raise HTTPException(409,'Accepted author agreement is required before inviting a final editor')
    editor=db.get(User,data.editor_id)
    if not editor or editor.role!='editor':raise HTTPException(400,'Selected user is not an editor')
    if db.scalar(select(FinalEditorInvitation).where(FinalEditorInvitation.manuscript_id==m.manuscript_id,FinalEditorInvitation.status.in_(['pending','accepted']))):raise HTTPException(409,'An active final editor invitation already exists')
    inv=FinalEditorInvitation(manuscript_id=m.manuscript_id,editor_id=editor.user_id,invited_by=current_user.user_id,status='pending');db.add(inv)
    db.add(Notification(user_id=editor.user_id,manuscript_id=m.manuscript_id,notification_type='final_editor_invitation',message=f'You have been invited to final edit manuscript #{m.manuscript_id}: {m.title}',is_read=False))
    try:db.commit();db.refresh(inv)
    except IntegrityError:db.rollback();raise HTTPException(409,'An active final editor invitation already exists')
    return summary_invitation(db,inv)

@router.post('/invitations/{invitation_id}/respond')
def respond(invitation_id:int,data:Respond,current_user:User=Depends(require_role('editor')),db:Session=Depends(get_db)):
    inv=db.get(FinalEditorInvitation,invitation_id)
    if not inv:raise HTTPException(404,'Invitation not found')
    if inv.editor_id!=current_user.user_id:raise HTTPException(403,'Only the invited editor may respond')
    m=db.get(Manuscript,inv.manuscript_id)
    if not m or m.status!='final_editing' or not accepted_current_agreement(db,m):raise HTTPException(409,'Manuscript is not available for final editing')
    state='accepted' if data.decision=='accept' else 'declined'
    response_time=datetime.now(timezone.utc)
    changed=db.execute(update(FinalEditorInvitation).where(FinalEditorInvitation.invitation_id==invitation_id,FinalEditorInvitation.status=='pending').values(status=state,responded_at=response_time))
    if changed.rowcount!=1:raise HTTPException(409,'Invitation already answered')
    from app.editor_invitation_revocation import is_revoked
    try:
        if is_revoked(db,'final',invitation_id):raise HTTPException(409,'Invitation unavailable')
    except HTTPException:
        db.rollback();raise
    automatic_intent=None
    if state=='accepted':
        from app.automatic_distribution_intents import capture_acceptance
        automatic_intent=capture_acceptance(db,inv.manuscript_id,'final',invitation_id,current_user.user_id,response_time)
    db.add(Notification(user_id=inv.invited_by,manuscript_id=inv.manuscript_id,notification_type='final_editor_response',message=f'Final editor {state} the invitation #{invitation_id} for manuscript #{inv.manuscript_id}.',is_read=False))
    db.commit()
    if automatic_intent:
        from app.automatic_distribution_intents import process_after_acceptance
        process_after_acceptance(db,automatic_intent)
    return {'invitation_id':invitation_id,'status':state}

@router.get('/my')
def my_final_work(current_user:User=Depends(require_role('author','editor')),db:Session=Depends(get_db)):
    if current_user.role=='editor':
        from app.editor_invitation_metadata import invitation_metadata
        invitations=db.scalars(select(FinalEditorInvitation).where(FinalEditorInvitation.editor_id==current_user.user_id).order_by(FinalEditorInvitation.invitation_id.desc())).all()
        from app.editor_invitation_revocation import effective_status
        return [{**summary_invitation(db,i),'title':m.title,'manuscript_status':m.status,'invitation_abstract':m.abstract if effective_status(db,'final',i)=='accepted' and m.status!='draft' else None,'invitation_metadata':invitation_metadata(db,m) if preview_eligible(db,m,i) else None,'submissions':submissions(db,m.manuscript_id) if effective_status(db,'final',i)=='accepted' else []} for i in invitations if (m:=db.get(Manuscript,i.manuscript_id))]
    manuscripts=db.scalars(select(Manuscript).where(Manuscript.author_id==current_user.user_id)).all()
    result=[]
    for m in manuscripts:
        items=submissions(db,m.manuscript_id)
        agreement=latest_agreement(db,m.manuscript_id)
        if not items and not (m.status=='final_editing' and agreement and agreement.status=='accepted'):
            continue
        invitation=db.scalar(select(FinalEditorInvitation).where(FinalEditorInvitation.manuscript_id==m.manuscript_id).order_by(FinalEditorInvitation.invitation_id.desc()).limit(1))
        from app.editor_invitation_revocation import effective_status
        result.append({'manuscript_id':m.manuscript_id,'title':m.title,'manuscript_status':m.status,'final_invitation_status':effective_status(db,'final',invitation) if invitation else None,'submissions':items})
    return result

def review_submission(submission_id,data,current_user,db,role):
    submission=db.get(FinalEditingSubmission,submission_id);link=db.get(FinalEditingSubmissionInvitation,submission_id)
    if not submission or not link:raise HTTPException(404,'Final editing submission not found')
    m=db.get(Manuscript,submission.manuscript_id);inv=db.get(FinalEditorInvitation,link.invitation_id)
    if not m or not inv or inv.manuscript_id!=m.manuscript_id or inv.editor_id!=submission.editor_id or inv.status!='accepted':raise HTTPException(409,'Final editing assignment is unavailable')
    if role=='author' and m.author_id!=current_user.user_id:raise HTTPException(403,'Only the manuscript author may confirm')
    if m.status!='final_editing' or not accepted_current_agreement(db,m):raise HTTPException(409,'Manuscript is not available for final editing')
    from app import sample_documents
    if sample_documents.registered(db,m.manuscript_id):
        from app.editor_invitation_revocation import effective_status
        if effective_status(db,'final',inv) != 'accepted': raise HTTPException(409,'Final editing assignment is unavailable')
        from app import sample_stage_artifacts
        sample_stage_artifacts.read(db,'final_editing',submission)
    latest=submissions(db,m.manuscript_id)
    if not latest or latest[0]['submission_id']!=submission_id:raise HTTPException(409,'Only the latest final edit can be reviewed')
    expected='pending_eic' if role=='eic' else 'pending_author'
    status=('pending_author' if data.decision=='approve' else 'eic_revision_requested') if role=='eic' else ('author_approved' if data.decision=='approve' else 'author_revision_requested')
    values={'status':status}
    if role=='eic':values.update(eic_comments=data.comments,eic_reviewed_at=datetime.now(timezone.utc),eic_approved_by=current_user.user_id if data.decision=='approve' else None)
    else:values.update(author_comments=data.comments,author_reviewed_at=datetime.now(timezone.utc))
    result=db.execute(update(FinalEditingSubmission).where(FinalEditingSubmission.submission_id==submission_id,FinalEditingSubmission.status==expected).values(**values))
    if result.rowcount!=1:raise HTTPException(409,'Submission is not awaiting this review')
    recipient=m.author_id if role=='eic' and data.decision=='approve' else inv.editor_id if data.decision=='request_revision' else inv.invited_by
    db.add(Notification(user_id=recipient,manuscript_id=m.manuscript_id,notification_type='final_editing_review',message=f'{role.upper()} reviewed final editing submission #{submission_id}: {data.decision}.',is_read=False))
    db.commit();return {'submission_id':submission_id,'status':status}

@router.post('/submissions/{submission_id}/eic-review')
def eic_review(submission_id:int,data:ReviewData,current_user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    return review_submission(submission_id,data,current_user,db,'eic')

@router.post('/submissions/{submission_id}/author-review')
def author_review(submission_id:int,data:ReviewData,current_user:User=Depends(require_role('author')),db:Session=Depends(get_db)):
    return review_submission(submission_id,data,current_user,db,'author')

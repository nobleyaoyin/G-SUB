
import os
import tempfile
import sqlite3
import hmac
from pathlib import Path
from app.config import DATA_ROOT, MODE, guard_demo_path
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select, update, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db

from app.models import (
    User,
    Manuscript,
    EICInitialScan,
    Notification,
    ReviewAssignment,
    ReviewAssignmentFile,
    ReviewRoundFile,
    InitialEditorInvitation,
    InitialEditingSubmission,
    PreReviewConfirmation,
    Review,
    EICDecision,
    FinalEditingSubmission,
    AuthorAgreement,
    FinalEditorInvitation,
    FinalEditingSubmissionInvitation,
    FormattingSubmission,
)

from app.schemas import (
    EICInitialScanCreate,
    InitialEditorInviteCreate,
    InitialEditorInvitationResponse,
    InitialEditorInvitationDecision,
    InitialEditingAuthorReview,
    InitialEditingEditorApproval,
    InitialEditingEICApproval,
    PreReviewConfirmationRequest,
    EICDecisionCreate,
)
from app.routers.users import require_role
from app.reviewer_invitations import invitation_status, not_declined
from app.review_progress import review_progress
from app.ai_prescreening_read import list_manuscript_ai_reports
from app.split_review import split_review_status
from app.agreement_content import issuance_template
from app.routers.final_workflow import accepted_current_agreement, summary_invitation, submissions as final_workflow_submissions
from app.routers.manuscripts import OnlineTextSave, validate_manuscript_file
from app import editor_text_drafts, online_versions
from app import blind_policy_store
from pydantic import BaseModel
from typing import Literal

BASE_DIR = DATA_ROOT
router = APIRouter(
    prefix="/eic",
    tags=["EIC"],
)


class ReviewPolicySelection(BaseModel):
    mode: Literal['single_blind', 'double_blind']
    expected_revision: int | None = None


def _policy_connection(db, *, write=False):
    connection = db.connection()
    if connection.dialect.name != 'sqlite' or connection.connection.driver_connection.in_transaction:
        raise HTTPException(503, 'Review policy transaction unavailable')
    connection.exec_driver_sql('BEGIN IMMEDIATE' if write else 'BEGIN')
    return connection.connection.driver_connection


def _policy_view(value):
    return {'state': 'missing' if value is None else ('locked' if value['locked_at'] else 'selected'),
            'mode': value['mode'] if value else None, 'revision': value['revision'] if value else None}


@router.get('/manuscripts/{manuscript_id}/review-policy')
def review_policy_get(manuscript_id: int, current_user: User = Depends(require_role('eic')), db: Session = Depends(get_db)):
    try:
        raw = _policy_connection(db)
        if not raw.execute("SELECT 1 FROM manuscripts WHERE manuscript_id=? AND status!='draft'", (manuscript_id,)).fetchone():
            raise HTTPException(404, 'Manuscript not found')
        return JSONResponse(_policy_view(blind_policy_store.read_policy(raw, manuscript_id)), headers={'Cache-Control': 'no-store'})
    except (blind_policy_store.PolicyError, sqlite3.DatabaseError, SQLAlchemyError):
        raise HTTPException(503, 'Review policy unavailable') from None


@router.put('/manuscripts/{manuscript_id}/review-policy')
def review_policy_put(manuscript_id: int, data: ReviewPolicySelection, current_user: User = Depends(require_role('eic')), db: Session = Depends(get_db)):
    try:
        raw = _policy_connection(db, write=True)
        if not raw.execute("SELECT 1 FROM manuscripts WHERE manuscript_id=? AND status!='draft'", (manuscript_id,)).fetchone():
            raise HTTPException(404, 'Manuscript not found')
        old = blind_policy_store.read_policy(raw, manuscript_id)
        if old is None and data.expected_revision is None:
            result = blind_policy_store.select_mode(raw, manuscript_id, data.mode, current_user.user_id)
        elif old is not None and data.expected_revision is not None:
            result = blind_policy_store.change_mode(raw, manuscript_id, data.mode, current_user.user_id, data.expected_revision)
        else:
            raise blind_policy_store.PolicyError('Stale policy')
        db.commit()
        return JSONResponse(_policy_view(result), headers={'Cache-Control': 'no-store'})
    except blind_policy_store.SchemaUnavailable:
        db.rollback()
        raise HTTPException(503, 'Review policy unavailable') from None
    except blind_policy_store.PolicyError:
        db.rollback()
        raise HTTPException(409, 'Policy is locked, stale, or requires legacy review') from None
    except (sqlite3.DatabaseError, SQLAlchemyError):
        db.rollback()
        raise HTTPException(503, 'Policy update unavailable; refresh before retrying') from None


@router.get('/manuscripts/{manuscript_id}/online-text/{stage}')
def editor_text_get(manuscript_id: int, stage: str, current_user: User = Depends(require_role('editor')), db: Session = Depends(get_db)):
    _, paths, content, version, _, _, rows = editor_text_drafts.state(db, BASE_DIR.resolve(), manuscript_id, current_user, stage, with_source=True)
    return JSONResponse({'content': content, 'version': version, 'history': [
        {'id': row['version_id'], 'number': row['version_number'], 'saved_at': row['saved_at'],
         'editor': current_user.name, 'filename': path.name, 'change_note': row['change_note'], 'is_current': index == len(paths)-1}
        for index, (path, row) in enumerate(zip(paths, rows))]}, headers={'Cache-Control':'no-store'})


@router.post('/manuscripts/{manuscript_id}/online-text/{stage}')
def editor_text_save(manuscript_id: int, stage: str, data: OnlineTextSave, current_user: User = Depends(require_role('editor')), db: Session = Depends(get_db)):
    try:
        encoded = data.content.encode('utf-8')
    except UnicodeError:
        raise HTTPException(400, 'Document must contain valid UTF-8 text') from None
    validate_manuscript_file('document.txt', encoded)
    try:
        connection = db.connection()
        if connection.dialect.name != 'sqlite' or connection.connection.driver_connection.in_transaction:
            raise HTTPException(503, 'Editor transaction unavailable')
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        directory, paths, _, version, source_path, source_text, _ = editor_text_drafts.state(db, BASE_DIR.resolve(), manuscript_id, current_user, stage, with_source=True)
        if version != data.expected_version:
            raise HTTPException(409, 'Document changed; reopen it before saving')
        path = editor_text_drafts.publish(directory, data.content, BASE_DIR.resolve()/'uploads', int(paths[-1].name[:20])+1 if paths else 1)
        online_versions.record(db, manuscript_id, current_user.user_id, stage, str(directory.relative_to(BASE_DIR.resolve())), source_path,
                               source_text.encode('utf-8'), str(path.relative_to(BASE_DIR.resolve())), encoded, data.change_note)
        db.commit()
        return {'message':'Draft version saved'}
    except HTTPException:
        db.rollback(); raise
    except (OSError, sqlite3.DatabaseError, SQLAlchemyError):
        db.rollback()
        raise HTTPException(503, 'Save outcome unavailable; reopen before retrying') from None


@router.get('/manuscripts/{manuscript_id}/online-text/{stage}/{filename}')
def editor_text_download(manuscript_id: int, stage: str, filename: str, current_user: User = Depends(require_role('editor')), db: Session = Depends(get_db)):
    directory, paths, _, _ = editor_text_drafts.state(db, BASE_DIR.resolve(), manuscript_id, current_user, stage)
    if filename not in {path.name for path in paths}:
        raise HTTPException(404, 'Draft unavailable')
    content = editor_text_drafts._read(directory/filename, directory).encode('utf-8')
    return Response(content=content, media_type='text/plain; charset=utf-8', headers={'Cache-Control':'no-store', 'Content-Disposition':f'attachment; filename="{filename}"'})


@router.get("/initial-editing/my", summary="List my initial editing workflow items")
def my_initial_editing(current_user: User = Depends(require_role("author", "editor")), db: Session = Depends(get_db)):
    from app.editor_invitation_metadata import invitation_metadata
    from app.editor_invitation_revocation import effective_status
    if current_user.role == "author":
        manuscripts = db.scalars(select(Manuscript).where(Manuscript.author_id == current_user.user_id, Manuscript.status != "draft").order_by(Manuscript.manuscript_id.desc())).all()
    else:
        manuscripts = db.scalars(select(Manuscript).join(InitialEditorInvitation, InitialEditorInvitation.manuscript_id == Manuscript.manuscript_id).where(InitialEditorInvitation.editor_id == current_user.user_id, InitialEditorInvitation.status.in_(["pending", "accepted"]), Manuscript.status != "draft").distinct().order_by(Manuscript.manuscript_id.desc())).all()
    result = []
    for manuscript in manuscripts:
        invitation_query = select(InitialEditorInvitation).where(InitialEditorInvitation.manuscript_id == manuscript.manuscript_id)
        if current_user.role == "editor":
            invitation_query = invitation_query.where(InitialEditorInvitation.editor_id == current_user.user_id, InitialEditorInvitation.status.in_(["pending", "accepted"]))
        invitation = db.scalar(invitation_query.order_by(InitialEditorInvitation.invitation_id.desc()).limit(1))
        invitation_status = effective_status(db,'initial',invitation) if invitation else None
        # A pending invitation permits its recipient to see only the invitation, not editing history.
        submissions = []
        if current_user.role == "author" or invitation_status == "accepted":
            query = select(InitialEditingSubmission).where(InitialEditingSubmission.manuscript_id == manuscript.manuscript_id)
            if current_user.role == "editor":
                query = query.where(InitialEditingSubmission.editor_id == current_user.user_id)
            submissions = db.scalars(query.order_by(InitialEditingSubmission.submission_id.desc())).all()
        if not invitation and not submissions:
            continue
        editor = db.get(User, invitation.editor_id) if invitation else None
        items = []
        for submission in submissions:
            confirmation = db.scalar(select(PreReviewConfirmation).where(PreReviewConfirmation.submission_id == submission.submission_id).order_by(PreReviewConfirmation.confirmation_id.desc()).limit(1))
            items.append({"submission_id": submission.submission_id, "status": submission.status, "comments": submission.comments, "author_comments": submission.author_comments, "editor_comments": submission.editor_comments, "eic_comments": submission.eic_comments, "confirmation": confirmation.decision if confirmation else None})
        result.append({"manuscript_id": manuscript.manuscript_id, "title": manuscript.title, "status": manuscript.status, "invitation": {"invitation_id": invitation.invitation_id, "status": invitation_status, "original_status": invitation.status, "editor": editor.name if editor else "Unknown", "invited_at": invitation.invited_at, "responded_at": invitation.responded_at} if invitation else None, "submissions": items, "invitation_abstract": manuscript.abstract if current_user.role == "editor" and invitation_status == "accepted" else None, "invitation_metadata": invitation_metadata(db, manuscript) if current_user.role == "editor" and invitation and (invitation_status == "accepted" or (invitation_status == "pending" and manuscript.status == "initial_editor_invited")) else None})
    return result


@router.get("/editors", summary="List editors for initial invitations")
def list_editors(current_user: User = Depends(require_role("eic")), db: Session = Depends(get_db)):
    return [{"user_id": u.user_id, "name": u.name} for u in db.scalars(
        select(User).where(User.role == "editor").order_by(User.name, User.user_id)
    )]



@router.get(
    "/manuscripts/{manuscript_id}/ai-prescreening",
    summary="Read advisory AI prescreening results",
)
def manuscript_ai_prescreening(
    manuscript_id: int,
    current_user: User = Depends(require_role("eic")),
    db: Session = Depends(get_db),
):
    """Return version-specific advisory reports for EIC only."""
    manuscript = db.get(Manuscript, manuscript_id)

    # Match the existing EIC overview visibility rule.
    if manuscript is None or manuscript.status == "draft":
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    return {
        "manuscript_id": manuscript_id,
        "advisory_only": True,
        "submissions": list_manuscript_ai_reports(
            db,
            manuscript_id,
        ),
    }


@router.get("/manuscripts/{manuscript_id}/document-timeline", summary="Recorded manuscript document evidence")
def manuscript_document_timeline(manuscript_id: int, current_user: User = Depends(require_role("eic")), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if manuscript is None or manuscript.status == 'draft':
        raise HTTPException(status_code=404, detail='Manuscript not found')
    from app.eic_document_timeline import document_timeline
    return document_timeline(db, manuscript)


@router.get("/manuscripts/{manuscript_id}/document-timeline/reviewed/{artifact_id}/download")
def timeline_reviewed_download(manuscript_id: int, artifact_id: str, current_user: User = Depends(require_role("eic")), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if manuscript is None or manuscript.status == 'draft':
        raise HTTPException(status_code=404, detail='Document unavailable')
    try:
        exists = db.scalar(text("SELECT 1 FROM distribution_artifacts WHERE artifact_id=:artifact AND manuscript_id=:mid AND kind='reviewed_document'"), {'artifact':artifact_id,'mid':manuscript_id})
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail='Document unavailable') from None
    if not exists:
        raise HTTPException(status_code=404, detail='Document unavailable')
    # Distribution artifacts are immutable; the existing download rechecks the
    # stored association and verifies its digest on the bytes it returns.
    db.rollback()
    from app.routers.document_distribution import download_reviewed
    return download_reviewed(artifact_id, current_user, db)


@router.get('/manuscripts/{manuscript_id}/document-timeline/formatting/{submission_id}/download')
def timeline_formatting_download(manuscript_id: int, submission_id: int,
        current_user: User = Depends(require_role('eic')), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if not manuscript or manuscript.status == 'draft':
        raise HTTPException(404, 'Document unavailable')
    submission = db.scalar(select(FormattingSubmission).where(
        FormattingSubmission.submission_id == submission_id,
        FormattingSubmission.manuscript_id == manuscript_id))
    if not submission:
        raise HTTPException(404, 'Document unavailable')
    from app.formatting_artifact_read import read_formatting_artifact
    from app.routers.manuscripts import ALLOWED_MANUSCRIPT_EXTENSIONS, MAX_MANUSCRIPT_FILE_SIZE
    content, extension = read_formatting_artifact(submission, manuscript_id, BASE_DIR,
        ALLOWED_MANUSCRIPT_EXTENSIONS, MAX_MANUSCRIPT_FILE_SIZE, db=db)
    return Response(content, media_type=ALLOWED_MANUSCRIPT_EXTENSIONS[extension], headers={
        'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
        'Content-Disposition':f'attachment; filename="formatting-document{extension}"'})


@router.get('/manuscripts/{manuscript_id}/document-timeline/submissions/{snapshot_id}/download')
def timeline_submission_download(manuscript_id: int, snapshot_id: str,
        current_user: User = Depends(require_role('eic')), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if not manuscript or manuscript.status == 'draft':
        raise HTTPException(404, 'Document unavailable')
    from app.submission_snapshot_history import read_snapshot
    from app.routers.manuscripts import ALLOWED_MANUSCRIPT_EXTENSIONS, MAX_MANUSCRIPT_FILE_SIZE
    content, extension = read_snapshot(db, manuscript, snapshot_id, BASE_DIR,
        ALLOWED_MANUSCRIPT_EXTENSIONS, MAX_MANUSCRIPT_FILE_SIZE)
    return Response(content, media_type=ALLOWED_MANUSCRIPT_EXTENSIONS[extension], headers={
        'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
        'Content-Disposition':f'attachment; filename="submitted-document{extension}"'})


@router.get('/manuscripts/{manuscript_id}/document-timeline/final-editing/{submission_id}/download')
def timeline_final_editing_download(manuscript_id: int, submission_id: int,
        current_user: User = Depends(require_role('eic')), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if not manuscript or manuscript.status == 'draft':
        raise HTTPException(404, 'Document unavailable')
    submission = db.scalar(select(FinalEditingSubmission).where(
        FinalEditingSubmission.submission_id == submission_id,
        FinalEditingSubmission.manuscript_id == manuscript_id))
    if submission is None:
        raise HTTPException(404, 'Document unavailable')
    from app.routers.manuscripts import ALLOWED_MANUSCRIPT_EXTENSIONS, read_final_history_file
    content, extension = read_final_history_file(submission, manuscript_id, BASE_DIR, db=db)
    return Response(content, media_type=ALLOWED_MANUSCRIPT_EXTENSIONS[extension], headers={
        'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
        'Content-Disposition':f'attachment; filename="final-edit-document{extension}"'})


@router.get("/manuscripts/{manuscript_id}/overview", summary="EIC manuscript workflow overview")
def manuscript_overview(manuscript_id: int, current_user: User = Depends(require_role("eic")), db: Session = Depends(get_db)):
    from app.editor_invitation_revocation import effective_status
    manuscript = db.get(Manuscript, manuscript_id)
    # Drafts remain private, including from EICs.
    if manuscript is None or manuscript.status == "draft":
        raise HTTPException(status_code=404, detail="Manuscript not found")
    author = db.get(User, manuscript.author_id)
    invitations = db.scalars(select(InitialEditorInvitation).where(InitialEditorInvitation.manuscript_id == manuscript_id).order_by(InitialEditorInvitation.invitation_id)).all()
    submissions = db.scalars(select(InitialEditingSubmission).where(InitialEditingSubmission.manuscript_id == manuscript_id).order_by(InitialEditingSubmission.submission_id)).all()
    assignments = db.scalars(select(ReviewAssignment).where(ReviewAssignment.manuscript_id == manuscript_id).order_by(ReviewAssignment.review_round, ReviewAssignment.assignment_id)).all()
    bindings = db.execute(select(ReviewAssignmentFile, ReviewRoundFile).join(
        ReviewRoundFile, ReviewRoundFile.round_file_id == ReviewAssignmentFile.round_file_id
    ).join(ReviewAssignment, ReviewAssignment.assignment_id == ReviewAssignmentFile.assignment_id).where(
        ReviewAssignment.manuscript_id == manuscript_id,
        ReviewRoundFile.manuscript_id == manuscript_id,
        ReviewRoundFile.review_round == ReviewAssignment.review_round,
    )).all()
    binding_by_assignment = {binding.assignment_id: {"round_file_id": source.round_file_id,
        "review_round": source.review_round, "source_kind": source.source_kind,
        "bound_at": binding.bound_at} for binding, source in bindings}
    scans = db.scalars(select(EICInitialScan).where(EICInitialScan.manuscript_id == manuscript_id).order_by(EICInitialScan.scan_id)).all()
    decisions = db.scalars(select(EICDecision).where(EICDecision.manuscript_id == manuscript_id).order_by(EICDecision.decision_id)).all()
    confirmations = db.scalars(select(PreReviewConfirmation).where(PreReviewConfirmation.manuscript_id == manuscript_id).order_by(PreReviewConfirmation.confirmation_id)).all()
    finals = db.scalars(select(FinalEditingSubmission).where(FinalEditingSubmission.manuscript_id == manuscript_id).order_by(FinalEditingSubmission.submission_id)).all()
    final_invitations = db.scalars(select(FinalEditorInvitation).where(FinalEditorInvitation.manuscript_id == manuscript_id).order_by(FinalEditorInvitation.invitation_id)).all()
    agreement = db.scalar(select(AuthorAgreement).where(AuthorAgreement.manuscript_id == manuscript_id).order_by(AuthorAgreement.agreement_id.desc()).limit(1))
    notices = db.scalars(select(Notification).where(Notification.manuscript_id == manuscript_id,
        Notification.notification_type.in_(['manuscript_submitted', 'initial_resubmission']))
        .order_by(Notification.created_at, Notification.notification_id)).all()
    submissions_notices = [n for n in notices if n.notification_type == 'manuscript_submitted']
    initial_notice = next((n for n in submissions_notices if n.created_at is not None), submissions_notices[0] if submissions_notices else None)
    submission_events = ([{'kind': 'submitted', 'id': initial_notice.notification_id, 'created_at': initial_notice.created_at}]
                         if initial_notice else [])
    submission_events.extend({'kind': 'initial_resubmission', 'id': n.notification_id, 'created_at': n.created_at}
                             for n in notices if n.notification_type == 'initial_resubmission')
    revision_files = db.scalars(select(ReviewRoundFile).where(ReviewRoundFile.manuscript_id == manuscript_id,
        ReviewRoundFile.source_kind == 'author_revision').order_by(ReviewRoundFile.round_file_id)).all()
    def name(user_id):
        user = db.get(User, user_id)
        return user.name if user else f"User #{user_id}"
    return {
        "manuscript": {"manuscript_id": manuscript_id, "title": manuscript.title, "abstract": manuscript.abstract, "status": manuscript.status, "review_round": manuscript.review_round, "author": author.name if author else "Unknown", "created_at": manuscript.created_at},
        "review_progress": review_progress(db, manuscript),
        "submission_events": submission_events,
        "revision_events": [{"round_file_id": r.round_file_id, "review_round": r.review_round,
                             "created_at": r.created_at} for r in revision_files],
        "split_review": split_review_status(db, manuscript),
        "author_agreement": {"status": agreement.status, "agreement_version": agreement.agreement_version, "responded_at": agreement.responded_at} if agreement else None,
        "scans": [{"decision": s.decision, "comments": s.comments, "created_at": s.created_at} for s in scans],
        "invitations": [{"invitation_id": i.invitation_id, "editor": name(i.editor_id), "status": effective_status(db,'initial',i), "original_status": i.status, "invited_at": i.invited_at, "responded_at": i.responded_at} for i in invitations],
        "submissions": [{"submission_id": s.submission_id, "editor": name(s.editor_id), "status": s.status, "comments": s.comments, "author_comments": s.author_comments, "editor_comments": s.editor_comments, "eic_comments": s.eic_comments, "created_at": s.created_at} for s in submissions],
        "confirmations": [{"submission_id": c.submission_id, "decision": c.decision, "comments": c.comments, "confirmed_at": c.confirmed_at} for c in confirmations],
        "assignments": [{"assignment_id": a.assignment_id, "review_round": a.review_round, "reviewer": name(a.reviewer_id), "assigned_by": name(a.assigned_by), "status": a.status, "assigned_at": a.assigned_at, "invitation_status": invitation_status(db, a), "recorded_round_binding": binding_by_assignment.get(a.assignment_id), "review": ({"comments": r.comments, "recommendation": r.recommendation, "submitted_at": r.submitted_at} if (r := db.scalar(select(Review).where(Review.assignment_id == a.assignment_id))) else None)} for a in assignments],
        "decisions": [{"review_round": d.review_round, "decision": d.decision, "comments": d.comments, "decided_at": d.decided_at} for d in decisions],
        "final_submissions": [{"submission_id": f.submission_id, "editor": name(f.editor_id), "status": f.status, "comments": f.comments, "created_at": f.created_at} for f in finals],
        "final_invitations": [summary_invitation(db, i) for i in final_invitations],
        "final_workflow_submissions": final_workflow_submissions(db, manuscript_id),
    }


@router.post(
    "/manuscripts/{manuscript_id}/initial-scan",
    status_code=status.HTTP_201_CREATED,
    summary="Perform EIC Initial Scan",
)
def perform_initial_scan(
    manuscript_id: int,
    scan_data: EICInitialScanCreate,
    current_user: User = Depends(require_role("eic")),
    db: Session = Depends(get_db),
):
    # Find the manuscript.
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Initial screening is only allowed for submitted manuscripts.
    if manuscript.status != "submitted":
        raise HTTPException(
            status_code=409,
            detail="Manuscript is not awaiting initial screening",
        )

    # Require a submitted PDF.
    from app.routers.manuscripts import manuscript_has_pdf

    if not manuscript_has_pdf(manuscript):
        raise HTTPException(
            status_code=409,
            detail="Manuscript PDF is missing",
        )

    # Prevent initial screening after peer review has started.
    existing_assignment = db.scalar(
        select(ReviewAssignment.assignment_id)
        .where(
            ReviewAssignment.manuscript_id == manuscript_id
        )
        .limit(1)
    )

    if existing_assignment is not None:
        raise HTTPException(
            status_code=409,
            detail="Peer review has already started",
        )

    # Map EIC decisions to separate workflow statuses.
    status_map = {
        "pass": "initial_scan_passed",
        "revision_required": "initial_revision_required",
        "reject": "initial_rejected",
    }

    new_status = status_map[scan_data.decision]

    # Save the initial screening history.
    scan = EICInitialScan(
        manuscript_id=manuscript_id,
        eic_id=current_user.user_id,
        decision=scan_data.decision,
        comments=scan_data.comments,
    )

    db.add(scan)

    # Update manuscript workflow status.
    manuscript.status = new_status

    # Notify the author.
    notification = Notification(
        user_id=manuscript.author_id,
        manuscript_id=manuscript_id,
        notification_type="eic_initial_scan",
        message=(
            f"EIC initial screening: {scan_data.decision}. "
            f"Comments: {scan_data.comments}"
        ),
    )

    db.add(notification)

    # Save all changes in one transaction.
    db.commit()
    db.refresh(scan)

    return {
        "scan_id": scan.scan_id,
        "manuscript_id": manuscript_id,
        "eic_id": current_user.user_id,
        "decision": scan.decision,
        "comments": scan.comments,
        "manuscript_status": manuscript.status,
        "created_at": scan.created_at,
    }


@router.post(
    "/initial-editor/invite",
    response_model=InitialEditorInvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite an Initial Editor",
)
def invite_initial_editor(
    invitation_data: InitialEditorInviteCreate,
    current_user: User = Depends(require_role("eic")),
    db: Session = Depends(get_db),
):
    manuscript = db.get(
        Manuscript,
        invitation_data.manuscript_id,
    )

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Only manuscripts that passed the EIC initial scan
    # can proceed to initial editing.
    if manuscript.status != "initial_scan_passed":
        raise HTTPException(
            status_code=409,
            detail="Manuscript has not passed initial screening",
        )

    # Verify the selected user is an editor.
    editor = db.get(User, invitation_data.editor_id)

    if editor is None or editor.role != "editor":
        raise HTTPException(
            status_code=400,
            detail="Selected user is not an editor",
        )

    # Prevent another active invitation or assignment.
    existing_invitation = db.scalar(
        select(InitialEditorInvitation)
        .where(
            InitialEditorInvitation.manuscript_id
            == manuscript.manuscript_id,
            InitialEditorInvitation.status.in_(
                ["pending", "accepted"]
            ),
        )
        .limit(1)
    )

    if existing_invitation is not None:
        raise HTTPException(
            status_code=409,
            detail="An active editor invitation already exists",
        )

    # Create invitation.
    invitation = InitialEditorInvitation(
        manuscript_id=manuscript.manuscript_id,
        editor_id=editor.user_id,
        invited_by=current_user.user_id,
        status="pending",
    )

    db.add(invitation)

    # Update manuscript workflow status.
    manuscript.status = "initial_editor_invited"

    # Notify the invited editor.
    db.add(
        Notification(
            user_id=editor.user_id,
            manuscript_id=manuscript.manuscript_id,
            notification_type="initial_editor_invitation",
            message=(
                f"You have been invited by the EIC to edit "
                f"manuscript #{manuscript.manuscript_id}: "
                f"{manuscript.title}"
            ),
        )
    )

    db.commit()
    db.refresh(invitation)

    return invitation


@router.post(
    "/initial-editor/invitations/{invitation_id}/respond",
    response_model=InitialEditorInvitationResponse,
    summary="Accept or Decline Initial Editor Invitation",
)
def respond_initial_editor_invitation(
    invitation_id: int,
    response_data: InitialEditorInvitationDecision,
    current_user: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
):
    invitation = db.get(
        InitialEditorInvitation,
        invitation_id,
    )

    if invitation is None:
        raise HTTPException(
            status_code=404,
            detail="Invitation not found",
        )

    # Only the invited editor can respond.
    if invitation.editor_id != current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail="You are not the invited editor",
        )

    if invitation.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="Invitation has already been answered",
        )

    manuscript = db.get(
        Manuscript,
        invitation.manuscript_id,
    )

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    if manuscript.status != "initial_editor_invited":
        raise HTTPException(
            status_code=409,
            detail="Manuscript is not awaiting an editor response",
        )

    # A conditional write serializes competing responses. The invitation,
    # manuscript and notification are committed together or rolled back.
    next_invitation = "accepted" if response_data.decision == "accept" else "declined"
    next_manuscript = "initial_editing" if response_data.decision == "accept" else "initial_scan_passed"
    response_time = datetime.now(timezone.utc)
    changed = db.execute(update(InitialEditorInvitation).where(
        InitialEditorInvitation.invitation_id == invitation_id,
        InitialEditorInvitation.editor_id == current_user.user_id,
        InitialEditorInvitation.status == "pending",
    ).values(status=next_invitation, responded_at=response_time))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Invitation has already been answered")
    advanced = db.execute(update(Manuscript).where(
        Manuscript.manuscript_id == invitation.manuscript_id,
        Manuscript.status == "initial_editor_invited",
    ).values(status=next_manuscript))
    if advanced.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Manuscript is not awaiting an editor response")

    from app.editor_invitation_revocation import is_revoked
    try:
        if is_revoked(db,'initial',invitation_id):
            raise HTTPException(status_code=409, detail="Invitation unavailable")
    except HTTPException:
        db.rollback()
        raise

    automatic_intent = None
    if next_invitation == "accepted":
        from app.automatic_distribution_intents import capture_acceptance
        automatic_intent = capture_acceptance(db, manuscript.manuscript_id, 'initial', invitation_id, current_user.user_id, response_time)

    # Notify the EIC who sent the invitation.
    db.add(
        Notification(
            user_id=invitation.invited_by,
            manuscript_id=manuscript.manuscript_id,
            notification_type="initial_editor_response",
            message=(
                f"Initial editor {current_user.name} has "
                f"{next_invitation} the invitation #{invitation_id} "
                f"for manuscript #{manuscript.manuscript_id}."
            ),
        )
    )

    db.commit()
    if automatic_intent:
        from app.automatic_distribution_intents import process_after_acceptance
        process_after_acceptance(db, automatic_intent)
    db.refresh(invitation)

    return invitation

@router.post(
    "/initial-editing/{manuscript_id}/submit",
    status_code=status.HTTP_201_CREATED,
    summary="Submit Initial Editing Document",
)
def submit_initial_editing(
    manuscript_id: int,
    file: UploadFile = File(...),
    comments: str = Form(...),
    expected_online_version: str | None = Form(None),
    current_user: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
):
    if expected_online_version is not None:
        connection = db.connection()
        if connection.dialect.name != 'sqlite' or connection.connection.driver_connection.in_transaction:
            raise HTTPException(503, 'Editor transaction unavailable')
        connection.exec_driver_sql('BEGIN IMMEDIATE')
    # Step 1: Find the manuscript.
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Step 2: Only allow submissions during initial editing.
    if manuscript.status != "initial_editing":
        raise HTTPException(
            status_code=409,
            detail="Manuscript is not in initial editing",
        )

    # Step 3: Verify that this editor accepted the invitation.
    invitation = db.scalar(
        select(InitialEditorInvitation).where(
            InitialEditorInvitation.manuscript_id == manuscript_id,
            InitialEditorInvitation.editor_id == current_user.user_id,
            InitialEditorInvitation.status == "accepted",
        )
    )

    from app.editor_invitation_revocation import effective_status
    if invitation is None or effective_status(db,'initial',invitation) != 'accepted':
        raise HTTPException(
            status_code=403,
            detail="You are not the assigned initial editor",
        )

    from app import sample_documents
    sample = sample_documents.registered(db, manuscript_id)
    if sample and expected_online_version is None:
        connection = db.connection()
        if connection.dialect.name != 'sqlite' or connection.connection.driver_connection.in_transaction:
            raise HTTPException(503, 'Editor transaction unavailable')
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        db.refresh(manuscript)
        db.refresh(invitation)
        if manuscript.status != 'initial_editing' or effective_status(db, 'initial', invitation) != 'accepted':
            raise HTTPException(409, 'Initial editing assignment changed')

    # Step 4: Prevent multiple pending submissions.
    pending_submission = db.scalar(
        select(InitialEditingSubmission).where(
            InitialEditingSubmission.manuscript_id == manuscript_id,
            InitialEditingSubmission.status == "pending_author",
        )
    )

    if pending_submission is not None:
        raise HTTPException(
            status_code=409,
            detail="An editing submission is already awaiting author review",
        )

    # Step 5: Validate comments.
    comments = comments.strip()

    if not comments or len(comments) > 5000:
        raise HTTPException(
            status_code=400,
            detail="Comments must contain 1 to 5000 characters",
        )

    # Validate using the same bounded checks used for manuscript uploads.
    from app.routers.manuscripts import MAX_MANUSCRIPT_FILE_SIZE, validate_manuscript_file
    extension = Path(file.filename or "").suffix.lower()
    if extension == ".pdf" and file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="PDF content type is required",
        )
    content = file.file.read(MAX_MANUSCRIPT_FILE_SIZE + 1)
    extension, _ = validate_manuscript_file(file.filename, content)
    if sample and expected_online_version is not None:
        raise HTTPException(503, 'Sample editor online drafts are not yet available')
    if expected_online_version is not None:
        if expected_online_version.startswith('docx:'):
            from app.routers.onlyoffice import selected_draft
            try:
                draft_bytes = selected_draft(db, manuscript_id, current_user.user_id, 'initial', expected_online_version[5:])
            except HTTPException:
                db.rollback(); raise
            valid = extension == '.docx' and hmac.compare_digest(content, draft_bytes)
        else:
            _, paths, draft, version = editor_text_drafts.state(db, BASE_DIR.resolve(), manuscript_id, current_user, 'initial')
            valid = bool(paths) and version == expected_online_version and hmac.compare_digest(content, draft.encode('utf-8'))
        if not valid:
            db.rollback()
            raise HTTPException(409, 'Selected online draft changed; reopen and select it again')

    # Sample and legacy objects have distinct roots and durable identities.
    artifact = None
    if sample:
        from app import sample_initial_editing
        artifact = sample_initial_editing.write(db, manuscript_id, extension, content)
        filename = artifact['version'] + extension
        stored_path = artifact['identity']
    else:
        upload_dir = guard_demo_path(BASE_DIR / "uploads" / "initial_editing" / str(manuscript_id))
        upload_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"editor_{current_user.user_id}_{timestamp}_{uuid4().hex[:8]}{extension}"
        file_path = upload_dir / filename
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=upload_dir, suffix=".tmp", delete=False) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(content)
            os.link(temp_path, file_path)
            temp_path.unlink()
        except OSError:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="Could not save edited document")
        stored_path = str(file_path.relative_to(BASE_DIR))

    # Step 8: Create an editing submission record.
    submission = InitialEditingSubmission(
        manuscript_id=manuscript_id,
        editor_id=current_user.user_id,
        file_path=stored_path,
        comments=comments,
        status="pending_author",
    )

    db.add(submission)
    if sample:
        db.flush()
        sample_initial_editing.bind(db, submission, artifact)

    # Step 9: Notify the author.
    db.add(
        Notification(
            user_id=manuscript.author_id,
            manuscript_id=manuscript_id,
            notification_type="initial_editing_submitted",
            message=(
                f"Editor {current_user.name} submitted an edited "
                f"document for manuscript #{manuscript_id}. "
                f"Comments: {comments}"
            ),
        )
    )

    # Step 10: Save the database changes.
    try:
        db.commit()
        db.refresh(submission)

    except Exception:
        db.rollback()
        # Commit acknowledgement can be ambiguous; retain the unique file
        # for reconciliation instead of deleting a possibly committed copy.
        raise

    return {
        "submission_id": submission.submission_id,
        "manuscript_id": manuscript_id,
        "editor_id": current_user.user_id,
        "filename": filename,
        **({} if sample else {"file_path": submission.file_path}),
        **({"version_id": artifact['version']} if sample else {}),
        "comments": submission.comments,
        "status": submission.status,
        "created_at": submission.created_at,
        "message": "Initial editing document submitted successfully",
    }

@router.get(
    "/initial-editing/submissions/{submission_id}/download",
    summary="Download Initial Editing Document",
)
def download_initial_editing_pdf(
    submission_id: int,
    current_user: User = Depends(
        require_role("author", "editor", "eic")
    ),
    db: Session = Depends(get_db),
):
    # Step 1: Find the editing submission.
    submission = db.get(
        InitialEditingSubmission,
        submission_id,
    )

    if submission is None:
        raise HTTPException(
            status_code=404,
            detail="Initial editing submission not found",
        )

    # Step 2: Find the related manuscript.
    manuscript = db.get(
        Manuscript,
        submission.manuscript_id,
    )

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Step 3: Check permissions.
    is_author = (
        current_user.role == "author"
        and manuscript.author_id == current_user.user_id
    )

    is_editor = (
        current_user.role == "editor"
        and submission.editor_id == current_user.user_id
    )

    is_eic = current_user.role == "eic"

    if not (is_author or is_editor or is_eic):
        raise HTTPException(
            status_code=403,
            detail="You cannot access this editing submission",
        )

    from app import sample_documents
    if sample_documents.registered(db, manuscript.manuscript_id):
        if is_editor:
            invitation = db.scalar(select(InitialEditorInvitation).where(
                InitialEditorInvitation.manuscript_id == manuscript.manuscript_id,
                InitialEditorInvitation.editor_id == current_user.user_id,
                InitialEditorInvitation.status == 'accepted'))
            from app.editor_invitation_revocation import effective_status
            if invitation is None or effective_status(db, 'initial', invitation) != 'accepted':
                raise HTTPException(403, 'Document unavailable')
        from app import sample_initial_editing
        from app.routers.manuscripts import ALLOWED_MANUSCRIPT_EXTENSIONS
        row, content = sample_initial_editing.read(db, submission)
        return Response(content, media_type=ALLOWED_MANUSCRIPT_EXTENSIONS['.' + row['file_format']],
                        headers={'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
                                 'Content-Disposition':f'attachment; filename="initial-editing.{row["file_format"]}"'})

    # Step 4: Resolve the stored PDF path safely.
    upload_root = guard_demo_path(
        BASE_DIR
        / "uploads"
        / "initial_editing"
        / str(manuscript.manuscript_id)
    ).resolve()

    pdf_path = guard_demo_path(BASE_DIR / submission.file_path).resolve()

    from app.routers.manuscripts import ALLOWED_MANUSCRIPT_EXTENSIONS
    if (
        not pdf_path.is_relative_to(upload_root)
        or pdf_path.suffix.lower() not in ALLOWED_MANUSCRIPT_EXTENSIONS
    ):
        raise HTTPException(
            status_code=500,
            detail="Invalid stored document path",
        )

    if not pdf_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Edited document file not found",
        )

    # Step 5: Return the PDF.
    return FileResponse(
        path=pdf_path,
        media_type=ALLOWED_MANUSCRIPT_EXTENSIONS[pdf_path.suffix.lower()],
        filename=(
            f"manuscript_{manuscript.manuscript_id}"
            f"_initial_edit_{submission.submission_id}{pdf_path.suffix.lower()}"
        ),
    )

@router.post(
    "/initial-editing/submissions/{submission_id}/author-review",
    summary="Review Initial Editing Submission as Author",
)
def review_initial_editing_as_author(
    submission_id: int,
    review_data: InitialEditingAuthorReview,
    current_user: User = Depends(require_role("author")),
    db: Session = Depends(get_db),
):
    # Step 1: Find the editing submission.
    submission = db.get(
        InitialEditingSubmission,
        submission_id,
    )

    if submission is None:
        raise HTTPException(
            status_code=404,
            detail="Initial editing submission not found",
        )

    # Step 2: Find the related manuscript.
    manuscript = db.get(
        Manuscript,
        submission.manuscript_id,
    )

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Step 3: Only the manuscript author can review.
    if manuscript.author_id != current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail="You are not the author of this manuscript",
        )

    # Step 4: Check workflow status.
    if manuscript.status != "initial_editing":
        raise HTTPException(
            status_code=409,
            detail="Manuscript is not in initial editing",
        )

    if submission.status != "pending_author":
        raise HTTPException(
            status_code=409,
            detail="This editing submission is not awaiting author review",
        )

    # Step 5: Record the author's decision.
    if review_data.decision == "approve":
        submission.status = "author_approved"
    else:
        submission.status = "author_revision_requested"

    submission.author_comments = review_data.comments
    submission.reviewed_at = datetime.now(timezone.utc)

    # Step 6: Notify the editor.
    db.add(
        Notification(
            user_id=submission.editor_id,
            manuscript_id=manuscript.manuscript_id,
            notification_type="initial_editing_author_review",
            message=(
                f"Author {current_user.name} reviewed initial editing "
                f"submission #{submission.submission_id}. "
                f"Decision: {review_data.decision}. "
                f"Comments: {review_data.comments}"
            ),
        )
    )

    # Step 7: Save changes.
    db.commit()
    db.refresh(submission)

    return {
        "submission_id": submission.submission_id,
        "manuscript_id": manuscript.manuscript_id,
        "author_id": current_user.user_id,
        "decision": review_data.decision,
        "status": submission.status,
        "author_comments": submission.author_comments,
        "reviewed_at": submission.reviewed_at,
        "message": "Author review submitted successfully",
    }

@router.post(
    "/initial-editing/submissions/{submission_id}/editor-approval",
    summary="Approve Initial Editing as Editor",
)
def approve_initial_editing_as_editor(
    submission_id: int,
    approval_data: InitialEditingEditorApproval,
    current_user: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
):
    # Step 1: Find the editing submission.
    submission = db.get(
        InitialEditingSubmission,
        submission_id,
    )

    if submission is None:
        raise HTTPException(
            status_code=404,
            detail="Initial editing submission not found",
        )

    # Step 2: Find the manuscript.
    manuscript = db.get(
        Manuscript,
        submission.manuscript_id,
    )

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Step 3: Verify the assigned editor.
    invitation = db.scalar(
        select(InitialEditorInvitation).where(
            InitialEditorInvitation.manuscript_id
            == manuscript.manuscript_id,
            InitialEditorInvitation.editor_id
            == current_user.user_id,
            InitialEditorInvitation.status == "accepted",
        )
    )

    from app.editor_invitation_revocation import effective_status
    if (
        invitation is None
        or effective_status(db,'initial',invitation) != 'accepted'
        or submission.editor_id != current_user.user_id
    ):
        raise HTTPException(
            status_code=403,
            detail="You are not the assigned editor",
        )

    # Step 4: Check the workflow stage.
    if manuscript.status != "initial_editing":
        raise HTTPException(
            status_code=409,
            detail="Manuscript is not in initial editing",
        )

    # Alice must approve before Bob can make a decision.
    if submission.status != "author_approved":
        raise HTTPException(
            status_code=409,
            detail="Author approval is required first",
        )

    # Step 5: Record Bob's decision.
    if approval_data.decision == "approve":
        submission.status = "editor_approved"
    else:
        submission.status = "editor_revision_requested"

    submission.editor_comments = approval_data.comments
    submission.editor_reviewed_at = datetime.now(timezone.utc)

    # Step 6: Notify the appropriate person.
    if approval_data.decision == "approve":
        # Notify the EIC who invited Bob.
        recipient_id = invitation.invited_by
        message = (
            f"Editor {current_user.name} approved initial editing "
            f"submission #{submission_id} for manuscript "
            f"#{manuscript.manuscript_id}. "
            f"Comments: {approval_data.comments}"
        )
    else:
        # Notify the author that further changes are required.
        recipient_id = manuscript.author_id
        message = (
            f"Editor {current_user.name} requested further changes "
            f"for initial editing submission #{submission_id}. "
            f"Comments: {approval_data.comments}"
        )

    db.add(
        Notification(
            user_id=recipient_id,
            manuscript_id=manuscript.manuscript_id,
            notification_type="initial_editing_editor_approval",
            message=message,
        )
    )

    # Step 7: Commit both the decision and notification.
    db.commit()
    db.refresh(submission)

    return {
        "submission_id": submission.submission_id,
        "manuscript_id": manuscript.manuscript_id,
        "editor_id": current_user.user_id,
        "decision": approval_data.decision,
        "status": submission.status,
        "editor_comments": submission.editor_comments,
        "editor_reviewed_at": submission.editor_reviewed_at,
        "message": "Editor approval submitted successfully",
    }

@router.post(
    "/initial-editing/submissions/{submission_id}/eic-approval",
    summary="Approve Initial Editing as EIC",
)
def approve_initial_editing_as_eic(
    submission_id: int,
    approval_data: InitialEditingEICApproval,
    current_user: User = Depends(require_role("eic")),
    db: Session = Depends(get_db),
):
    # Step 1: Find the initial editing submission.
    submission = db.get(
        InitialEditingSubmission,
        submission_id,
    )

    if submission is None:
        raise HTTPException(
            status_code=404,
            detail="Initial editing submission not found",
        )

    # Step 2: Find the manuscript.
    manuscript = db.get(
        Manuscript,
        submission.manuscript_id,
    )

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Step 3: Verify the workflow stage.
    if manuscript.status != "initial_editing":
        raise HTTPException(
            status_code=409,
            detail="Manuscript is not in initial editing",
        )

    # Bob must approve before Emma can review.
    if submission.status != "editor_approved":
        raise HTTPException(
            status_code=409,
            detail="Editor approval is required first",
        )

    # Step 4: Record Emma's decision.
    if approval_data.decision == "approve":
        submission.status = "eic_approved"
        submission.eic_approved_by = current_user.user_id

        # The author must still confirm the pre-review version.
        manuscript.status = "pre_review_confirmation"
    else:
        submission.status = "eic_revision_requested"
        submission.eic_approved_by = None

        # Return to initial editing.
        manuscript.status = "initial_editing"

    submission.eic_comments = approval_data.comments
    submission.eic_reviewed_at = datetime.now(timezone.utc)

    # Step 5: Notify Alice and Bob.
    recipients = {
        manuscript.author_id,
        submission.editor_id,
    }

    for recipient_id in recipients:
        db.add(
            Notification(
                user_id=recipient_id,
                manuscript_id=manuscript.manuscript_id,
                notification_type="initial_editing_eic_approval",
                message=(
                    f"EIC {current_user.name} reviewed initial editing "
                    f"submission #{submission_id}. "
                    f"Decision: {approval_data.decision}. "
                    f"Comments: {approval_data.comments}"
                ),
            )
        )

    # Step 6: Save the decision and notifications.
    db.commit()
    db.refresh(submission)
    db.refresh(manuscript)

    return {
        "submission_id": submission.submission_id,
        "manuscript_id": manuscript.manuscript_id,
        "eic_id": current_user.user_id,
        "decision": approval_data.decision,
        "submission_status": submission.status,
        "manuscript_status": manuscript.status,
        "eic_comments": submission.eic_comments,
        "eic_reviewed_at": submission.eic_reviewed_at,
        "eic_approved_by": submission.eic_approved_by,
        "message": "EIC approval submitted successfully",
    }

@router.post(
    "/initial-editing/submissions/{submission_id}/pre-review-confirmation",
    summary="Confirm Pre-review Version as Author",
)
def confirm_pre_review_version(
    submission_id: int,
    confirmation_data: PreReviewConfirmationRequest,
    current_user: User = Depends(require_role("author")),
    db: Session = Depends(get_db),
):
    # Step 1: Find the approved editing submission.
    submission = db.get(InitialEditingSubmission, submission_id)

    if submission is None:
        raise HTTPException(
            status_code=404,
            detail="Initial editing submission not found",
        )

    manuscript = db.get(Manuscript, submission.manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Step 2: Only the manuscript's author may confirm.
    if manuscript.author_id != current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail="Only the manuscript author can confirm this version",
        )

    # Step 3: Verify the workflow state.
    if manuscript.status != "pre_review_confirmation":
        raise HTTPException(
            status_code=409,
            detail="Manuscript is not awaiting pre-review confirmation",
        )

    if submission.status != "eic_approved":
        raise HTTPException(
            status_code=409,
            detail="EIC approval is required first",
        )

    # Step 4: Prevent duplicate decisions for this version.
    existing = db.scalar(
        select(PreReviewConfirmation).where(
            PreReviewConfirmation.submission_id == submission_id
        )
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="This version has already been reviewed by the author",
        )

    # Validate the exact approved submission, never the manuscript's latest file.
    from app.routers.manuscripts import MAX_MANUSCRIPT_FILE_SIZE, validate_manuscript_file
    from app import sample_documents
    sample = sample_documents.registered(db, manuscript.manuscript_id)
    if sample:
        from app import sample_initial_editing
        artifact, content = sample_initial_editing.read(db, submission)
        validate_manuscript_file('editing.' + artifact['file_format'], content, historical=True)
    else:
        upload_root = guard_demo_path(BASE_DIR / "uploads" / "initial_editing" / str(manuscript.manuscript_id)).resolve()
        pdf_path = guard_demo_path(BASE_DIR / submission.file_path).resolve()
        if not pdf_path.is_relative_to(upload_root) or not pdf_path.is_file():
            raise HTTPException(status_code=409, detail="Approved document is missing or has an invalid path")
        try:
            with pdf_path.open("rb") as document:
                validate_manuscript_file(pdf_path.name, document.read(MAX_MANUSCRIPT_FILE_SIZE + 1), historical=True)
        except (OSError, HTTPException):
            raise HTTPException(status_code=409, detail="Approved document is unavailable or invalid") from None

    # Step 6: Record Alice's decision and the PDF version.
    confirmation = PreReviewConfirmation(
        manuscript_id=manuscript.manuscript_id,
        submission_id=submission.submission_id,
        author_id=current_user.user_id,
        file_path=submission.file_path,
        decision=confirmation_data.decision,
        comments=confirmation_data.comments,
    )

    db.add(confirmation)

    if confirmation_data.decision == "confirm":
        # The manuscript can now proceed to peer review.
        manuscript.status = "ready_for_peer_review"
    else:
        # Further editing is required.
        manuscript.status = "initial_editing"

    # Step 7: Notify the EIC and assigned editor.
    recipients = {submission.editor_id}

    if submission.eic_approved_by is not None:
        recipients.add(submission.eic_approved_by)

    for recipient_id in recipients:
        db.add(
            Notification(
                user_id=recipient_id,
                manuscript_id=manuscript.manuscript_id,
                notification_type="pre_review_confirmation",
                message=(
                    f"Author {current_user.name} reviewed pre-review "
                    f"version for manuscript #{manuscript.manuscript_id}. "
                    f"Decision: {confirmation_data.decision}. "
                    f"Comments: {confirmation_data.comments}"
                ),
            )
        )

    # Step 8: Save everything.
    db.commit()
    db.refresh(confirmation)
    db.refresh(manuscript)

    return {
        "confirmation_id": confirmation.confirmation_id,
        "manuscript_id": manuscript.manuscript_id,
        "submission_id": submission.submission_id,
        "author_id": confirmation.author_id,
        "decision": confirmation.decision,
        "comments": confirmation.comments,
        **({} if sample else {"file_path": confirmation.file_path}),
        "confirmed_at": confirmation.confirmed_at,
        "manuscript_status": manuscript.status,
        "message": "Pre-review confirmation submitted successfully",
    }

@router.post(
    "/manuscripts/{manuscript_id}/decision",
    status_code=status.HTTP_201_CREATED,
    summary="Make EIC Decision After Peer Review",
)
def make_eic_decision(
    manuscript_id: int,
    decision_data: EICDecisionCreate,
    current_user: User = Depends(require_role("eic")),
    db: Session = Depends(get_db),
):
    # Step 1: Find the manuscript.
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Step 2: Check the manuscript workflow status.
    if manuscript.status not in (
        "ready_for_peer_review",
        "revised",
    ):
        raise HTTPException(
            status_code=409,
            detail="Manuscript is not ready for an EIC decision",
        )

    current_round = manuscript.review_round

    if (decision_data.expected_review_round is not None
            and decision_data.expected_review_round != current_round):
        raise HTTPException(status_code=409, detail="Review round changed; refresh before deciding")

    progress = review_progress(db, manuscript, current_round)
    if not progress['can_decide']:
        raise HTTPException(status_code=409, detail=progress['blocked_reason'])

    # Step 3: Get all reviewer assignments for this round.
    assignments = db.scalars(
        select(ReviewAssignment).where(
            ReviewAssignment.manuscript_id == manuscript_id,
            ReviewAssignment.review_round == current_round,
            not_declined(),
        )
    ).all()

    if not assignments:
        raise HTTPException(
            status_code=409,
            detail="No reviewers assigned for this round",
        )

    # Step 4: Require every assigned reviewer to finish.
    for assignment in assignments:
        review = db.scalar(
            select(Review).where(
                Review.assignment_id == assignment.assignment_id,
            )
        )

        if review is None or assignment.status != "completed":
            raise HTTPException(
                status_code=409,
                detail="Not all reviewers have completed their reviews",
            )

    # Step 5: Prevent duplicate decisions for the same round.
    existing_decision = db.scalar(
        select(EICDecision).where(
            EICDecision.manuscript_id == manuscript_id,
            EICDecision.review_round == current_round,
        )
    )

    if existing_decision is not None:
        raise HTTPException(
            status_code=409,
            detail="An EIC decision already exists for this review round",
        )

    template = None
    if decision_data.decision == 'accept':
        try:
            template = issuance_template(MODE)
        except RuntimeError:
            raise HTTPException(status_code=503, detail='Approved author agreement template is unavailable') from None
        from importlib import import_module
        guards = import_module('migrations.034_agreement_snapshot_guards')
        try:
            conn = db.connection()
            if conn.dialect.name != 'sqlite': raise RuntimeError('Agreement guards unavailable')
            raw = conn.connection.driver_connection
            installed = raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(guards.MIGRATION_ID,)).fetchone()
            present = any(raw.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone() for name in guards.DDL)
            if template.approval_status == 'approved' or installed or present:
                if not installed: raise RuntimeError('Agreement guards unavailable')
                for name, sql in guards.DDL.items():
                    row = raw.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
                    if not row or not row[0] or guards.normalize(row[0]) != guards.normalize(sql):
                        raise RuntimeError('Agreement guards unavailable')
        except Exception:
            raise HTTPException(status_code=503, detail='Agreement snapshot protection is unavailable') from None

    # Step 6: Map the decision to the next workflow status.
    status_map = {
        "accept": "awaiting_author_agreement",
        "reject": "rejected",
        "revision_required": "revision_required",
    }

    manuscript.status = status_map[decision_data.decision]

    # Step 7: Save the EIC decision history.
    decision = EICDecision(
        manuscript_id=manuscript_id,
        eic_id=current_user.user_id,
        review_round=current_round,
        decision=decision_data.decision,
        comments=decision_data.comments,
    )

    db.add(decision)
    if decision_data.decision == "accept":
        db.flush()
        db.add(AuthorAgreement(manuscript_id=manuscript_id, decision_id=decision.decision_id,
                               author_id=manuscript.author_id, agreement_version=template.version,
                               agreement_text=template.text, status="pending"))

    # Step 8: Notify the author.
    db.add(
        Notification(
            user_id=manuscript.author_id,
            manuscript_id=manuscript_id,
            notification_type="eic_decision",
            message=(
                f"EIC decision for manuscript #{manuscript_id}, "
                f"round {current_round}: {decision_data.decision}."
            ),
            is_read=False,
        )
    )

    # Step 9: Notify the editors responsible for this manuscript.
    editor_ids = {
        assignment.assigned_by
        for assignment in assignments
        if assignment.assigned_by is not None
    }

    for editor_id in editor_ids:
        if editor_id == current_user.user_id:
            continue
        recipient = db.get(User, editor_id)
        if not recipient or recipient.role not in ('editor', 'eic'):
            continue

        db.add(
            Notification(
                user_id=editor_id,
                manuscript_id=manuscript_id,
                notification_type="eic_decision",
                message=(
                    f"EIC decision for manuscript #{manuscript_id}, "
                    f"round {current_round}: {decision_data.decision}."
                ),
                is_read=False,
            )
        )

    # Step 10: Save everything.
    db.commit()
    db.refresh(decision)
    db.refresh(manuscript)

    return {
        "decision_id": decision.decision_id,
        "manuscript_id": manuscript.manuscript_id,
        "eic_id": decision.eic_id,
        "review_round": decision.review_round,
        "decision": decision.decision,
        "comments": decision.comments,
        "manuscript_status": manuscript.status,
        "decided_at": decision.decided_at,
        "message": "EIC decision recorded successfully",
    }

@router.post(
    "/final-editing/{manuscript_id}/submit",
    status_code=status.HTTP_201_CREATED,
    summary="Submit Final Editing Document",
)
def submit_final_editing(
    manuscript_id: int,
    file: UploadFile = File(...),
    comments: str = Form(...),
    expected_online_version: str | None = Form(None),
    current_user: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
):
    if expected_online_version is not None:
        connection = db.connection()
        if connection.dialect.name != 'sqlite' or connection.connection.driver_connection.in_transaction:
            raise HTTPException(503, 'Editor transaction unavailable')
        connection.exec_driver_sql('BEGIN IMMEDIATE')
    # Step 1: Find the manuscript.
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Step 2: Manuscript must be in final editing.
    if manuscript.status != "final_editing":
        raise HTTPException(
            status_code=409,
            detail="Manuscript is not in final editing",
        )

    # Existing final-editing manuscripts without an agreement retain legacy behavior.
    agreement = db.scalar(select(AuthorAgreement).where(AuthorAgreement.manuscript_id == manuscript_id).order_by(AuthorAgreement.agreement_id.desc()).limit(1))
    if agreement is None and db.scalar(select(FinalEditorInvitation.invitation_id).where(
            FinalEditorInvitation.manuscript_id == manuscript_id).limit(1)) is not None:
        raise HTTPException(status_code=409, detail="Author agreement acceptance is required before final editing")
    if agreement is not None and not accepted_current_agreement(db, manuscript):
        raise HTTPException(status_code=409, detail="Author agreement acceptance is required before final editing")

    # New agreements require an accepted final-editor invitation; historical
    # final-editing records without agreements keep their previous rule.
    final_invitation = None
    if agreement is not None:
        final_invitation = db.scalar(select(FinalEditorInvitation).where(
            FinalEditorInvitation.manuscript_id == manuscript_id,
            FinalEditorInvitation.status == 'accepted'))
        from app.editor_invitation_revocation import effective_status
        if final_invitation is None or final_invitation.editor_id != current_user.user_id or effective_status(db,'final',final_invitation) != 'accepted':
            raise HTTPException(status_code=403, detail='Only the accepted final editor may submit')
        latest = db.scalar(select(FinalEditingSubmission).join(FinalEditingSubmissionInvitation,
            FinalEditingSubmissionInvitation.submission_id == FinalEditingSubmission.submission_id).where(
            FinalEditingSubmission.manuscript_id == manuscript_id).order_by(FinalEditingSubmission.submission_id.desc()).limit(1))
        if latest is not None and latest.status not in ('eic_revision_requested', 'author_revision_requested'):
            raise HTTPException(status_code=409, detail='The current final edit is awaiting review or already approved')
    else:
        editor_assignment = db.scalar(
        select(ReviewAssignment).where(
            ReviewAssignment.manuscript_id == manuscript_id,
            ReviewAssignment.assigned_by == current_user.user_id,
        )
        )
        if editor_assignment is None:
            raise HTTPException(status_code=403, detail="You are not an assigned editor for this manuscript")

    from app import sample_documents
    sample = sample_documents.registered(db, manuscript_id)
    if sample:
        if final_invitation is None or expected_online_version is not None:
            raise HTTPException(503, 'Sample final editing requires an accepted assignment and uploaded artifact')
        connection = db.connection()
        if connection.dialect.name != 'sqlite' or connection.connection.driver_connection.in_transaction:
            raise HTTPException(503, 'Editor transaction unavailable')
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        db.refresh(manuscript); db.refresh(final_invitation)
        from app.editor_invitation_revocation import effective_status
        if (manuscript.status != 'final_editing' or not accepted_current_agreement(db, manuscript)
                or final_invitation.editor_id != current_user.user_id
                or effective_status(db, 'final', final_invitation) != 'accepted'):
            raise HTTPException(409, 'Final editing assignment changed')

    # Step 4: Prevent multiple pending submissions.
    pending_submission = db.scalar(
        select(FinalEditingSubmission).where(
            FinalEditingSubmission.manuscript_id == manuscript_id,
            FinalEditingSubmission.status.in_(
                ["pending_author", "author_approved"]
            ),
        )
    )

    if pending_submission is not None:
        raise HTTPException(
            status_code=409,
            detail="A final editing submission is awaiting approval",
        )

    # Step 5: Validate comments.
    comments = comments.strip()

    if not comments or len(comments) > 5000:
        raise HTTPException(
            status_code=400,
            detail="Comments must contain 1 to 5000 characters",
        )

    # Final editing may supply a PDF or UTF-8 text source; the formatted
    # publication proof remains a separately reviewed PDF.
    from app.routers.manuscripts import ALLOWED_MANUSCRIPT_EXTENSIONS, validate_manuscript_file
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_MANUSCRIPT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Final editing accepts PDF, DOCX, DOC or UTF-8 TXT files")
    if extension == ".pdf" and file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="PDF content type is required")
    max_size = 10 * 1024 * 1024
    content = file.file.read(max_size + 1)
    validate_manuscript_file(file.filename, content)
    if expected_online_version is not None:
        if expected_online_version.startswith('docx:'):
            from app.routers.onlyoffice import selected_draft
            try:
                draft_bytes = selected_draft(db, manuscript_id, current_user.user_id, 'final', expected_online_version[5:])
            except HTTPException:
                db.rollback(); raise
            valid = extension == '.docx' and hmac.compare_digest(content, draft_bytes)
        else:
            _, paths, draft, version = editor_text_drafts.state(db, BASE_DIR.resolve(), manuscript_id, current_user, 'final')
            valid = bool(paths) and version == expected_online_version and hmac.compare_digest(content, draft.encode('utf-8'))
        if not valid:
            db.rollback()
            raise HTTPException(409, 'Selected online draft changed; reopen and select it again')

    artifact = None
    if sample:
        from app import sample_stage_artifacts
        artifact = sample_stage_artifacts.write(db, 'final_editing', manuscript_id, extension, content)
        filename = artifact['version'] + extension
        stored_path = artifact['identity']
    else:
        upload_dir = guard_demo_path(BASE_DIR / "uploads" / "final_editing" / str(manuscript_id))
        upload_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"editor_{current_user.user_id}_{timestamp}_{uuid4().hex[:8]}{extension}"
        file_path = upload_dir / filename
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=upload_dir, suffix=".tmp", delete=False) as temp_file:
                temp_path = Path(temp_file.name); temp_file.write(content)
            os.link(temp_path, file_path); temp_path.unlink()
        except OSError:
            if temp_path is not None: temp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="Could not save final edited document")
        stored_path = str(file_path.relative_to(BASE_DIR))

    # Step 8: Create final editing record.
    submission = FinalEditingSubmission(
        manuscript_id=manuscript_id,
        editor_id=current_user.user_id,
        file_path=stored_path,
        comments=comments,
        status="pending_eic" if final_invitation else "pending_author",
    )

    db.add(submission)

    # Step 9: Notify author.
    db.add(
        Notification(
            user_id=final_invitation.invited_by if final_invitation else manuscript.author_id,
            manuscript_id=manuscript_id,
            notification_type="final_editing_submitted",
            message=(
                f"Editor {current_user.name} submitted a final edited "
                f"document for manuscript #{manuscript_id}. "
                f"Comments: {comments}"
            ),
        )
    )

    # Step 10: Commit.
    try:
        db.flush()
        if final_invitation:
            db.add(FinalEditingSubmissionInvitation(submission_id=submission.submission_id, invitation_id=final_invitation.invitation_id))
        if sample:
            db.flush()
            sample_stage_artifacts.bind(db, submission, current_user.user_id, artifact)
        db.commit()
        db.refresh(submission)

    except Exception:
        db.rollback()
        # Commit acknowledgement can be ambiguous; retain the unique file
        # for reconciliation instead of deleting a possibly committed copy.
        raise

    return {
        "submission_id": submission.submission_id,
        "manuscript_id": manuscript_id,
        "editor_id": current_user.user_id,
        "filename": filename,
        **({} if sample else {"file_path": submission.file_path}),
        **({"version_id": artifact['version']} if sample else {}),
        "comments": submission.comments,
        "status": submission.status,
        "created_at": submission.created_at,
        "message": "Final editing document submitted successfully",
    }

@router.get(
    "/final-editing/submissions/{submission_id}/download",
    summary="Download Final Editing Document",
)
def download_final_editing_pdf(
    submission_id: int,
    current_user: User = Depends(
        require_role("author", "editor", "eic")
    ),
    db: Session = Depends(get_db),
):
    # Step 1: Find the final editing submission.
    submission = db.get(
        FinalEditingSubmission,
        submission_id,
    )

    if submission is None:
        raise HTTPException(
            status_code=404,
            detail="Final editing submission not found",
        )

    # Step 2: Find the related manuscript.
    manuscript = db.get(
        Manuscript,
        submission.manuscript_id,
    )

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Step 3: Check permissions.
    is_author = (
        current_user.role == "author"
        and manuscript.author_id == current_user.user_id
    )

    is_editor = (
        current_user.role == "editor"
        and submission.editor_id == current_user.user_id
    )

    is_eic = current_user.role == "eic"

    if not (is_author or is_editor or is_eic):
        raise HTTPException(
            status_code=403,
            detail="You cannot access this final editing submission",
        )

    from app import sample_documents
    if sample_documents.registered(db, manuscript.manuscript_id):
        if is_editor:
            invitation = db.scalar(select(FinalEditorInvitation).join(FinalEditingSubmissionInvitation,
                FinalEditingSubmissionInvitation.invitation_id == FinalEditorInvitation.invitation_id).where(
                FinalEditingSubmissionInvitation.submission_id == submission_id,
                FinalEditorInvitation.manuscript_id == manuscript.manuscript_id,
                FinalEditorInvitation.editor_id == current_user.user_id))
            from app.editor_invitation_revocation import effective_status
            if invitation is None or effective_status(db, 'final', invitation) != 'accepted':
                raise HTTPException(403, 'Document unavailable')
        from app import sample_stage_artifacts
        from app.routers.manuscripts import ALLOWED_MANUSCRIPT_EXTENSIONS
        row, content = sample_stage_artifacts.read(db, 'final_editing', submission)
        return Response(content, media_type=ALLOWED_MANUSCRIPT_EXTENSIONS['.' + row['file_format']],
                        headers={'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
                                 'Content-Disposition':f'attachment; filename="final-editing.{row["file_format"]}"'})

    # Step 4: Resolve the PDF path safely.
    upload_root = guard_demo_path(
        BASE_DIR
        / "uploads"
        / "final_editing"
        / str(manuscript.manuscript_id)
    ).resolve()

    pdf_path = guard_demo_path(BASE_DIR / submission.file_path).resolve()

    if (
        not pdf_path.is_relative_to(upload_root)
        or pdf_path.suffix.lower() not in (".pdf", ".txt", ".docx", ".doc")
    ):
        raise HTTPException(
            status_code=500,
            detail="Invalid stored final editing path",
        )

    if not pdf_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Final edited document not found",
        )

    # Step 5: Return the PDF.
    return FileResponse(
        path=pdf_path,
        media_type={".txt": "text/plain", ".pdf": "application/pdf", ".doc": "application/msword", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[pdf_path.suffix.lower()],
        filename=(
            f"manuscript_{manuscript.manuscript_id}"
            f"_final_edit_{submission.submission_id}{pdf_path.suffix.lower()}"
        ),
    )

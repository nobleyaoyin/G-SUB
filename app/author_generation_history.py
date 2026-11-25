"""Owner-safe projection: no reviewer documents, identities or private comments."""
from datetime import datetime, timezone
from fastapi import HTTPException

from sqlalchemy import inspect, select
from app.models import (AuthorAgreement, FinalEditorInvitation, FinalEditingSubmission, FinalEditingSubmissionInvitation,
    FormatterInvitation, FormattingSubmission, InitialEditingSubmission, Notification, PreReviewConfirmation,
    PrototypePublication, ReviewRoundFile)


def approved_final_submissions(db, manuscript_id):
    """Final artifacts with matching manuscript, editor and recorded approvals."""
    return db.scalars(select(FinalEditingSubmission).join(FinalEditingSubmissionInvitation).join(
        FinalEditorInvitation, FinalEditorInvitation.invitation_id == FinalEditingSubmissionInvitation.invitation_id).where(
        FinalEditingSubmission.manuscript_id == manuscript_id, FinalEditingSubmission.status == 'author_approved',
        FinalEditorInvitation.manuscript_id == manuscript_id, FinalEditorInvitation.editor_id == FinalEditingSubmission.editor_id,
        FinalEditorInvitation.status == 'accepted', FinalEditingSubmission.author_reviewed_at.is_not(None),
        FinalEditingSubmission.eic_reviewed_at.is_not(None), FinalEditingSubmission.eic_approved_by.is_not(None))).all()


def generation_history(db, manuscript):
    mid=manuscript.manuscript_id
    tables=set(inspect(db.connection()).get_table_names())
    entries=[]; unavailable=[]
    def add(key,section,stage,title,round_no=None,when=None,status='Historical release status unavailable.',version=None,download=None,file_format=None):
        entries.append({'id':key,'section':section,'stage':stage,'title':title,'review_round':round_no,
                        'recorded_at':when,'status':status,'version':version,'download':download,
                        'file_format':file_format if file_format in {'pdf','docx','doc','txt'} else None})
    try:
        from app.submission_snapshot_history import snapshot_rows
        snapshots=snapshot_rows(db, manuscript)
    except HTTPException:
        snapshots=[]; unavailable.append('submission snapshot evidence')
    for item in snapshots:
        try:
            when=datetime.fromisoformat(item['submitted_at'].replace('Z','+00:00'))
        except (ValueError, TypeError, AttributeError):
            when=None
        initial=item['submission_kind']=='initial'
        add(f"submission-snapshot:{item['snapshot_id']}", 'submissions' if initial else 'generations',
            'Submission' if initial else 'Revision', 'Original submission source' if initial else 'Author revision source',
            round_no=item['review_round'], when=when, status='Submitted; integrity verified on download',
            version=item['submission_sequence'], download={'kind':'author_submission','id':item['snapshot_id']},
            file_format=item['file_format'])
    if 'notifications' in tables:
        notification=db.scalar(select(Notification).where(Notification.manuscript_id==mid,
            Notification.notification_type=='manuscript_submitted').order_by(Notification.notification_id).limit(1))
        if notification and not any(x['submission_kind']=='initial' for x in snapshots):
            add('original-submission','submissions','Submission','Original submission notification',when=notification.created_at,status='Submission recorded; exact file version unavailable')
    else: unavailable.append('submission evidence')
    if 'review_round_files' in tables:
        rows=db.scalars(select(ReviewRoundFile).where(ReviewRoundFile.manuscript_id==mid,
            ReviewRoundFile.source_kind=='author_revision').order_by(ReviewRoundFile.review_round)).all()
        for row in rows:
            if any(x['submission_kind']=='peer_revision' and x['review_round']==row.review_round and x['file_ref']==row.file_path for x in snapshots):
                continue
            add(f'revision:{row.round_file_id}','generations','Revision','Author revision source',round_no=row.review_round,
                when=row.created_at,status='Revision source recorded; file integrity unavailable')
    else: unavailable.append('revision evidence')
    if {'pre_review_confirmations','initial_editing_submissions','review_round_files'} <= tables:
        rows=db.execute(select(PreReviewConfirmation,InitialEditingSubmission,ReviewRoundFile).join(InitialEditingSubmission,
            InitialEditingSubmission.submission_id==PreReviewConfirmation.submission_id).outerjoin(ReviewRoundFile,
            (ReviewRoundFile.confirmation_id==PreReviewConfirmation.confirmation_id) &
            (ReviewRoundFile.manuscript_id==mid) & (ReviewRoundFile.source_kind=='initial_editing') &
            (ReviewRoundFile.review_round==1) & (ReviewRoundFile.file_path==InitialEditingSubmission.file_path)).where(
            PreReviewConfirmation.manuscript_id==mid,InitialEditingSubmission.manuscript_id==mid,
            PreReviewConfirmation.author_id==manuscript.author_id,PreReviewConfirmation.decision=='confirm',
            InitialEditingSubmission.status=='eic_approved')).all()
        for confirmation,submission,source in rows:
            if not confirmation.file_path or confirmation.file_path != submission.file_path:
                if 'initial editing evidence inconsistent' not in unavailable:
                    unavailable.append('initial editing evidence inconsistent')
                continue
            add(f'initial-confirmation:{confirmation.confirmation_id}','generations','Initial Editing',
                'Author-confirmed editorial source',round_no=source.review_round if source else None,when=confirmation.confirmed_at,
                status='Confirmed; file integrity unavailable')
    else: unavailable.append('initial editing evidence')
    if {'final_editing_submissions','final_editing_submission_invitations','final_editor_invitations'} <= tables:
        rows=approved_final_submissions(db, mid)
        for row in rows:
            add(f'final:{row.submission_id}','outputs','Final Editing','Approved final editing document',
                when=row.eic_reviewed_at,status='Approved; file integrity unavailable',
                download={'kind':'approved_final','id':row.submission_id})
    else: unavailable.append('final editing evidence')
    if 'author_agreements' in tables:
        for item in db.scalars(select(AuthorAgreement).where(AuthorAgreement.manuscript_id==mid,
            AuthorAgreement.author_id==manuscript.author_id)):
            add(f'agreement:{item.agreement_id}','outputs','Author Agreement','Author agreement',when=item.created_at,
                status=f'Agreement {item.status}; approval of template not established here',version=item.agreement_version)
    else: unavailable.append('agreement evidence')
    if {'formatting_submissions','formatter_invitations'} <= tables:
        for item in db.scalars(select(FormattingSubmission).join(FormatterInvitation,
            FormatterInvitation.invitation_id==FormattingSubmission.invitation_id).where(FormattingSubmission.manuscript_id==mid,
            FormatterInvitation.manuscript_id==mid,FormatterInvitation.status=='accepted',
            FormattingSubmission.status=='approved',FormattingSubmission.author_reviewed_at.is_not(None),
            FormattingSubmission.eic_reviewed_at.is_not(None),FormattingSubmission.eic_id.is_not(None))):
            publication=db.get(PrototypePublication,mid) if 'prototype_publications' in tables else None
            published=bool(publication and publication.submission_id==item.submission_id)
            add(f'formatting:{item.submission_id}','outputs','Publication' if published else 'Formatting',
                'Published formatting artifact' if published else 'Approved formatting artifact',
                when=publication.published_at if published else item.eic_reviewed_at,
                status='Published (local prototype)' if published else 'Approved',
                download={'kind':'approved_formatting','id':item.submission_id})
    else: unavailable.append('formatting evidence')
    def chronological(entry):
        value = entry['recorded_at']
        if not isinstance(value, datetime):
            return (1, datetime.max, entry['id'])
        # SQLite strips timezone information from the UTC timestamps stored by this application.
        utc = value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
        return (0, utc, entry['id'])
    entries.sort(key=chronological)
    return {'manuscript_id':mid,'entries':entries,'unavailable_sources':unavailable,
        'historical_notice':'Historical release status unavailable. Artifacts with unknown release are not listed.'}

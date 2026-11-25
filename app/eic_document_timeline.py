"""EIC-only, read-only projection of recorded document evidence.

A source binding is not a receipt; missing integrity and transfer evidence remain
unknown. This projection never returns storage locations or manuscript contents.
"""
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import inspect, select, text
from app.agreement_content import TEMPLATES, snapshot_status
from app.models import (AuthorAgreement, FinalEditingSubmission, FormattingSubmission,
    InitialEditingSubmission, InitialEditorInvitation, FinalEditorInvitation, Notification, PreReviewConfirmation, PrototypePublication,
    ReviewAssignment, ReviewAssignmentFile, ReviewRoundFile)


def _recorded_time_key(event):
    """Sort recorded timestamps without claiming a transfer sequence."""
    value = event.get('timestamp')
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if not isinstance(value, datetime):
            raise ValueError('No recorded timestamp')
        value = value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
        return (0, value, event['id'])
    except (ValueError, TypeError, OverflowError):
        return (1, datetime.max, event['id'])


def document_timeline(db, manuscript):
    mid = manuscript.manuscript_id
    available = set(inspect(db.connection()).get_table_names())
    events = []
    unavailable = []

    def add(key, stage, kind, direction, at=None, review_round=None, version=None, round_kind=None,
            status='unknown', source='unknown', destination='unknown', integrity='unknown', download=None,
            notification_evidence=None, email_evidence=None, download_evidence=None):
        events.append({'id': key, 'stage': stage, 'artifact_type': kind,
            'direction': direction, 'timestamp': at, 'review_round': review_round, 'round_kind':round_kind,
            'version': version, 'status': status, 'source': source,
            'destination': destination, 'integrity': integrity, 'download': download,
            'notification_evidence': notification_evidence, 'email_evidence': email_evidence,
            'download_evidence': download_evidence})

    try:
        from app.submission_snapshot_history import snapshot_rows
        snapshots = snapshot_rows(db, manuscript)
    except HTTPException:
        snapshots = []; unavailable.append('submission snapshot evidence')
    for item in snapshots:
        add(f"submission-snapshot:{item['snapshot_id']}", 'Submission' if item['submission_kind']=='initial' else 'Revision',
            'author submission source', 'inbound', item['submitted_at'], review_round=item['review_round'],
            version=item['submission_sequence'], status='submitted', source='Author', destination='G-SUB',
            integrity='verified on download', download={'kind':'author_submission','id':item['snapshot_id']})

    if 'notifications' in available:
        notices = db.scalars(select(Notification).where(Notification.manuscript_id == mid,
            Notification.notification_type == 'manuscript_submitted').order_by(Notification.notification_id)).all()
        if notices:
            add(f'submission-notification:{notices[0].notification_id}', 'Submission', 'submission notification',
                'inbound', notices[0].created_at, status='recorded', source='Author', destination='G-SUB')
        responses = db.scalars(select(Notification).where(Notification.manuscript_id == mid,
            Notification.notification_type.in_(['initial_editor_response', 'final_editor_response']))).all()
        for notice in responses:
            initial = notice.notification_type == 'initial_editor_response'
            table = 'initial_editor_invitations' if initial else 'final_editor_invitations'
            model = InitialEditorInvitation if initial else FinalEditorInvitation
            match = re.search(r' (accepted|declined) the invitation #([0-9]+) for manuscript #([0-9]+)\.$', notice.message or '')
            invitation = db.get(model, int(match.group(2))) if match and table in available else None
            verified = bool(invitation and int(match.group(3)) == mid and invitation.manuscript_id == mid
                and invitation.invited_by == notice.user_id and invitation.status == match.group(1))
            status = ('in-app acceptance notification recorded' if match.group(1) == 'accepted'
                      else 'in-app decline notification recorded') if verified else 'in-app response notification recorded; association unavailable'
            add(f'editor-response-notification:{notice.notification_id}', 'Initial Editing' if initial else 'Final Editing',
                'editor invitation response notification', 'unknown', notice.created_at, status=status,
                source='Initial Editor' if initial else 'Final Editor', destination='Inviting EIC' if verified else 'unknown')
    else:
        unavailable.append('submission notifications')
    if 'initial_editing_submissions' in available:
        for item in db.scalars(select(InitialEditingSubmission).where(InitialEditingSubmission.manuscript_id == mid)):
            add(f'initial:{item.submission_id}', 'Initial Editing', 'editing submission', 'inbound',
                item.created_at, status='uploaded', source='Initial Editor', destination='G-SUB')
    else: unavailable.append('initial editing submissions')
    if 'pre_review_confirmations' in available:
        for item in db.scalars(select(PreReviewConfirmation).where(PreReviewConfirmation.manuscript_id == mid)):
            add(f'confirmation:{item.confirmation_id}', 'Initial Editing', 'pre-review confirmation', 'unknown',
                item.confirmed_at, status='recorded', source='Author', destination='unknown')
    else: unavailable.append('pre-review confirmations')
    if 'review_round_files' in available:
        for item in db.scalars(select(ReviewRoundFile).where(ReviewRoundFile.manuscript_id == mid)):
            stage = 'Revision' if item.source_kind == 'author_revision' else 'Peer Review'
            add(f'round-source:{item.round_file_id}', stage, item.source_kind, 'inbound' if stage == 'Revision' else 'unknown',
                item.created_at, review_round=item.review_round, status='source bound',
                source='Author' if stage == 'Revision' else 'Initial Editing', destination='unknown')
    else: unavailable.append('review round sources')
    bound_assignments = set()
    if {'review_assignment_files', 'review_round_files', 'review_assignments'} <= available:
        rows = db.execute(select(ReviewAssignmentFile, ReviewRoundFile, ReviewAssignment).join(
            ReviewRoundFile, ReviewRoundFile.round_file_id == ReviewAssignmentFile.round_file_id).join(
            ReviewAssignment, ReviewAssignment.assignment_id == ReviewAssignmentFile.assignment_id).where(
            ReviewAssignment.manuscript_id == mid, ReviewRoundFile.manuscript_id == mid,
            ReviewAssignment.review_round == ReviewRoundFile.review_round)).all()
        for binding, source, assignment in rows:
            bound_assignments.add(assignment.assignment_id)
            add(f'reviewer-binding:{assignment.assignment_id}', 'Peer Review', 'assignment source binding',
                'outbound', binding.bound_at, review_round=source.review_round,
                status='bound; delivery unknown', source='G-SUB', destination=f'Assignment #{assignment.assignment_id}')
    else: unavailable.append('review assignment bindings')
    if 'review_assignments' in available:
        for assignment in db.scalars(select(ReviewAssignment).where(ReviewAssignment.manuscript_id == mid)):
            if assignment.assignment_id not in bound_assignments:
                add(f'reviewer-binding-unavailable:{assignment.assignment_id}', 'Peer Review',
                    'assignment source binding', 'outbound', review_round=assignment.review_round,
                    status='source binding unavailable; delivery unknown',
                    destination=f'Assignment #{assignment.assignment_id}', integrity='unavailable')
    if 'final_editing_submissions' in available:
        for item in db.scalars(select(FinalEditingSubmission).where(FinalEditingSubmission.manuscript_id == mid)):
            add(f'final:{item.submission_id}', 'Final Editing', 'editing submission', 'inbound', item.created_at,
                status='uploaded', source='Final Editor', destination='G-SUB',
                integrity='unavailable', download={'kind':'final_editing','id':item.submission_id})
    else: unavailable.append('final editing submissions')
    if 'author_agreements' in available:
        for item in db.scalars(select(AuthorAgreement).where(AuthorAgreement.manuscript_id == mid)):
            template_state = snapshot_status(item.agreement_version, item.agreement_text)
            template = TEMPLATES.get(item.agreement_version)
            if template_state == 'approved' and not (template and template.approval_reference and template.approved_by and template.approved_at):
                template_state = 'unverified'
            template_label = {'prototype':'template approval pending', 'approved':'approved template',
                              'unverified':'template approval unavailable'}.get(template_state, 'template approval unavailable')
            add(f'agreement:{item.agreement_id}', 'Author Agreement', 'agreement', 'outbound', item.created_at,
                version=item.agreement_version, status=f'generated; Author {item.status}; {template_label}', source='G-SUB', destination='Author')
    else: unavailable.append('author agreements')
    if 'formatting_submissions' in available:
        for item in db.scalars(select(FormattingSubmission).where(FormattingSubmission.manuscript_id == mid)):
            add(f'formatting:{item.submission_id}', 'Formatting', 'formatting submission', 'inbound',
                item.created_at, status=f'uploaded; review {item.status}', source='Formatter', destination='G-SUB',
                integrity='verified on download', download={'kind':'formatting','id':item.submission_id})
    else: unavailable.append('formatting submissions')
    if 'prototype_publications' in available:
        for item in db.scalars(select(PrototypePublication).where(PrototypePublication.manuscript_id == mid)):
            add(f'publication:{item.submission_id}', 'Publication', 'publication record', 'outbound',
                item.published_at, status='publication recorded', source='G-SUB', destination='unknown')
    else: unavailable.append('publication records')
    if {'distribution_artifacts', 'distribution_grants', 'distribution_revocations'} <= available:
        round_join = 'LEFT JOIN editor_distribution_grant_rounds r ON r.grant_id=g.grant_id AND r.manuscript_id=g.manuscript_id' if 'editor_distribution_grant_rounds' in available else ''
        round_column = 'r.review_round' if round_join else 'NULL'
        kind_column = 'r.round_kind' if round_join else 'NULL'
        mode_column = 'r.mode' if round_join else 'NULL'
        rows = db.execute(text(f'''SELECT g.grant_id,g.initial_invitation_id,g.final_invitation_id,
            g.recipient_id,g.created_at,a.version,{round_column} AS round_no,{kind_column} AS round_kind,{mode_column} AS mode,rev.created_at AS revoked_at,
            g.notification_state,g.email_state
            FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id
            AND a.manuscript_id=g.manuscript_id LEFT JOIN distribution_revocations rev ON rev.grant_id=g.grant_id {round_join}
            WHERE g.manuscript_id=:mid AND g.recipient_role='editor' '''), {'mid':mid}).all()
        for row in rows:
            stage = 'Initial Editing' if row.initial_invitation_id else 'Final Editing'
            add(f'grant:{row.grant_id}', stage, 'editor source grant', 'outbound', row.created_at,
                review_round=row.round_no, round_kind=row.round_kind, version=row.version,
                status=f'{row.mode+" " if row.mode in ("manual","automatic") else ""}grant {"revoked" if row.revoked_at else "recorded"}; delivery unknown',
                source='G-SUB', destination=f'Editor #{row.recipient_id}', integrity='digest recorded; not verified',
                notification_evidence=row.notification_state if row.notification_state in ('created', 'not_requested') else 'unknown',
                email_evidence=row.email_state if row.email_state == 'not_requested' else 'unknown',
                download_evidence='unknown')
        reviewed = db.execute(text('''SELECT artifact_id,review_round,review_assignment_id,version,created_at,format
            FROM distribution_artifacts WHERE manuscript_id=:mid AND kind='reviewed_document' '''), {'mid':mid}).all()
        for row in reviewed:
            add(f'reviewed:{row.artifact_id}', 'Peer Review', 'reviewed document', 'inbound', row.created_at,
                review_round=row.review_round, version=row.version, status='uploaded',
                source=f'Assignment #{row.review_assignment_id}', destination='G-SUB',
                integrity='verified on download', download={'kind':'reviewed_document','id':row.artifact_id,'format':row.format})
    else: unavailable.append('distribution and reviewed documents')
    events.sort(key=_recorded_time_key)
    return {'manuscript_id':mid, 'events':events, 'unavailable_sources':unavailable}

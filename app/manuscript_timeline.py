"""Small, read-only timeline of recorded events; never includes comment text."""
from datetime import datetime, timezone
from sqlalchemy import select
from app.models import (
    AuthorAgreement, EICDecision, EICInitialScan, FinalEditingSubmission,
    FinalEditorInvitation, FormatterInvitation, FormattingSubmission,
    InitialEditingSubmission, InitialEditorInvitation, PrototypePublication,
    Review, ReviewAssignment, ReviewerInvitation, ReviewerInvitationInvalidation,
    ReviewRoundFile, Notification,
)
from app.reviewer_invitations import may_review


def _timestamp(value):
    """Normalize real dates to UTC; unknown or malformed dates stay unknown."""
    try:
        if isinstance(value, str):
            if len(value) < 16 or value[10] not in ('T', ' '):
                return None
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if not isinstance(value, datetime):
            return None
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()
    except (ValueError, OverflowError):
        return None


def _event_order(item):
    return item['timestamp'] is not None, item['timestamp'] or '', item['key']


def reviewer_timeline_assignments(db, manuscript, user):
    """Only current, eligible assignments with no recorded invalidation."""
    candidates = db.scalars(select(ReviewAssignment).where(
        ReviewAssignment.manuscript_id == manuscript.manuscript_id,
        ReviewAssignment.reviewer_id == user.user_id,
        ReviewAssignment.review_round == manuscript.review_round,
        ReviewAssignment.status.in_(('assigned', 'completed')))).all()
    return [assignment for assignment in candidates if may_review(db, assignment)
            and not db.scalar(select(ReviewerInvitationInvalidation.invalidation_id).where(
                ReviewerInvitationInvalidation.assignment_id == assignment.assignment_id))]


def role_timeline(db, manuscript, user):
    events = []
    def add(kind, stage, identifier, at, description, round_no=None, *, recorded=False):
        # A row can establish an event even when its historical date is absent.
        # Optional workflow timestamps alone cannot establish an event.
        at = _timestamp(at)
        if at is None and not recorded:
            return
        events.append({'key': f'{kind}:{identifier}', 'stage': stage, 'timestamp': at,
                       'description': description, 'review_round': round_no})
    mid, uid, role = manuscript.manuscript_id, user.user_id, user.role
    if role == 'reviewer':
        assignments = reviewer_timeline_assignments(db, manuscript, user)
        for a in assignments:
            invitation = db.get(ReviewerInvitation, a.assignment_id)
            if invitation:
                add('review-invitation', 'Peer Review', a.assignment_id, invitation.invited_at, 'Review invitation received', a.review_round, recorded=True)
                if invitation.status in ('accepted', 'declined'):
                    add('review-response', 'Peer Review', a.assignment_id, invitation.responded_at, f'Invitation {invitation.status}', a.review_round, recorded=True)
            review = db.scalar(select(Review).where(Review.assignment_id == a.assignment_id))
            if review:
                add('review', 'Peer Review', a.assignment_id, review.submitted_at, 'Review submitted', a.review_round, recorded=True)
    elif role == 'formatter':
        invitations = db.scalars(select(FormatterInvitation).where(
            FormatterInvitation.manuscript_id == mid, FormatterInvitation.formatter_id == uid,
            FormatterInvitation.status == 'accepted')).all()
        for inv in invitations:
            add('format-invitation', 'Formatting', inv.invitation_id, inv.invited_at, 'Formatting invitation received', recorded=True)
            add('format-accepted', 'Formatting', inv.invitation_id, inv.responded_at, 'Formatting invitation accepted', recorded=True)
            for sub in db.scalars(select(FormattingSubmission).where(FormattingSubmission.invitation_id == inv.invitation_id)):
                add('format-submission', 'Formatting', sub.submission_id, sub.created_at, 'Formatting submitted', recorded=True)
                add('format-author-review', 'Formatting', sub.submission_id, sub.author_reviewed_at, 'Author reviewed formatting')
                add('format-eic-review', 'Formatting', sub.submission_id, sub.eic_reviewed_at, 'EIC reviewed formatting')
    elif role in ('author', 'editor'):
        if role == 'author':
            add('created', 'Submission', mid, manuscript.created_at, 'Manuscript created', recorded=True)
            # These notifications are created in the submission transaction.
            # Initial submission may notify several EICs, so display it once.
            notices = db.scalars(select(Notification).where(
                Notification.manuscript_id == mid,
                Notification.notification_type.in_(['manuscript_submitted', 'initial_resubmission'])
            ).order_by(Notification.created_at, Notification.notification_id)).all()
            submissions = [notice for notice in notices if notice.notification_type == 'manuscript_submitted']
            if submissions:
                first_submission = next((notice for notice in submissions if notice.created_at is not None), submissions[0])
                add('submitted', 'Submission', mid, first_submission.created_at, 'Manuscript submitted', recorded=True)
            for notice in notices:
                if notice.notification_type == 'initial_resubmission':
                    add('initial-resubmission', 'Initial Screening', notice.notification_id,
                        notice.created_at, 'Manuscript resubmitted for initial screening', recorded=True)
            for scan in db.scalars(select(EICInitialScan).where(EICInitialScan.manuscript_id == mid)):
                add('screening', 'Initial Screening', scan.scan_id, scan.created_at, 'Initial screening recorded', recorded=True)
            for decision in db.scalars(select(EICDecision).where(EICDecision.manuscript_id == mid)):
                description = 'Revision requested' if decision.decision == 'revision_required' else 'Editorial decision recorded'
                add('decision', 'EIC Decision', decision.decision_id, decision.decided_at, description, decision.review_round, recorded=True)
            for agreement in db.scalars(select(AuthorAgreement).where(AuthorAgreement.manuscript_id == mid, AuthorAgreement.author_id == uid)):
                add('agreement', 'Author Agreement', agreement.agreement_id, agreement.created_at, 'Author agreement requested', recorded=True)
                if agreement.status in ('accepted', 'declined'):
                    add('agreement-response', 'Author Agreement', agreement.agreement_id, agreement.responded_at, f'Author agreement {agreement.status}', recorded=True)
            for sub in db.scalars(select(FinalEditingSubmission).where(FinalEditingSubmission.manuscript_id == mid)):
                add('final-submission', 'Final Editing', sub.submission_id, sub.created_at, 'Final editing submitted', recorded=True)
            for sub in db.scalars(select(FormattingSubmission).where(FormattingSubmission.manuscript_id == mid)):
                add('format-submission', 'Formatting', sub.submission_id, sub.created_at, 'Formatting submitted', recorded=True)
            pub = db.get(PrototypePublication, mid)
            if pub: add('publication', 'Publication', mid, pub.published_at, 'Local publication recorded', recorded=True)
        # A round-file row is created in the same transaction as formal peer
        # revision resubmission. A file upload or initial binding alone is not
        # evidence that the author submitted a revision.
        for record in db.scalars(select(ReviewRoundFile).where(
                ReviewRoundFile.manuscript_id == mid,
                ReviewRoundFile.source_kind == 'author_revision')):
            add('author-revision', 'Submission', record.round_file_id, record.created_at,
                'Revised manuscript submitted', record.review_round, recorded=True)
        for model, stage, label in ((InitialEditorInvitation, 'Initial Editing', 'Initial editor'), (FinalEditorInvitation, 'Final Editing', 'Final editor')):
            query = select(model).where(model.manuscript_id == mid)
            if role == 'editor': query = query.where(model.editor_id == uid)
            for inv in db.scalars(query):
                add('editor-invitation-' + stage, stage, inv.invitation_id, inv.invited_at, f'{label} invited', recorded=True)
                if inv.status in ('accepted', 'declined'):
                    add('editor-response-' + stage, stage, inv.invitation_id, inv.responded_at, f'{label} invitation {inv.status}', recorded=True)
        query = select(InitialEditingSubmission).where(InitialEditingSubmission.manuscript_id == mid)
        if role == 'editor': query = query.where(InitialEditingSubmission.editor_id == uid)
        for sub in db.scalars(query):
            add('initial-submission', 'Initial Editing', sub.submission_id, sub.created_at, 'Initial editing submitted', recorded=True)
            # Timestamps establish that a review occurred; the latest mutable
            # status cannot reliably reconstruct its historical decision.
            add('initial-author-review', 'Initial Editing', sub.submission_id, sub.reviewed_at, 'Author reviewed initial editing')
            add('initial-editor-review', 'Initial Editing', sub.submission_id, sub.editor_reviewed_at, 'Editor reviewed initial editing')
            add('initial-eic-review', 'Initial Editing', sub.submission_id, sub.eic_reviewed_at, 'EIC reviewed initial editing')
        if role == 'editor':
            for sub in db.scalars(select(FinalEditingSubmission).where(FinalEditingSubmission.manuscript_id == mid, FinalEditingSubmission.editor_id == uid)):
                add('final-submission', 'Final Editing', sub.submission_id, sub.created_at, 'Final editing submitted', recorded=True)
            for inv in db.scalars(select(FormatterInvitation).where(
                    FormatterInvitation.manuscript_id == mid, FormatterInvitation.formatter_id == uid,
                    FormatterInvitation.status == 'accepted')):
                add('format-invitation', 'Formatting', inv.invitation_id, inv.invited_at, 'Formatting invitation received', recorded=True)
                add('format-accepted', 'Formatting', inv.invitation_id, inv.responded_at, 'Formatting invitation accepted', recorded=True)
                for sub in db.scalars(select(FormattingSubmission).where(FormattingSubmission.invitation_id == inv.invitation_id)):
                    add('format-submission', 'Formatting', sub.submission_id, sub.created_at, 'Formatting submitted', recorded=True)
                    add('format-author-review', 'Formatting', sub.submission_id, sub.author_reviewed_at, 'Author reviewed formatting')
                    add('format-eic-review', 'Formatting', sub.submission_id, sub.eic_reviewed_at, 'EIC reviewed formatting')
    events.sort(key=_event_order, reverse=True)
    return events

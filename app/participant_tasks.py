"""Conservative, read-only task hints for an already-authorized progress view.

This projection does not authorize actions. Missing or ambiguous evidence is
reported as unavailable; invitation history never expands progress access.
"""
from sqlalchemy import inspect, select
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException

from app.models import (
    AuthorAgreement, EICDecision, FinalEditorInvitation, FinalEditingSubmission,
    FinalEditingSubmissionInvitation, FormatterInvitation, FormattingSubmission,
    InitialEditorInvitation, InitialEditingSubmission, PreReviewConfirmation, Review, ReviewAssignment,
    ReviewerInvitation, ReviewerInvitationInvalidation, ReviewRoundFile,
)
from app.review_progress import review_progress


def _task(state, message, stage):
    return {"task_state": state, "task_message": message, "relevant_stage": stage,
            "action_label": None, "permitted_action_target": None}


def _linked_task(message, stage, label, target, manuscript_id):
    return {**_task('action_required', message, stage), 'action_label': label,
            'permitted_action_target': f'#{target}-{manuscript_id}'}


def _pre_review_confirmation_available(db, manuscript):
    """Match the existing confirmation form and endpoint, failing closed."""
    submission = db.scalar(select(InitialEditingSubmission).where(
        InitialEditingSubmission.manuscript_id == manuscript.manuscript_id
    ).order_by(InitialEditingSubmission.submission_id.desc()).limit(1))
    if not submission or submission.status != 'eic_approved':
        return False
    if db.scalar(select(PreReviewConfirmation.confirmation_id).where(
            PreReviewConfirmation.submission_id == submission.submission_id).limit(1)) is not None:
        return False
    from app.routers import eic
    from app.routers.manuscripts import MAX_MANUSCRIPT_FILE_SIZE, validate_manuscript_file
    root = eic.guard_demo_path(eic.BASE_DIR / 'uploads' / 'initial_editing' / str(manuscript.manuscript_id)).resolve()
    path = eic.guard_demo_path(eic.BASE_DIR / submission.file_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return False
    with path.open('rb') as document:
        validate_manuscript_file(path.name, document.read(MAX_MANUSCRIPT_FILE_SIZE + 1), historical=True)
    return True


def _reviewer_invitation_available(db, manuscript):
    """Check the ordinary invitation prerequisites without creating a round file."""
    from app.blind_policy_store import read_policy, PolicyError
    from app.review_files import validate_round_file
    import sqlite3
    try:
        if type(manuscript.review_round) is not int or manuscript.review_round < 1:
            return False
        connection = db.connection()
        if connection.dialect.name != 'sqlite':
            return False
        policy = read_policy(connection.connection.driver_connection, manuscript.manuscript_id)
        # Protected-mode artifacts have separate prerequisites; do not predict them here.
        if not policy or policy['mode'] != 'single_blind':
            return False
        record = db.scalar(select(ReviewRoundFile).where(
            ReviewRoundFile.manuscript_id == manuscript.manuscript_id,
            ReviewRoundFile.review_round == manuscript.review_round))
        if record is None and manuscript.review_round == 1:
            confirmations = db.scalars(select(PreReviewConfirmation).join(
                InitialEditingSubmission, PreReviewConfirmation.submission_id == InitialEditingSubmission.submission_id
            ).where(PreReviewConfirmation.manuscript_id == manuscript.manuscript_id,
                    PreReviewConfirmation.author_id == manuscript.author_id,
                    PreReviewConfirmation.decision == 'confirm',
                    InitialEditingSubmission.manuscript_id == manuscript.manuscript_id,
                    InitialEditingSubmission.status == 'eic_approved')).all()
            if len(confirmations) != 1:
                return False
            confirmation = confirmations[0]
            record = ReviewRoundFile(manuscript_id=manuscript.manuscript_id, review_round=1,
                source_kind='initial_editing', confirmation_id=confirmation.confirmation_id,
                file_path=confirmation.file_path)
        if record is None:
            return False
        validate_round_file(record, manuscript, db)
        return True
    except (PolicyError, sqlite3.Error, SQLAlchemyError, HTTPException, OSError, TypeError, ValueError):
        return False


def _review_policy_selection_available(db, manuscript):
    """Policy selection is possible only before any assignment exists."""
    from app.blind_policy_store import read_policy, PolicyError
    import sqlite3
    try:
        connection = db.connection()
        if connection.dialect.name != 'sqlite':
            return False
        if db.scalar(select(ReviewAssignment.assignment_id).where(
                ReviewAssignment.manuscript_id == manuscript.manuscript_id).limit(1)) is not None:
            return False
        return read_policy(connection.connection.driver_connection, manuscript.manuscript_id) is None
    except (PolicyError, sqlite3.Error, SQLAlchemyError):
        return False


def reviewer_assignment_task(db, assignment, manuscript):
    """Neutral invitation task; caller must authenticate and check ownership.

    This intentionally conveys no manuscript metadata or document capability.
    An absent invalidation ledger makes current eligibility unknowable.
    """
    stage = 'Peer Review'
    if manuscript is None or not isinstance(manuscript.review_round, int):
        return _task('unavailable', 'Assignment information is unavailable.', stage)
    if not isinstance(assignment.review_round, int) or assignment.review_round > manuscript.review_round:
        return _task('unavailable', 'Assignment information is unavailable.', stage)
    if assignment.review_round < manuscript.review_round:
        return _task('stale', 'This assignment is no longer in the current review round.', stage)
    if manuscript.status not in ('ready_for_peer_review', 'revised'):
        return _task('stale', 'This assignment is no longer open for review.', stage)
    if not inspect(db.connection()).has_table('reviewer_invitation_invalidations'):
        return _task('unavailable', 'Assignment eligibility is unavailable.', stage)
    invalidation = db.scalar(select(ReviewerInvitationInvalidation.invalidation_id).where(
        ReviewerInvitationInvalidation.assignment_id == assignment.assignment_id))
    if invalidation:
        return _task('stale', 'This assignment is no longer active.', stage)
    invitation = db.get(ReviewerInvitation, assignment.assignment_id)
    if invitation and invitation.status == 'declined':
        return _task('declined', 'You declined this review invitation.', stage)
    if assignment.status in ('cancelled', 'revoked', 'superseded'):
        return _task('stale', 'This assignment is no longer active.', stage)
    if assignment.status not in ('assigned', 'completed'):
        return _task('unavailable', 'Assignment information is unavailable.', stage)
    if invitation and invitation.status == 'pending':
        return _task('pending', 'Your review invitation is awaiting a response.', stage)
    if invitation and invitation.status != 'accepted':
        return _task('unavailable', 'Assignment information is unavailable.', stage)
    review = db.scalar(select(Review.review_id).where(Review.assignment_id == assignment.assignment_id))
    if assignment.status == 'completed' and review is not None:
        progress = review_progress(db, manuscript, assignment.review_round)
        if progress.get('incomplete_assignments', 0) > 0:
            return _task('waiting', 'Your review was submitted. Waiting for other reviews.', stage)
        return _task('waiting', 'Your review was submitted. Waiting for editorial action.', stage)
    if assignment.status == 'completed' or review is not None:
        return _task('unavailable', 'Assignment information is unavailable.', stage)
    return _task('unavailable', 'Your assignment is active; current review action eligibility is unconfirmed.', stage)


def participant_task(db, manuscript, user, stage):
    """Return only the current user's neutral task, after caller authorization."""
    status, role, mid, uid = manuscript.status, user.role, manuscript.manuscript_id, user.user_id
    unavailable = lambda: _task('unavailable', 'Current task eligibility is unavailable.', stage)
    if not stage:
        return unavailable()
    if role == 'author':
        if manuscript.author_id != uid:
            return unavailable()
        if status == 'pre_review_confirmation':
            try:
                if _pre_review_confirmation_available(db, manuscript):
                    return _linked_task('Confirm the pre-review version.', stage,
                                        'View initial editing', 'initial-editing-action', mid)
            except (SQLAlchemyError, HTTPException, OSError, TypeError, ValueError):
                pass
            return unavailable()
        if status == 'initial_editing':
            try:
                submission = db.scalar(select(InitialEditingSubmission).where(
                    InitialEditingSubmission.manuscript_id == mid
                ).order_by(InitialEditingSubmission.submission_id.desc()).limit(1))
                if submission and submission.status == 'pending_author':
                    return {**_task('action_required', 'Review the submitted initial edit.', stage),
                            'action_label': 'View initial editing',
                            'permitted_action_target': f'#initial-editing-action-{mid}'}
                if submission and submission.status in ('author_approved', 'author_revision_requested',
                                                         'editor_revision_requested', 'eic_revision_requested'):
                    from app.editor_invitation_revocation import effective_status
                    invitation = db.scalar(select(InitialEditorInvitation).where(
                        InitialEditorInvitation.manuscript_id == mid,
                        InitialEditorInvitation.editor_id == submission.editor_id,
                        InitialEditorInvitation.status == 'accepted').order_by(
                        InitialEditorInvitation.invitation_id.desc()).limit(1))
                    if invitation and effective_status(db, 'initial', invitation) == 'accepted':
                        return _task('waiting', 'Waiting for the initial editor to continue the edit.', stage)
                if submission and submission.status == 'editor_approved':
                    return _task('waiting', 'Waiting for the EIC to review the initial edit.', stage)
            except SQLAlchemyError:
                return unavailable()
            return unavailable()
        if status == 'final_editing':
            try:
                from app.editor_invitation_revocation import effective_status
                from app.routers.final_workflow import accepted_current_agreement
                if not accepted_current_agreement(db, manuscript):
                    return unavailable()
                row = db.execute(select(FinalEditingSubmission, FinalEditorInvitation).join(
                    FinalEditingSubmissionInvitation,
                    FinalEditingSubmissionInvitation.submission_id == FinalEditingSubmission.submission_id
                ).join(FinalEditorInvitation,
                    FinalEditorInvitation.invitation_id == FinalEditingSubmissionInvitation.invitation_id
                ).where(FinalEditingSubmission.manuscript_id == mid)
                  .order_by(FinalEditingSubmission.submission_id.desc()).limit(1)).first()
                if row:
                    submission, invitation = row
                    if (submission.status == 'pending_author' and invitation.manuscript_id == mid
                            and invitation.editor_id == submission.editor_id
                            and effective_status(db, 'final', invitation) == 'accepted'):
                        return _linked_task('Review the submitted final edit.', stage,
                                            'View final editing', 'final-editing-action', mid)
            except SQLAlchemyError:
                return unavailable()
            return unavailable()
        if status == 'awaiting_author_agreement':
            try:
                agreement = db.scalar(select(AuthorAgreement).join(
                    EICDecision, AuthorAgreement.decision_id == EICDecision.decision_id).where(
                    AuthorAgreement.manuscript_id == mid,
                    AuthorAgreement.author_id == uid, EICDecision.manuscript_id == mid,
                    EICDecision.review_round == manuscript.review_round,
                    EICDecision.decision == 'accept').order_by(AuthorAgreement.agreement_id.desc()).limit(1))
                if agreement and agreement.status == 'pending' and agreement.responded_at is None:
                    return _linked_task('Review and respond to your author agreement.', stage,
                                        'View author agreement', 'author-agreement-action', mid)
            except SQLAlchemyError:
                return unavailable()
            return unavailable()
        if status == 'formatting':
            try:
                from app.routers import formatting
                from app.formatting_artifact_read import read_formatting_artifact
                submission = db.scalar(select(FormattingSubmission).where(
                    FormattingSubmission.manuscript_id == mid
                ).order_by(FormattingSubmission.submission_id.desc()).limit(1))
                if submission is None:
                    return unavailable()
                invitation = db.get(FormatterInvitation, submission.invitation_id)
                final = formatting.latest_final(db, mid)
                if not (invitation and invitation.manuscript_id == mid and invitation.status == 'accepted'
                        and formatting.ready_final(final) and final.submission_id == invitation.final_submission_id):
                    return unavailable()
                if submission.status in ('pending_author', 'pending_eic'):
                    read_formatting_artifact(submission, mid, formatting.BASE_DIR,
                        formatting.ALLOWED_MANUSCRIPT_EXTENSIONS, formatting.MAX_MANUSCRIPT_FILE_SIZE, db=db)
                    if submission.status == 'pending_author':
                        return _linked_task('Review the formatted proof.', stage,
                                            'View formatting review', 'author-formatting-action', mid)
                    return _task('waiting', 'Waiting for the EIC to review the formatted proof.', stage)
                if submission.status in ('author_revision_requested', 'eic_revision_requested'):
                    return _task('waiting', 'Waiting for the formatter to submit corrections.', stage)
                if submission.status == 'approved':
                    return _task('waiting', 'Waiting for the EIC to complete the publication step.', stage)
            except (SQLAlchemyError, HTTPException, OSError):
                return unavailable()
            return unavailable()
        if status in ('initial_revision_required', 'revision_required'):
            return _linked_task('Prepare and submit the requested revision.', stage,
                                'View manuscript actions', 'author-manuscript-actions', mid)
        if status == 'draft':
            return _linked_task('Complete the draft and submit it when ready.', stage,
                                'View manuscript actions', 'author-manuscript-actions', mid)
        if status in ('published', 'initial_rejected', 'rejected'):
            return _task('no_action', 'No further action is currently required.', stage)
        if status in ('submitted', 'initial_scan_passed', 'initial_editor_invited', 'ready_for_peer_review', 'revised'):
            return _task('waiting', 'Waiting for the editorial workflow to advance.', stage)
        return unavailable()
    try:
        if role == 'reviewer':
            assignments = db.scalars(select(ReviewAssignment).where(
                ReviewAssignment.manuscript_id == mid, ReviewAssignment.reviewer_id == uid,
                ReviewAssignment.review_round == manuscript.review_round,
                ReviewAssignment.status.in_(['assigned', 'completed']))).all()
            if len(assignments) != 1:
                return unavailable()
            assignment = assignments[0]
            invitation = db.get(ReviewerInvitation, assignment.assignment_id)
            if invitation and invitation.status == 'pending':
                return _task('pending', 'Your review invitation is awaiting a response.', stage)
            if invitation and invitation.status == 'declined':
                return _task('declined', 'You declined this review invitation.', stage)
            if invitation and invitation.status != 'accepted':
                return unavailable()
            review = db.scalar(select(Review.review_id).where(Review.assignment_id == assignment.assignment_id))
            if assignment.status == 'completed' and review is not None:
                return _task('waiting', 'Your review was submitted. Waiting for editorial action.', stage)
            if assignment.status == 'completed' or review is not None:
                return unavailable()
            return _task('unavailable', 'Your assignment is active; current review action eligibility is unconfirmed.', stage)
        if role == 'eic':
            if status == 'pre_review_confirmation':
                try:
                    if _pre_review_confirmation_available(db, manuscript):
                        return _task('waiting', 'Waiting for the author to confirm the pre-review version.', stage)
                except (SQLAlchemyError, HTTPException, OSError, TypeError, ValueError):
                    pass
                return unavailable()
            if status == 'initial_editing':
                pending = db.scalar(select(InitialEditingSubmission.submission_id).where(
                    InitialEditingSubmission.manuscript_id == mid,
                    InitialEditingSubmission.status == 'editor_approved').limit(1))
                if pending is not None:
                    return _linked_task('Review the editor-approved initial edit.', stage,
                                        'View initial editing review', 'eic-initial-review', mid)
                return unavailable()
            if status == 'initial_scan_passed':
                active = db.scalar(select(InitialEditorInvitation.invitation_id).where(
                    InitialEditorInvitation.manuscript_id == mid,
                    InitialEditorInvitation.status.in_(['pending', 'accepted'])).limit(1))
                if active is not None:
                    return unavailable()
                return _linked_task('Invite an initial editor.', stage,
                                    'View initial editor assignment', 'eic-initial-assignment', mid)
            if status == 'initial_editor_invited':
                pending = db.scalar(select(InitialEditorInvitation).where(
                    InitialEditorInvitation.manuscript_id == mid,
                    InitialEditorInvitation.status == 'pending').limit(1))
                from app.editor_invitation_revocation import effective_status
                if pending is not None and effective_status(db, 'initial', pending) == 'pending':
                    return _task('waiting', 'Waiting for the invited initial editor to respond.', stage)
                return unavailable()
            if status == 'revision_required':
                decision = db.scalar(select(EICDecision.decision_id).where(
                    EICDecision.manuscript_id == mid, EICDecision.review_round == manuscript.review_round,
                    EICDecision.decision == 'revision_required').limit(1))
                if decision is not None:
                    return _task('waiting', 'Waiting for the author to submit the requested revision.', stage)
                return unavailable()
            if status == 'awaiting_author_agreement':
                agreement = db.scalar(select(AuthorAgreement).join(
                    EICDecision, AuthorAgreement.decision_id == EICDecision.decision_id).where(
                    AuthorAgreement.manuscript_id == mid, AuthorAgreement.author_id == manuscript.author_id,
                    EICDecision.manuscript_id == mid, EICDecision.review_round == manuscript.review_round,
                    EICDecision.decision == 'accept').order_by(AuthorAgreement.agreement_id.desc()).limit(1))
                if agreement and agreement.status == 'pending' and agreement.responded_at is None:
                    return _task('waiting', 'Waiting for the author to respond to the agreement.', stage)
                return unavailable()
            if status in ('ready_for_peer_review', 'revised'):
                progress = review_progress(db, manuscript)
                if (type(manuscript.review_round) is int and manuscript.review_round > 0
                        and progress.get('active_assignments') == 0 and progress.get('can_decide') is False
                        and _review_policy_selection_available(db, manuscript)):
                    return _linked_task('Select a review policy before inviting reviewers.', stage,
                                        'View review policy', 'eic-reviewer-management', mid)
                if (progress.get('active_assignments') == 0 and progress.get('can_decide') is False
                        and db.scalar(select(EICDecision.decision_id).where(
                            EICDecision.manuscript_id == mid,
                            EICDecision.review_round == manuscript.review_round)) is None
                        and _reviewer_invitation_available(db, manuscript)):
                    return _linked_task('Invite a reviewer for the current round.', stage,
                                        'View reviewer invitations', 'eic-reviewer-management', mid)
                if progress.get('can_decide') is True:
                    if db.scalar(select(EICDecision.decision_id).where(
                        EICDecision.manuscript_id == mid,
                        EICDecision.review_round == manuscript.review_round)) is not None:
                        return _task('no_action', 'A decision for this round is already recorded.', stage)
                    return _linked_task('Review the current editorial decision controls.', stage,
                                        'View editorial decision', 'eic-decision', mid)
                if progress.get('can_decide') is False:
                    return _task('waiting', 'Waiting for the current review requirements to be met.', stage)
                return unavailable()
            if status == 'submitted':
                return _linked_task('Review the initial screening controls.', stage,
                                    'View initial screening', 'eic-initial-screening', mid)
            if status in ('published', 'initial_rejected', 'rejected'):
                return _task('no_action', 'No further action is currently required.', stage)
            return unavailable()
        if role in ('editor', 'formatter'):
            model, actor = ((FormatterInvitation, FormatterInvitation.formatter_id) if status in ('formatting', 'published') else
                            (FinalEditorInvitation, FinalEditorInvitation.editor_id) if status == 'final_editing' else
                            (InitialEditorInvitation, InitialEditorInvitation.editor_id))
            invitations = db.scalars(select(model).where(model.manuscript_id == mid, actor == uid)
                                     .order_by(model.invitation_id.desc())).all()
            if not invitations:
                return unavailable()
            invitation = invitations[0]
            if model in (InitialEditorInvitation, FinalEditorInvitation):
                from app.editor_invitation_revocation import effective_status
                if effective_status(db,'initial' if model is InitialEditorInvitation else 'final',invitation)=='revoked':
                    return _task('stale', 'This editor invitation has been revoked.', stage)
            if invitation.status == 'pending':
                return _task('pending', 'Your invitation is awaiting a response.', stage)
            if invitation.status == 'declined':
                return _task('declined', 'You declined this invitation.', stage)
            if invitation.status == 'accepted':
                if model is InitialEditorInvitation and status == 'initial_editing':
                    latest = db.scalar(select(InitialEditingSubmission).where(
                        InitialEditingSubmission.manuscript_id == mid).order_by(InitialEditingSubmission.submission_id.desc()).limit(1))
                    if latest is None:
                        return _linked_task('Prepare and submit the initial edit.', stage,
                                            'View initial editing', 'initial-editing-action', mid)
                    if latest.editor_id != uid:
                        return unavailable()
                    if latest.status == 'pending_author':
                        return _task('waiting', 'Waiting for the author to review the initial edit.', stage)
                    if latest.status == 'author_approved':
                        return _linked_task('Review the author-approved initial edit.', stage,
                                            'View initial editing', 'initial-editing-action', mid)
                    if latest.status == 'editor_approved':
                        return _task('waiting', 'Waiting for the EIC to review the initial edit.', stage)
                    if latest.status in ('author_revision_requested', 'editor_revision_requested', 'eic_revision_requested'):
                        pending = db.scalar(select(InitialEditingSubmission.submission_id).where(
                            InitialEditingSubmission.manuscript_id == mid,
                            InitialEditingSubmission.status == 'pending_author').limit(1))
                        if pending is None:
                            return _linked_task('Revise and submit the initial edit.', stage,
                                                'View initial editing', 'initial-editing-action', mid)
                    return unavailable()
                if model is FinalEditorInvitation and status == 'final_editing':
                    from app.routers.final_workflow import accepted_current_agreement
                    if not accepted_current_agreement(db, manuscript):
                        return unavailable()
                    latest = db.scalar(select(FinalEditingSubmission).join(FinalEditingSubmissionInvitation,
                        FinalEditingSubmissionInvitation.submission_id == FinalEditingSubmission.submission_id)
                        .where(FinalEditingSubmission.manuscript_id == mid)
                        .order_by(FinalEditingSubmission.submission_id.desc()).limit(1))
                    if latest is None:
                        if db.scalar(select(FinalEditingSubmission.submission_id).where(
                            FinalEditingSubmission.manuscript_id == mid,
                            FinalEditingSubmission.status.in_(['pending_author', 'author_approved'])).limit(1)) is not None:
                            return unavailable()
                        return _linked_task('Prepare and submit the final edit.', stage,
                                            'View final editing', 'final-editing-action', mid)
                    if latest.editor_id != uid:
                        return unavailable()
                    if latest.status in ('pending_eic', 'pending_author'):
                        return _task('waiting', 'Waiting for the final edit to be reviewed.', stage)
                    if latest.status == 'author_approved':
                        return _task('no_action', 'The final edit was approved by the author.', stage)
                    if latest.status in ('eic_revision_requested', 'author_revision_requested'):
                        pending = db.scalar(select(FinalEditingSubmission.submission_id).where(
                            FinalEditingSubmission.manuscript_id == mid,
                            FinalEditingSubmission.status.in_(['pending_author', 'author_approved'])).limit(1))
                        if pending is None:
                            return _linked_task('Revise and submit the final edit.', stage,
                                                'View final editing', 'final-editing-action', mid)
                    return unavailable()
                if model is FormatterInvitation and status == 'formatting':
                    from app.routers.formatting import latest_final, ready_final
                    final = latest_final(db, mid)
                    if not final or not ready_final(final) or final.submission_id != invitation.final_submission_id:
                        return unavailable()
                    latest = db.scalar(select(FormattingSubmission).where(FormattingSubmission.manuscript_id == mid)
                                       .order_by(FormattingSubmission.submission_id.desc()).limit(1))
                    if latest is None:
                        return _linked_task('Prepare and submit the formatted proof.', stage,
                                            'View formatting actions', 'formatting-action', mid)
                    if latest.invitation_id != invitation.invitation_id:
                        return unavailable()
                    if latest.status in ('pending_author', 'pending_eic'):
                        return _task('waiting', 'Waiting for the formatted proof to be reviewed.', stage)
                    if latest.status == 'approved':
                        return _task('no_action', 'The formatted proof has been approved.', stage)
                    if latest.status in ('author_revision_requested', 'eic_revision_requested'):
                        active = db.scalar(select(FormattingSubmission.submission_id).where(
                            FormattingSubmission.manuscript_id == mid,
                            FormattingSubmission.status.in_(['pending_author', 'pending_eic', 'approved'])).limit(1))
                        if active is None:
                            return _linked_task('Revise and submit the formatted proof.', stage,
                                                'View formatting actions', 'formatting-action', mid)
                    return unavailable()
                return unavailable()
            return unavailable()
    except SQLAlchemyError:
        return unavailable()
    return unavailable()

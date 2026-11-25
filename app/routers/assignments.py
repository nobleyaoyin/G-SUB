from app.config import DATA_ROOT
from fastapi.responses import JSONResponse
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import inspect, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
import logging
import sqlite3
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Literal
from sqlalchemy.orm import Session, SessionTransactionOrigin
from app.database import get_db
from app.models import (
    User,
    Manuscript,
    ReviewAssignment,
    Review,
    Notification,
    PreReviewConfirmation,
    InitialEditingSubmission,
    InitialEditorInvitation,
    ReviewRoundFile,
    ReviewAssignmentFile,
    ReviewerInvitation,
    ReviewerInvitationInvalidation,
)
from app.schemas import ReviewAssignmentCreate, ReviewAssignmentResponse
from app.routers.users import require_role
from app.routers.manuscripts import manuscript_has_pdf, can_access_manuscript
from app.review_files import get_or_create_round_one, resolve_assignment_file, validate_round_file
from app.reviewer_invitations import invitation_status, not_declined
from app.participant_tasks import reviewer_assignment_task
from app.review_progress import review_progress
from app.email.enqueue_mode import EnqueueMode, OutboxSchemaUnavailable, check_outbox_schema, reviewer_email_enqueue_mode
from app.email.outbox import enqueue_reviewer_invitation
from app.email.service import notify_workflow_email
from app.reviewer_profiles import load_profiles, profiles, schema_available
from app.reviewer_metadata_gate import MetadataMode, MetadataAccessDenied, MetadataSchemaUnavailable, ReviewerSafeAssignmentDTO, ReviewerAssignmentDoubleDTO, reviewer_metadata_mode, reviewer_assignment_dtos
from app.reviewer_metadata_gate import _security_context
from app.blind_policy_store import read_policy, select_mode, change_mode, lock_mode, PolicyError
from app.reviewer_demo_download import DemoArtifactContext, AuthenticatedEditorialAuthority, reviewer_demo_artifact_context
from app import reviewer_artifact_binding, reviewer_artifact_service
from app.reviewer_artifact_storage import StorageError
from app.split_review import split_review_status
from app.reviewer_document_release import release_reviewer_document, reviewer_document_available
from app.editor_invitation_revocation import is_revoked


router = APIRouter(
    prefix="/assignments",
    tags=["Review Assignments"]
)
BASE_DIR = DATA_ROOT
logger = logging.getLogger(__name__)


def _has_current_initial_editor_invitation(db, manuscript_id, editor_id):
    """Allow an editor only while at least one accepted invitation is not revoked."""
    invitations = db.scalars(select(InitialEditorInvitation.invitation_id).where(
        InitialEditorInvitation.manuscript_id == manuscript_id,
        InitialEditorInvitation.editor_id == editor_id,
        InitialEditorInvitation.status == "accepted",
    ).order_by(InitialEditorInvitation.invitation_id.desc())).all()
    return any(not is_revoked(db, 'initial', invitation_id) for invitation_id in invitations)


class DemoPolicySelection(BaseModel):
    mode: Literal['single_blind', 'double_blind']
    expected_revision: int | None = None


def _demo_connection(db, mode, *, write=False):
    if mode is not MetadataMode.EXPERIMENTAL:
        raise HTTPException(404, 'Demo workflow unavailable')
    connection = db.connection()
    if connection.dialect.name != 'sqlite':
        raise HTTPException(503, 'Demo workflow unavailable')
    raw = connection.connection.driver_connection
    if raw.in_transaction:
        raise HTTPException(503, 'Demo transaction unavailable')
    connection.exec_driver_sql('BEGIN IMMEDIATE' if write else 'BEGIN')
    return raw


def _demo_eic(raw, user_id, manuscript_id):
    if not raw.execute("SELECT 1 FROM users WHERE user_id=? AND role='eic'", (user_id,)).fetchone():
        raise HTTPException(403, 'EIC access required')
    if not raw.execute("SELECT 1 FROM manuscripts WHERE manuscript_id=? AND status!='draft'", (manuscript_id,)).fetchone():
        raise HTTPException(404, 'Manuscript unavailable')


@router.get('/demo-policy/{manuscript_id}')
def demo_policy_get(manuscript_id: int, current_user: User = Depends(require_role('eic')),
                    db: Session = Depends(get_db), mode: MetadataMode = Depends(reviewer_metadata_mode)):
    try:
        raw = _demo_connection(db, mode)
        _demo_eic(raw, current_user.user_id, manuscript_id)
        value = read_policy(raw, manuscript_id)
        return {'mode': value['mode'] if value else None, 'revision': value['revision'] if value else None,
                'locked': bool(value and value['locked_at'])}
    except (PolicyError, sqlite3.DatabaseError, SQLAlchemyError):
        raise HTTPException(503, 'Demo policy unavailable') from None


@router.put('/demo-policy/{manuscript_id}')
def demo_policy_put(manuscript_id: int, data: DemoPolicySelection, current_user: User = Depends(require_role('eic')),
                    db: Session = Depends(get_db), mode: MetadataMode = Depends(reviewer_metadata_mode)):
    try:
        raw = _demo_connection(db, mode, write=True)
        _demo_eic(raw, current_user.user_id, manuscript_id)
        old = read_policy(raw, manuscript_id)
        if old is None and data.expected_revision is None:
            result = select_mode(raw, manuscript_id, data.mode, current_user.user_id)
        elif old is not None and data.expected_revision is not None:
            result = change_mode(raw, manuscript_id, data.mode, current_user.user_id, data.expected_revision)
        else:
            raise PolicyError('Policy is stale')
        db.commit()
        return {'mode': result['mode'], 'revision': result['revision'], 'locked': bool(result['locked_at'])}
    except PolicyError:
        db.rollback()
        raise HTTPException(409, 'Policy is locked, stale, or cannot be changed') from None
    except (sqlite3.DatabaseError, SQLAlchemyError):
        db.rollback()
        raise HTTPException(503, 'Policy update outcome unavailable; refresh before retrying') from None


@router.post('/demo-invitations', status_code=201)
def demo_invitation(data: ReviewAssignmentCreate, current_user: User = Depends(require_role('eic')),
                    db: Session = Depends(get_db), mode: MetadataMode = Depends(reviewer_metadata_mode),
                    artifact_context: DemoArtifactContext | None = Depends(reviewer_demo_artifact_context)):
    return _demo_invitation(data, current_user, db, mode, artifact_context)


def _demo_invitation(data, current_user, db, mode, artifact_context, *, require_split=False):
    try:
        raw = _demo_connection(db, mode, write=True)
        _demo_eic(raw, current_user.user_id, data.manuscript_id)
        policy = read_policy(raw, data.manuscript_id)
        if not policy:
            raise HTTPException(409, 'Select a review mode before inviting reviewers')
        manuscript = db.get(Manuscript, data.manuscript_id)
        if manuscript.status not in ('ready_for_peer_review', 'revised') or manuscript.review_round != data.review_round:
            raise HTTPException(409, 'Review round unavailable')
        if require_split and not split_review_status(db, manuscript)['can_invite_additional']:
            raise HTTPException(409, 'No eligible split or an additional reviewer is already active')
        _security_context(raw, data.reviewer_id)
        if db.scalar(select(ReviewAssignment).where(ReviewAssignment.manuscript_id == data.manuscript_id,
                ReviewAssignment.reviewer_id == data.reviewer_id, ReviewAssignment.review_round == data.review_round)):
            raise HTTPException(409, 'Reviewer already assigned')
        if data.review_round == 1:
            source = get_or_create_round_one(db, manuscript)
        else:
            source = db.scalar(select(ReviewRoundFile).where(ReviewRoundFile.manuscript_id == data.manuscript_id,
                ReviewRoundFile.review_round == data.review_round))
            if not source: raise HTTPException(409, 'Review source unavailable')
            validate_round_file(source, manuscript, db)
        if policy['mode'] == 'double_blind':
            if type(artifact_context) is not DemoArtifactContext:
                raise HTTPException(409, 'Double-Blind artifact readiness is unavailable')
            reviewer_artifact_binding.verify_preinvitation(raw, artifact_context.proof, artifact_context.provenance,
                artifact_context.storage, data.manuscript_id, data.review_round, source.round_file_id)
        assignment = ReviewAssignment(manuscript_id=data.manuscript_id, reviewer_id=data.reviewer_id,
            assigned_by=current_user.user_id, review_round=data.review_round, status='assigned')
        db.add(assignment); db.flush()
        db.add(ReviewAssignmentFile(assignment_id=assignment.assignment_id, round_file_id=source.round_file_id))
        db.add(ReviewerInvitation(assignment_id=assignment.assignment_id, status='pending')); db.flush()
        if not policy['locked_at']:
            lock_mode(raw, data.manuscript_id, assignment.assignment_id, current_user.user_id, policy['revision'])
        reviewer = db.get(User, data.reviewer_id)
        db.add(Notification(user_id=data.reviewer_id, manuscript_id=data.manuscript_id,
            notification_type='review_invitation', message='You have a reviewer invitation.', is_read=False))
        db.commit()
    except (MetadataAccessDenied, MetadataSchemaUnavailable, PolicyError, reviewer_artifact_service.ArtifactError, StorageError, ValueError):
        db.rollback()
        raise HTTPException(409, 'Reviewer invitation unavailable') from None
    except HTTPException:
        db.rollback()
        raise
    except (sqlite3.DatabaseError, SQLAlchemyError):
        db.rollback()
        raise HTTPException(503, 'Invitation outcome unavailable; refresh before retrying') from None

    if reviewer is not None:
        notify_workflow_email(
            "reviewer_invitation",
            reviewer.email,
            {"manuscript_id": manuscript.manuscript_id},
        )
    return {'assignment_id': assignment.assignment_id, 'invitation_status': 'pending'}


@router.post('/additional-reviewer', status_code=201)
def invite_additional_reviewer(data: ReviewAssignmentCreate, current_user: User = Depends(require_role('eic')),
        db: Session = Depends(get_db), mode: MetadataMode = Depends(reviewer_metadata_mode),
        context: DemoArtifactContext | None = Depends(reviewer_demo_artifact_context)):
    if mode is MetadataMode.EXPERIMENTAL:
        return _demo_invitation(data, current_user, db, mode, context, require_split=True)
    if mode is not MetadataMode.DISABLED:
        raise HTTPException(503, 'Additional reviewer unavailable')
    return _invitation_operation(data, current_user, db, EnqueueMode.DISABLED, require_split=True)


@router.post('/demo-invitations/{assignment_id}/bind-artifact')
def demo_bind_artifact(assignment_id: int, current_user: User = Depends(require_role('eic')),
                       db: Session = Depends(get_db), mode: MetadataMode = Depends(reviewer_metadata_mode),
                       context: DemoArtifactContext | None = Depends(reviewer_demo_artifact_context)):
    try:
        raw = _demo_connection(db, mode, write=True)
        row = raw.execute('''SELECT a.manuscript_id,a.review_round,f.round_file_id FROM review_assignments a
            JOIN review_assignment_files f ON f.assignment_id=a.assignment_id WHERE a.assignment_id=?''', (assignment_id,)).fetchone()
        if not row or type(context) is not DemoArtifactContext:
            raise HTTPException(409, 'Reviewer artifact unavailable')
        mid, rnd, source_id = row
        _demo_eic(raw, current_user.user_id, mid)
        policy = read_policy(raw, mid)
        if not policy or not policy['locked_at']:
            raise HTTPException(409, 'Reviewer artifact unavailable')
        artifact_id, art_revision, source_revision = reviewer_artifact_binding.verify_preinvitation(
            raw, context.proof, context.provenance, context.storage, mid, rnd, source_id)
        reviewer_artifact_binding.bind(raw, current_user, AuthenticatedEditorialAuthority(current_user),
            context.proof, context.provenance, context.storage, assignment_id, artifact_id,
            expected_policy_revision=policy['revision'], expected_artifact_revision=art_revision,
            expected_source_revision=source_revision)
        db.commit()
        return {'assignment_id': assignment_id, 'artifact_bound': True}
    except HTTPException:
        db.rollback(); raise
    except (MetadataAccessDenied, MetadataSchemaUnavailable, PolicyError, reviewer_artifact_service.ArtifactError, StorageError):
        db.rollback(); raise HTTPException(409, 'Reviewer artifact unavailable') from None
    except (sqlite3.DatabaseError, SQLAlchemyError):
        db.rollback(); raise HTTPException(503, 'Binding outcome unavailable; refresh before retrying') from None


def _sqlite_busy(error):
    original = getattr(error, 'orig', error)
    code = getattr(original, 'sqlite_errorcode', None)
    return code is not None and (code & 0xff) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def _rollback_or_unknown(db):
    try:
        db.rollback()
        return True
    except Exception:
        logger.error('reviewer_invitation_rollback_unknown')
        return False


_UNKNOWN = 'Invitation outcome could not be confirmed; refresh the reviewer assignment list before trying again.'


class _EnqueueFailure(Exception):
    def __init__(self, error):
        self.error = error

def assignment_to_response(
    db: Session,
    assignment: ReviewAssignment,
    manuscript: Manuscript
) -> ReviewAssignmentResponse:
    """Include manuscript information without changing database tables."""
    response = ReviewAssignmentResponse.model_validate(assignment)

    try:
        resolve_assignment_file(db, assignment, manuscript)
        available = True
    except HTTPException:
        available = False

    return response.model_copy(update={
        "invitation_status": invitation_status(db, assignment),
        "manuscript_title": manuscript.title,
        "manuscript_status": manuscript.status,
        "has_pdf": manuscript_has_pdf(manuscript),
        "review_file_available": available,
        "review_file_status": "available" if available else "unavailable",
    })


def assignments_to_responses(
    db: Session,
    assignments: list[ReviewAssignment]
) -> list[ReviewAssignmentResponse]:
    """Load related manuscripts in one query to avoid per-row DB lookups."""
    if not assignments:
        return []

    manuscript_ids = {
        assignment.manuscript_id
        for assignment in assignments
    }

    manuscripts = db.scalars(
        select(Manuscript).where(
            Manuscript.manuscript_id.in_(manuscript_ids)
        )
    ).all()

    by_id = {
        manuscript.manuscript_id: manuscript
        for manuscript in manuscripts
    }

    result = []

    for assignment in assignments:
        manuscript = by_id.get(assignment.manuscript_id)

        if manuscript is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Assignment references a missing manuscript"
            )

        result.append(
            assignment_to_response(db, assignment, manuscript)
        )

    return result


@router.get("/manuscript/{manuscript_id}/reviewer-directory")
def search_reviewer_directory(
    manuscript_id: int,
    current_user: Annotated[User, Depends(require_role("editor", "eic"))],
    response: Response,
    db: Session = Depends(get_db),
    q: str | None = Query(None, max_length=100),
    offset: int = Query(0, ge=0, le=100000),
):
    """Browse or search bounded reviewer contact data for an authorized assignment."""
    manuscript = db.get(Manuscript, manuscript_id)
    if manuscript is None:
        raise HTTPException(status_code=404, detail="Manuscript not found")
    if current_user.role == "editor" and not _has_current_initial_editor_invitation(
        db, manuscript_id, current_user.user_id
    ):
        raise HTTPException(status_code=403, detail="You are not the assigned editor for this manuscript")
    if manuscript.status not in ("ready_for_peer_review", "revised"):
        raise HTTPException(status_code=409, detail="Manuscript is not ready for reviewer assignment")
    if q is None and current_user.role != "eic":
        raise HTTPException(status_code=403, detail="Reviewer browsing is restricted to the EIC")
    search_terms = []
    if q is not None:
        term = q.strip()
        if len(term) < 2:
            raise HTTPException(status_code=422, detail="Enter at least two search characters")
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        search_terms = [User.name.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\")]
        if schema_available(db):
            search_terms.append(User.user_id.in_(select(profiles.c.user_id).where(profiles.c.institution.ilike(pattern, escape="\\"))))
    query = select(User).where(User.role == "reviewer")
    if search_terms:
        query = query.where(or_(*search_terms))
    reviewers = db.scalars(query.order_by(User.name, User.user_id).offset(offset).limit(20)).all()
    ids = [user.user_id for user in reviewers]
    assignments = db.scalars(select(ReviewAssignment).where(
        ReviewAssignment.manuscript_id == manuscript_id,
        ReviewAssignment.review_round == manuscript.review_round,
        ReviewAssignment.reviewer_id.in_(ids),
    ).order_by(ReviewAssignment.assignment_id.desc())).all() if ids else []
    by_reviewer = {}
    for assignment in assignments:
        by_reviewer.setdefault(assignment.reviewer_id, assignment)
    profiles_by_user = load_profiles(db, ids)
    response.headers["Cache-Control"] = "no-store"
    return [{
        "reviewer_id": reviewer.user_id,
        "name": reviewer.name,
        "email": reviewer.email,
        "invitation_status": invitation_status(db, by_reviewer[reviewer.user_id]) if reviewer.user_id in by_reviewer else None,
        "assignment_status": by_reviewer[reviewer.user_id].status if reviewer.user_id in by_reviewer else None,
        "selectable": reviewer.user_id not in by_reviewer,
        "profile": profiles_by_user.get(reviewer.user_id),
    } for reviewer in reviewers]


# Editor: Assign a reviewer to a manuscript
@router.post(
    "/",
    response_model=ReviewAssignmentResponse,
    status_code=status.HTTP_201_CREATED
)
def assign_reviewer(
    assignment_data: ReviewAssignmentCreate,
    current_user: Annotated[
        User,
        Depends(require_role("editor", "eic"))
    ],
    db: Session = Depends(get_db),
    enqueue_mode: EnqueueMode = Depends(reviewer_email_enqueue_mode),
    metadata_mode: MetadataMode = Depends(reviewer_metadata_mode),
):
    if metadata_mode is not MetadataMode.DISABLED:
        raise HTTPException(409, 'Use the guarded demo invitation workflow')
    if not isinstance(enqueue_mode, EnqueueMode):
        raise HTTPException(status_code=503, detail='Reviewer invitation is temporarily unavailable.')
    return _invitation_operation(assignment_data, current_user, db, enqueue_mode)


def _invitation_operation(data, current_user, db, enqueue_mode, *, require_split=False):
    """Own a fresh SQLite write transaction; never take over caller-owned work."""
    transaction = db.get_transaction()
    if (db.in_nested_transaction() or db.new or db.dirty or db.deleted or
            (transaction is not None and transaction.origin is not SessionTransactionOrigin.AUTOBEGIN)):
        raise HTTPException(503, 'Reviewer invitation requires a clean transaction')
    connection = db.connection()
    if connection.dialect.name != 'sqlite' or connection.connection.driver_connection.in_transaction:
        raise HTTPException(503, 'Reviewer invitation requires a fresh transaction')
    raw = connection.connection.driver_connection
    try:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
    except (SQLAlchemyError, sqlite3.DatabaseError) as error:
        if _sqlite_busy(error):
            raise HTTPException(503, 'Reviewer invitation is temporarily unavailable due to database contention. Refresh the reviewer assignment list before retrying.') from None
        raise HTTPException(503, 'Reviewer invitation transaction unavailable') from None

    try:
        if require_split:
            _demo_eic(raw, current_user.user_id, data.manuscript_id)
            manuscript = db.get(Manuscript, data.manuscript_id)
            if manuscript.review_round != data.review_round or not split_review_status(db, manuscript)['can_invite_additional']:
                raise HTTPException(409, 'No eligible split or an additional reviewer is already active')
        new_assignment, manuscript = _assign_reviewer(data, current_user, db, enqueue_mode, raw)
        reviewer = db.get(User, new_assignment.reviewer_id)
    except Exception as error:
        if not _rollback_or_unknown(db):
            raise HTTPException(503, _UNKNOWN) from None
        if isinstance(error, HTTPException):
            raise
        cause = error.error if isinstance(error, _EnqueueFailure) else error
        if _sqlite_busy(cause):
            raise HTTPException(503, 'Reviewer invitation was not saved due to temporary database contention. Refresh the reviewer assignment list before retrying.') from None
        if isinstance(error, _EnqueueFailure):
            raise HTTPException(503, 'Reviewer invitation was not saved because notification queueing failed.') from None
        if isinstance(error, (SQLAlchemyError, sqlite3.DatabaseError)):
            raise HTTPException(503, 'Reviewer invitation was not saved due to a database error.') from None
        raise

    try:
        db.commit()
        db.refresh(new_assignment)
        response = assignment_to_response(db, new_assignment, manuscript)
    except Exception:
        logger.error('reviewer_invitation_commit_or_refresh_unknown')
        _rollback_or_unknown(db)
        raise HTTPException(503, _UNKNOWN) from None
    if reviewer is not None and enqueue_mode is EnqueueMode.DISABLED:
        notify_workflow_email(
            "reviewer_invitation",
            reviewer.email,
            {"manuscript_id": manuscript.manuscript_id},
        )
    return response


def _assign_reviewer(assignment_data, current_user, db, enqueue_mode, raw):
    """Perform invitation writes in the outer operation's immediate transaction."""
    # Step 1: Find the manuscript
    manuscript = db.get(
        Manuscript,
        assignment_data.manuscript_id
    )

    if manuscript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manuscript not found"
        )


    # Step 2: Validate manuscript workflow status.
    if manuscript.status not in ("ready_for_peer_review", "revised"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manuscript is not ready for reviewer assignment",
        )

    # Step 2.1: Verify author confirmation for the first review round.
    if manuscript.review_round == 1:
        confirmation = db.scalar(
            select(PreReviewConfirmation)
            .join(
                InitialEditingSubmission,
                PreReviewConfirmation.submission_id
                == InitialEditingSubmission.submission_id,
            )
            .where(
                PreReviewConfirmation.manuscript_id
                == manuscript.manuscript_id,
                PreReviewConfirmation.author_id
                == manuscript.author_id,
                PreReviewConfirmation.decision == "confirm",
                InitialEditingSubmission.status == "eic_approved",
                InitialEditingSubmission.manuscript_id
                == manuscript.manuscript_id,
            )
            .order_by(
                PreReviewConfirmation.confirmation_id.desc()
            )
        )

        if confirmation is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Author pre-review confirmation is required",
            )

    # Step 2.2: Verify that the current editor is assigned
    # to this manuscript.
    if current_user.role == "editor" and not _has_current_initial_editor_invitation(
        db, manuscript.manuscript_id, current_user.user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the assigned editor for this manuscript",
        )

    # Both the policy event chain and invitation binding require foreign keys.
    # Report a readiness failure before attempting either check or any writes.
    if raw.execute('PRAGMA foreign_keys').fetchone() != (1,):
        raise HTTPException(503, 'Reviewer invitation is not ready.')

    try:
        policy = read_policy(raw, assignment_data.manuscript_id)
    except PolicyError:
        raise HTTPException(503, 'Review policy unavailable') from None
    if not policy:
        raise HTTPException(409, 'An EIC must select a review policy before inviting reviewers')

    # Step 3: Use the manuscript's current review round
    expected_round = manuscript.review_round

    if assignment_data.review_round != expected_round:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This manuscript requires review round {expected_round}"
        )

    # Step 4: Find the reviewer
    reviewer = db.get(
        User,
        assignment_data.reviewer_id
    )

    if reviewer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reviewer not found"
        )

    if reviewer.role != "reviewer":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected user is not a reviewer"
        )

    # Step 5: Prevent duplicate assignments in the same round
    existing_assignment = db.scalar(
        select(ReviewAssignment).where(
            ReviewAssignment.manuscript_id == assignment_data.manuscript_id,
            ReviewAssignment.reviewer_id == assignment_data.reviewer_id,
            ReviewAssignment.review_round == expected_round
        )
    )

    if existing_assignment is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reviewer already assigned in this review round"
        )


    # The preflight is only reached by an explicitly overridden test dependency.
    # It precedes get_or_create_round_one, which can itself write and flush.
    if enqueue_mode is EnqueueMode.ENQUEUE_ONLY:
        try:
            check_outbox_schema(db)
        except (OutboxSchemaUnavailable, SQLAlchemyError, ImportError, OSError, AttributeError) as error:
            logger.error('reviewer_invitation_preflight_unavailable')
            if _sqlite_busy(error):
                raise HTTPException(status_code=503, detail='Reviewer invitation is temporarily unavailable due to database contention. Refresh the reviewer assignment list before retrying.') from None
            raise HTTPException(status_code=503, detail='Reviewer invitation is unavailable because the notification queue is not ready.') from None

    def build_invitation():
        # Bind the assignment to the formally authorized file for this round.
        if expected_round == 1:
            round_file = get_or_create_round_one(db, manuscript)
        else:
            round_file = db.scalar(select(ReviewRoundFile).where(
                ReviewRoundFile.manuscript_id == manuscript.manuscript_id,
                ReviewRoundFile.review_round == expected_round,
            ))
            if round_file is None:
                raise HTTPException(status_code=409, detail="No recorded file for this review round; contact the editorial team")
            validate_round_file(round_file, manuscript, db)

        # Step 6: Create the assignment
        new_assignment = ReviewAssignment(
            manuscript_id=assignment_data.manuscript_id,
            reviewer_id=assignment_data.reviewer_id,
            assigned_by=current_user.user_id,
            review_round=expected_round,
            status="assigned"
        )

        db.add(new_assignment)
        db.flush()
        db.add(ReviewAssignmentFile(assignment_id=new_assignment.assignment_id, round_file_id=round_file.round_file_id))
        db.add(ReviewerInvitation(assignment_id=new_assignment.assignment_id, status="pending"))
        db.flush()
        if not policy['locked_at']:
            try:
                lock_mode(raw, manuscript.manuscript_id, new_assignment.assignment_id,
                          current_user.user_id, policy['revision'], assignment_actor=True)
            except PolicyError:
                raise HTTPException(409, 'Review policy cannot be locked; refresh and retry') from None

        # Step 7: Notify the assigned reviewer
        notification = Notification(
            user_id=reviewer.user_id,
            manuscript_id=manuscript.manuscript_id,
            notification_type="review_invitation",
            message=(
                "You have a reviewer invitation."
            ),
            is_read=False
        )

        db.add(notification)

        return new_assignment

    new_assignment = build_invitation()
    if enqueue_mode is EnqueueMode.ENQUEUE_ONLY:
        try:
            enqueue_reviewer_invitation(db, new_assignment.assignment_id)
        except Exception as error:
            logger.error('reviewer_invitation_enqueue_failed: %s', type(error).__name__)
            raise _EnqueueFailure(error) from None
    return new_assignment, manuscript



class InvitationResponse(BaseModel):
    decision: Literal["accept", "decline"]


@router.get('/{assignment_id}/task', summary='Get your reviewer invitation task')
def reviewer_task(assignment_id: int, current_user: User = Depends(require_role('reviewer')),
                  db: Session = Depends(get_db), mode: MetadataMode = Depends(reviewer_metadata_mode),
                  artifact_context: DemoArtifactContext | None = Depends(reviewer_demo_artifact_context)):
    """Return only own neutral task; this does not confer manuscript access."""
    headers = {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}
    if type(mode) is not MetadataMode:
        raise HTTPException(503, 'Task unavailable', headers=headers)
    try:
        connection = db.connection()
        if mode is MetadataMode.EXPERIMENTAL:
            if connection.dialect.name != 'sqlite':
                raise MetadataSchemaUnavailable('Task unavailable')
            raw = connection.connection.driver_connection
            if not raw.in_transaction:
                connection.exec_driver_sql('BEGIN')
            _security_context(raw, current_user.user_id)
        assignment = db.scalar(select(ReviewAssignment).where(
            ReviewAssignment.assignment_id == assignment_id,
            ReviewAssignment.reviewer_id == current_user.user_id))
        if assignment is None:
            raise HTTPException(404, 'Task not found', headers=headers)
        manuscript = db.get(Manuscript, assignment.manuscript_id)
        task = reviewer_assignment_task(db, assignment, manuscript)
        # Only the ordinary submission path is classified here. Experimental
        # review submission has additional artifact-context checks and remains
        # unavailable until those can be verified without guessing its contract.
        if (mode is MetadataMode.DISABLED and task['task_message'] ==
                'Your assignment is active; current review action eligibility is unconfirmed.' and
                reviewer_document_available(db, current_user, assignment_id, mode, artifact_context)):
            task = {**task, 'task_state':'action_required',
                    'task_message':'Complete and submit your review using the review form.',
                    'action_label':'View review form',
                    'permitted_action_target':f'#review-action-{assignment_id}'}
        return JSONResponse(task, headers=headers)
    except MetadataAccessDenied:
        raise HTTPException(404, 'Task not found', headers=headers) from None
    except (MetadataSchemaUnavailable, sqlite3.DatabaseError, SQLAlchemyError):
        raise HTTPException(503, 'Task unavailable', headers=headers) from None


@router.post("/{assignment_id}/invitation-response")
def respond_reviewer_invitation(assignment_id: int, data: InvitationResponse, current_user: User = Depends(require_role("reviewer")), db: Session = Depends(get_db)):
    assignment = db.get(ReviewAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if assignment.reviewer_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="This invitation belongs to another reviewer")
    manuscript = db.get(Manuscript, assignment.manuscript_id)
    if manuscript is None or manuscript.status not in ("ready_for_peer_review", "revised") or manuscript.review_round != assignment.review_round:
        raise HTTPException(status_code=409, detail="This review round is no longer open")
    new_status = "accepted" if data.decision == "accept" else "declined"
    conditions = [ReviewerInvitation.assignment_id == assignment_id, ReviewerInvitation.status == "pending"]
    try:
        if inspect(db.connection()).has_table('reviewer_invitation_invalidations'):
            conditions.append(~select(ReviewerInvitationInvalidation.invalidation_id).where(
                ReviewerInvitationInvalidation.assignment_id == assignment_id).exists())
        result = db.execute(update(ReviewerInvitation).where(*conditions).values(status=new_status, responded_at=datetime.now(timezone.utc)))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Invitation unavailable") from None
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Invitation is not pending")
    recipient = db.get(User, assignment.assigned_by)
    if recipient and recipient.role in ('editor', 'eic'):
        db.add(Notification(user_id=recipient.user_id, manuscript_id=assignment.manuscript_id, notification_type="review_invitation_response", message=f"A reviewer invitation was {new_status} for round {assignment.review_round}.", is_read=False))
    db.commit()
    return {"assignment_id": assignment_id, "invitation_status": new_status}



# Editor: View all review assignments
@router.get(
    "/",
    response_model=list[ReviewAssignmentResponse],
    summary="Get All Review Assignments"
)
def get_all_assignments(
    current_user: Annotated[
        User,
        Depends(require_role("editor"))
    ],
    db: Session = Depends(get_db)
):
    assignments = db.scalars(
        select(ReviewAssignment).order_by(
            ReviewAssignment.assignment_id
        )
    ).all()

    accessible = []
    for assignment in assignments:
        manuscript = db.get(Manuscript, assignment.manuscript_id)
        if manuscript and can_access_manuscript(db, manuscript, current_user):
            accessible.append(assignment)
    return assignments_to_responses(db, accessible)


# Reviewer: View their own assignments
@router.get(
    "/my",
    response_model=list[ReviewerSafeAssignmentDTO | ReviewerAssignmentDoubleDTO],
    summary="Get My Review Assignments"
)
def get_my_assignments(
    current_user: Annotated[
        User,
        Depends(require_role("reviewer"))
    ],
    db: Session = Depends(get_db),
    metadata_mode: MetadataMode = Depends(reviewer_metadata_mode),
    artifact_context: DemoArtifactContext | None = Depends(reviewer_demo_artifact_context),
):
    if type(metadata_mode) is not MetadataMode:
        raise HTTPException(status_code=503, detail='Reviewer assignments unavailable', headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})
    try:
        connection = db.connection()
        if connection.dialect.name != 'sqlite':
            raise MetadataSchemaUnavailable('Reviewer assignments unavailable')
        raw = connection.connection.driver_connection
        if not raw.in_transaction:
            connection.exec_driver_sql('BEGIN')
    except (MetadataSchemaUnavailable, sqlite3.DatabaseError, SQLAlchemyError):
        raise HTTPException(status_code=503, detail='Reviewer assignments unavailable', headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'}) from None
    if metadata_mode is MetadataMode.EXPERIMENTAL:
        try:
            payload=reviewer_assignment_dtos(raw,current_user.user_id)
            for item in payload:
                available = reviewer_document_available(db, current_user, item['assignment_id'], metadata_mode, artifact_context)
                item.update(review_file_available=available, review_file_status='available' if available else 'unavailable')
        except (MetadataSchemaUnavailable,MetadataAccessDenied,sqlite3.DatabaseError,SQLAlchemyError):
            raise HTTPException(status_code=503, detail='Reviewer assignments unavailable', headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'}) from None
        return JSONResponse(content=payload,headers={'Cache-Control':'no-store','Pragma':'no-cache'})
    assignments = db.scalars(
        select(ReviewAssignment)
        .where(
            ReviewAssignment.reviewer_id == current_user.user_id
        )
        .order_by(
            ReviewAssignment.assignment_id
        )
        .execution_options(populate_existing=True)
    ).all()

    # Reviewer lists use a neutral allowlist even when policy is unresolved.
    manuscript_ids = {assignment.manuscript_id for assignment in assignments}
    manuscript_rows = db.scalars(select(Manuscript).where(Manuscript.manuscript_id.in_(manuscript_ids)).execution_options(populate_existing=True)).all() if manuscript_ids else []
    by_id = {manuscript.manuscript_id: manuscript for manuscript in manuscript_rows}
    payload = []
    for assignment in assignments:
        manuscript = by_id.get(assignment.manuscript_id)
        if manuscript is None:
            raise HTTPException(status_code=500, detail='Assignment references a missing manuscript')
        available = reviewer_document_available(db, current_user, assignment.assignment_id, metadata_mode, artifact_context)
        payload.append(ReviewerSafeAssignmentDTO(
            assignment_id=assignment.assignment_id, manuscript_id=assignment.manuscript_id,
            review_round=assignment.review_round, status=assignment.status,
            invitation_status=invitation_status(db, assignment), assigned_at=assignment.assigned_at,
            manuscript_status=manuscript.status, has_pdf=manuscript_has_pdf(manuscript),
            review_file_available=available, review_file_status='available' if available else 'unavailable',
        ).model_dump(mode='json'))
    return JSONResponse(content=payload, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})


# Editor: View all assignments for a manuscript
@router.get(
    "/manuscript/{manuscript_id}",
    response_model=list[ReviewAssignmentResponse],
    summary="Get Manuscript Review Progress"
)
def get_manuscript_review_progress(
    manuscript_id: int,
    current_user: Annotated[
        User,
        Depends(require_role("editor", "eic"))
    ],
    db: Session = Depends(get_db)
):
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manuscript not found"
        )

    if not can_access_manuscript(db, manuscript, current_user):
        raise HTTPException(status_code=403, detail="You are not an assigned editor")

    assignments = db.scalars(
        select(ReviewAssignment)
        .where(
            ReviewAssignment.manuscript_id == manuscript_id
        )
        .order_by(
            ReviewAssignment.review_round,
            ReviewAssignment.assignment_id
        )
    ).all()

    return [
        assignment_to_response(db, assignment, manuscript)
        for assignment in assignments
    ]


# Editor: Get current review round summary
@router.get(
    "/manuscript/{manuscript_id}/summary",
    summary="Get Manuscript Review Summary"
)
def get_manuscript_review_summary(
    manuscript_id: int,
    current_user: Annotated[
        User,
        Depends(require_role("editor", "eic"))
    ],
    db: Session = Depends(get_db)
):
    # Step 1: Find manuscript
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manuscript not found"
        )

    if not can_access_manuscript(db, manuscript, current_user):
        raise HTTPException(status_code=403, detail="You are not an assigned editor")

    # Step 2: Use current review round
    review_round = manuscript.review_round

    # Step 3: Get assignments for current round
    assignments = db.scalars(
        select(ReviewAssignment).where(
            ReviewAssignment.manuscript_id == manuscript_id,
            ReviewAssignment.review_round == review_round,
            not_declined(),
        )
    ).all()

    # Step 4: Find completed reviews
    assignment_ids = [
        assignment.assignment_id
        for assignment in assignments
    ]

    reviewed_ids = set()

    if assignment_ids:
        reviewed_ids = set(
            db.scalars(
                select(Review.assignment_id).where(
                    Review.assignment_id.in_(assignment_ids)
                )
            ).all()
        )

    # Step 5: Calculate progress
    total_reviewers = len(assignments)

    completed_reviews = sum(
        assignment.assignment_id in reviewed_ids
        for assignment in assignments
    )

    pending_reviews = total_reviewers - completed_reviews

    # Step 6: Return summary
    return {
        "manuscript_id": manuscript_id,
        "decision_progress": review_progress(db, manuscript, review_round),
        "review_round": review_round,
        "total_reviewers": total_reviewers,
        "completed_reviews": completed_reviews,
        "pending_reviews": pending_reviews,
        "all_reviews_completed": (
            total_reviewers > 0
            and pending_reviews == 0
        )
    }

@router.get(
    "/{assignment_id}/download",
    summary="Download Assigned Peer-review Document",
)
def download_assigned_review_pdf(
    assignment_id: int,
    current_user: Annotated[
        User,
        Depends(require_role("reviewer")),
    ],
    db: Session = Depends(get_db),
    metadata_mode: MetadataMode = Depends(reviewer_metadata_mode),
    artifact_context: DemoArtifactContext | None = Depends(reviewer_demo_artifact_context),
):
    return release_reviewer_document(db, current_user, assignment_id, metadata_mode, artifact_context)

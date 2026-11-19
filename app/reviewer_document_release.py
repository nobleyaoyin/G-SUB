"""Policy-aware reviewer document release; never infer missing policy."""
import sqlite3

from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError

from app.blind_policy_store import PolicyError, read_policy
from app.models import Manuscript, ReviewAssignment, ReviewerInvitationInvalidation
from app.review_files import snapshot_assignment_file
from app.reviewer_artifact_read import ArtifactReadUnavailable, read_reviewer_artifact
from app.main_reviewer_context import AuthenticatedReviewerAuthority, ReviewerArtifactContext
from app.main_reviewer_authority import AuthorityUnavailable
from app.reviewer_metadata_gate import MetadataAccessDenied, MetadataMode, MetadataSchemaUnavailable, _security_context
from app.routers.manuscripts import ALLOWED_MANUSCRIPT_EXTENSIONS

HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}


def evaluate_reviewer_document(db, reviewer, assignment_id, metadata_mode, artifact_context):
    """Authorize a reviewer and snapshot a policy-permitted document.

    A missing trusted artifact adapter is a denial, never a source fallback.
    This function makes no claim that an approved document is anonymous.
    """
    try:
        if reviewer.role != 'reviewer' or type(metadata_mode) is not MetadataMode:
            raise MetadataAccessDenied('Review file unavailable')
        connection = db.connection()
        if connection.dialect.name != 'sqlite':
            raise MetadataSchemaUnavailable('Review file unavailable')
        raw = connection.connection.driver_connection
        if not raw.in_transaction:
            connection.exec_driver_sql('BEGIN')
        if metadata_mode is MetadataMode.EXPERIMENTAL:
            _security_context(raw, reviewer.user_id)
        assignment = db.get(ReviewAssignment, assignment_id, populate_existing=True)
        if assignment is None or assignment.reviewer_id != reviewer.user_id:
            raise MetadataAccessDenied('Review file unavailable')
        manuscript = db.get(Manuscript, assignment.manuscript_id, populate_existing=True)
        if manuscript is None or db.query(ReviewerInvitationInvalidation).filter_by(assignment_id=assignment_id).first():
            raise MetadataAccessDenied('Review file unavailable')
        policy = read_policy(raw, manuscript.manuscript_id)
        if not policy or not policy['locked_at']:
            raise MetadataAccessDenied('Review file unavailable')
        # Every release requires the current authenticated reviewer, active
        # lifecycle and this exact accepted, current-round assignment.
        AuthenticatedReviewerAuthority(reviewer).authorize(
            raw, reviewer, 'read_artifact', manuscript.manuscript_id)
        row = raw.execute("SELECT 1 FROM reviewer_invitations WHERE assignment_id=? AND status='accepted'", (assignment_id,)).fetchone()
        if (not row or assignment.status != 'assigned'
                or assignment.review_round != manuscript.review_round
                or manuscript.status not in ('ready_for_peer_review', 'revised')):
            raise MetadataAccessDenied('Review file unavailable')
        if policy['mode'] == 'single_blind':
            snapshot = snapshot_assignment_file(db, assignment, manuscript)
            return snapshot.content, ALLOWED_MANUSCRIPT_EXTENSIONS[snapshot.extension], f'review-document{snapshot.extension}'
        if policy['mode'] == 'double_blind':
            if type(artifact_context) is not ReviewerArtifactContext:
                raise MetadataAccessDenied('Approved review file unavailable')
            snapshot = read_reviewer_artifact(raw, reviewer, AuthenticatedReviewerAuthority(reviewer),
                artifact_context.proof, artifact_context.provenance, artifact_context.storage, assignment_id)
            return snapshot.content, snapshot.media_type, snapshot.filename
        raise MetadataAccessDenied('Review file unavailable')
    except (PolicyError, ArtifactReadUnavailable, AuthorityUnavailable, MetadataAccessDenied, MetadataSchemaUnavailable,
            sqlite3.DatabaseError, SQLAlchemyError, HTTPException):
        raise HTTPException(409, 'Review file unavailable. Contact the editorial team.', headers=HEADERS) from None


def release_reviewer_document(db, reviewer, assignment_id, metadata_mode, artifact_context):
    content, media_type, filename = evaluate_reviewer_document(db, reviewer, assignment_id, metadata_mode, artifact_context)
    return Response(content=content, media_type=media_type,
                    headers={**HEADERS, 'Content-Disposition': f'attachment; filename="{filename}"'})


def reviewer_document_available(db, reviewer, assignment_id, metadata_mode, artifact_context):
    try:
        evaluate_reviewer_document(db, reviewer, assignment_id, metadata_mode, artifact_context)
        return True
    except HTTPException:
        return False

"""Non-routed source/policy read foundation; no durable attestation or release.

The caller must supply an authenticated ORM principal and a server-owned trusted
prospective proof adapter. Never expose the adapter or lineage object as an
untrusted API input. No production proof adapter is configured by this module.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import SessionTransactionOrigin, object_session

from app import blind_policy_store, reviewer_artifact_service
from app.models import InitialEditingSubmission, Manuscript, PreReviewConfirmation, ReviewRoundFile, User
from app.review_files import snapshot_round_file


class FoundationUnavailable(ValueError):
    """The source, policy or trusted proof cannot be verified."""


def _server_proof_adapter():
    """No production proof authority exists; future wiring requires review."""
    return None


@dataclass(frozen=True)
class EphemeralLineage:
    observation_id: str
    manuscript_id: int
    review_round: int
    source_id: int
    source_revision: str
    source_sha256: str
    byte_length: int
    format: str
    workflow_event: str
    policy_event_id: str
    policy_revision: int
    actor_id: int
    observed_at: datetime


def capture(db, principal, manuscript_id, source_id, expected_policy_revision, *, proof_adapter=None):
    """Capture an ephemeral observation, never historical approval evidence.

    `principal` must originate from server authentication in this same session;
    the proof adapter must be an application-controlled authority, not request
    data. The adapter verifies an independently recorded prospective approval and
    returns (proof_id, digest, size, format) for this manuscript/round/source.
    Requires a fresh SQLite transaction. The caller owns the resulting read
    transaction and must explicitly end it before a subsequent fresh read.
    """
    if not isinstance(principal, User) or object_session(principal) is not db:
        raise FoundationUnavailable('Authenticated EIC required')
    if db.new or db.dirty or db.deleted:
        raise FoundationUnavailable('A clean read session is required')
    transaction = db.get_transaction()
    if db.in_nested_transaction() or (transaction is not None and transaction.origin is not SessionTransactionOrigin.AUTOBEGIN):
        raise FoundationUnavailable('Caller-owned transaction cannot be reused')
    if any(type(value) is not int or value < 1 for value in (manuscript_id, source_id, expected_policy_revision)):
        raise FoundationUnavailable('Invalid context')
    configured_adapter = _server_proof_adapter()
    if configured_adapter is None or proof_adapter is not configured_adapter:
        raise FoundationUnavailable('Trusted prospective source proof unavailable')
    try:
        connection = db.connection()
        if connection.dialect.name != 'sqlite':
            raise FoundationUnavailable('Source verification unavailable')
        raw = connection.connection.driver_connection
        if raw.in_transaction:
            raise FoundationUnavailable('Fresh read transaction required')
        connection.exec_driver_sql('BEGIN')
        user = db.get(User, principal.user_id, populate_existing=True)
        if user is not principal or user.role != 'eic':
            raise FoundationUnavailable('Authenticated EIC required')
        manuscript = db.get(Manuscript, manuscript_id, populate_existing=True)
        record = db.get(ReviewRoundFile, source_id, populate_existing=True)
        if manuscript is None or record is None:
            raise FoundationUnavailable('Source unavailable')
        source = reviewer_artifact_service._source(raw, manuscript_id, source_id)
        if record.review_round == 1:
            confirmation = db.get(PreReviewConfirmation, record.confirmation_id, populate_existing=True)
            submission = db.get(InitialEditingSubmission, confirmation.submission_id, populate_existing=True) if confirmation else None
            approver = db.get(User, submission.eic_approved_by, populate_existing=True) if submission and submission.eic_approved_by else None
            if not confirmation or not confirmation.confirmed_at or not submission or not submission.eic_reviewed_at or not approver or approver.role != 'eic':
                raise FoundationUnavailable('Workflow approval evidence unavailable')
        if record.review_round > 1 and manuscript.file_path != record.file_path:
            raise FoundationUnavailable('Source revision is stale')
        policy = blind_policy_store.read_policy(raw, manuscript_id)
        if not policy or policy['mode'] != 'double_blind' or policy['locked_at'] or policy['revision'] != expected_policy_revision:
            raise FoundationUnavailable('Selected policy unavailable or stale')
        proof_id, digest, size, fmt = proof_adapter.verify_prospective(
            manuscript_id, record.review_round, source_id, source[4])
        if not isinstance(proof_id, str) or not proof_id:
            raise FoundationUnavailable('Trusted prospective source proof unavailable')
        snapshot = snapshot_round_file(db, record, manuscript)
        if (digest, size, fmt) != (snapshot.sha256, len(snapshot.content), snapshot.extension.lstrip('.')):
            raise FoundationUnavailable('Source proof mismatch')
        if proof_adapter.verify_prospective(manuscript_id, record.review_round, source_id, source[4]) != (proof_id, digest, size, fmt):
            raise FoundationUnavailable('Source proof changed')
        if reviewer_artifact_service._source(raw, manuscript_id, source_id) != source or blind_policy_store.read_policy(raw, manuscript_id) != policy:
            raise FoundationUnavailable('Source or policy changed')
        event = f'confirmation:{source[4]}' if record.review_round == 1 else f'round-file:{source_id}'
        return EphemeralLineage(str(uuid4()), manuscript_id, record.review_round, source_id, proof_id,
            snapshot.sha256, len(snapshot.content), snapshot.extension.lstrip('.'), event,
            policy['last_event_id'], policy['revision'], user.user_id, datetime.now(timezone.utc))
    except FoundationUnavailable:
        raise
    except Exception as exc:
        raise FoundationUnavailable('Source verification unavailable') from exc


def revalidate(db, principal, observation, *, proof_adapter=None):
    """Recheck in a fresh caller-owned transaction, not durable authorization."""
    if not isinstance(observation, EphemeralLineage):
        raise FoundationUnavailable('Lineage unavailable')
    current = capture(db, principal, observation.manuscript_id, observation.source_id,
                      observation.policy_revision, proof_adapter=proof_adapter)
    fields = ('manuscript_id', 'review_round', 'source_id', 'source_revision', 'source_sha256',
              'byte_length', 'format', 'workflow_event', 'policy_event_id', 'policy_revision', 'actor_id')
    if any(getattr(current, name) != getattr(observation, name) for name in fields):
        raise FoundationUnavailable('Lineage is stale')
    return current

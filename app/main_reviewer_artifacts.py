"""Main-owned guards for candidate-backed reviewer artifacts.

Never treat a candidate digest as evidence of anonymity. The recorded EIC
checklist and approval are required, and are rechecked at every read.
"""
from importlib import import_module

from fastapi import HTTPException
from sqlalchemy.orm import object_session

from app import eic_prospective_proof as proofs
from app import reviewer_artifact_service as service
from app.eic_source_evidence_bridge import EICSourceEvidenceBridge
from app.reviewer_artifact_storage import StorageMetadata, StorageError

schema = import_module('migrations.023_reviewer_candidate_intake')
publication_schema = import_module('migrations.024_reviewer_publication_audit')
preparation_schema = import_module('migrations.038_candidate_preparation_provenance')


def require_publication_schema(raw):
    try:
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (publication_schema.MIGRATION_ID,)).fetchone():
            raise RuntimeError('Publication audit unavailable')
        publication_schema.validate_schema(raw)
    except Exception as exc:
        raise service.ArtifactError('Publication audit unavailable') from exc


def require_publication(raw, artifact_id, manuscript_id, review_round, artifact_version, digest, proof_id):
    require_publication_schema(raw)
    row = raw.execute('''SELECT manuscript_id,review_round,artifact_version,artifact_sha256,source_proof_id,result
        FROM reviewer_publication_audit WHERE artifact_id=?''', (artifact_id,)).fetchone()
    if not row or row[:5] != (manuscript_id, review_round, artifact_version, digest, proof_id) or row[5] not in ('published', 'reaffirmed'):
        raise service.ArtifactError('Publication evidence unavailable')


def checked(db, raw, candidate_id, manuscript_id):
    if not raw.in_transaction:
        raise service.ArtifactError('Candidate transaction unavailable')
    try:
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (schema.MIGRATION_ID,)).fetchone():
            raise service.ArtifactError('Candidate schema unavailable')
        schema.validate_schema(raw)
        row = raw.execute('''SELECT r.review_round,r.source_id,r.proof_id,r.source_evidence_id,r.sha256,
            r.byte_size,r.format,r.artifact_version,v.verifier_id,a.approver_id
            FROM reviewer_candidate_reservations r
            JOIN reviewer_candidate_publications p ON p.candidate_id=r.candidate_id
            JOIN reviewer_candidate_verifications v ON v.candidate_id=r.candidate_id
                AND v.sha256=r.sha256 AND v.artifact_version=r.artifact_version
                AND v.checklist='reviewer_anonymity_v1:1111111111'
            JOIN reviewer_candidate_approvals a ON a.candidate_id=r.candidate_id
                AND a.sha256=r.sha256 AND a.artifact_version=r.artifact_version
            WHERE r.candidate_id=? AND r.manuscript_id=? AND NOT EXISTS
                (SELECT 1 FROM reviewer_candidate_withdrawals w WHERE w.candidate_id=r.candidate_id)''',
            (candidate_id, manuscript_id)).fetchone()
        if not row:
            raise service.ArtifactError('Approved candidate unavailable')
        rnd, sid, pid, evidence_id, digest, size, fmt, version, verifier, approver = row
        if (raw.execute("SELECT 1 FROM sqlite_master WHERE name='candidate_review_rejections'").fetchone()
                or raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (preparation_schema.MIGRATION_ID,)).fetchone()):
            if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (preparation_schema.MIGRATION_ID,)).fetchone():
                raise service.ArtifactError('Preparation provenance unavailable')
            preparation_schema.validate_schema(raw)
            if raw.execute('SELECT 1 FROM candidate_review_rejections WHERE candidate_id=?', (candidate_id,)).fetchone():
                raise service.ArtifactError('Candidate rejected')
            if (raw.execute('SELECT 1 FROM candidate_preparation_events WHERE candidate_id=?', (candidate_id,)).fetchone()
                    and not raw.execute('SELECT 1 FROM candidate_filename_verifications WHERE candidate_id=? AND sha256=? AND artifact_version=?', (candidate_id, digest, version)).fetchone()):
                raise service.ArtifactError('Filename verification unavailable')
        proofs.actor(raw, verifier, 'eic')
        proofs.actor(raw, approver, 'eic')
        proof = proofs.verify(db, raw, pid, manuscript_id, rnd, sid)
        evidence = raw.execute('''SELECT evidence_id,source_sha256 FROM source_provenance_evidence
            WHERE source_round_file_id=? AND manuscript_id=? AND review_round=? AND proof_reference=?
            AND revision=(SELECT MAX(revision) FROM source_provenance_evidence WHERE source_round_file_id=?)''',
            (sid, manuscript_id, rnd, pid, sid)).fetchone()
        if not evidence or evidence != (evidence_id, proof.sha256) or digest == proof.sha256:
            raise service.ArtifactError('Candidate provenance unavailable')
        metadata = StorageMetadata(candidate_id, digest, size, fmt)
        with proofs.storage() as private:
            content = private.read_verified(metadata)
        return row, metadata, content
    except (HTTPException, StorageError, RuntimeError) as exc:
        raise service.ArtifactError('Approved candidate unavailable') from exc


class GuardedCandidateStorage:
    """Read only the currently valid candidate; publication reuses its bytes."""
    def __init__(self, db, raw, manuscript_id, candidate_id):
        self.db, self.raw, self.manuscript_id, self.candidate_id = db, raw, manuscript_id, candidate_id

    def publish(self, content, fmt):
        _, metadata, expected = checked(self.db, self.raw, self.candidate_id, self.manuscript_id)
        if content != expected or fmt != metadata.format:
            raise StorageError('Candidate bytes unavailable')
        return metadata

    def read_verified(self, metadata):
        _, current, content = checked(self.db, self.raw, self.candidate_id, self.manuscript_id)
        if current != metadata:
            raise StorageError('Candidate identity unavailable')
        return content


class EICAuthority(EICSourceEvidenceBridge):
    def authorize(self, raw, principal, action, manuscript_id, *, prepared_by=None):
        if action not in ('prepare', 'approved', 'bind', 'withdrawn'):
            raise service.ArtifactError('EIC artifact authority unavailable')
        return super().authorize(raw, principal, 'capture_source', manuscript_id)


class ReviewerAuthority:
    def __init__(self, session, raw, reviewer):
        self.session, self.raw, self.reviewer = session, raw, reviewer

    def authorize(self, raw, principal, action, manuscript_id, *, prepared_by=None):
        if (raw is not self.raw or not raw.in_transaction or principal is not self.reviewer
                or object_session(principal) is not self.session or action != 'read_artifact'):
            raise service.ArtifactError('Reviewer authority unavailable')
        try:
            proofs.actor(raw, principal.user_id, 'reviewer')
        except HTTPException as exc:
            raise service.ArtifactError('Reviewer authority unavailable') from exc
        return principal.user_id

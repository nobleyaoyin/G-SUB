"""Main-owned bridge from prospective proof to artifact source evidence.

This bridge establishes source provenance only. It neither creates nor releases
a Reviewer artifact, and it is not an anonymization mechanism.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib

from fastapi import HTTPException

from app import eic_prospective_proof as proofs
from app import reviewer_artifact_service as service
from app.reviewer_artifact_storage import StorageMetadata, StorageError
from app.protected_eic_auth import require_current_eic
from app.routers.manuscripts import validate_manuscript_file


@dataclass(frozen=True)
class ArtifactCandidate:
    """Metadata for a candidate only; it is not anonymity or publication evidence."""
    source_proof_id: str
    sha256: str
    byte_size: int
    format: str


class EICSourceEvidenceBridge:
    """Server-created adapters bound to one session and authenticated request."""

    def __init__(self, session, raw, credentials, actor_id):
        self.session, self.raw, self.credentials, self.actor_id = session, raw, credentials, actor_id

    def _transaction(self, raw):
        if raw is not self.raw or not raw.in_transaction:
            raise service.ArtifactError('Source proof transaction unavailable')

    def authorize(self, raw, principal, action, manuscript_id, *, prepared_by=None):
        self._transaction(raw)
        if action != 'capture_source' or principal != self.actor_id:
            raise service.ArtifactError('EIC source authority unavailable')
        try:
            require_current_eic(raw, self.session, self.credentials, self.actor_id)
        except HTTPException as exc:
            raise service.ArtifactError('EIC source authority unavailable') from exc
        return self.actor_id

    def _verified(self, raw, manuscript_id, review_round, source_id):
        self._transaction(raw)
        row = raw.execute('''SELECT p.proof_id, r.storage_id FROM eic_prospective_proofs p
            JOIN eic_proof_reservations r ON r.storage_id=p.storage_id
            WHERE r.manuscript_id=? AND r.review_round=? AND r.source_id=?''',
            (manuscript_id, review_round, source_id)).fetchone()
        if not row:
            raise service.ArtifactError('Prospective source proof unavailable')
        try:
            result = proofs.verify(self.session, raw, row[0], manuscript_id, review_round, source_id)
        except (HTTPException, StorageError) as exc:
            raise service.ArtifactError('Prospective source proof unavailable') from exc
        return result, row[1]

    def verify_prospective(self, raw, manuscript_id, review_round, source_id, confirmation_id):
        self._transaction(raw)
        row = raw.execute('SELECT confirmation_id FROM review_round_files WHERE round_file_id=? AND manuscript_id=? AND review_round=?',
                          (source_id, manuscript_id, review_round)).fetchone()
        if not row or row[0] != confirmation_id:
            raise service.ArtifactError('Source confirmation unavailable')
        proof, _ = self._verified(raw, manuscript_id, review_round, source_id)
        return proof.proof_id, proof.sha256, proof.byte_size, proof.format

    def validate_candidate(self, raw, manuscript_id, review_round, source_id, content, fmt):
        """Validate a distinct candidate without publishing or approving it."""
        self.authorize(raw, self.actor_id, 'capture_source', manuscript_id)
        proof, _ = self._verified(raw, manuscript_id, review_round, source_id)
        if not isinstance(content, bytes) or fmt not in ('pdf', 'docx', 'doc', 'txt'):
            raise service.ArtifactError('Reviewer artifact candidate unavailable')
        try:
            validate_manuscript_file('candidate.' + fmt, content)
        except HTTPException as exc:
            raise service.ArtifactError('Reviewer artifact candidate unavailable') from exc
        digest = hashlib.sha256(content).hexdigest()
        if digest == proof.sha256:
            raise service.ArtifactError('Candidate must differ from approved source')
        return ArtifactCandidate(proof.proof_id, digest, len(content), fmt)

    @contextmanager
    def open_attested_source(self, raw, manuscript_id, review_round, source_id, source_path):
        self._transaction(raw)
        row = raw.execute('SELECT file_path FROM review_round_files WHERE round_file_id=? AND manuscript_id=? AND review_round=?',
                          (source_id, manuscript_id, review_round)).fetchone()
        if not row or row[0] != source_path:
            raise service.ArtifactError('Source identity unavailable')
        proof, storage_id = self._verified(raw, manuscript_id, review_round, source_id)
        metadata = StorageMetadata(storage_id, proof.sha256, proof.byte_size, proof.format)
        try:
            with proofs.storage() as private, private.open_verified(metadata) as fd:
                yield fd, proof.sha256, proof.byte_size, proof.format
        except (HTTPException, StorageError) as exc:
            raise service.ArtifactError('Source snapshot unavailable') from exc

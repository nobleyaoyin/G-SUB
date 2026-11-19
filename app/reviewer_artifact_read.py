"""Disconnected reviewer snapshot prototype; not a public download endpoint.

The authority, proof and provenance adapters must be selected by trusted code;
this module does not authenticate a request or establish document anonymity.
"""
from dataclasses import dataclass

from app import reviewer_artifact_binding as binding, reviewer_artifact_service as service


class ArtifactReadUnavailable(ValueError):
    """Sanitized denial for unavailable, inconsistent or unauthorized reads."""


@dataclass(frozen=True)
class VerifiedReviewerSnapshot:
    content: bytes
    filename: str
    media_type: str


_MEDIA = {
    'pdf': 'application/pdf',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'doc': 'application/msword',
    'txt': 'text/plain',
}


def _reviewer_actor(db,principal,authority,mid,reviewer_id):
    actor=service._actor(db,authority,principal,'read_artifact',mid)
    if actor!=reviewer_id: raise service.ArtifactError('Reviewer unavailable')
    return actor


def read_reviewer_artifact(db, principal, authority, proof_adapter, provenance, storage, assignment_id):
    """Return verified bytes and neutral metadata from one explicit read snapshot.

    The caller supplies an already-open SQLite connection in an explicit read
    transaction and a principal verified by trusted authority. No commit,
    retry, HTTP response, source fallback or privileged identity is returned.
    """
    try:
        if not db.in_transaction: raise ArtifactReadUnavailable('Artifact unavailable')
        service._id(assignment_id)
        row=db.execute('''SELECT b.artifact_id,p.revision,a.state_revision,s.revision
          FROM reviewer_artifact_assignments b
          JOIN review_assignments x ON x.assignment_id=b.assignment_id
          JOIN blind_policies p ON p.manuscript_id=x.manuscript_id
          JOIN reviewer_artifacts a ON a.artifact_id=b.artifact_id
          JOIN artifact_approval_evidence e ON e.artifact_id=a.artifact_id AND e.approval_event_id=a.current_event_id
          JOIN source_provenance_evidence s ON s.evidence_id=e.source_evidence_id
          WHERE b.assignment_id=?''',(assignment_id,)).fetchone()
        if not row: raise ArtifactReadUnavailable('Artifact unavailable')
        artifact_id,policy_revision,artifact_revision,source_revision=row
        _,content,fmt=binding._verify(db,principal,authority,proof_adapter,provenance,storage,assignment_id,artifact_id,_reviewer_actor,
            expected_policy_revision=policy_revision,expected_artifact_revision=artifact_revision,expected_source_revision=source_revision)
        if fmt not in _MEDIA: raise ArtifactReadUnavailable('Artifact unavailable')
        return VerifiedReviewerSnapshot(content=content,filename='review-document.'+fmt,media_type=_MEDIA[fmt])
    except Exception:
        # Preserve a uniform public-facing error without leaking SQL, paths or identities.
        raise ArtifactReadUnavailable('Artifact unavailable') from None

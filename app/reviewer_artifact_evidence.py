"""Opt-in, disconnected evidence prototype; no production adapters or routes.

Trusted dependencies must authenticate users and independently verify a
prospective proof captured at source approval, not manufacture it from a
current file. Callers control SQLite transactions and adapter construction.
"""
from importlib import import_module
from uuid import uuid4

from app import reviewer_artifact_service as service
from app.reviewer_artifact_storage import read_verified_fd

schema = import_module('migrations.013_artifact_evidence')


def _context(db):
    service._context(db)
    try:
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(schema.MIGRATION_ID,)).fetchone(): raise service.ArtifactError('Evidence schema unavailable')
        schema.validate_schema(db)
    except service.ArtifactError: raise
    except Exception as error: raise service.ArtifactError('Evidence schema unavailable or incompatible') from error


def capture_source(db, principal, authority, proof_adapter, provenance, manuscript_id, source_id, expected_revision):
    """Persist a trusted previously captured prospective proof, not a new guess.

    proof_adapter.verify_prospective must return (opaque_proof_id, digest,
    size, format) from an independently trusted approval-time record bound to
    this exact manuscript, round, source and workflow. No production adapter
    exists. Current bytes are checked separately against that prior proof.
    """
    _context(db); service._id(manuscript_id); service._id(source_id)
    if type(expected_revision) is not int or expected_revision < 0: raise service.ArtifactError('Invalid evidence revision')
    actor=service._actor(db,authority,principal,'capture_source',manuscript_id)
    source=service._source(db,manuscript_id,source_id)
    proof_id,digest,size,fmt=proof_adapter.verify_prospective(db,manuscript_id,source[2],source_id,source[4])
    with provenance.open_attested_source(db,manuscript_id,source[2],source_id,source[5]) as (fd,prior_digest,prior_size,prior_fmt):
        if (digest,size,fmt)!=(prior_digest,prior_size,prior_fmt): raise service.ArtifactError('Prospective source proof mismatch')
        read_verified_fd(fd,digest,size,fmt)
    last=db.execute('SELECT COALESCE(MAX(revision),0) FROM source_provenance_evidence WHERE source_round_file_id=?',(source_id,)).fetchone()[0]
    if last!=expected_revision: raise service.ArtifactError('Source evidence revision is stale')
    confirmation=submission=eic=None
    if source[2]==1:
        row=db.execute('''SELECT c.confirmation_id,s.submission_id,s.eic_approved_by FROM pre_review_confirmations c
          JOIN initial_editing_submissions s ON s.submission_id=c.submission_id WHERE c.confirmation_id=?''',(source[4],)).fetchone()
        if not row or row[2] is None: raise service.ArtifactError('Explicit EIC approval evidence unavailable')
        confirmation,submission,eic=row
    evidence_id=uuid4().hex
    db.execute('INSERT INTO source_provenance_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (evidence_id,manuscript_id,source[2],source_id,digest,size,fmt,confirmation,submission,eic,proof_id,actor,service._now(),last+1))
    return evidence_id


def approve_with_evidence(db, principal, authority, provenance, storage, artifact_id, source_evidence_id, expected_state_revision, *, checklist_acknowledged=False, checklist_key='reviewer_document', checklist_version=1):
    """Opt-in atomic approval+declaration; neither commits nor retries."""
    _context(db)
    if checklist_acknowledged is not True or checklist_key!='reviewer_document' or type(checklist_version) is not int or checklist_version!=1:
        raise service.ArtifactError('Explicit supported checklist acknowledgement required')
    row=db.execute('''SELECT a.manuscript_id,a.source_round_file_id,a.source_sha256,a.artifact_sha256,a.prepared_by,s.revision,s.byte_size,s.format
        FROM reviewer_artifacts a JOIN source_provenance_evidence s ON s.evidence_id=? AND s.source_round_file_id=a.source_round_file_id
        AND s.manuscript_id=a.manuscript_id AND s.review_round=a.review_round AND s.source_sha256=a.source_sha256
        WHERE a.artifact_id=? AND s.revision=(SELECT MAX(x.revision) FROM source_provenance_evidence x WHERE x.source_round_file_id=s.source_round_file_id)''',(source_evidence_id,artifact_id)).fetchone()
    if not row: raise service.ArtifactError('Current source evidence unavailable')
    mid,sid,digest,artifact_digest,preparer,_,source_size,source_format=row
    actor=service._actor(db,authority,principal,'approved',mid,prepared_by=preparer)
    source=service._source(db,mid,sid)
    with provenance.open_attested_source(db,mid,source[2],sid,source[5]) as (fd,prior_digest,prior_size,prior_format):
        if (prior_digest,prior_size,prior_format)!=(digest,source_size,source_format): raise service.ArtifactError('Source evidence mismatch')
        read_verified_fd(fd,digest,source_size,source_format)
    db.execute('SAVEPOINT artifact_evidence_approval')
    try:
        revision=service.transition(db,principal,authority,provenance,storage,artifact_id,'approved',expected_state_revision,human_review_attested=True)
        event=db.execute('SELECT current_event_id,approved_by,approved_at FROM reviewer_artifacts WHERE artifact_id=?',(artifact_id,)).fetchone()
        if not event or event[1]!=actor: raise service.ArtifactError('Approval actor mismatch')
        evidence_id=uuid4().hex
        db.execute('INSERT INTO artifact_approval_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (evidence_id,artifact_id,event[0],source_evidence_id,artifact_digest,revision,actor,event[2],checklist_key,checklist_version,1,1))
        db.execute('RELEASE SAVEPOINT artifact_evidence_approval')
        return evidence_id,revision
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT artifact_evidence_approval'); db.execute('RELEASE SAVEPOINT artifact_evidence_approval')
        raise

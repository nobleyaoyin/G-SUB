"""Private EIC candidate intake and human attestation; no Reviewer release."""
from importlib import import_module
import sqlite3
from uuid import uuid4
import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import eic_prospective_proof as proofs, reviewer_artifact_service
from app import reviewer_artifact_evidence, reviewer_artifact_binding, blind_policy_store
from app.database import get_db
from app.eic_source_evidence_bridge import EICSourceEvidenceBridge
from app.main_reviewer_artifacts import EICAuthority, GuardedCandidateStorage, checked as checked_approved, require_publication_schema
from app.models import User
from app.reviewer_artifact_storage import StorageError, StorageMetadata
from app.routers.eic_prospective_proofs import now, reauthenticate
from app.routers.manuscripts import MAX_MANUSCRIPT_FILE_SIZE
from app.routers.users import bearer_scheme, require_role

schema = import_module('migrations.023_reviewer_candidate_intake')
preparation_schema = import_module('migrations.038_candidate_preparation_provenance')
router = APIRouter(prefix='/eic', tags=['private reviewer candidates'])


class Checklist(BaseModel):
    model_config = ConfigDict(extra='forbid')
    author_names: StrictBool
    affiliations: StrictBool
    contact_information: StrictBool
    document_metadata: StrictBool
    word_comments: StrictBool
    revision_history: StrictBool
    headers_footers: StrictBool
    hidden_text: StrictBool
    figures_supplements: StrictBool
    acknowledgements_references: StrictBool
    filename_verified: StrictBool = False
    expected_sha256: str | None = None
    expected_artifact_version: int | None = None
    expected_review_round: int | None = None

    @model_validator(mode='after')
    def require_all(self):
        if not all(getattr(self, key) for key in ('author_names', 'affiliations', 'contact_information',
                   'document_metadata', 'word_comments', 'revision_history', 'headers_footers',
                   'hidden_text', 'figures_supplements', 'acknowledgements_references')):
            raise ValueError('All applicable checklist items require human review')
        return self


class Rejection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator('reason')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('A rejection reason is required')
        return value.strip()


class ApprovalContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_sha256: str
    expected_artifact_version: int
    expected_review_round: int
    confirmed: StrictBool


def prepared_candidate(raw, candidate_id):
    return bool(raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidate_preparation_events'").fetchone()
                and raw.execute('SELECT 1 FROM candidate_preparation_events WHERE candidate_id=?', (candidate_id,)).fetchone())


def check_context(data, row):
    if (not data or data.expected_sha256 != row[4] or data.expected_artifact_version != row[7]
            or data.expected_review_round != row[0]):
        raise HTTPException(409, 'Candidate changed; reload before continuing')


@router.get('/manuscripts/{manuscript_id}/reviewer-candidate-reconciliation')
def candidate_reconciliation(manuscript_id: int, user: User = Depends(require_role('eic')),
                             credentials=Depends(bearer_scheme), db: Session = Depends(get_db)):
    """Report known incomplete reservations; never remove or modify files."""
    try:
        raw = begin(db, credentials, user.user_id)
        if not raw.execute("SELECT 1 FROM manuscripts WHERE manuscript_id=? AND status!='draft'", (manuscript_id,)).fetchone():
            raise HTTPException(404, 'Manuscript unavailable')
        rows = raw.execute('''SELECT r.candidate_id,r.reserved_at,r.sha256,r.byte_size,r.format,
            p.candidate_id IS NOT NULL,a.candidate_id IS NOT NULL,w.candidate_id IS NOT NULL
            FROM reviewer_candidate_reservations r
            LEFT JOIN reviewer_candidate_publications p ON p.candidate_id=r.candidate_id
            LEFT JOIN reviewer_candidate_approvals a ON a.candidate_id=r.candidate_id
            LEFT JOIN reviewer_candidate_withdrawals w ON w.candidate_id=r.candidate_id
            WHERE r.manuscript_id=? ORDER BY r.reserved_at,r.candidate_id LIMIT 1001''',
            (manuscript_id,)).fetchall()
        if len(rows) > 1000:
            raise HTTPException(503, 'Reconciliation inventory limit exceeded')
        candidates = []
        with proofs.storage() as private:
            entries = private.inspect_entries()
            for cid, stamp, digest, size, fmt, stored, approved, withdrawn in rows:
                inspection = private.inspect_reserved(cid)
                integrity = 'unavailable'
                if inspection['state'] == 'regular' and inspection['owned_by_service']:
                    try:
                        private.read_verified(StorageMetadata(cid, digest, size, fmt))
                        integrity = 'verified'
                    except StorageError:
                        integrity = 'mismatch_or_unavailable'
                candidates.append({'candidate_id': cid, 'reserved_at': stamp,
                    'file': inspection, 'integrity': integrity, 'stored': bool(stored),
                    'approved': bool(approved), 'withdrawn': bool(withdrawn),
                    'stage_entry': entries.get('.stage-' + cid, 'missing'),
                    'cleanup': 'not performed; references and age require review'})
        return {'dry_run': True, 'checked_at': now(), 'manuscript_id': manuscript_id,
                'candidates': candidates,
                'incomplete': [{'candidate_id': c['candidate_id'], 'reserved_at': c['reserved_at'],
                                'entry': c['file']['state'], 'stage_entry': c['stage_entry'],
                                'cleanup': 'not performed; ownership and age review required'}
                               for c in candidates if not c['stored']]}
    except HTTPException:
        raise
    except (sqlite3.Error, SQLAlchemyError, StorageError):
        raise HTTPException(503, 'Reconciliation unavailable') from None
    finally:
        db.rollback()


def begin(db, credentials, actor_id):
    raw = proofs.begin(db)
    reauthenticate(credentials, db, actor_id)
    proofs.actor(raw, actor_id, 'eic')
    try:
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (schema.MIGRATION_ID,)).fetchone():
            raise RuntimeError('Candidate schema unavailable')
        schema.validate_schema(raw)
    except (sqlite3.Error, RuntimeError):
        raise HTTPException(503, 'Candidate schema unavailable') from None
    return raw


def source_evidence(raw, manuscript_id, round_number, source_id, proof_id):
    row = raw.execute('''SELECT evidence_id FROM source_provenance_evidence WHERE manuscript_id=? AND review_round=?
        AND source_round_file_id=? AND proof_reference=? AND revision=(SELECT MAX(revision)
        FROM source_provenance_evidence WHERE source_round_file_id=?)''',
        (manuscript_id, round_number, source_id, proof_id, source_id)).fetchone()
    if not row:
        raise HTTPException(409, 'Current source evidence unavailable')
    return row[0]


def require_preparation_schema(raw):
    try:
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (preparation_schema.MIGRATION_ID,)).fetchone():
            raise RuntimeError('Preparation provenance unavailable')
        preparation_schema.validate_schema(raw)
    except (sqlite3.Error, RuntimeError):
        raise HTTPException(503, 'Preparation provenance unavailable') from None


def checked_candidate(db, raw, manuscript_id, candidate_id, *, allow_rejected=False):
    row = raw.execute('''SELECT r.review_round,r.source_id,r.proof_id,r.source_evidence_id,r.sha256,
        r.byte_size,r.format,r.artifact_version FROM reviewer_candidate_reservations r
        JOIN reviewer_candidate_publications p ON p.candidate_id=r.candidate_id
        WHERE r.candidate_id=? AND r.manuscript_id=?''', (candidate_id, manuscript_id)).fetchone()
    if not row:
        raise HTTPException(404, 'Candidate unavailable')
    if (raw.execute("SELECT 1 FROM sqlite_master WHERE name='candidate_review_rejections'").fetchone()
            or raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (preparation_schema.MIGRATION_ID,)).fetchone()):
        require_preparation_schema(raw)
        if not allow_rejected and raw.execute('SELECT 1 FROM candidate_review_rejections WHERE candidate_id=?', (candidate_id,)).fetchone():
            raise HTTPException(409, 'Candidate rejected')
    rnd, sid, pid, evidence_id, digest, size, fmt, version = row
    proof = proofs.verify(db, raw, pid, manuscript_id, rnd, sid)
    if digest == proof.sha256 or source_evidence(raw, manuscript_id, rnd, sid, pid) != evidence_id:
        raise HTTPException(409, 'Candidate provenance unavailable')
    with proofs.storage() as private:
        content = private.read_verified(StorageMetadata(candidate_id, digest, size, fmt))
    return row, content


@router.post('/manuscripts/{manuscript_id}/reviewer-candidates', status_code=201)
async def submit_candidate(manuscript_id: int, review_round: int = Form(..., gt=0),
        source_id: int = Form(..., gt=0), artifact_version: int = Form(..., gt=0),
        fmt: str = Form(...), file: UploadFile = File(...), metadata_preparation: str = Form('none'), user: User = Depends(require_role('eic')),
        credentials=Depends(bearer_scheme), db: Session = Depends(get_db)):
    """Store a separately supplied file privately; it is not approved or released."""
    content = await file.read(MAX_MANUSCRIPT_FILE_SIZE + 1)
    candidate_id = uuid4().hex
    try:
        raw = begin(db, credentials, user.user_id)
        if metadata_preparation not in ('none', 'docx-v1'):
            raise HTTPException(400, 'Unsupported metadata preparation')
        if metadata_preparation == 'docx-v1':
            if fmt != 'docx':
                raise HTTPException(400, 'DOCX preparation requires a DOCX candidate')
            require_preparation_schema(raw)
            input_sha256 = hashlib.sha256(content).hexdigest()
            from app.reviewer_candidate_docx import prepare_docx_metadata, PreparationError
            try:
                content = prepare_docx_metadata(content)
            except PreparationError:
                raise HTTPException(409, 'Candidate requires manual document preparation') from None
        bridge = EICSourceEvidenceBridge(db, raw, credentials, user.user_id)
        candidate = bridge.validate_candidate(raw, manuscript_id, review_round, source_id, content, fmt)
        evidence_id = source_evidence(raw, manuscript_id, review_round, source_id, candidate.source_proof_id)
        raw.execute('INSERT INTO reviewer_candidate_reservations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (candidate_id, manuscript_id, review_round, source_id, candidate.source_proof_id, evidence_id,
             artifact_version, candidate.sha256, candidate.byte_size, fmt, user.user_id, now()))
        if metadata_preparation == 'docx-v1':
            source = proofs.verify(db, raw, candidate.source_proof_id, manuscript_id, review_round, source_id)
            raw.execute('INSERT INTO candidate_preparation_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (candidate_id, manuscript_id, review_round, source_id, source.sha256, input_sha256,
                 candidate.sha256, metadata_preparation, user.user_id, now(), 'prepared', 'unverified', 'pending'))
        db.commit()
        with proofs.storage() as private:
            private.publish_reserved(candidate_id, content, fmt)
        raw = begin(db, credentials, user.user_id)
        if metadata_preparation == 'docx-v1':
            require_preparation_schema(raw)
            recorded = raw.execute('''SELECT manuscript_id,review_round,source_id,source_sha256,input_sha256,
                prepared_sha256,method,actor_id FROM candidate_preparation_events WHERE candidate_id=?''', (candidate_id,)).fetchone()
            if recorded != (manuscript_id, review_round, source_id, source.sha256, input_sha256,
                            candidate.sha256, metadata_preparation, user.user_id):
                raise HTTPException(409, 'Preparation provenance changed')
        bridge = EICSourceEvidenceBridge(db, raw, credentials, user.user_id)
        checked = bridge.validate_candidate(raw, manuscript_id, review_round, source_id, content, fmt)
        if checked != candidate or source_evidence(raw, manuscript_id, review_round, source_id, candidate.source_proof_id) != evidence_id:
            raise HTTPException(409, 'Candidate source changed')
        raw.execute('INSERT INTO reviewer_candidate_publications VALUES (?,?)', (candidate_id, now()))
        db.commit()
        return {'candidate_id': candidate_id, 'artifact_version': artifact_version, 'sha256': candidate.sha256,
                'byte_size': candidate.byte_size, 'format': fmt, 'status': 'private_unverified',
                'metadata_preparation': metadata_preparation, 'human_content_review_required': True}
    except HTTPException:
        db.rollback()
        raise
    except reviewer_artifact_service.ArtifactError:
        db.rollback()
        raise HTTPException(409, 'Candidate source or file unavailable') from None
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Candidate version unavailable') from None
    except (sqlite3.Error, SQLAlchemyError, StorageError):
        db.rollback()
        raise HTTPException(503, 'Candidate outcome unavailable; reconcile reservation') from None


@router.get('/manuscripts/{manuscript_id}/reviewer-candidates/{candidate_id}/processing')
def candidate_processing(manuscript_id: int, candidate_id: str, response: Response, user: User = Depends(require_role('eic')),
                         credentials=Depends(bearer_scheme), db: Session = Depends(get_db)):
    """Report recorded preparation and independently recorded human decisions."""
    try:
        raw = begin(db, credentials, user.user_id)
        require_preparation_schema(raw)
        candidate, _ = checked_candidate(db, raw, manuscript_id, candidate_id, allow_rejected=True)
        row = raw.execute('''SELECT e.review_round,e.source_id,e.source_sha256,e.input_sha256,e.prepared_sha256,
          e.method,e.actor_id,e.processed_at,e.result,e.verification_status,e.human_review_status,
          v.verifier_id,v.verified_at,a.approver_id,a.approved_at,x.reviewer_id,x.reviewed_at,x.reason
          FROM candidate_preparation_events e
          LEFT JOIN reviewer_candidate_verifications v ON v.candidate_id=e.candidate_id
          LEFT JOIN reviewer_candidate_approvals a ON a.candidate_id=e.candidate_id
          LEFT JOIN candidate_review_rejections x ON x.candidate_id=e.candidate_id
          WHERE e.candidate_id=? AND e.manuscript_id=?''', (candidate_id, manuscript_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Preparation record unavailable')
        response.headers['Cache-Control'] = 'no-store'
        filename = raw.execute('SELECT verifier_id,verified_at FROM candidate_filename_verifications WHERE candidate_id=?', (candidate_id,)).fetchone()
        return {'candidate_id': candidate_id, 'manuscript_id': manuscript_id, 'review_round': row[0], 'artifact_version': candidate[7],
                'source_id': row[1], 'source_sha256': row[2], 'input_sha256': row[3],
                'prepared_sha256': row[4], 'method': row[5], 'actor_id': row[6], 'processed_at': row[7],
                'result': row[8], 'initial_verification_status': row[9], 'initial_human_review_status': row[10],
                'human_review': {'status': 'rejected' if row[15] is not None else 'verified' if row[11] is not None else 'pending',
                                 'verifier_id': row[11], 'verified_at': row[12],
                                 'rejected_by': row[15], 'rejected_at': row[16], 'reason': row[17]},
                'filename_verification': {'status': 'verified' if filename else 'pending', 'verifier_id': filename[0] if filename else None, 'verified_at': filename[1] if filename else None},
                'approval': {'status': 'approved' if row[13] is not None else 'pending',
                             'approver_id': row[13], 'approved_at': row[14]}}
    except HTTPException:
        raise
    except (sqlite3.Error, SQLAlchemyError, StorageError):
        raise HTTPException(503, 'Preparation record unavailable') from None
    finally:
        db.rollback()


@router.post('/manuscripts/{manuscript_id}/reviewer-candidates/{candidate_id}/reject')
def reject_candidate(manuscript_id: int, candidate_id: str, data: Rejection,
                     user: User = Depends(require_role('eic')), credentials=Depends(bearer_scheme),
                     db: Session = Depends(get_db)):
    """Record an explicit rejection; the candidate cannot later be approved."""
    try:
        raw = begin(db, credentials, user.user_id)
        require_preparation_schema(raw)
        row, _ = checked_candidate(db, raw, manuscript_id, candidate_id)
        raw.execute('INSERT INTO candidate_review_rejections VALUES (?,?,?,?,?,?,?)',
                    (candidate_id, user.user_id, now(), row[4], row[7], 'rejected', data.reason))
        db.commit()
        return {'candidate_id': candidate_id, 'status': 'rejected'}
    except HTTPException:
        db.rollback(); raise
    except sqlite3.IntegrityError:
        db.rollback(); raise HTTPException(409, 'Candidate rejection unavailable') from None
    except (sqlite3.Error, SQLAlchemyError, StorageError):
        db.rollback(); raise HTTPException(503, 'Candidate rejection unavailable') from None


@router.get('/manuscripts/{manuscript_id}/reviewer-candidates/{candidate_id}/content')
def inspect_candidate(manuscript_id: int, candidate_id: str, user: User = Depends(require_role('eic')),
                      credentials=Depends(bearer_scheme), db: Session = Depends(get_db)):
    try:
        raw = begin(db, credentials, user.user_id)
        row, content = checked_candidate(db, raw, manuscript_id, candidate_id, allow_rejected=True)
        return Response(content, media_type='application/octet-stream', headers={
            'Content-Disposition': f'attachment; filename="review-candidate.{row[6]}"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    except StorageError:
        raise HTTPException(409, 'Candidate unavailable') from None
    finally:
        db.rollback()


@router.post('/manuscripts/{manuscript_id}/reviewer-candidates/{candidate_id}/verify')
def verify_candidate(manuscript_id: int, candidate_id: str, checklist: Checklist,
                     user: User = Depends(require_role('eic')), credentials=Depends(bearer_scheme),
                     db: Session = Depends(get_db)):
    """Record the EIC's explicit review of all ten items; not artifact approval."""
    try:
        raw = begin(db, credentials, user.user_id)
        row, _ = checked_candidate(db, raw, manuscript_id, candidate_id)
        if prepared_candidate(raw, candidate_id):
            require_preparation_schema(raw)
            check_context(checklist, row)
            if not checklist.filename_verified:
                raise HTTPException(422, 'Filename verification required')
            raw.execute('INSERT INTO candidate_filename_verifications VALUES (?,?,?,?,?)',
                        (candidate_id, user.user_id, now(), row[4], row[7]))
        raw.execute('INSERT INTO reviewer_candidate_verifications VALUES (?,?,?,?,?,?)',
                    (candidate_id, user.user_id, now(), 'reviewer_anonymity_v1:1111111111', row[4], row[7]))
        db.commit()
        return {'candidate_id': candidate_id, 'status': 'human_verified_not_approved'}
    except HTTPException:
        db.rollback()
        raise
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Candidate already verified or unavailable') from None
    except (sqlite3.Error, SQLAlchemyError, StorageError):
        db.rollback()
        raise HTTPException(503, 'Candidate verification unavailable') from None


@router.post('/manuscripts/{manuscript_id}/reviewer-candidates/{candidate_id}/approve')
def approve_candidate(manuscript_id: int, candidate_id: str, data: ApprovalContext | None = None, user: User = Depends(require_role('eic')),
                      credentials=Depends(bearer_scheme), db: Session = Depends(get_db)):
    """Record artifact approval, but do not bind or distribute it to Reviewers."""
    try:
        raw = begin(db, credentials, user.user_id)
        row, _ = checked_candidate(db, raw, manuscript_id, candidate_id)
        rnd, source_id, proof_id, evidence_id, digest, size, fmt, version = row
        if prepared_candidate(raw, candidate_id):
            require_preparation_schema(raw)
            check_context(data, row)
            if not data.confirmed or not raw.execute('SELECT 1 FROM candidate_filename_verifications WHERE candidate_id=? AND sha256=? AND artifact_version=?', (candidate_id, digest, version)).fetchone():
                raise HTTPException(409, 'Filename verification and explicit confirmation required')
        verification = raw.execute('''SELECT verifier_id FROM reviewer_candidate_verifications
            WHERE candidate_id=? AND checklist='reviewer_anonymity_v1:1111111111'
            AND sha256=? AND artifact_version=?''', (candidate_id, digest, version)).fetchone()
        if not verification:
            raise HTTPException(409, 'Human verification required')
        proofs.actor(raw, verification[0], 'eic')
        if raw.execute('SELECT 1 FROM reviewer_candidate_withdrawals WHERE candidate_id=?', (candidate_id,)).fetchone():
            raise HTTPException(409, 'Candidate withdrawn')
        raw.execute('INSERT OR IGNORE INTO reviewer_candidate_approvals VALUES (?,?,?,?,?)',
                    (candidate_id, user.user_id, now(), digest, version))
        db.commit()
        return {'candidate_id': candidate_id, 'status': 'approved_not_distributed'}
    except HTTPException:
        db.rollback()
        raise
    except reviewer_artifact_service.ArtifactError:
        db.rollback()
        raise HTTPException(409, 'Artifact approval unavailable') from None
    except (sqlite3.Error, SQLAlchemyError, StorageError):
        db.rollback()
        raise HTTPException(503, 'Artifact approval outcome unavailable') from None
    finally:
        db.rollback()


@router.post('/manuscripts/{manuscript_id}/reviewer-candidates/{candidate_id}/withdraw')
def withdraw_candidate(manuscript_id: int, candidate_id: str, user: User = Depends(require_role('eic')),
                       credentials=Depends(bearer_scheme), db: Session = Depends(get_db)):
    """Append a withdrawal event for a previously approved artifact."""
    try:
        raw = begin(db, credentials, user.user_id)
        row = raw.execute('''SELECT r.candidate_id FROM reviewer_candidate_reservations r
            JOIN reviewer_candidate_approvals a ON a.candidate_id=r.candidate_id
            WHERE r.candidate_id=? AND r.manuscript_id=?''', (candidate_id, manuscript_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Artifact unavailable')
        raw.execute('INSERT OR IGNORE INTO reviewer_candidate_withdrawals VALUES (?,?,?)',
                    (candidate_id, user.user_id, now()))
        db.commit()
        return {'candidate_id': candidate_id, 'status': 'withdrawn'}
    except HTTPException:
        db.rollback()
        raise
    except reviewer_artifact_service.ArtifactError:
        db.rollback()
        raise HTTPException(409, 'Artifact withdrawal unavailable') from None
    except (sqlite3.Error, SQLAlchemyError):
        db.rollback()
        raise HTTPException(503, 'Artifact withdrawal outcome unavailable') from None
    finally:
        db.rollback()


@router.post('/manuscripts/{manuscript_id}/reviewer-candidates/{candidate_id}/publish')
def publish_candidate(manuscript_id: int, candidate_id: str, user: User = Depends(require_role('eic')),
                      credentials=Depends(bearer_scheme), db: Session = Depends(get_db)):
    """Publish an approved candidate into the existing artifact evidence ledger."""
    try:
        raw = begin(db, credentials, user.user_id)
        require_publication_schema(raw)
        row, metadata, content = checked_approved(db, raw, candidate_id, manuscript_id)
        rnd, sid, proof_id, evidence_id, digest, _, fmt, version, _, _ = row
        evidence = raw.execute('SELECT revision FROM source_provenance_evidence WHERE evidence_id=?', (evidence_id,)).fetchone()
        if not evidence:
            raise reviewer_artifact_service.ArtifactError('Source evidence unavailable')
        authority = EICAuthority(db, raw, credentials, user.user_id)
        provenance = EICSourceEvidenceBridge(db, raw, credentials, user.user_id)
        storage = GuardedCandidateStorage(db, raw, manuscript_id, candidate_id)
        existing = raw.execute('SELECT artifact_id,state_revision FROM reviewer_artifacts WHERE storage_id=?', (candidate_id,)).fetchone()
        if existing:
            if not raw.execute('SELECT 1 FROM reviewer_publication_audit WHERE artifact_id=?', (existing[0],)).fetchone():
                # A present-time EIC reaffirmation is not a historical publication timestamp.
                raw.execute('INSERT INTO reviewer_publication_audit VALUES (?,?,?,?,?,?,?,?,?)',
                    (existing[0], user.user_id, manuscript_id, rnd, version, digest, proof_id, now(), 'reaffirmed'))
            reviewer_artifact_binding._verify_artifact(raw, provenance, provenance, storage,
                manuscript_id, rnd, sid, existing[0], existing[1], evidence[0])
            db.commit()
            return {'artifact_id': existing[0], 'status': 'published'}
        prepared = reviewer_artifact_service.prepare(raw, user.user_id, authority, provenance, storage,
            manuscript_id, sid, content, fmt, version)
        reviewer_artifact_evidence.approve_with_evidence(raw, user.user_id, authority, provenance, storage,
            prepared.artifact_id, evidence_id, prepared.state_revision, checklist_acknowledged=True)
        raw.execute('INSERT INTO reviewer_publication_audit VALUES (?,?,?,?,?,?,?,?,?)',
            (prepared.artifact_id, user.user_id, manuscript_id, rnd, version, digest, proof_id, now(), 'published'))
        db.commit()
        return {'artifact_id': prepared.artifact_id, 'status': 'published'}
    except HTTPException:
        db.rollback(); raise
    except (reviewer_artifact_service.ArtifactError, StorageError, blind_policy_store.PolicyError):
        db.rollback(); raise HTTPException(409, 'Artifact publication unavailable') from None
    except (sqlite3.Error, SQLAlchemyError):
        db.rollback(); raise HTTPException(503, 'Artifact publication outcome unavailable') from None
    finally:
        db.rollback()


@router.post('/manuscripts/{manuscript_id}/reviewer-candidates/{candidate_id}/bind/{assignment_id}')
def bind_candidate(manuscript_id: int, candidate_id: str, assignment_id: int,
                   user: User = Depends(require_role('eic')), credentials=Depends(bearer_scheme),
                   db: Session = Depends(get_db)):
    try:
        raw = begin(db, credentials, user.user_id)
        row, _, _ = checked_approved(db, raw, candidate_id, manuscript_id)
        rnd, sid, _, evidence_id, _, _, _, _, _, _ = row
        artifact = raw.execute('SELECT artifact_id,state_revision FROM reviewer_artifacts WHERE storage_id=?', (candidate_id,)).fetchone()
        evidence = raw.execute('SELECT revision FROM source_provenance_evidence WHERE evidence_id=?', (evidence_id,)).fetchone()
        policy = blind_policy_store.read_policy(raw, manuscript_id)
        if not artifact or not evidence or not policy or not policy['locked_at']:
            raise reviewer_artifact_service.ArtifactError('Artifact unavailable')
        authority = EICAuthority(db, raw, credentials, user.user_id)
        provenance = EICSourceEvidenceBridge(db, raw, credentials, user.user_id)
        storage = GuardedCandidateStorage(db, raw, manuscript_id, candidate_id)
        existing = raw.execute('SELECT artifact_id FROM reviewer_artifact_assignments WHERE assignment_id=?', (assignment_id,)).fetchone()
        if existing:
            if existing[0] != artifact[0]:
                raise reviewer_artifact_service.ArtifactError('Assignment already bound')
            reviewer_artifact_binding._verify(raw, user.user_id, authority, provenance, provenance, storage,
                assignment_id, artifact[0], reviewer_artifact_binding._editorial_actor,
                expected_policy_revision=policy['revision'], expected_artifact_revision=artifact[1], expected_source_revision=evidence[0])
        else:
            reviewer_artifact_binding.bind(raw, user.user_id, authority, provenance, provenance, storage,
                assignment_id, artifact[0], expected_policy_revision=policy['revision'],
                expected_artifact_revision=artifact[1], expected_source_revision=evidence[0])
        db.commit()
        return {'assignment_id': assignment_id, 'artifact_id': artifact[0], 'status': 'bound'}
    except HTTPException:
        db.rollback(); raise
    except (reviewer_artifact_service.ArtifactError, StorageError, blind_policy_store.PolicyError):
        db.rollback(); raise HTTPException(409, 'Artifact binding unavailable') from None
    except (sqlite3.Error, SQLAlchemyError):
        db.rollback(); raise HTTPException(503, 'Artifact binding outcome unavailable') from None
    finally:
        db.rollback()


@router.post('/manuscripts/{manuscript_id}/reviewer-candidates/{candidate_id}/withdraw-artifact')
def withdraw_published_artifact(manuscript_id: int, candidate_id: str,
        user: User = Depends(require_role('eic')), credentials=Depends(bearer_scheme),
        db: Session = Depends(get_db)):
    """Withdraw the separately published artifact, even after source revocation."""
    try:
        raw = begin(db, credentials, user.user_id)
        artifact = raw.execute('''SELECT a.artifact_id,a.status,a.state_revision FROM reviewer_artifacts a
            JOIN reviewer_candidate_reservations r ON r.candidate_id=a.storage_id
            WHERE a.storage_id=? AND a.manuscript_id=? AND r.manuscript_id=?''',
            (candidate_id, manuscript_id, manuscript_id)).fetchone()
        if not artifact:
            raise HTTPException(404, 'Artifact unavailable')
        if artifact[1] == 'withdrawn':
            return {'artifact_id': artifact[0], 'status': 'withdrawn'}
        if artifact[1] != 'approved':
            raise reviewer_artifact_service.ArtifactError('Artifact unavailable')
        authority = EICAuthority(db, raw, credentials, user.user_id)
        provenance = EICSourceEvidenceBridge(db, raw, credentials, user.user_id)
        reviewer_artifact_service.transition(raw, user.user_id, authority, provenance, None,
                                              artifact[0], 'withdrawn', artifact[2])
        db.commit()
        return {'artifact_id': artifact[0], 'status': 'withdrawn'}
    except HTTPException:
        db.rollback(); raise
    except reviewer_artifact_service.ArtifactError:
        db.rollback(); raise HTTPException(409, 'Artifact withdrawal unavailable') from None
    except (sqlite3.Error, SQLAlchemyError):
        db.rollback(); raise HTTPException(503, 'Artifact withdrawal outcome unavailable') from None
    finally:
        db.rollback()

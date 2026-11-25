"""Authenticated prospective EIC source attestations; no Reviewer release."""
from datetime import datetime, timezone
import sqlite3
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.database import get_db
from app.models import User
from app.routers.users import bearer_scheme, require_role
from app import eic_prospective_proof as proofs
from app.review_files import snapshot_round_file
from app.reviewer_artifact_storage import StorageError
from app import reviewer_artifact_evidence, reviewer_artifact_service
from app.eic_source_evidence_bridge import EICSourceEvidenceBridge
from app.protected_eic_auth import require_current_eic

router = APIRouter(prefix='/eic', tags=['EIC prospective proof'])


class Attestation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    review_round: int = Field(gt=0)
    source_id: int = Field(gt=0)
    identity_removed: StrictBool
    identifying_metadata_removed: StrictBool
    manual_review_completed: StrictBool

    @model_validator(mode='after')
    def all_acknowledged(self):
        if not (self.identity_removed and self.identifying_metadata_removed and self.manual_review_completed):
            raise ValueError('All anonymization attestations are required')
        return self


class Revocation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=1000)


class SourceEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: int = Field(gt=0)
    expected_revision: int = Field(ge=0)


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def reauthenticate(credentials, db, expected_id):
    raw = db.connection().connection.driver_connection
    return require_current_eic(raw, db, credentials, expected_id)


@router.post('/manuscripts/{manuscript_id}/source-provenance-evidence', status_code=status.HTTP_201_CREATED)
def capture_source_evidence(manuscript_id: int, data: SourceEvidenceRequest,
                            user: User = Depends(require_role('eic')),
                            credentials=Depends(bearer_scheme), db: Session = Depends(get_db)):
    """Record verified prospective source lineage; grants no file access."""
    try:
        raw = proofs.begin(db)
        reauthenticate(credentials, db, user.user_id)
        adapter = EICSourceEvidenceBridge(db, raw, credentials, user.user_id)
        evidence_id = reviewer_artifact_evidence.capture_source(
            raw, user.user_id, adapter, adapter, adapter, manuscript_id, data.source_id, data.expected_revision)
        db.commit()
        return {'evidence_id': evidence_id, 'source_id': data.source_id,
                'revision': data.expected_revision + 1}
    except HTTPException:
        db.rollback()
        raise
    except reviewer_artifact_service.ArtifactError:
        db.rollback()
        raise HTTPException(409, 'Source evidence unavailable or stale') from None
    except (sqlite3.Error, SQLAlchemyError):
        db.rollback()
        raise HTTPException(503, 'Source evidence outcome unavailable') from None


@router.post('/manuscripts/{manuscript_id}/prospective-proofs', status_code=status.HTTP_201_CREATED)
def approve_source(manuscript_id: int, data: Attestation,
                   user: User = Depends(require_role('eic')),
                   credentials=Depends(bearer_scheme), db: Session = Depends(get_db)):
    """Attest the current round source prospectively; does not distribute it."""
    key, key_id = proofs.signing_configuration()
    private = proofs.storage()
    actor_id = user.user_id
    storage_id, proof_id = uuid4().hex, uuid4().hex
    try:
        raw = proofs.begin(db)
        reauthenticate(credentials, db, actor_id)
        proofs.actor(raw, actor_id, 'eic')
        manuscript, source, policy = proofs.context(db, raw, manuscript_id, data.review_round, data.source_id)
        if raw.execute('SELECT 1 FROM eic_prospective_proofs WHERE source_id=?', (data.source_id,)).fetchone():
            raise HTTPException(409, 'This source already has an EIC proof')
        snapshot = snapshot_round_file(db, source, manuscript)
        fmt = snapshot.extension.lstrip('.')
        raw.execute('INSERT INTO eic_proof_reservations VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (storage_id, manuscript_id, data.review_round, data.source_id, actor_id,
                     policy['revision'], policy['last_event_id'], snapshot.sha256, len(snapshot.content), fmt, now()))
        db.commit()  # Durable reservation makes a publication interruption reconcilable.
        private.publish_reserved(storage_id, snapshot.content, fmt)
        raw = proofs.begin(db)
        reauthenticate(credentials, db, actor_id)
        proofs.actor(raw, actor_id, 'eic')
        manuscript, source, current = proofs.context(db, raw, manuscript_id, data.review_round, data.source_id)
        if (current['revision'], current['last_event_id']) != (policy['revision'], policy['last_event_id']):
            raise HTTPException(409, 'Review policy changed; proof was not issued')
        fresh = snapshot_round_file(db, source, manuscript)
        if (fresh.sha256, len(fresh.content), fresh.extension) != (snapshot.sha256, len(snapshot.content), snapshot.extension):
            raise HTTPException(409, 'Review source changed; proof was not issued')
        if proofs.signing_configuration() != (key, key_id):
            raise HTTPException(503, 'EIC proof signing configuration changed')
        approved_at = now()
        fields = [proof_id, manuscript_id, data.review_round, data.source_id, actor_id,
                  policy['revision'], policy['last_event_id'], snapshot.sha256, len(snapshot.content), fmt,
                  approved_at, proofs.CHECKLIST, key_id, storage_id]
        raw.execute('INSERT INTO eic_prospective_proofs VALUES (?,?,?,?,?,?,?)',
                    (proof_id, storage_id, data.source_id, proofs.CHECKLIST, key_id, proofs.signature(key, fields), approved_at))
        db.commit()
        return {'proof_id':proof_id, 'manuscript_id':manuscript_id, 'review_round':data.review_round,
                'source_id':data.source_id, 'sha256':snapshot.sha256, 'byte_size':len(snapshot.content),
                'format':fmt, 'approved_at':approved_at, 'status':'active', 'checklist':proofs.CHECKLIST}
    except HTTPException:
        db.rollback()
        raise
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(409, 'This source already has an EIC proof') from None
    except (StorageError, sqlite3.Error, SQLAlchemyError):
        db.rollback()
        raise HTTPException(503, 'Proof outcome unavailable; inspect reservations before retrying') from None
    finally:
        private.close()


@router.get('/manuscripts/{manuscript_id}/prospective-proofs/{proof_id}')
def verify_proof(manuscript_id: int, proof_id: str, review_round: int, source_id: int,
                 user: User = Depends(require_role('eic')), credentials=Depends(bearer_scheme), db: Session = Depends(get_db)):
    try:
        raw = proofs.begin(db)
        reauthenticate(credentials, db, user.user_id)
        proofs.actor(raw, user.user_id, 'eic')
        result = proofs.verify(db, raw, proof_id, manuscript_id, review_round, source_id)
        return {'proof_id':result.proof_id, 'manuscript_id':result.manuscript_id,
                'review_round':result.review_round, 'source_id':result.source_id,
                'sha256':result.sha256, 'byte_size':result.byte_size, 'format':result.format,
                'approved_at':result.approved_at, 'status':'active'}
    finally:
        db.rollback()


@router.post('/manuscripts/{manuscript_id}/prospective-proofs/{proof_id}/revoke')
def revoke_proof(manuscript_id: int, proof_id: str, data: Revocation,
                 user: User = Depends(require_role('eic')), credentials=Depends(bearer_scheme), db: Session = Depends(get_db)):
    if not data.reason.strip():
        raise HTTPException(422, 'Revocation reason required')
    try:
        raw = proofs.begin(db)
        reauthenticate(credentials, db, user.user_id)
        proofs.actor(raw, user.user_id, 'eic')
        row = raw.execute('''SELECT 1 FROM eic_prospective_proofs p JOIN eic_proof_reservations r
            ON r.storage_id=p.storage_id JOIN manuscripts m ON m.manuscript_id=r.manuscript_id
            WHERE p.proof_id=? AND r.manuscript_id=? AND m.status!='draft' ''', (proof_id, manuscript_id)).fetchone()
        if not row:
            raise HTTPException(404, 'EIC proof unavailable')
        raw.execute('INSERT OR IGNORE INTO eic_proof_revocations VALUES (?,?,?,?)',
                    (proof_id, user.user_id, data.reason.strip(), now()))
        db.commit()
        return {'proof_id':proof_id, 'status':'revoked'}
    except HTTPException:
        db.rollback()
        raise
    except (sqlite3.Error, SQLAlchemyError):
        db.rollback()
        raise HTTPException(503, 'Revocation outcome unavailable') from None

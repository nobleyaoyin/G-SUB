"""Prospective EIC source attestations; this module does not release documents.

Proofs are created only by the authenticated router. Storage IDs and proof IDs
are server generated. A proof is not a claim of independent anonymization and
must not be used as a Reviewer download authorization by itself.
"""
import hashlib
import hmac
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import SessionTransactionOrigin
from sqlalchemy.exc import SQLAlchemyError
from app import blind_policy_store, lifecycle_integrity
from app.config import DATA_ROOT
from app.models import Manuscript, ReviewRoundFile
from app.review_files import snapshot_round_file
from app.routers.users import get_current_user
from app.reviewer_artifact_storage import ArtifactStorage, StorageError, StorageMetadata

schema = import_module('migrations.022_eic_prospective_proof')
CHECKLIST = 'eic_anonymization_v1'
_ID = re.compile(r'^[0-9a-f]{32}$')
_KEY_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_KEY = re.compile(r'^[0-9a-f]{64}$')


@dataclass(frozen=True)
class VerifiedProof:
    proof_id: str
    manuscript_id: int
    review_round: int
    source_id: int
    actor_id: int
    sha256: str
    byte_size: int
    format: str
    approved_at: str
    content: bytes


def signing_configuration():
    key, key_id = os.environ.get('GSUB_EIC_PROOF_SECRET', ''), os.environ.get('GSUB_EIC_PROOF_KEY_ID', '')
    if not _KEY.fullmatch(key) or len(set(key)) < 12 or not _KEY_ID.fullmatch(key_id):
        raise HTTPException(503, 'EIC proof signing configuration unavailable')
    return bytes.fromhex(key), key_id


def storage():
    root = os.environ.get('GSUB_EIC_PROOF_PRIVATE_ROOT', '')
    try:
        path = Path(root)
        if not root or not path.is_absolute() or not path.is_dir() or path.resolve() != path:
            raise ValueError('Invalid private root')
        source_root = DATA_ROOT.resolve()
        if path == source_root or path.is_relative_to(source_root) or source_root.is_relative_to(path):
            raise ValueError('Private root overlaps application data')
        return ArtifactStorage(path)
    except (StorageError, OSError, ValueError):
        raise HTTPException(503, 'Private EIC proof storage unavailable') from None


def begin(db):
    tx = db.get_transaction()
    if db.new or db.dirty or db.deleted or db.in_nested_transaction() or (tx is not None and tx.origin is not SessionTransactionOrigin.AUTOBEGIN):
        raise HTTPException(503, 'A fresh EIC proof transaction is required')
    connection = db.connection()
    raw = connection.connection.driver_connection
    if connection.dialect.name != 'sqlite' or raw.in_transaction:
        raise HTTPException(503, 'A fresh EIC proof transaction is required')
    try:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        if not raw.execute('PRAGMA foreign_keys').fetchone()[0]:
            raise RuntimeError('Foreign keys unavailable')
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (schema.MIGRATION_ID,)).fetchone():
            raise RuntimeError('Proof schema unavailable')
        schema.validate_schema(raw)
        return raw
    except (sqlite3.Error, SQLAlchemyError, RuntimeError):
        db.rollback()
        raise HTTPException(503, 'EIC proof schema unavailable') from None


def actor(raw, actor_id, role):
    try:
        lifecycle_integrity.active_actor(raw, actor_id, role)
    except lifecycle_integrity.LifecycleIntegrityError:
        raise HTTPException(403, 'EIC proof authority unavailable') from None


def context(db, raw, manuscript_id, review_round, source_id):
    manuscript = db.get(Manuscript, manuscript_id, populate_existing=True)
    source = db.get(ReviewRoundFile, source_id, populate_existing=True)
    if not manuscript or not source or manuscript.status not in ('ready_for_peer_review', 'revised') or manuscript.review_round != review_round or source.manuscript_id != manuscript_id or source.review_round != review_round:
        raise HTTPException(404, 'Review source unavailable')
    try:
        policy = blind_policy_store.read_policy(raw, manuscript_id)
        if not policy or policy['mode'] != 'double_blind':
            raise HTTPException(409, 'Double Blind policy unavailable')
    except blind_policy_store.PolicyError:
        raise HTTPException(503, 'Review policy unavailable') from None
    return manuscript, source, policy


def signature(key, fields):
    encoded = json.dumps(fields, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    return hmac.new(key, encoded, hashlib.sha256).hexdigest()


def policy_still_valid(raw, policy, revision, event_id):
    recorded = raw.execute('SELECT mode FROM blind_policy_events WHERE manuscript_id=? AND revision=? AND event_id=?',
                           (policy['manuscript_id'], revision, event_id)).fetchone()
    return recorded == ('double_blind',) and (policy['revision'] == revision or (
        policy['revision'] == revision + 1 and policy['locked_at'] is not None and policy['mode'] == 'double_blind'))


def verify(db, raw, proof_id, manuscript_id, review_round, source_id):
    if not isinstance(proof_id, str) or not _ID.fullmatch(proof_id):
        raise HTTPException(404, 'EIC proof unavailable')
    key, key_id = signing_configuration()
    row = raw.execute('''SELECT p.proof_id,r.manuscript_id,r.review_round,r.source_id,r.actor_id,
        r.policy_revision,r.policy_event_id,r.sha256,r.byte_size,r.format,p.approved_at,p.checklist,
        p.key_id,p.signature,r.storage_id FROM eic_prospective_proofs p
        JOIN eic_proof_reservations r ON r.storage_id=p.storage_id
        WHERE p.proof_id=? AND NOT EXISTS (SELECT 1 FROM eic_proof_revocations x WHERE x.proof_id=p.proof_id)''', (proof_id,)).fetchone()
    if not row or row[1:4] != (manuscript_id, review_round, source_id) or row[12] != key_id:
        raise HTTPException(404, 'EIC proof unavailable')
    if not hmac.compare_digest(signature(key, list(row[:13]) + [row[14]]), row[13]):
        raise HTTPException(409, 'EIC proof integrity unavailable')
    actor(raw, row[4], 'eic')
    manuscript, source, policy = context(db, raw, manuscript_id, review_round, source_id)
    if not policy_still_valid(raw, policy, row[5], row[6]):
        raise HTTPException(409, 'EIC proof policy changed')
    snap = snapshot_round_file(db, source, manuscript)
    if (snap.sha256, len(snap.content), snap.extension.lstrip('.')) != (row[7], row[8], row[9]):
        raise HTTPException(409, 'EIC proof source changed')
    try:
        with storage() as private:
            content = private.read_verified(StorageMetadata(row[14], row[7], row[8], row[9]))
    except StorageError:
        raise HTTPException(409, 'EIC proof snapshot unavailable') from None
    return VerifiedProof(row[0], row[1], row[2], row[3], row[4], row[7], row[8], row[9], row[10], content)


def verify_for_reviewer(db, raw, proof_id, credentials, assignment_id):
    """Authenticate and verify current assignment; this is not an HTTP release."""
    if not isinstance(credentials, HTTPAuthorizationCredentials):
        raise HTTPException(401, 'Authentication required')
    user = get_current_user(credentials, db)
    reviewer_id = user.user_id
    actor(raw, reviewer_id, 'reviewer')
    row = raw.execute('''SELECT a.manuscript_id,a.review_round,f.round_file_id FROM review_assignments a
      JOIN manuscripts m ON m.manuscript_id=a.manuscript_id
      JOIN reviewer_invitations i ON i.assignment_id=a.assignment_id
      JOIN review_assignment_files f ON f.assignment_id=a.assignment_id
      WHERE a.assignment_id=? AND a.reviewer_id=? AND a.status='assigned' AND i.status='accepted'
      AND a.review_round=m.review_round AND m.status IN ('ready_for_peer_review','revised')
      AND NOT EXISTS (SELECT 1 FROM reviewer_invitation_invalidations x WHERE x.assignment_id=a.assignment_id)''',
      (assignment_id, reviewer_id)).fetchone()
    if not row:
        raise HTTPException(404, 'EIC proof unavailable')
    return verify(db, raw, proof_id, *row)

"""Authenticated source-evidence bridge tests using the Batch 38 disposable fixture."""
import sqlite3
from datetime import datetime, timezone
import hashlib
from unittest.mock import patch

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from test_batch38_eic_proof import fixture
from app import models
from app import eic_prospective_proof as proofs, reviewer_artifact_service
from app import reviewer_artifact_evidence
from app.eic_source_evidence_bridge import EICSourceEvidenceBridge
from app.security import create_access_token


def record_synthetic_initial_approval(f, chief):
    submission = f.db.query(models.InitialEditingSubmission).filter_by(manuscript_id=f.mid).one()
    submission.eic_approved_by = chief.user_id
    submission.eic_reviewed_at = datetime.now(timezone.utc)
    confirmation = f.db.query(models.PreReviewConfirmation).filter_by(manuscript_id=f.mid).one()
    confirmation.confirmed_at = datetime.now(timezone.utc)
    f.db.commit()


def test_authenticated_eic_links_real_proof_and_revocation_fails_closed(fixture):
    f, chief, headers, aid, source_id, payload, _ = fixture
    record_synthetic_initial_approval(f, chief)
    proofs = f'/eic/manuscripts/{f.mid}/prospective-proofs'
    evidence = f'/eic/manuscripts/{f.mid}/source-provenance-evidence'
    request = {'source_id': source_id, 'expected_revision': 0}
    assert f.client.post(evidence, headers=headers(f.reviewer), json=request).status_code == 403
    assert f.client.post(evidence, headers=headers(f.author), json=request).status_code == 403
    assert f.client.post(evidence, headers=headers(chief), json=request).status_code == 409
    result = f.client.post(proofs, headers=headers(chief), json=payload)
    assert result.status_code == 201, result.text
    proof_id = result.json()['proof_id']
    linked = f.client.post(evidence, headers=headers(chief), json=request)
    assert linked.status_code == 201, linked.text
    with sqlite3.connect(f.db_path) as db:
        row = db.execute('SELECT proof_reference,source_round_file_id,source_sha256 FROM source_provenance_evidence WHERE evidence_id=?',
                         (linked.json()['evidence_id'],)).fetchone()
    assert row == (proof_id, source_id, result.json()['sha256'])
    assert f.client.post(evidence, headers=headers(chief), json=request).status_code == 409
    assert f.client.post(evidence, headers=headers(chief), json={'source_id': 999999, 'expected_revision': 0}).status_code == 409
    assert f.client.post(f'{proofs}/{proof_id}/revoke', headers=headers(chief), json={'reason': 'synthetic'}).status_code == 200
    assert f.client.post(evidence, headers=headers(chief), json={'source_id': source_id, 'expected_revision': 1}).status_code == 409
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)).status_code == 409


def test_changed_snapshot_cannot_be_captured(fixture):
    f, chief, headers, _, source_id, payload, private = fixture
    record_synthetic_initial_approval(f, chief)
    proofs = f'/eic/manuscripts/{f.mid}/prospective-proofs'
    result = f.client.post(proofs, headers=headers(chief), json=payload)
    assert result.status_code == 201, result.text
    with sqlite3.connect(f.db_path) as db:
        storage_id = db.execute('SELECT storage_id FROM eic_prospective_proofs WHERE proof_id=?',
                                (result.json()['proof_id'],)).fetchone()[0]
    path = private / storage_id
    path.chmod(0o600)
    path.write_bytes(b'%PDF-tampered')
    path.chmod(0o400)
    response = f.client.post(f'/eic/manuscripts/{f.mid}/source-provenance-evidence', headers=headers(chief),
                             json={'source_id': source_id, 'expected_revision': 0})
    assert response.status_code == 409
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM source_provenance_evidence').fetchone()[0] == 0


def test_candidate_boundary_checks_distinct_bytes_without_approving(fixture):
    f, chief, headers, _, source_id, payload, _ = fixture
    record_synthetic_initial_approval(f, chief)
    result = f.client.post(f'/eic/manuscripts/{f.mid}/prospective-proofs', headers=headers(chief), json=payload)
    assert result.status_code == 201, result.text
    f.db.rollback()
    raw = proofs.begin(f.db)
    credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=create_access_token(chief.user_id, lifecycle_generation=1))
    bridge = EICSourceEvidenceBridge(f.db, raw, credentials, chief.user_id)
    with pytest.raises(reviewer_artifact_service.ArtifactError):
        bridge.validate_candidate(raw, f.mid, 1, source_id, b'%PDF-first', 'pdf')
    candidate = bridge.validate_candidate(raw, f.mid, 1, source_id, b'%PDF-distinct', 'pdf')
    assert candidate.sha256 == hashlib.sha256(b'%PDF-distinct').hexdigest()
    assert candidate.source_proof_id == result.json()['proof_id']
    assert raw.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0] == 0
    f.db.rollback()


def test_failed_evidence_transaction_rolls_back(fixture):
    f, chief, headers, _, source_id, payload, _ = fixture
    record_synthetic_initial_approval(f, chief)
    issued = f.client.post(f'/eic/manuscripts/{f.mid}/prospective-proofs', headers=headers(chief), json=payload)
    assert issued.status_code == 201, issued.text
    capture = reviewer_artifact_evidence.capture_source

    def fail_after_insert(*args, **kwargs):
        capture(*args, **kwargs)
        raise sqlite3.OperationalError('synthetic failure')

    with patch('app.reviewer_artifact_evidence.capture_source', side_effect=fail_after_insert):
        response = f.client.post(f'/eic/manuscripts/{f.mid}/source-provenance-evidence', headers=headers(chief),
                                 json={'source_id': source_id, 'expected_revision': 0})
    assert response.status_code == 503
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM source_provenance_evidence').fetchone()[0] == 0

"""Prospective EIC proof HTTP tests against disposable database and private files."""
import hashlib
import importlib
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from app import models
from app import eic_prospective_proof as proofs
from app.database import get_db
from app.routers.users import get_current_user
from app.security import create_access_token
import app.main as main
import test_reviewer_download as fixtures

migration = importlib.import_module('migrations.022_eic_prospective_proof')


@pytest.fixture
def fixture(monkeypatch, request):
    f = fixtures.ReviewerDownloadsTest(methodName='test_first_round_binding_and_access')
    f.setUp()
    try:
        chief = models.User(name='Synthetic EIC', email='batch38@example.com', password_hash='x', role='eic')
        f.db.add(chief); f.db.commit()
        stamp = '2026-01-01T00:00:00.000000Z'
        for actor in (chief, f.reviewer, f.other):
            eid = f'batch38-active-{actor.user_id}'
            f.db.add(models.AccountLifecycleEvent(event_id=eid, user_id=actor.user_id, sequence=1,
                from_state=None, to_state='active', auth_generation=1, actor_user_id=chief.user_id,
                occurred_at=stamp, reason_code='initial_enrollment'))
        f.db.flush()
        for actor in (chief, f.reviewer, f.other):
            eid = f'batch38-active-{actor.user_id}'
            f.db.add(models.AccountLifecycle(user_id=actor.user_id, state='active', sequence=1,
                                            auth_generation=1, last_event_id=eid))
        f.db.commit()
        migration.migrate(f.db_path); migration.migrate(f.db_path)
        private = f.root / 'eic-private'; private.mkdir(mode=0o700)
        monkeypatch.setenv('GSUB_EIC_PROOF_PRIVATE_ROOT', str(private))
        monkeypatch.setenv('GSUB_EIC_PROOF_SECRET', '0123456789abcdef' * 4)
        monkeypatch.setenv('GSUB_EIC_PROOF_KEY_ID', 'synthetic-v1')
        main.app.dependency_overrides.pop(get_current_user, None)
        def headers(user):
            with sqlite3.connect(f.db_path) as raw:
                state = raw.execute('SELECT auth_generation FROM account_lifecycle WHERE user_id=? AND state=\'active\'', (user.user_id,)).fetchone()
            generation = state[0] if user.role == 'eic' and state else None
            return {'Authorization': f'Bearer {create_access_token(user.user_id, lifecycle_generation=generation)}'}
        mode = getattr(request, 'param', 'double_blind')
        selected = f.client.put(f'/eic/manuscripts/{f.mid}/review-policy', headers=headers(chief), json={'mode':mode})
        assert selected.status_code == 200, selected.text
        assignment = f.client.post('/assignments/', headers=headers(f.editor), json={'manuscript_id':f.mid,'reviewer_id':f.reviewer.user_id,'review_round':1})
        assert assignment.status_code == 201, assignment.text
        aid = assignment.json()['assignment_id']
        response = f.client.post(f'/assignments/{aid}/invitation-response', headers=headers(f.reviewer), json={'decision':'accept'})
        assert response.status_code == 200, response.text
        f.db.expire_all()
        binding = f.db.get(models.ReviewAssignmentFile, aid)
        source_id = binding.round_file_id
        f.db.rollback()
        def isolated_session():
            with f.Session() as session:
                yield session
        main.app.dependency_overrides[get_db] = isolated_session
        payload = {'review_round':1,'source_id':source_id,'identity_removed':True,
                   'identifying_metadata_removed':True,'manual_review_completed':True}
        yield f, chief, headers, aid, source_id, payload, private
    finally:
        f.tearDown()


def test_bearer_eic_issues_persistent_exact_proof_and_revokes(fixture):
    f, chief, headers, aid, source_id, payload, private = fixture
    endpoint = f'/eic/manuscripts/{f.mid}/prospective-proofs'
    assert f.client.post(endpoint, headers=headers(f.author), json=payload).status_code == 403
    assert f.client.post(endpoint, headers=headers(f.reviewer), json=payload).status_code == 403
    assert f.client.post(endpoint, headers=headers(f.editor), json=payload).status_code == 403
    assert f.client.post(endpoint, json=payload).status_code == 401
    assert f.client.post(endpoint, headers=headers(chief), json={**payload,'manual_review_completed':False}).status_code == 422
    assert f.client.post(endpoint, headers=headers(chief), json={k:v for k,v in payload.items() if k != 'identity_removed'}).status_code == 422
    assert f.client.post(endpoint, headers=headers(chief), json={**payload,'proof_id':'client-supplied'}).status_code == 422
    assert f.client.post(endpoint, headers=headers(chief), json={**payload,'review_round':2}).status_code == 404
    assert f.client.post(endpoint, headers=headers(chief), json={**payload,'source_id':999999}).status_code == 404
    assert f.client.post('/eic/manuscripts/999999/prospective-proofs', headers=headers(chief), json=payload).status_code == 404
    issued = f.client.post(endpoint, headers=headers(chief), json=payload)
    assert issued.status_code == 201, issued.text
    body = issued.json(); proof_id = body['proof_id']
    assert body['sha256'] == hashlib.sha256(b'%PDF-first').hexdigest()
    assert body['source_id'] == source_id and body['review_round'] == 1 and body['byte_size'] == len(b'%PDF-first')
    assert f.client.post(endpoint, headers=headers(chief), json=payload).status_code == 409
    url = f'{endpoint}/{proof_id}?review_round=1&source_id={source_id}'
    assert f.client.get(url, headers=headers(chief)).status_code == 200
    assert f.client.get(url, headers=headers(f.reviewer)).status_code == 403
    f.db.rollback()
    raw = proofs.begin(f.db)
    reviewer_credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=create_access_token(f.reviewer.user_id))
    other_credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=create_access_token(f.other.user_id))
    checked = proofs.verify_for_reviewer(f.db, raw, proof_id, reviewer_credentials, aid)
    assert checked.content == b'%PDF-first'
    with pytest.raises(HTTPException):
        proofs.verify_for_reviewer(f.db, raw, proof_id, other_credentials, aid)
    with pytest.raises(HTTPException):
        proofs.verify_for_reviewer(f.db, raw, proof_id, f.reviewer.user_id, aid)
    f.db.rollback()
    # The existing Reviewer HTTP endpoint remains independently fail-closed.
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)).status_code == 409
    f.db.rollback()
    assert f.client.post(f'{endpoint}/{proof_id}/revoke', headers=headers(f.reviewer), json={'reason':'Synthetic'}).status_code == 403
    revoke = f.client.post(f'{endpoint}/{proof_id}/revoke', headers=headers(chief), json={'reason':'Synthetic'})
    assert revoke.status_code == 200
    assert f.client.post(f'{endpoint}/{proof_id}/revoke', headers=headers(chief), json={'reason':'Retry'}).status_code == 200
    assert f.client.get(url, headers=headers(chief)).status_code == 404
    f.db.rollback()
    raw = proofs.begin(f.db)
    with pytest.raises(HTTPException) as revoked:
        proofs.verify_for_reviewer(f.db, raw, proof_id, reviewer_credentials, aid)
    assert revoked.value.status_code == 404
    f.db.rollback()
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM eic_proof_revocations WHERE proof_id=?',(proof_id,)).fetchone()[0] == 1


def test_changed_source_and_snapshot_are_rejected(fixture):
    f, chief, headers, _, source_id, payload, private = fixture
    endpoint = f'/eic/manuscripts/{f.mid}/prospective-proofs'
    issued = f.client.post(endpoint, headers=headers(chief), json=payload)
    assert issued.status_code == 201, issued.text
    proof_id = issued.json()['proof_id']
    url = f'{endpoint}/{proof_id}?review_round=1&source_id={source_id}'
    assert f.client.get(url, headers=headers(chief)).status_code == 200
    source = f.root / f.pdf
    source.write_bytes(b'%PDF-altered')
    assert f.client.get(url, headers=headers(chief)).status_code == 409
    source.write_bytes(b'%PDF-first')
    with sqlite3.connect(f.db_path) as db:
        storage_id = db.execute('SELECT storage_id FROM eic_prospective_proofs WHERE proof_id=?',(proof_id,)).fetchone()[0]
    path = private / storage_id
    path.chmod(0o600); path.write_bytes(b'%PDF-broken'); path.chmod(0o400)
    assert f.client.get(url, headers=headers(chief)).status_code == 409


def test_storage_failure_has_no_issued_proof(fixture):
    f, chief, headers, _, _, payload, _ = fixture
    endpoint = f'/eic/manuscripts/{f.mid}/prospective-proofs'
    with patch('app.reviewer_artifact_storage.ArtifactStorage.publish_reserved', side_effect=proofs.StorageError('synthetic')):
        response = f.client.post(endpoint, headers=headers(chief), json=payload)
    assert response.status_code == 503
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM eic_prospective_proofs').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM eic_proof_reservations').fetchone()[0] == 1


@pytest.mark.parametrize('fixture', ['single_blind'], indirect=True)
def test_single_blind_policy_cannot_issue_double_blind_proof(fixture):
    f, chief, headers, _, _, payload, _ = fixture
    result = f.client.post(f'/eic/manuscripts/{f.mid}/prospective-proofs', headers=headers(chief), json=payload)
    assert result.status_code == 409
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM eic_prospective_proofs').fetchone()[0] == 0


def test_signature_tamper_and_database_immutability(fixture, monkeypatch):
    f, chief, headers, _, source_id, payload, _ = fixture
    endpoint = f'/eic/manuscripts/{f.mid}/prospective-proofs'
    result = f.client.post(endpoint, headers=headers(chief), json=payload)
    assert result.status_code == 201, result.text
    proof_id = result.json()['proof_id']
    url = f'{endpoint}/{proof_id}?review_round=1&source_id={source_id}'
    assert f.client.get(url, headers=headers(chief)).status_code == 200
    with sqlite3.connect(f.db_path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE eic_prospective_proofs SET signature=? WHERE proof_id=?", ('0'*64, proof_id))
        db.rollback()
    monkeypatch.setenv('GSUB_EIC_PROOF_SECRET', 'fedcba9876543210' * 4)
    assert f.client.get(url, headers=headers(chief)).status_code == 409
    monkeypatch.setenv('GSUB_EIC_PROOF_SECRET', '0123456789abcdef' * 4)
    assert f.client.get(url, headers=headers(chief)).status_code == 200


def test_database_failure_leaves_reservation_but_no_proof(fixture):
    f, chief, headers, _, _, payload, private = fixture
    endpoint = f'/eic/manuscripts/{f.mid}/prospective-proofs'
    with patch('app.eic_prospective_proof.signature', side_effect=sqlite3.OperationalError('synthetic')):
        result = f.client.post(endpoint, headers=headers(chief), json=payload)
    assert result.status_code == 503
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM eic_prospective_proofs').fetchone()[0] == 0
        reservation = db.execute('SELECT storage_id FROM eic_proof_reservations').fetchone()[0]
    assert (private / reservation).is_file()


def test_concurrent_issuance_never_creates_two_proofs(fixture):
    f, chief, headers, _, source_id, payload, _ = fixture
    endpoint = f'/eic/manuscripts/{f.mid}/prospective-proofs'
    auth = headers(chief)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: f.client.post(endpoint, headers=auth, json=payload), range(2)))
    assert sorted(r.status_code for r in results) in ([201, 409], [201, 503])
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM eic_prospective_proofs WHERE source_id=?', (source_id,)).fetchone()[0] == 1


def test_revocation_does_not_affect_another_manuscript_reviewer(fixture):
    f, chief, headers, _, _, payload, _ = fixture
    first_endpoint = f'/eic/manuscripts/{f.mid}/prospective-proofs'
    first = f.client.post(first_endpoint, headers=headers(chief), json=payload)
    assert first.status_code == 201, first.text
    with f.Session() as db:
        manuscript = models.Manuscript(title='Other synthetic paper', abstract='Synthetic', author_id=f.author.user_id,
                                       status='ready_for_peer_review', review_round=1)
        db.add(manuscript); db.flush()
        mid = manuscript.manuscript_id
        path = f.write(f'uploads/initial_editing/{mid}/other.pdf', b'%PDF-other')
        submission = models.InitialEditingSubmission(manuscript_id=mid, editor_id=f.editor.user_id, file_path=path,
            comments='Synthetic', status='eic_approved', eic_approved_by=chief.user_id)
        db.add(submission); db.flush()
        db.add(models.PreReviewConfirmation(manuscript_id=mid, submission_id=submission.submission_id,
            author_id=f.author.user_id, file_path=path, decision='confirm', comments='Synthetic'))
        db.add(models.InitialEditorInvitation(manuscript_id=mid, editor_id=f.editor.user_id,
            invited_by=chief.user_id, status='accepted'))
        db.commit()
    selected = f.client.put(f'/eic/manuscripts/{mid}/review-policy', headers=headers(chief), json={'mode':'double_blind'})
    assert selected.status_code == 200, selected.text
    assignment = f.client.post('/assignments/', headers=headers(f.editor),
                               json={'manuscript_id':mid,'reviewer_id':f.other.user_id,'review_round':1})
    assert assignment.status_code == 201, assignment.text
    aid = assignment.json()['assignment_id']
    assert f.client.post(f'/assignments/{aid}/invitation-response', headers=headers(f.other), json={'decision':'accept'}).status_code == 200
    with f.Session() as db:
        source_id = db.get(models.ReviewAssignmentFile, aid).round_file_id
    second_payload = {**payload, 'source_id':source_id}
    second = f.client.post(f'/eic/manuscripts/{mid}/prospective-proofs', headers=headers(chief), json=second_payload)
    assert second.status_code == 201, second.text
    assert f.client.post(f"{first_endpoint}/{first.json()['proof_id']}/revoke", headers=headers(chief), json={'reason':'Synthetic'}).status_code == 200
    with f.Session() as db:
        raw = proofs.begin(db)
        credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=create_access_token(f.other.user_id))
        verified = proofs.verify_for_reviewer(db, raw, second.json()['proof_id'], credentials, aid)
        assert verified.content == b'%PDF-other'
        db.rollback()


def test_missing_signing_key_does_not_reserve_or_issue(fixture, monkeypatch):
    f, chief, headers, _, _, payload, _ = fixture
    monkeypatch.delenv('GSUB_EIC_PROOF_SECRET')
    result = f.client.post(f'/eic/manuscripts/{f.mid}/prospective-proofs', headers=headers(chief), json=payload)
    assert result.status_code == 503
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM eic_proof_reservations').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM eic_prospective_proofs').fetchone()[0] == 0

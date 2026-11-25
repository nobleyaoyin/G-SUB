"""Private candidate intake tests against synthetic disposable data only."""
from importlib import import_module
import sqlite3
from unittest.mock import patch

from test_batch38_eic_proof import fixture
from test_batch39_source_evidence import record_synthetic_initial_approval
from app.reviewer_artifact_storage import StorageError
from app.routers import eic_reviewer_candidates

migration = import_module('migrations.023_reviewer_candidate_intake')
CHECKS = {key: True for key in ('author_names', 'affiliations', 'contact_information',
    'document_metadata', 'word_comments', 'revision_history', 'headers_footers',
    'hidden_text', 'figures_supplements', 'acknowledgements_references')}


def ready(fixture):
    f, chief, headers, aid, sid, payload, private = fixture
    record_synthetic_initial_approval(f, chief)
    migration.migrate(f.db_path)
    migration.migrate(f.db_path)
    import_module('migrations.024_reviewer_publication_audit').migrate(f.db_path)
    import_module('migrations.024_reviewer_publication_audit').migrate(f.db_path)
    issued = f.client.post(f'/eic/manuscripts/{f.mid}/prospective-proofs', headers=headers(chief), json=payload)
    assert issued.status_code == 201, issued.text
    evidence = f.client.post(f'/eic/manuscripts/{f.mid}/source-provenance-evidence', headers=headers(chief),
                             json={'source_id': sid, 'expected_revision': 0})
    assert evidence.status_code == 201, evidence.text
    return f, chief, headers, aid, sid, issued.json()['proof_id'], private


def submit(f, chief, headers, sid, content=b'%PDF-anonymized-candidate', version=1):
    return f.client.post(f'/eic/manuscripts/{f.mid}/reviewer-candidates', headers=headers(chief),
        data={'review_round': 1, 'source_id': sid, 'artifact_version': version, 'fmt': 'pdf'},
        files={'file': ('supplied-name.pdf', content, 'application/pdf')})


def test_real_eic_private_upload_and_explicit_human_check(fixture):
    f, chief, headers, aid, sid, proof_id, private = ready(fixture)
    assert submit(f, chief, headers, sid, b'%PDF-first').status_code == 409
    uploaded = submit(f, chief, headers, sid)
    assert uploaded.status_code == 201, uploaded.text
    candidate = uploaded.json()['candidate_id']
    assert uploaded.json()['status'] == 'private_unverified'
    endpoint = f'/eic/manuscripts/{f.mid}/reviewer-candidates/{candidate}'
    assert f.client.get(endpoint + '/content', headers=headers(f.reviewer)).status_code == 403
    inspected = f.client.get(endpoint + '/content', headers=headers(chief))
    assert inspected.status_code == 200 and inspected.content == b'%PDF-anonymized-candidate'
    assert 'review-candidate.pdf' in inspected.headers['content-disposition']
    assert f.client.post(endpoint + '/verify', headers=headers(chief), json={**CHECKS, 'author_names': False}).status_code == 422
    assert f.client.post(endpoint + '/verify', headers=headers(f.author), json=CHECKS).status_code == 403
    assert f.client.post(endpoint + '/approve', headers=headers(chief)).status_code == 409
    verified = f.client.post(endpoint + '/verify', headers=headers(chief), json=CHECKS)
    assert verified.status_code == 200 and verified.json()['status'] == 'human_verified_not_approved'
    assert f.client.post(endpoint + '/verify', headers=headers(chief), json=CHECKS).status_code == 409
    assert f.client.post(endpoint + '/approve', headers=headers(f.reviewer)).status_code == 403
    approved = f.client.post(endpoint + '/approve', headers=headers(chief))
    assert approved.status_code == 200, approved.text
    assert approved.json()['status'] == 'approved_not_distributed'
    assert f.client.post(endpoint + '/approve', headers=headers(chief)).json() == approved.json()
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)).status_code == 409
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT checklist FROM reviewer_candidate_verifications WHERE candidate_id=?', (candidate,)).fetchone()[0] == 'reviewer_anonymity_v1:1111111111'
        assert db.execute('SELECT candidate_id FROM reviewer_candidate_approvals').fetchone() == (candidate,)
        assert db.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0] == 0
    assert f.client.post(f'/eic/manuscripts/{f.mid}/prospective-proofs/{proof_id}/revoke', headers=headers(chief), json={'reason':'synthetic'}).status_code == 200
    assert f.client.get(endpoint + '/content', headers=headers(chief)).status_code == 404
    assert f.client.post(endpoint + '/withdraw', headers=headers(f.reviewer)).status_code == 403
    withdrawn = f.client.post(endpoint + '/withdraw', headers=headers(chief))
    assert withdrawn.status_code == 200 and withdrawn.json()['status'] == 'withdrawn'
    assert f.client.post(endpoint + '/withdraw', headers=headers(chief)).json() == withdrawn.json()
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM reviewer_candidate_withdrawals').fetchone()[0] == 1


def test_failed_storage_keeps_reservation_without_available_candidate(fixture):
    f, chief, headers, _, sid, _, _ = ready(fixture)
    with patch('app.reviewer_artifact_storage.ArtifactStorage.publish_reserved', side_effect=StorageError('synthetic')):
        response = submit(f, chief, headers, sid)
    assert response.status_code == 503
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM reviewer_candidate_reservations').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM reviewer_candidate_publications').fetchone()[0] == 0


def test_changed_private_candidate_blocks_verification_and_approval(fixture):
    f, chief, headers, _, sid, _, private = ready(fixture)
    uploaded = submit(f, chief, headers, sid)
    assert uploaded.status_code == 201
    candidate = uploaded.json()['candidate_id']
    endpoint = f'/eic/manuscripts/{f.mid}/reviewer-candidates/{candidate}'
    assert f.client.post(endpoint + '/verify', headers=headers(chief), json=CHECKS).status_code == 200
    path = private / candidate
    path.chmod(0o600)
    path.write_bytes(b'%PDF-replaced')
    path.chmod(0o400)
    assert f.client.post(endpoint + '/approve', headers=headers(chief)).status_code == 503
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0] == 0


def test_database_failure_after_storage_leaves_only_reservation(fixture):
    f, chief, headers, _, sid, _, private = ready(fixture)
    original = eic_reviewer_candidates.begin
    calls = []

    def fail_second_begin(*args):
        calls.append(1)
        if len(calls) == 2:
            raise sqlite3.OperationalError('synthetic database failure')
        return original(*args)

    with patch('app.routers.eic_reviewer_candidates.begin', side_effect=fail_second_begin):
        response = submit(f, chief, headers, sid)
    assert response.status_code == 503
    with sqlite3.connect(f.db_path) as db:
        candidate = db.execute('SELECT candidate_id FROM reviewer_candidate_reservations').fetchone()[0]
        assert db.execute('SELECT count(*) FROM reviewer_candidate_publications').fetchone()[0] == 0
    assert (private / candidate).is_file()

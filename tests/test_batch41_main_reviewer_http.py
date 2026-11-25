"""Bearer-authenticated Main candidate publication and download."""
import sqlite3
import pytest
from app import models
from app.reviewer_artifact_service import ArtifactError
from app.reviewer_artifact_storage import StorageError
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from test_batch38_eic_proof import fixture
from test_batch40_reviewer_candidates import ready, submit, CHECKS


def published_fixture(fixture):
    f, chief, headers, aid, sid, proof_id, private = ready(fixture)
    upload = submit(f, chief, headers, sid)
    assert upload.status_code == 201, upload.text
    candidate = upload.json()['candidate_id']
    base = f'/eic/manuscripts/{f.mid}/reviewer-candidates/{candidate}'
    assert f.client.post(base + '/verify', headers=headers(chief), json=CHECKS).status_code == 200
    assert f.client.post(base + '/approve', headers=headers(chief)).status_code == 200
    assert f.client.post(base + '/publish', headers=headers(chief)).status_code == 200
    assert f.client.post(base + f'/bind/{aid}', headers=headers(chief)).status_code == 200
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)).status_code == 200
    return f, chief, headers, aid, proof_id, private, candidate, base


def test_real_candidate_publication_binding_and_reviewer_download(fixture):
    f, chief, headers, aid, sid, proof_id, private = ready(fixture)
    upload = submit(f, chief, headers, sid)
    assert upload.status_code == 201, upload.text
    candidate = upload.json()['candidate_id']
    base = f'/eic/manuscripts/{f.mid}/reviewer-candidates/{candidate}'
    assert f.client.post(base + '/publish', headers=headers(chief)).status_code == 409
    assert f.client.post(base + '/verify', headers=headers(chief), json=CHECKS).status_code == 200
    assert f.client.post(base + '/approve', headers=headers(chief)).status_code == 200
    published = f.client.post(base + '/publish', headers=headers(chief))
    assert published.status_code == 200, published.text
    assert f.client.post(base + '/publish', headers=headers(chief)).json() == published.json()
    bound = f.client.post(base + f'/bind/{aid}', headers=headers(chief))
    assert bound.status_code == 200, bound.text
    assert f.client.post(base + f'/bind/{aid}', headers=headers(chief)).json() == bound.json()
    response = f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer))
    assert response.status_code == 200, response.text
    assert response.content == b'%PDF-anonymized-candidate'
    assert response.content != b'%PDF-first'
    assert response.headers['content-disposition'] == 'attachment; filename="review-document.pdf"'
    assert f.author.email not in str(response.headers)
    assert f.author.name not in str(response.headers)
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.other)).status_code == 409
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.author)).status_code == 403
    assert f.client.post(base + '/withdraw', headers=headers(chief)).status_code == 200
    denied = f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer))
    assert denied.status_code == 409 and b'%PDF-first' not in denied.content
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM reviewer_artifact_assignments').fetchone()[0] == 1


@pytest.mark.parametrize('failure', ['proof_revoked', 'bytes_changed', 'assignment_invalidated', 'artifact_withdrawn'])
def test_live_rechecks_deny_after_state_changes(fixture, failure):
    f, chief, headers, aid, proof_id, private, candidate, base = published_fixture(fixture)
    if failure == 'proof_revoked':
        assert f.client.post(f'/eic/manuscripts/{f.mid}/prospective-proofs/{proof_id}/revoke',
                             headers=headers(chief), json={'reason': 'synthetic'}).status_code == 200
    elif failure == 'bytes_changed':
        path = private / candidate
        path.chmod(0o600)
        path.write_bytes(b'%PDF-tampered')
        path.chmod(0o400)
    elif failure == 'artifact_withdrawn':
        withdrawn = f.client.post(base + '/withdraw-artifact', headers=headers(chief))
        assert withdrawn.status_code == 200, withdrawn.text
        assert f.client.post(base + '/withdraw-artifact', headers=headers(chief)).json() == withdrawn.json()
    else:
        f.db.add(models.ReviewerInvitationInvalidation(
            invalidation_id='batch41-synthetic-cancel', assignment_id=aid,
            kind='cancelled', actor_user_id=chief.user_id,
            occurred_at='2026-01-01T00:00:00.000000Z', reason_code='editorial_cancellation'))
        f.db.commit()
    denied = f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer))
    assert denied.status_code == 409 and b'%PDF-first' not in denied.content


def test_reconciliation_is_eic_only_read_only_and_reports_reservation(fixture):
    f, chief, headers, _, sid, _, private = ready(fixture)
    with patch('app.reviewer_artifact_storage.ArtifactStorage.publish_reserved', side_effect=StorageError('synthetic')):
        assert submit(f, chief, headers, sid).status_code == 503
    url = f'/eic/manuscripts/{f.mid}/reviewer-candidate-reconciliation'
    assert f.client.get(url, headers=headers(f.reviewer)).status_code == 403
    response = f.client.get(url, headers=headers(chief))
    assert response.status_code == 200, response.text
    assert response.json()['dry_run'] is True
    assert len(response.json()['incomplete']) == 1
    assert response.json()['incomplete'][0]['entry'] == 'missing'
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM reviewer_candidate_reservations').fetchone()[0] == 1


def test_concurrent_publication_creates_one_artifact(fixture):
    f, chief, headers, _, sid, _, _ = ready(fixture)
    upload = submit(f, chief, headers, sid)
    assert upload.status_code == 201
    candidate = upload.json()['candidate_id']
    base = f'/eic/manuscripts/{f.mid}/reviewer-candidates/{candidate}'
    assert f.client.post(base + '/verify', headers=headers(chief), json=CHECKS).status_code == 200
    assert f.client.post(base + '/approve', headers=headers(chief)).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: f.client.post(base + '/publish', headers=headers(chief)), range(2)))
    assert all(r.status_code == 200 for r in responses), [(r.status_code, r.text) for r in responses]
    assert responses[0].json() == responses[1].json()
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0] == 1


def test_invalidating_one_reviewer_preserves_other_assignment(fixture):
    f, chief, headers, aid, _, _, _, base = published_fixture(fixture)
    created = f.client.post('/assignments/', headers=headers(f.editor),
        json={'manuscript_id': f.mid, 'reviewer_id': f.other.user_id, 'review_round': 1})
    assert created.status_code == 201, created.text
    other_id = created.json()['assignment_id']
    assert f.client.post(f'/assignments/{other_id}/invitation-response', headers=headers(f.other),
                         json={'decision': 'accept'}).status_code == 200
    assert f.client.post(base + f'/bind/{other_id}', headers=headers(chief)).status_code == 200
    assert f.client.get(f'/assignments/{other_id}/download', headers=headers(f.other)).status_code == 200
    f.db.add(models.ReviewerInvitationInvalidation(
        invalidation_id='batch41-one-reviewer-only', assignment_id=aid,
        kind='cancelled', actor_user_id=chief.user_id,
        occurred_at='2026-01-01T00:00:00.000000Z', reason_code='editorial_cancellation'))
    f.db.commit()
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)).status_code == 409
    other = f.client.get(f'/assignments/{other_id}/download', headers=headers(f.other))
    assert other.status_code == 200 and other.content == b'%PDF-anonymized-candidate'


def test_publication_failure_rolls_back_artifact_record(fixture):
    f, chief, headers, _, sid, _, _ = ready(fixture)
    upload = submit(f, chief, headers, sid)
    assert upload.status_code == 201
    base = f"/eic/manuscripts/{f.mid}/reviewer-candidates/{upload.json()['candidate_id']}"
    assert f.client.post(base + '/verify', headers=headers(chief), json=CHECKS).status_code == 200
    assert f.client.post(base + '/approve', headers=headers(chief)).status_code == 200
    with patch('app.reviewer_artifact_evidence.approve_with_evidence', side_effect=ArtifactError('synthetic failure')):
        assert f.client.post(base + '/publish', headers=headers(chief)).status_code == 409
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM artifact_approval_evidence').fetchone()[0] == 0
    assert f.client.post(base + '/publish', headers=headers(chief)).status_code == 200

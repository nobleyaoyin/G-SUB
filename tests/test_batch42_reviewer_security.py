"""Additional real-bearer HTTP and reconciliation regression tests."""
import sqlite3
from pathlib import Path
from importlib import import_module

import pytest
from unittest.mock import patch
from app import models
from app.reviewer_artifact_storage import StorageError
from test_batch38_eic_proof import fixture
from test_batch41_main_reviewer_http import published_fixture
from test_batch40_reviewer_candidates import ready, submit, CHECKS


def assert_denied(response, author):
    assert response.status_code == 409
    assert b'%PDF-first' not in response.content
    assert b'%PDF-anonymized-candidate' not in response.content
    assert author.name not in response.text and author.email not in response.text
    assert author.name not in str(response.headers) and author.email not in str(response.headers)


def test_wrong_round_and_unassigned_are_denied(fixture):
    f, chief, headers, aid, _, _, _, base = published_fixture(fixture)
    assert_denied(f.client.get(f'/assignments/{aid}/download', headers=headers(f.other)), f.author)
    assert f.client.post(f'/eic/manuscripts/999999/reviewer-candidates/00000000000000000000000000000000/bind/{aid}',
                         headers=headers(chief)).status_code in (404, 409)
    manuscript = f.db.get(models.Manuscript, f.mid)
    manuscript.review_round = 2
    f.db.commit()
    assert_denied(f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)), f.author)


def test_invalid_signing_key_denies_without_fallback(fixture, monkeypatch):
    f, _, headers, aid, _, _, _, _ = published_fixture(fixture)
    monkeypatch.setenv('GSUB_EIC_PROOF_SECRET', 'fedcba9876543210' * 4)
    assert_denied(f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)), f.author)


def test_inactive_reviewer_is_denied(fixture):
    f, chief, headers, aid, _, _, _, _ = published_fixture(fixture)
    actor_id = f.reviewer.user_id
    eid = 'batch42-disabled-reviewer'
    f.db.add(models.AccountLifecycleEvent(event_id=eid, user_id=actor_id, sequence=2,
        from_state='active', to_state='disabled', auth_generation=2, actor_user_id=chief.user_id,
        occurred_at='2026-01-02T00:00:00.000000Z', reason_code='administrative_disable'))
    f.db.flush()
    state = f.db.get(models.AccountLifecycle, actor_id)
    state.state, state.sequence, state.auth_generation, state.last_event_id = 'disabled', 2, 2, eid
    f.db.commit()
    assert_denied(f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)), f.author)


def test_reconciliation_reports_integrity_and_missing_without_modifying(fixture):
    f, chief, headers, _, _, private, candidate, _ = published_fixture(fixture)
    url = f'/eic/manuscripts/{f.mid}/reviewer-candidate-reconciliation'
    initial = f.client.get(url, headers=headers(chief))
    assert initial.status_code == 200
    item = next(c for c in initial.json()['candidates'] if c['candidate_id'] == candidate)
    assert item['file']['state'] == 'regular' and item['file']['owned_by_service']
    assert item['file']['age_seconds'] >= 0 and item['integrity'] == 'verified' and item['approved']
    path = private / candidate
    path.chmod(0o600)
    path.write_bytes(b'%PDF-changed')
    path.chmod(0o400)
    response = f.client.get(url, headers=headers(chief))
    changed = next(c for c in response.json()['candidates'] if c['candidate_id'] == candidate)
    assert changed['integrity'] == 'mismatch_or_unavailable'
    assert path.read_bytes() == b'%PDF-changed'


def test_publication_audit_is_durable_and_retry_does_not_duplicate(fixture):
    f, chief, headers, _, proof_id, _, candidate, base = published_fixture(fixture)
    assert f.client.post(base + '/publish', headers=headers(chief)).status_code == 200
    with sqlite3.connect(f.db_path) as db:
        row = db.execute('''SELECT manuscript_id,review_round,artifact_version,source_proof_id,result
            FROM reviewer_publication_audit''').fetchone()
        assert row == (f.mid, 1, 1, proof_id, 'published')
        assert db.execute('SELECT count(*) FROM reviewer_publication_audit').fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE reviewer_publication_audit SET result='published'")


def test_audit_write_failure_rolls_back_publication(fixture):
    f, chief, headers, _, sid, _, _ = ready(fixture)
    upload = submit(f, chief, headers, sid)
    assert upload.status_code == 201
    base = f"/eic/manuscripts/{f.mid}/reviewer-candidates/{upload.json()['candidate_id']}"
    assert f.client.post(base + '/verify', headers=headers(chief), json=CHECKS).status_code == 200
    assert f.client.post(base + '/approve', headers=headers(chief)).status_code == 200
    with patch('app.routers.eic_reviewer_candidates.now', side_effect=sqlite3.OperationalError('synthetic')):
        assert f.client.post(base + '/publish', headers=headers(chief)).status_code == 503
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM reviewer_publication_audit').fetchone()[0] == 0
    assert f.client.post(base + '/publish', headers=headers(chief)).status_code == 200


def test_legacy_publication_requires_present_time_eic_reaffirmation(fixture):
    f, chief, headers, aid, _, _, _, base = published_fixture(fixture)
    migration = import_module('migrations.024_reviewer_publication_audit')
    with sqlite3.connect(f.db_path) as db:
        db.execute('DROP TRIGGER reviewer_publication_audit_no_delete')
        db.execute('DELETE FROM reviewer_publication_audit')
        db.execute(migration.DDL['reviewer_publication_audit_no_delete'])
        db.commit()
    assert_denied(f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)), f.author)
    assert f.client.post(base + '/publish', headers=headers(chief)).status_code == 200
    with sqlite3.connect(f.db_path) as db:
        assert db.execute('SELECT result FROM reviewer_publication_audit').fetchone()[0] == 'reaffirmed'
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer)).status_code == 200

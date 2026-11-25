"""Option B foundation: real isolated boundaries plus explicit missing contracts.

No test-only implementation of the future artifact lifecycle is substituted
for production. Xfails denote specifications whose production API is absent.
"""
import hashlib
import os
import sqlite3
from contextlib import contextmanager

import pytest
from sqlalchemy.orm import Session

from app import models, reviewer_artifact_service as artifact_service
from app.database import engine as configured_engine
from app.routers import assignments
from tests.test_phase_2f_policy_management import policy_api
from tests.test_phase_2f_reviewer_projections import api_factory
from tests.test_phase_2f_reviewer_document_release import setup_file
from tests import test_phase_2f_invitation_transactions as transactions
from tests import test_phase_2f_policy_management as policy_checks


def test_prototype_source_identity_first_and_later_round_without_invitation(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Configured Main database connection is forbidden')
    monkeypatch.setattr(configured_engine, 'connect', deny)
    monkeypatch.setattr(configured_engine, 'raw_connection', deny)
    db = sqlite3.connect(':memory:')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
      CREATE TABLE manuscripts (manuscript_id INTEGER PRIMARY KEY, author_id INTEGER, review_round INTEGER, status TEXT);
      CREATE TABLE initial_editing_submissions (submission_id INTEGER PRIMARY KEY, manuscript_id INTEGER, status TEXT, file_path TEXT);
      CREATE TABLE pre_review_confirmations (confirmation_id INTEGER PRIMARY KEY, submission_id INTEGER, manuscript_id INTEGER, author_id INTEGER, decision TEXT, file_path TEXT);
      CREATE TABLE review_round_files (round_file_id INTEGER PRIMARY KEY, manuscript_id INTEGER REFERENCES manuscripts(manuscript_id), review_round INTEGER, source_kind TEXT, confirmation_id INTEGER, file_path TEXT);
      INSERT INTO manuscripts VALUES (1, 10, 1, 'ready_for_peer_review');
      INSERT INTO initial_editing_submissions VALUES (1, 1, 'eic_approved', 'synthetic.txt');
      INSERT INTO pre_review_confirmations VALUES (1, 1, 1, 10, 'confirm', 'synthetic.txt');
      INSERT INTO review_round_files VALUES (1, 1, 1, 'initial_editing', 1, 'synthetic.txt');
    ''')
    try:
        assert db.execute('PRAGMA database_list').fetchall() == [(0, 'main', '')]
        assert artifact_service._source(db, 1, 1)[2:5] == (1, 'initial_editing', 1)
        with pytest.raises(artifact_service.ArtifactError):
            artifact_service._source(db, 1, 99)
        db.execute("UPDATE pre_review_confirmations SET decision='request_revision'")
        with pytest.raises(artifact_service.ArtifactError):
            artifact_service._source(db, 1, 1)
        db.execute("UPDATE pre_review_confirmations SET decision='confirm'")
        db.execute("UPDATE initial_editing_submissions SET status='editor_approved'")
        with pytest.raises(artifact_service.ArtifactError):
            artifact_service._source(db, 1, 1)
        db.execute("UPDATE manuscripts SET review_round=2,status='revised'")
        db.execute("INSERT INTO review_round_files VALUES (2,1,2,'author_revision',NULL,'revision.txt')")
        assert artifact_service._source(db, 1, 2)[2:5] == (2, 'author_revision', None)
        with pytest.raises(artifact_service.ArtifactError):
            artifact_service._source(db, 1, 1)
    finally:
        db.close()


def test_prototype_source_digest_verification_detects_changed_bytes(monkeypatch, tmp_path):
    def deny(*args, **kwargs):
        raise AssertionError('Configured Main database connection is forbidden')
    monkeypatch.setattr(configured_engine, 'connect', deny)
    monkeypatch.setattr(configured_engine, 'raw_connection', deny)
    path = tmp_path / 'synthetic.txt'
    original = b'synthetic source text'
    path.write_bytes(original)
    digest = hashlib.sha256(original).hexdigest()

    class Provenance:
        @contextmanager
        def open_attested_source(self, *args):
            fd = os.open(path, os.O_RDONLY)
            try:
                yield fd, digest, len(original), 'txt'
            finally:
                os.close(fd)

    source = (2, 'revised', 2, 'author_revision', None, 'synthetic.txt')
    assert artifact_service._verified_source(None, Provenance(), 1, 2, source, digest) == digest
    path.write_bytes(b'synthetic source TEXT')
    with pytest.raises(ValueError):
        artifact_service._verified_source(None, Provenance(), 1, 2, source, digest)


def test_policy_revision_aba_and_actual_invitation_event(policy_api):
    client, actor, engine = policy_api
    actor['id'] = 4
    path = '/eic/manuscripts/2/review-policy'
    assert client.put(path, json={'mode': 'double_blind'}).json()['revision'] == 1
    assert client.put(path, json={'mode': 'single_blind', 'expected_revision': 1}).json()['revision'] == 2
    assert client.put(path, json={'mode': 'double_blind', 'expected_revision': 2}).json()['revision'] == 3
    assert client.put(path, json={'mode': 'single_blind', 'expected_revision': 1}).status_code == 409
    response = client.post('/assignments/', json={'manuscript_id': 2, 'reviewer_id': 5, 'review_round': 2})
    assert response.status_code == 201
    with engine.connect() as connection:
        rows = connection.exec_driver_sql('SELECT revision,mode,action,invitation_id FROM blind_policy_events WHERE manuscript_id=2 ORDER BY revision').all()
        assert rows == [(1, 'double_blind', 'selected', None), (2, 'single_blind', 'changed', None),
                        (3, 'double_blind', 'changed', None), (4, 'double_blind', 'locked', response.json()['assignment_id'])]
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA database_list').all()[0][2] == ''
    with pytest.raises(AssertionError, match='forbidden'):
        configured_engine.connect()


@pytest.mark.parametrize('failure', ['before', 'after_flush', 'after_lock', 'notification'])
def test_existing_owner_rolls_back_confirmed_failures(policy_api, monkeypatch, failure):
    transactions.test_failures_roll_back_all_records(policy_api, monkeypatch, failure)


def test_existing_outbox_failure_rolls_back(policy_api, monkeypatch):
    policy_checks.test_queue_failure_rolls_back_lock_and_invitation(policy_api, monkeypatch)


@pytest.mark.parametrize('point', ['commit', 'refresh'])
def test_existing_post_commit_uncertainty_and_retry(policy_api, monkeypatch, point):
    transactions.test_uncertain_commit_or_refresh_reports_unknown_and_retry_is_safe(policy_api, monkeypatch, point)


@pytest.mark.parametrize('same_reviewer', [True, False])
def test_existing_independent_connection_contention(policy_api, monkeypatch, same_reviewer):
    transactions.test_shared_memory_contention_and_competing_retry(policy_api, monkeypatch, same_reviewer)


@pytest.mark.parametrize('invitation', ['pending', 'accepted', 'declined'])
def test_double_blind_without_artifact_denies_list_and_download(api_factory, monkeypatch, tmp_path, invitation):
    client, _, engine, path, original = setup_file(api_factory, monkeypatch, tmp_path, 'double')
    with Session(engine) as db:
        db.get(models.ReviewerInvitation, 1).status = invitation
        db.commit()
    listing = client.get('/assignments/my')
    assert listing.status_code == 200
    item, = listing.json()
    assert item['review_file_available'] is False
    response = client.get('/assignments/1/download')
    assert response.status_code == 409
    assert original not in response.content
    assert path.read_bytes() == original
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(original).digest()


def test_legacy_policyless_and_wrong_reviewer_denied(api_factory, monkeypatch, tmp_path):
    client, actor, _, path, original = setup_file(api_factory, monkeypatch, tmp_path, 'missing')
    assert client.get('/assignments/1/download').status_code == 409
    actor['id'] = 5
    assert client.get('/assignments/1/download').status_code == 409
    assert path.read_bytes() == original


@pytest.mark.parametrize('state', ['accepted', 'completed', 'legacy'])
def test_single_blind_round_binding_requires_active_accepted_assignment(api_factory, monkeypatch, tmp_path, state):
    client, _, engine, _, original = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    assignment_id = 1
    with Session(engine) as db:
        if state == 'completed':
            db.get(models.ReviewAssignment, 1).status = 'completed'
        elif state == 'legacy':
            assignment_id = 2
            db.add(models.ReviewAssignment(assignment_id=2, manuscript_id=1, reviewer_id=2, assigned_by=3, review_round=2, status='assigned'))
            db.flush()
            db.add(models.ReviewAssignmentFile(assignment_id=2, round_file_id=1))
        db.commit()
    response = client.get(f'/assignments/{assignment_id}/download')
    if state == 'accepted':
        assert response.status_code == 200 and response.content == original
    else:
        assert response.status_code == 409 and original not in response.content
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('case', [
    'first-round source materialization with EIC approval and author confirmation',
    'later-round trusted source revision and digest', 'missing source row', 'missing trusted source proof',
    'source byte replacement', 'source revision replacement',
    'provisional private artifact identity version selected revision and digest',
    'provisional artifact remains unapproved unbound and unavailable',
    'stale candidate after policy revision change', 'stale candidate after policy ABA',
    'preparer EIC or assigned Editor', 'different EIC approves exact bytes and real lock event',
    'reject self approval', 'reject author reviewer formatter and missing actor',
    'reject missing checklist', 'reject wrong artifact version', 'reject wrong artifact digest',
    'reject wrong source revision and digest', 'reject wrong lock event', 'reject revoked or rejected candidate',
    'provisional unapproved rejected stale and revoked candidate cannot bind',
    'wrong assignment or round and declined invitation cannot bind',
    'accepted invitation with valid approval binds each eligible assignment',
    'reviewer release denies before approval acceptance and correct binding',
    'reviewer release denies revoked source or artifact changes and policy mismatch',
    'reviewer release denies wrong reviewer assignment round and invalidation',
    'concurrent revocation and download enforce documented snapshot ordering',
])
def test_future_option_b_contract_not_implemented(case):
    pytest.xfail('Future production Option B contract not implemented: ' + case)

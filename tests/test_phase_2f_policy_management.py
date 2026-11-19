"""Isolated HTTP policy management and invitation transaction checks."""
import sqlite3

import pytest
from sqlalchemy.orm import Session

from app import models
from app.database import Base, engine as configured_engine
from app.routers import assignments, eic
from app.email.enqueue_mode import EnqueueMode, reviewer_email_enqueue_mode
from tests.test_phase_2f_reviewer_projections import api_factory


@pytest.fixture
def policy_api(api_factory, monkeypatch):
    client, actor, engine = api_factory('missing')
    client.app.include_router(eic.router)
    Base.metadata.create_all(engine, tables=[models.Notification.__table__])
    with Session(engine) as db:
        db.add(models.Manuscript(manuscript_id=2, author_id=1, title='Synthetic', abstract='Synthetic', status='revised', review_round=2))
        db.add(models.ReviewRoundFile(round_file_id=2, manuscript_id=2, review_round=2, source_kind='author_revision', file_path='synthetic.txt'))
        db.commit()
    monkeypatch.setattr(assignments, 'validate_round_file', lambda *args: None)
    return client, actor, engine


@pytest.mark.parametrize('mode', ['single_blind', 'double_blind'])
def test_eic_selects_and_locks_with_real_invitation(policy_api, mode):
    client, actor, engine = policy_api
    actor['id'] = 4
    path = '/eic/manuscripts/2/review-policy'
    assert client.get(path).json()['state'] == 'missing'
    selected = client.put(path, json={'mode': mode, 'expected_revision': None})
    assert selected.status_code == 200 and selected.json() == {'state': 'selected', 'mode': mode, 'revision': 1}
    invitation = client.post('/assignments/', json={'manuscript_id': 2, 'reviewer_id': 5, 'review_round': 2})
    assert invitation.status_code == 201, invitation.text
    assert client.get(path).json() == {'state': 'locked', 'mode': mode, 'revision': 2}
    assert client.put(path, json={'mode': mode, 'expected_revision': 2}).status_code == 409
    with engine.connect() as connection:
        events = connection.exec_driver_sql('SELECT revision, action, actor_id, invitation_id FROM blind_policy_events WHERE manuscript_id=2 ORDER BY revision').all()
        assert events == [(1, 'selected', 4, None), (2, 'locked', 4, invitation.json()['assignment_id'])]
        with pytest.raises(Exception):
            connection.exec_driver_sql("DELETE FROM blind_policy_events WHERE manuscript_id=2")
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


@pytest.mark.parametrize('actor_id', [1, 2, 3, 5])
def test_non_eic_cannot_select(policy_api, actor_id):
    client, actor, _ = policy_api
    actor['id'] = actor_id
    assert client.put('/eic/manuscripts/2/review-policy', json={'mode': 'single_blind'}).status_code == 403


def test_failed_invitation_does_not_lock_and_legacy_is_not_reconciled(policy_api):
    client, actor, engine = policy_api
    actor['id'] = 4
    path = '/eic/manuscripts/2/review-policy'
    assert client.put(path, json={'mode': 'single_blind'}).status_code == 200
    assert client.post('/assignments/', json={'manuscript_id': 2, 'reviewer_id': 1, 'review_round': 2}).status_code == 400
    assert client.get(path).json()['state'] == 'selected'
    assert client.put('/eic/manuscripts/1/review-policy', json={'mode': 'single_blind'}).status_code == 409
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT count(*) FROM blind_policy_events WHERE manuscript_id=2').scalar() == 1


def test_missing_policy_blocks_invitation(policy_api):
    client, actor, _ = policy_api
    actor['id'] = 4
    assert client.post('/assignments/', json={'manuscript_id': 2, 'reviewer_id': 5, 'review_round': 2}).status_code == 409


def test_revision_checks_and_unlocked_change(policy_api):
    client, actor, engine = policy_api
    actor['id'] = 4
    path = '/eic/manuscripts/2/review-policy'
    assert client.put(path, json={'mode': 'single_blind'}).status_code == 200
    assert client.put(path, json={'mode': 'double_blind', 'expected_revision': 99}).status_code == 409
    changed = client.put(path, json={'mode': 'double_blind', 'expected_revision': 1})
    assert changed.json() == {'state': 'selected', 'mode': 'double_blind', 'revision': 2}
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT action FROM blind_policy_events WHERE manuscript_id=2 ORDER BY revision').scalars().all() == ['selected', 'changed']


def test_editor_invitation_locks_as_editor(policy_api):
    client, actor, engine = policy_api
    actor['id'] = 4
    assert client.put('/eic/manuscripts/2/review-policy', json={'mode': 'double_blind'}).status_code == 200
    with Session(engine) as db:
        db.add(models.InitialEditorInvitation(manuscript_id=2, editor_id=3, invited_by=4, status='accepted'))
        db.commit()
    actor['id'] = 3
    response = client.post('/assignments/', json={'manuscript_id': 2, 'reviewer_id': 5, 'review_round': 2})
    assert response.status_code == 201, response.text
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT actor_id FROM blind_policy_events WHERE manuscript_id=2 AND action='locked'").scalar() == 3
    with pytest.raises(AssertionError):
        configured_engine.connect()


def test_unassigned_editor_remains_forbidden(policy_api):
    client, actor, _ = policy_api
    actor['id'] = 3
    assert client.post('/assignments/', json={'manuscript_id': 2, 'reviewer_id': 5, 'review_round': 2}).status_code == 403


def test_queue_failure_rolls_back_lock_and_invitation(policy_api, monkeypatch):
    client, actor, engine = policy_api
    actor['id'] = 4
    assert client.put('/eic/manuscripts/2/review-policy', json={'mode': 'single_blind'}).status_code == 200
    client.app.dependency_overrides[reviewer_email_enqueue_mode] = lambda: EnqueueMode.ENQUEUE_ONLY
    monkeypatch.setattr(assignments, 'check_outbox_schema', lambda db: None)
    def fail(*args):
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr(assignments, 'enqueue_reviewer_invitation', fail)
    assert client.post('/assignments/', json={'manuscript_id': 2, 'reviewer_id': 5, 'review_round': 2}).status_code == 503
    assert client.get('/eic/manuscripts/2/review-policy').json()['state'] == 'selected'
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT count(*) FROM review_assignments WHERE manuscript_id=2').scalar() == 0
        assert connection.exec_driver_sql('SELECT count(*) FROM blind_policy_events WHERE manuscript_id=2').scalar() == 1

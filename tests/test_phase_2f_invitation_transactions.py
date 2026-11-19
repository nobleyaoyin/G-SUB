"""Invitation transaction checks using synthetic in-memory SQLite only."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models
from app.database import engine as configured_engine
from app.email.enqueue_mode import EnqueueMode
from app.routers import assignments
from app.schemas import ReviewAssignmentCreate
from tests.test_phase_2f_policy_management import policy_api
from tests.test_phase_2f_reviewer_projections import api_factory


def choose(client, actor):
    actor['id'] = 4
    assert client.put('/eic/manuscripts/2/review-policy', json={'mode': 'single_blind'}).status_code == 200


def post(client, reviewer=5):
    return client.post('/assignments/', json={'manuscript_id': 2, 'reviewer_id': reviewer, 'review_round': 2})


def assert_no_invitation(engine):
    with engine.connect() as conn:
        for table in ('review_assignments', 'reviewer_invitations', 'review_assignment_files', 'notifications'):
            if table in ('reviewer_invitations', 'review_assignment_files'):
                query = f'SELECT count(*) FROM {table} WHERE assignment_id IN (SELECT assignment_id FROM review_assignments WHERE manuscript_id=2)'
            else:
                query = f'SELECT count(*) FROM {table} WHERE manuscript_id=2'
            assert conn.exec_driver_sql(query).scalar() == 0
        assert conn.exec_driver_sql('SELECT revision FROM blind_policies WHERE manuscript_id=2').scalar() == 1
        assert conn.exec_driver_sql('SELECT count(*) FROM blind_policy_events WHERE manuscript_id=2').scalar() == 1


def test_success_commits_every_bound_record(policy_api):
    client, actor, engine = policy_api
    choose(client, actor)
    response = post(client)
    assert response.status_code == 201
    assignment_id = response.json()['assignment_id']
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT round_file_id FROM review_assignment_files WHERE assignment_id=?', (assignment_id,)).scalar() == 2
        assert conn.exec_driver_sql('SELECT status FROM reviewer_invitations WHERE assignment_id=?', (assignment_id,)).scalar() == 'pending'
        assert conn.exec_driver_sql('SELECT lock_invitation_id FROM blind_policies WHERE manuscript_id=2').scalar() == assignment_id
        assert conn.exec_driver_sql('SELECT count(*) FROM notifications WHERE manuscript_id=2 AND user_id=5').scalar() == 1


def test_additional_reviewer_uses_same_owned_transaction(policy_api, monkeypatch):
    client, actor, engine = policy_api
    choose(client, actor)
    monkeypatch.setattr(assignments, 'split_review_status', lambda *args: {'can_invite_additional': True})
    response = client.post('/assignments/additional-reviewer', json={'manuscript_id': 2, 'reviewer_id': 5, 'review_round': 2})
    assert response.status_code == 201, response.text
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT lock_invitation_id FROM blind_policies WHERE manuscript_id=2').scalar() == response.json()['assignment_id']


@pytest.mark.parametrize('failure', ['before', 'after_flush', 'after_lock', 'notification'])
def test_failures_roll_back_all_records(policy_api, monkeypatch, failure):
    client, actor, engine = policy_api
    choose(client, actor)
    original_lock = assignments.lock_mode
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic failure')
    if failure == 'before':
        monkeypatch.setattr(assignments, 'validate_round_file', fail)
    elif failure == 'after_flush':
        monkeypatch.setattr(assignments, 'lock_mode', fail)
    elif failure == 'after_lock':
        def lock_then_fail(*args, **kwargs):
            original_lock(*args, **kwargs)
            raise RuntimeError('synthetic failure')
        monkeypatch.setattr(assignments, 'lock_mode', lock_then_fail)
    else:
        monkeypatch.setattr(assignments, 'Notification', fail)
    with pytest.raises(RuntimeError, match='synthetic'):
        post(client)
    assert_no_invitation(engine)


def test_caller_work_and_explicit_or_nested_transactions_are_not_owned(policy_api):
    client, actor, engine = policy_api
    choose(client, actor)
    with Session(engine) as db:
        user = db.get(models.User, 4)
        db.add(models.User(user_id=40, name='Pending', email='pending@example.test', password_hash='x', role='reviewer'))
        with pytest.raises(HTTPException) as rejected:
            assignments._invitation_operation(ReviewAssignmentCreate(manuscript_id=2, reviewer_id=5, review_round=2), user, db, EnqueueMode.DISABLED)
        assert rejected.value.status_code == 503 and db.new
        db.rollback()
        assert db.get(models.User, 40) is None
    with Session(engine) as db:
        with db.begin():
            user = db.get(models.User, 4)
            with pytest.raises(HTTPException):
                assignments._invitation_operation(ReviewAssignmentCreate(manuscript_id=2, reviewer_id=5, review_round=2), user, db, EnqueueMode.DISABLED)
            assert db.in_transaction()
            with db.begin_nested():
                with pytest.raises(HTTPException):
                    assignments._invitation_operation(ReviewAssignmentCreate(manuscript_id=2, reviewer_id=5, review_round=2), user, db, EnqueueMode.DISABLED)
    assert_no_invitation(engine)


def test_caller_owned_raw_transaction_is_not_committed_or_rolled_back(policy_api):
    client, actor, engine = policy_api
    choose(client, actor)
    with Session(engine) as db:
        user = db.get(models.User, 4)
        connection = db.connection()
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        connection.exec_driver_sql("UPDATE users SET name='Uncommitted' WHERE user_id=4")
        with pytest.raises(HTTPException):
            assignments._invitation_operation(ReviewAssignmentCreate(manuscript_id=2, reviewer_id=5, review_round=2), user, db, EnqueueMode.DISABLED)
        assert connection.connection.driver_connection.in_transaction
        db.rollback()
    with Session(engine) as db:
        assert db.get(models.User, 4).name == 'EIC'
    assert_no_invitation(engine)


@pytest.mark.parametrize('point', ['commit', 'refresh'])
def test_uncertain_commit_or_refresh_reports_unknown_and_retry_is_safe(policy_api, monkeypatch, point):
    client, actor, engine = policy_api
    choose(client, actor)
    original = getattr(Session, point)
    triggered = False
    def fail_after(self, *args, **kwargs):
        nonlocal triggered
        result = original(self, *args, **kwargs)
        if not triggered:
            triggered = True
            raise RuntimeError('synthetic acknowledgement failure')
        return result
    with monkeypatch.context() as scoped:
        scoped.setattr(Session, point, fail_after)
        response = post(client)
    assert response.status_code == 503 and 'could not be confirmed' in response.json()['detail']
    assert post(client).status_code == 409
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT count(*) FROM review_assignments WHERE manuscript_id=2').scalar() == 1
        assert conn.exec_driver_sql('SELECT revision FROM blind_policies WHERE manuscript_id=2').scalar() == 2


@pytest.mark.parametrize('same_reviewer', [True, False])
def test_shared_memory_contention_and_competing_retry(policy_api, monkeypatch, same_reviewer):
    client, actor, source_engine = policy_api
    choose(client, actor)
    # Shared-cache URI is a named, disposable SQLite memory database; never a file.
    uri = f'file:gsub_{uuid4().hex}?mode=memory&cache=shared'
    anchor = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=0)
    source = source_engine.raw_connection()
    source.driver_connection.backup(anchor)
    source.close()
    assert anchor.execute('PRAGMA database_list').fetchall()[0][2] == ''
    engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=0))
    from sqlalchemy import event
    @event.listens_for(engine, 'connect')
    def fk(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        assert connection.execute('PRAGMA database_list').fetchall()[0][2] == ''
    entered, release = Event(), Event()
    original_lock = assignments.lock_mode
    def pause(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_lock(*args, **kwargs)
    monkeypatch.setattr(assignments, 'lock_mode', pause)
    def invite(reviewer):
        with Session(engine) as db:
            actor_user = db.get(models.User, 4)
            try:
                response = assignments._invitation_operation(ReviewAssignmentCreate(manuscript_id=2, reviewer_id=reviewer, review_round=2), actor_user, db, EnqueueMode.DISABLED)
                return (201, response.assignment_id)
            except HTTPException as error:
                return (error.status_code, error.detail)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(invite, 5)
            assert entered.wait(5)
            second = pool.submit(invite, 5 if same_reviewer else 2)
            assert second.result(timeout=5)[0] == 503
            release.set()
            assert first.result(timeout=5)[0] == 201
        retry = invite(5 if same_reviewer else 2)
        assert retry[0] == (409 if same_reviewer else 201)
        with engine.connect() as conn:
            assert conn.exec_driver_sql('SELECT count(*) FROM review_assignments WHERE manuscript_id=2').scalar() == (1 if same_reviewer else 2)
            assert conn.exec_driver_sql('SELECT count(*) FROM blind_policy_events WHERE manuscript_id=2').scalar() == 2
        with pytest.raises(AssertionError):
            configured_engine.connect()
    finally:
        release.set()
        engine.dispose()
        anchor.close()

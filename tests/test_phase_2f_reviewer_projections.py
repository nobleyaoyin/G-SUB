"""Reviewer projections with real policy history and in-memory HTTP fixtures."""
from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import blind_policy_store as store, models
from app.database import Base, engine as configured_engine, get_db
from app.routers import assignments, manuscripts
from app.routers.users import get_current_user
from tests.test_phase_2f_policy_store_isolated import _declared_policy_ddl


@pytest.fixture
def api_factory(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Configured Main database connection is forbidden')
    monkeypatch.setattr(configured_engine, 'connect', blocked)
    monkeypatch.setattr(configured_engine, 'raw_connection', blocked)
    engines = []
    clients = []

    def make(policy):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        engines.append(engine)
        @event.listens_for(engine, 'connect')
        def enforce_fk(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            assert connection.execute('PRAGMA database_list').fetchall() == [(0, 'main', '')]
        tables = [models.User, models.Manuscript, models.ReviewAssignment, models.ReviewerInvitation,
                  models.ReviewerInvitationInvalidation, models.InitialEditorInvitation, models.FinalEditorInvitation,
                  models.ManuscriptReviewPolicy, models.EICInitialScan, models.InitialEditingSubmission,
                  models.PreReviewConfirmation, models.ReviewRoundFile, models.ReviewAssignmentFile,
                  models.AccountLifecycleEvent, models.AccountLifecycle]
        Base.metadata.create_all(engine, tables=[item.__table__ for item in tables])
        with engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE schema_migrations (migration_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)')
            for ddl in _declared_policy_ddl().values():
                connection.exec_driver_sql(ddl)
            connection.exec_driver_sql("INSERT INTO schema_migrations VALUES ('011_blind_review_policy', 'synthetic')")
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            db.add_all([models.User(user_id=i, name=name, email=f'{i}@example.test', password_hash='x', role=role)
                        for i, name, role in [(1, 'Author', 'author'), (2, 'Reviewer', 'reviewer'),
                                              (3, 'Editor', 'editor'), (4, 'EIC', 'eic'), (5, 'Other', 'reviewer')]])
            db.commit()
        with engine.begin() as connection:
            for uid in (2, 5):
                event_id = f'synthetic-active-{uid}'
                connection.exec_driver_sql(
                    'INSERT INTO account_lifecycle_events VALUES (?,?,?,?,?,?,?,?,?)',
                    (event_id, uid, 1, None, 'active', 1, 4,
                     '2026-01-01T00:00:00.000000Z', 'initial_enrollment'))
                connection.exec_driver_sql(
                    'INSERT INTO account_lifecycle VALUES (?,?,?,?,?)',
                    (uid, 'active', 1, 1, event_id))
        with Session(engine) as db:
            db.add(models.Manuscript(manuscript_id=1, author_id=1, title='Identifying synthetic title',
                                     abstract='Private synthetic abstract', status='ready_for_peer_review',
                                     review_round=1, created_at=now))
            db.commit()
        if policy not in ('missing', 'unavailable'):
            raw_connection = engine.raw_connection()
            raw = raw_connection.driver_connection
            store.begin_write(raw)
            store.select_mode(raw, 1, 'single_blind' if policy in ('single', 'unlocked', 'invalid') else 'double_blind', 4)
            raw.commit()
            raw_connection.close()
        with Session(engine) as db:
            db.add(models.ReviewAssignment(assignment_id=1, manuscript_id=1, reviewer_id=2, assigned_by=3,
                                           review_round=1, status='assigned'))
            db.add(models.InitialEditorInvitation(invitation_id=1, manuscript_id=1, editor_id=3, invited_by=4, status='accepted'))
            db.commit()
            db.add(models.ReviewerInvitation(assignment_id=1, status='accepted'))
            db.commit()
        if policy in ('single', 'double'):
            raw_connection = engine.raw_connection()
            raw = raw_connection.driver_connection
            store.begin_write(raw)
            store.lock_mode(raw, 1, 1, 4, 1)
            raw.commit()
            raw_connection.close()
        elif policy == 'invalid':
            with engine.begin() as connection:
                connection.exec_driver_sql('UPDATE blind_policies SET updated_by=3 WHERE manuscript_id=1')
        elif policy == 'unavailable':
            with engine.begin() as connection:
                connection.exec_driver_sql("DELETE FROM schema_migrations WHERE migration_id='011_blind_review_policy'")
        app = FastAPI()
        app.include_router(manuscripts.router)
        app.include_router(assignments.router)
        actor = {'id': 2}
        def session_override():
            with Session(engine) as db:
                yield db
        def user_override(db: Session = Depends(get_db)):
            return db.get(models.User, actor['id'])
        app.dependency_overrides[get_db] = session_override
        app.dependency_overrides[get_current_user] = user_override
        client = TestClient(app)
        clients.append(client)
        return client, actor, engine

    yield make
    for client in clients:
        client.close()
    for engine in engines:
        engine.dispose()


@pytest.mark.parametrize('policy', ['single', 'double'])
def test_real_locked_policy_detail_allowlists(api_factory, policy):
    client, _, _ = api_factory(policy)
    response = client.get('/manuscripts/1')
    expected = {'manuscript_id': 1, 'review_round': 1}
    if policy == 'single':
        expected['author_name'] = 'Author'
    assert response.status_code == 200
    assert response.json() == expected
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('policy,detail_status', [('single', 200), ('double', 200), ('missing', 404),
                                                 ('unlocked', 404), ('invalid', 404), ('unavailable', 503)])
def test_reviewer_progress_and_assignment_are_neutral_in_all_policy_states(api_factory, policy, detail_status):
    client, _, engine = api_factory(policy)
    detail = client.get('/manuscripts/1')
    assert detail.status_code == detail_status
    assert 'author_id' not in detail.text and 'Identifying synthetic title' not in detail.text
    progress = client.get('/manuscripts/1/progress')
    assert progress.status_code == 200
    assert progress.headers['cache-control'] == 'no-store'
    assert set(progress.json()) == {'manuscript_id', 'status', 'review_round', 'current_stage', 'next_action', 'stages', 'participant_task'}
    task = progress.json()['participant_task']
    assert set(task) == {'task_state', 'task_message', 'relevant_stage', 'action_label', 'permitted_action_target'}
    assert 'Identifying synthetic title' not in str(task) and 'author_id' not in str(task)
    assert progress.json()['current_stage'] == 'Peer Review'
    assert all(set(stage) == {'name', 'state'} for stage in progress.json()['stages'])
    assert 'Identifying synthetic title' not in progress.text and 'author_id' not in progress.text
    listing = client.get('/assignments/my')
    assert listing.status_code == 200 and listing.headers['cache-control'] == 'no-store'
    row, = listing.json()
    assert set(row) == {'assignment_id', 'manuscript_id', 'review_round', 'status', 'invitation_status',
                        'assigned_at', 'manuscript_status', 'has_pdf', 'review_file_available', 'review_file_status'}
    assert (row['assignment_id'], row['manuscript_id'], row['review_round'], row['status'], row['invitation_status']) == (1, 1, 1, 'assigned', 'accepted')
    assert 'Identifying synthetic title' not in listing.text and 'author_id' not in listing.text
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT count(*) FROM review_assignments').scalar() == 1
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


def test_unauthorized_reviewer_and_configured_engine_guard(api_factory):
    client, actor, _ = api_factory('single')
    actor['id'] = 5
    assert client.get('/manuscripts/1').status_code == 404
    assert client.get('/manuscripts/1/progress').status_code == 404
    assert client.get('/assignments/my').json() == []
    with pytest.raises(AssertionError, match='forbidden'):
        configured_engine.connect()
    with pytest.raises(AssertionError, match='forbidden'):
        configured_engine.raw_connection()


@pytest.mark.parametrize('invitation', ['legacy', 'pending'])
def test_unresolved_policy_preserves_invitation_and_progress_authorization(api_factory, invitation):
    client, _, engine = api_factory('missing')
    with engine.begin() as connection:
        if invitation == 'legacy':
            connection.exec_driver_sql('DELETE FROM reviewer_invitations WHERE assignment_id=1')
        else:
            connection.exec_driver_sql("UPDATE reviewer_invitations SET status='pending' WHERE assignment_id=1")
    listing = client.get('/assignments/my')
    assert listing.status_code == 200 and listing.json()[0]['invitation_status'] == invitation
    assert 'Identifying synthetic title' not in listing.text
    assert client.get('/manuscripts/1/progress').status_code == (200 if invitation == 'legacy' else 404)
    assert client.get('/manuscripts/1').status_code == 404


def test_assignment_list_does_not_report_available_without_policy(api_factory, monkeypatch):
    client, _, _ = api_factory('missing')
    monkeypatch.setattr(assignments, 'resolve_assignment_file', lambda db, assignment, manuscript: 'synthetic')
    item, = client.get('/assignments/my').json()
    assert item['review_file_available'] is False and item['review_file_status'] == 'unavailable'
    assert 'synthetic' not in str(item)


@pytest.mark.parametrize('actor_id', [1, 3, 4])
def test_author_editor_and_eic_retain_detail_and_progress_metadata(api_factory, actor_id):
    client, actor, _ = api_factory('missing')
    actor['id'] = actor_id
    detail = client.get('/manuscripts/1')
    assert detail.status_code == 200 and detail.json()['author_id'] == 1
    assert set(detail.json()) == {'manuscript_id', 'title', 'abstract', 'author_id', 'status', 'created_at', 'has_pdf', 'file_type'}
    assert detail.json()['title'] == 'Identifying synthetic title'
    progress = client.get('/manuscripts/1/progress')
    assert progress.status_code == 200 and progress.json()['title'] == 'Identifying synthetic title'
    assert set(progress.json()) == {'manuscript_id', 'title', 'status', 'review_round', 'current_stage', 'next_action', 'stages', 'participant_task'}
    if actor_id in (1, 4):
        initial = next(stage for stage in progress.json()['stages'] if stage['name'] == 'Initial Editing')
        assert len(initial['steps']) == 6

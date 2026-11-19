"""Migration-free HTTP coverage of reviewer manuscript-detail redaction."""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, engine as configured_engine, get_db
from app.reviewer_metadata_gate import MetadataMode, reviewer_metadata_mode
from app.routers import assignments, manuscripts
from app.routers.users import get_current_user


@pytest.fixture
def isolated_api(monkeypatch):
    def block_database(*args, **kwargs):
        raise AssertionError('Configured database must not be accessed')
    monkeypatch.setattr(configured_engine, 'connect', block_database)
    monkeypatch.setattr(configured_engine, 'raw_connection', block_database)
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    @event.listens_for(engine, 'connect')
    def enable_fk(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    tables = [models.User, models.Manuscript, models.ReviewAssignment,
              models.ReviewerInvitation, models.ReviewerInvitationInvalidation,
              models.InitialEditorInvitation, models.FinalEditorInvitation]
    Base.metadata.create_all(engine, tables=[item.__table__ for item in tables])
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add_all([models.User(user_id=i, name=name, email=f'{i}@example.test', password_hash='x', role=role)
                    for i, name, role in [(1, 'Author', 'author'), (2, 'Reviewer', 'reviewer'),
                                          (3, 'Editor', 'editor'), (4, 'EIC', 'eic'), (5, 'Other', 'reviewer')]])
        db.commit()
        db.add(models.Manuscript(manuscript_id=1, author_id=1, title='Private synthetic title',
                                 abstract='Private synthetic abstract', status='ready_for_peer_review', review_round=1, created_at=now))
        db.commit()
        db.add(models.ReviewAssignment(assignment_id=1, manuscript_id=1, reviewer_id=2, assigned_by=3,
                                       review_round=1, status='assigned'))
        db.add(models.InitialEditorInvitation(invitation_id=1, manuscript_id=1, editor_id=3, invited_by=4, status='accepted'))
        db.commit()
        db.add(models.ReviewerInvitation(assignment_id=1, status='accepted'))
        db.commit()
    app = FastAPI()
    app.include_router(manuscripts.router)
    app.include_router(assignments.router)
    actor = {'id': 2}
    def session_override():
        with Session(engine) as db:
            yield db
    def user_override():
        with Session(engine) as db:
            return db.get(models.User, actor['id'])
    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[get_current_user] = user_override
    client = TestClient(app)
    yield client, actor, monkeypatch, app
    client.close()
    engine.dispose()


@pytest.mark.parametrize('mode', ['single_blind', 'double_blind'])
def test_reviewer_detail_returns_only_neutral_fields(isolated_api, mode):
    client, _, monkeypatch, _ = isolated_api
    monkeypatch.setattr('app.reviewer_metadata_gate.blind_policy_store.read_policy',
                        lambda raw, mid: {'mode': mode, 'locked_at': 'synthetic'})
    response = client.get('/manuscripts/1')
    assert response.status_code == 200
    expected = {'manuscript_id': 1, 'review_round': 1}
    if mode == 'single_blind':
        expected['author_name'] = 'Author'
    assert response.json() == expected
    assert response.headers['cache-control'] == 'no-store'
    assert not {'author_id', 'title', 'abstract'} & response.json().keys()


@pytest.mark.parametrize('policy', [None, {}, {'mode': 'invalid', 'locked_at': 'synthetic'},
                                   {'mode': 'single_blind', 'locked_at': None}])
def test_missing_invalid_or_unlocked_policy_fails_closed(isolated_api, policy):
    client, _, monkeypatch, _ = isolated_api
    monkeypatch.setattr('app.reviewer_metadata_gate.blind_policy_store.read_policy', lambda raw, mid: policy)
    response = client.get('/manuscripts/1')
    assert response.status_code == 404
    assert 'author_id' not in response.text
    assert 'Private synthetic' not in response.text


def test_missing_policy_schema_fails_closed(isolated_api):
    client, _, _, _ = isolated_api
    response = client.get('/manuscripts/1')
    assert response.status_code == 503
    assert 'Private synthetic' not in response.text


def test_inconsistent_policy_history_fails_closed(isolated_api):
    client, _, monkeypatch, _ = isolated_api
    from app.blind_policy_store import PolicyError
    def invalid_policy(*args):
        raise PolicyError('Synthetic inconsistent policy history')
    monkeypatch.setattr('app.reviewer_metadata_gate.blind_policy_store.read_policy', invalid_policy)
    response = client.get('/manuscripts/1')
    assert response.status_code == 404
    assert 'Private synthetic' not in response.text


def test_unassigned_reviewer_denied_before_policy_read(isolated_api):
    client, actor, monkeypatch, _ = isolated_api
    actor['id'] = 5
    def forbidden_policy(*args):
        raise AssertionError('Unauthorized reviewer must not read policy')
    monkeypatch.setattr('app.reviewer_metadata_gate.blind_policy_store.read_policy', forbidden_policy)
    assert client.get('/manuscripts/1').status_code == 404


@pytest.mark.parametrize('actor_id', [1, 3, 4])
def test_authorized_nonreviewers_keep_existing_details(isolated_api, actor_id):
    client, actor, _, _ = isolated_api
    actor['id'] = actor_id
    response = client.get('/manuscripts/1')
    assert response.status_code == 200
    assert response.json()['author_id'] == 1
    assert response.json()['title'] == 'Private synthetic title'
    assert response.json()['abstract'] == 'Private synthetic abstract'


def test_experimental_single_blind_detail_strips_author_even_from_legacy_dto(isolated_api):
    client, _, monkeypatch, app = isolated_api
    app.dependency_overrides[reviewer_metadata_mode] = lambda: MetadataMode.EXPERIMENTAL
    from app.blind_review_visibility import ReviewerSingleBlindDTO
    monkeypatch.setattr(manuscripts, 'reviewer_metadata_dto', lambda raw, mid, uid:
                        ReviewerSingleBlindDTO(manuscript_id=1, review_round=1, author_id=1, author_name='Author'))
    response = client.get('/manuscripts/1')
    assert response.status_code == 200
    assert response.json() == {'manuscript_id': 1, 'review_round': 1, 'author_name': 'Author'}


def test_experimental_single_blind_assignment_omits_author_id(isolated_api):
    client, _, monkeypatch, app = isolated_api
    app.dependency_overrides[reviewer_metadata_mode] = lambda: MetadataMode.EXPERIMENTAL
    from app.blind_review_visibility import ReviewerSingleBlindDTO
    monkeypatch.setattr('app.reviewer_metadata_gate._security_context', lambda raw, uid: None)
    monkeypatch.setattr('app.reviewer_metadata_gate.reviewer_metadata_dto', lambda raw, mid, uid:
                        ReviewerSingleBlindDTO(manuscript_id=1, review_round=1, author_id=1, author_name='Author'))
    response = client.get('/assignments/my')
    assert response.status_code == 200
    assert response.json() == [{'assignment_id': 1, 'manuscript_id': 1, 'review_round': 1,
                                'status': 'assigned', 'invitation_status': 'accepted',
                                'review_file_available': False, 'review_file_status': 'unavailable'}]

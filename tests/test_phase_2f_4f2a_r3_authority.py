"""Bearer-based scope checks using synthetic users and isolated SQLite."""
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app import models
from app.database import Base
from app.security import create_access_token
from app.source_authority import authorize_source_scope
from app import source_policy_foundation
from app.source_policy_foundation import FoundationUnavailable, capture
from tests.test_phase_2f_4f2a_foundation import context
from tests.test_phase_2f_policy_management import policy_api
from tests.test_phase_2f_reviewer_projections import api_factory


@pytest.fixture
def scope_fixture(policy_api):
    _, _, engine = policy_api
    Base.metadata.create_all(engine, tables=[models.UserEmailVerification.__table__])
    with Session(engine) as db:
        db.add(models.InitialEditorInvitation(manuscript_id=2, editor_id=3, invited_by=4, status='accepted'))
        db.add(models.Manuscript(manuscript_id=3, author_id=1, title='Other synthetic', abstract='Synthetic', status='revised', review_round=2))
        db.add(models.User(user_id=9, name='Formatter', email='formatter@example.test', password_hash='x', role='formatter'))
        db.commit()
    return engine


def credentials(user_id):
    return HTTPAuthorizationCredentials(scheme='Bearer', credentials=create_access_token(user_id))


@pytest.mark.parametrize('actor_id', [4, 3])
def test_real_synthetic_bearer_authorizes_eic_and_assigned_editor(scope_fixture, actor_id):
    with Session(scope_fixture) as db:
        assert authorize_source_scope(db, credentials(actor_id), 2).user_id == actor_id


@pytest.mark.parametrize('actor_id', [1, 2, 5, 9])
def test_other_roles_denied_with_eic_positive_control(scope_fixture, actor_id):
    with Session(scope_fixture) as db:
        assert authorize_source_scope(db, credentials(4), 2).role == 'eic'
        with pytest.raises(HTTPException) as denied:
            authorize_source_scope(db, credentials(actor_id), 2)
        assert denied.value.status_code == 403


def test_editor_wrong_manuscript_and_invalid_token_denied(scope_fixture):
    with Session(scope_fixture) as db:
        assert authorize_source_scope(db, credentials(3), 2).role == 'editor'
        with pytest.raises(HTTPException) as denied:
            authorize_source_scope(db, credentials(3), 3)
        assert denied.value.status_code == 403
        with pytest.raises(HTTPException) as unauthenticated:
            authorize_source_scope(db, HTTPAuthorizationCredentials(scheme='Bearer', credentials='invalid'), 2)
        assert unauthenticated.value.status_code == 401


def test_pending_orm_changes_not_flushed(scope_fixture):
    with Session(scope_fixture) as db:
        assert authorize_source_scope(db, credentials(4), 2).role == 'eic'
        db.get(models.Manuscript, 2).title = 'uncommitted synthetic'
        with pytest.raises(HTTPException) as denied:
            authorize_source_scope(db, credentials(4), 2)
        assert denied.value.status_code == 503 and db.dirty
        db.rollback()
        assert db.get(models.Manuscript, 2).title != 'uncommitted synthetic'


def test_source_mutation_between_proof_and_snapshot_denied(context, monkeypatch):
    _, engine, path, content, proof = context
    with Session(engine) as db:
        assert capture(db, db.get(models.User, 4), 2, 2, 1, proof_adapter=proof).source_id == 2
        db.rollback()
        class MutatingProof:
            def verify_prospective(self, *args):
                result = proof.verify_prospective(*args)
                path.write_bytes(content.upper())
                return result
        adapter = MutatingProof()
        monkeypatch.setattr(source_policy_foundation, '_server_proof_adapter', lambda: adapter)
        with pytest.raises(FoundationUnavailable, match='proof mismatch'):
            capture(db, db.get(models.User, 4), 2, 2, 1, proof_adapter=adapter)

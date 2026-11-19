"""FastAPI authentication and authority checks with in-memory synthetic data."""
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main_reviewer_authority import AuthorityUnavailable
from app.main_reviewer_dependencies import reviewer_authority, editorial_authority
from app.models import User, UserEmailVerification
from app.routers.users import get_current_user
from app.security import create_access_token


@pytest.fixture
def client():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    User.__table__.create(engine)
    UserEmailVerification.__table__.create(engine)
    with engine.begin() as c:
        for sql in (
            'CREATE TABLE account_lifecycle (user_id INTEGER, state TEXT, sequence INTEGER, auth_generation INTEGER, last_event_id TEXT)',
            'CREATE TABLE account_lifecycle_events (user_id INTEGER, event_id TEXT, sequence INTEGER, from_state TEXT, to_state TEXT, auth_generation INTEGER)',
            'CREATE TABLE manuscripts (manuscript_id INTEGER, status TEXT, review_round INTEGER)',
            'CREATE TABLE review_assignments (assignment_id INTEGER, manuscript_id INTEGER, reviewer_id INTEGER, status TEXT, review_round INTEGER)',
            'CREATE TABLE reviewer_invitations (assignment_id INTEGER, status TEXT)',
            'CREATE TABLE reviewer_invitation_invalidations (assignment_id INTEGER)',
        ): c.exec_driver_sql(sql)
        c.exec_driver_sql("INSERT INTO users(user_id,name,email,password_hash,role,created_at) VALUES (1,'R','r@example.invalid','x','reviewer','2020-01-01'),(2,'E','e@example.invalid','x','eic','2020-01-01')")
        c.exec_driver_sql("INSERT INTO account_lifecycle VALUES (1,'active',1,1,'r'),(2,'active',1,1,'e')")
        c.exec_driver_sql("INSERT INTO account_lifecycle_events VALUES (1,'r',1,NULL,'active',1),(2,'e',1,NULL,'active',1)")
        c.exec_driver_sql("INSERT INTO manuscripts VALUES (7,'ready_for_peer_review',1),(8,'draft',1)")
        c.exec_driver_sql("INSERT INTO review_assignments VALUES (9,7,1,'assigned',1)")
        c.exec_driver_sql("INSERT INTO reviewer_invitations VALUES (9,'accepted')")
    app = FastAPI()
    def db_override():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    @app.get('/scope/{manuscript_id}')
    def reviewer_scope(manuscript_id: int, principal=Depends(get_current_user), authority=Depends(reviewer_authority), db=Depends(get_db)):
        raw = db.connection().connection.driver_connection
        if not raw.in_transaction: raw.execute('BEGIN')
        try: return {'actor': authority.authorize(raw, principal, 'read_artifact', manuscript_id)}
        except AuthorityUnavailable: raise HTTPException(403, 'Unavailable') from None
    @app.get('/editor/{manuscript_id}')
    def editorial_scope(manuscript_id: int, principal=Depends(get_current_user), authority=Depends(editorial_authority), db=Depends(get_db)):
        raw = db.connection().connection.driver_connection
        if not raw.in_transaction: raw.execute('BEGIN')
        try: return {'actor': authority.authorize(raw, principal, 'bind', manuscript_id)}
        except AuthorityUnavailable: raise HTTPException(403, 'Unavailable') from None
    with TestClient(app) as c:
        yield c
    engine.dispose()


def test_real_token_reviewer_scope_and_authentication(client):
    reviewer = {'Authorization': 'Bearer ' + create_access_token(1)}
    assert client.get('/scope/7', headers=reviewer).json() == {'actor': 1}
    assert client.get('/scope/8', headers=reviewer).status_code == 403
    assert client.get('/scope/7').status_code == 401
    assert client.get('/scope/7', headers={'Authorization': 'Bearer invalid'}).status_code == 401
    assert client.get('/editor/7', headers=reviewer).status_code == 403


def test_real_token_eic_scope(client):
    eic = {'Authorization': 'Bearer ' + create_access_token(2)}
    assert client.get('/editor/7', headers=eic).json() == {'actor': 2}
    assert client.get('/editor/8', headers=eic).status_code == 403
    assert client.get('/scope/7', headers=eic).status_code == 403

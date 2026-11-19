"""Actual APIs with disposable databases and synthetic review files only."""
from pathlib import Path
import os
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from database.bootstrap.initialize import initialize
from app import blind_policy_store, review_files
from app.database import get_db
from app.main import app
from app.security import create_access_token, hash_password

STAMP = '2026-01-01T00:00:00.000000Z'

@pytest.fixture
def environment(monkeypatch):
    dbpath = initialize('phase26-' + uuid4().hex + '.sqlite')
    data_root = Path.cwd() / '.test-data' / ('files-' + uuid4().hex)
    data_root.mkdir(mode=0o700)
    source = data_root / 'uploads/manuscripts/1/revision.txt'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'Synthetic reviewed manuscript content.')
    monkeypatch.setattr(review_files, 'BASE_DIR', data_root)
    raw = sqlite3.connect(dbpath)
    raw.execute('PRAGMA foreign_keys=ON')
    password = hash_password('isolated-fixture-password')
    for uid, role in [(1,'author'),(2,'reviewer'),(3,'eic'),(4,'editor'),(5,'reviewer')]:
        raw.execute('INSERT INTO users(user_id,name,email,password_hash,role,created_at) VALUES (?,?,?,?,?,?)',
                    (uid, role, f'{uid}@example.com', password, role, STAMP))
    for uid in (2,5):
        event_id = f'active-{uid}'
        raw.execute('INSERT INTO account_lifecycle_events VALUES (?,?,?,?,?,?,?,?,?)',
                    (event_id,uid,1,None,'active',1,3,STAMP,'initial_enrollment'))
        raw.execute('INSERT INTO account_lifecycle VALUES (?,?,?,?,?)', (uid,'active',1,1,event_id))
    for mid in (1,2):
        raw.execute('INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,created_at,file_path) VALUES (?,?,?,?,?,?,?,?)',
                    (mid,'Synthetic','Synthetic',1,'ready_for_peer_review',2,STAMP,'uploads/manuscripts/1/revision.txt'))
    raw.commit()
    for mid,mode in [(1,'single_blind'),(2,'double_blind')]:
        blind_policy_store.begin_write(raw)
        blind_policy_store.select_mode(raw,mid,mode,3)
        raw.execute('INSERT INTO review_assignments(assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (?,?,?,?,?,?,?)', (mid,mid,2,3,2,'assigned',STAMP))
        raw.execute('INSERT INTO reviewer_invitations(assignment_id,status,invited_at) VALUES (?,?,?)', (mid,'accepted',STAMP))
        blind_policy_store.lock_mode(raw,mid,mid,3,1)
        raw.commit()
        raw.execute('INSERT INTO review_round_files(round_file_id,manuscript_id,review_round,source_kind,confirmation_id,file_path,created_at) VALUES (?,?,?,?,?,?,?)', (mid,mid,2,'author_revision',None,'uploads/manuscripts/1/revision.txt',STAMP))
        raw.execute('INSERT INTO review_assignment_files(assignment_id,round_file_id,bound_at) VALUES (?,?,?)',(mid,mid,STAMP))
        raw.commit()
    raw.close()
    engine = create_engine('sqlite:///' + str(dbpath), connect_args={'check_same_thread': False})
    @event.listens_for(engine, 'connect')
    def enable_fk(connection, _): connection.execute('PRAGMA foreign_keys=ON')
    def override():
        with Session(engine) as session: yield session
    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client, dbpath, source
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def auth(uid): return {'Authorization': 'Bearer ' + create_access_token(uid)}


def test_single_blind_positive_double_blind_and_cross_actor_denial(environment):
    client, _, source = environment
    good = client.get('/assignments/1/download', headers=auth(2))
    assert good.status_code == 200 and good.content == source.read_bytes()
    double = client.get('/assignments/2/download', headers=auth(2))
    assert double.status_code == 409 and source.read_bytes() not in double.content
    assert client.get('/assignments/1/download', headers=auth(5)).status_code == 409
    assert client.get('/assignments/1/download', headers=auth(1)).status_code == 403


def test_revoked_assignment_cannot_download(environment):
    client, dbpath, source = environment
    assert client.get('/assignments/1/download', headers=auth(2)).content == source.read_bytes()
    with sqlite3.connect(dbpath) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('INSERT INTO reviewer_invitation_invalidations VALUES (?,?,?,?,?,?,?)',
                   ('revocation-1',1,'cancelled',None,3,STAMP,'editorial_cancellation'))
    denied = client.get('/assignments/1/download', headers=auth(2))
    assert denied.status_code == 409 and source.read_bytes() not in denied.content


def test_author_authentication_positive_and_negative(environment):
    client, _, _ = environment
    ok = client.post('/users/login', json={'email':'1@example.com','password':'isolated-fixture-password'})
    assert ok.status_code == 200 and ok.json().get('access_token')
    assert client.post('/users/login', json={'email':'1@example.com','password':'incorrect'}).status_code == 401


def test_author_editor_eic_final_editor_and_formatter_visibility(environment):
    client, dbpath, _ = environment
    with sqlite3.connect(dbpath) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute("INSERT INTO users(user_id,name,email,password_hash,role,created_at) VALUES (6,'Formatter','6@example.com','x','formatter',?)", (STAMP,))
        db.execute("INSERT INTO initial_editor_invitations(invitation_id,manuscript_id,editor_id,invited_by,status,invited_at) VALUES (1,1,4,3,'accepted',?)", (STAMP,))
        db.execute("INSERT INTO final_editor_invitations(invitation_id,manuscript_id,editor_id,invited_by,status,invited_at) VALUES (1,1,4,3,'accepted',?)", (STAMP,))
        db.execute("INSERT INTO final_editing_submissions(submission_id,manuscript_id,editor_id,file_path,comments,status,created_at) VALUES (1,1,4,'synthetic.txt','synthetic','eic_approved',?)", (STAMP,))
        db.execute("INSERT INTO formatter_invitations(invitation_id,manuscript_id,formatter_id,invited_by,final_submission_id,status,invited_at) VALUES (1,1,6,3,1,'accepted',?)", (STAMP,))
    assert client.get('/manuscripts/my', headers=auth(1)).status_code == 200
    assert client.get('/eic/initial-editing/my', headers=auth(4)).status_code == 200
    assert client.get('/eic/editors', headers=auth(3)).status_code == 200
    assert client.get('/eic/editors', headers=auth(1)).status_code == 403
    assert client.get('/final-workflow/my', headers=auth(4)).status_code == 200
    assert client.get('/final-workflow/my', headers=auth(2)).status_code == 403
    assert client.get('/formatting/my', headers=auth(6)).status_code == 200
    assert client.get('/formatting/manuscripts/1', headers=auth(4)).status_code == 403


def test_pending_invitation_and_wrong_round_denied(environment):
    client, dbpath, source = environment
    assert client.get('/assignments/1/download', headers=auth(2)).content == source.read_bytes()
    with sqlite3.connect(dbpath) as db:
        db.execute("UPDATE reviewer_invitations SET status='pending' WHERE assignment_id=1")
    assert client.get('/assignments/1/download', headers=auth(2)).status_code == 409
    with sqlite3.connect(dbpath) as db:
        db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=1")
    assert client.get('/assignments/1/download', headers=auth(2)).status_code == 200
    with sqlite3.connect(dbpath) as db:
        db.execute('UPDATE review_assignments SET review_round=3 WHERE assignment_id=1')
    assert client.get('/assignments/1/download', headers=auth(2)).status_code == 409


def test_main_review_policy_route_fails_closed_and_requires_eic(environment):
    client, _, source = environment
    assert client.get('/assignments/1/download', headers=auth(2)).content == source.read_bytes()
    assert client.get('/assignments/review-policy/1', headers=auth(3)).status_code == 404
    assert client.get('/assignments/review-policy/1', headers=auth(1)).status_code == 403
    assert client.put('/assignments/review-policy/1', headers=auth(3), json={'mode':'single_blind'}).status_code == 404

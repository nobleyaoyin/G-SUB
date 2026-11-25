"""Role-filtered timeline tests using synthetic, in-memory SQLite only."""
from datetime import datetime, timezone
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.models import (User, Manuscript, ReviewAssignment, ReviewerInvitation, Review,
    EICInitialScan, InitialEditorInvitation, InitialEditingSubmission,
    FinalEditorInvitation, FinalEditingSubmission, FinalEditingSubmissionInvitation,
    FormatterInvitation, FormattingSubmission)
from app.routers.manuscripts import router
from app.routers.users import get_current_user


@pytest.fixture
def timeline():
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    @event.listens_for(engine, 'connect')
    def fk(db, _): db.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    stamp = datetime(2026,1,1,tzinfo=timezone.utc)
    with Session(engine) as db:
        for uid, role in [(1,'author'),(2,'reviewer'),(3,'editor'),(4,'eic'),(5,'reviewer'),(6,'formatter'),(7,'author')]:
            db.add(User(user_id=uid, name=f'Person {uid}', email=f'{uid}@example.test', password_hash='synthetic', role=role))
        db.flush()
        db.add_all([Manuscript(manuscript_id=1,title='Private title',abstract='Private abstract',author_id=1,status='ready_for_peer_review',review_round=1,created_at=stamp),
                    Manuscript(manuscript_id=2,title='Other title',abstract='Other abstract',author_id=7,status='submitted',review_round=1,created_at=stamp)])
        db.flush()
        db.add_all([InitialEditorInvitation(invitation_id=1,manuscript_id=1,editor_id=3,invited_by=4,status='accepted',invited_at=stamp,responded_at=stamp),
                    EICInitialScan(scan_id=1,manuscript_id=1,eic_id=4,decision='pass',comments='PRIVATE SCREENING',created_at=stamp),
                    ReviewAssignment(assignment_id=1,manuscript_id=1,reviewer_id=2,assigned_by=3,review_round=1,status='assigned',assigned_at=stamp),
                    ReviewAssignment(assignment_id=2,manuscript_id=1,reviewer_id=5,assigned_by=3,review_round=1,status='assigned',assigned_at=stamp)])
        db.flush()
        db.add_all([ReviewerInvitation(assignment_id=1,status='accepted',invited_at=stamp,responded_at=stamp),
                    ReviewerInvitation(assignment_id=2,status='accepted',invited_at=stamp,responded_at=stamp),
                    Review(review_id=1,assignment_id=1,comments='PRIVATE REVIEW ONE',recommendation='accept',submitted_at=stamp),
                    Review(review_id=2,assignment_id=2,comments='PRIVATE REVIEW TWO',recommendation='reject',submitted_at=stamp)])
        db.commit()
    actor={'id':1}
    def get_session():
        with Session(engine) as session: yield session
    def current(db=Depends(get_db)): return db.get(User,actor['id'])
    app=FastAPI(); app.include_router(router); app.dependency_overrides[get_db]=get_session; app.dependency_overrides[get_current_user]=current
    with TestClient(app) as client: yield client,actor,engine,stamp
    engine.dispose()


def test_role_scoping_order_and_no_private_content(timeline):
    client, actor, _, _ = timeline
    author=client.get('/manuscripts/1/timeline'); assert author.status_code==200
    assert author.headers['cache-control']=='no-store'
    events=author.json()['events']; assert events and all(e['timestamp'] for e in events)
    assert [e['key'] for e in events] == sorted([e['key'] for e in events],reverse=True)
    assert 'PRIVATE' not in str(author.json()) and 'reviewer_id' not in str(author.json())
    actor['id']=2
    own=client.get('/manuscripts/1/timeline'); assert own.status_code==200
    assert {e['description'] for e in own.json()['events']} == {'Review invitation received','Invitation accepted','Review submitted'}
    assert 'PRIVATE' not in str(own.json()) and 'Person 5' not in str(own.json())
    actor['id']=3
    editor=client.get('/manuscripts/1/timeline'); assert editor.status_code==200
    assert any(e['description']=='Initial editor invited' for e in editor.json()['events'])
    assert 'PRIVATE' not in str(editor.json())
    actor['id']=7
    assert client.get('/manuscripts/1/timeline').status_code==404
    assert client.get('/manuscripts/2/timeline').status_code==200


def test_formatter_only_own_events_and_assignment_gate(timeline):
    client, actor, engine, stamp = timeline
    actor['id']=6; assert client.get('/manuscripts/1/timeline').status_code==404
    with Session(engine) as db:
        m=db.get(Manuscript,1); m.status='formatting'
        db.add(FinalEditorInvitation(invitation_id=3,manuscript_id=1,editor_id=3,invited_by=4,status='accepted',invited_at=stamp))
        db.add(FinalEditingSubmission(submission_id=1,manuscript_id=1,editor_id=3,file_path='synthetic.pdf',comments='PRIVATE FINAL',status='author_approved',author_reviewed_at=stamp,eic_reviewed_at=stamp,eic_approved_by=4,created_at=stamp))
        db.flush(); db.add(FinalEditingSubmissionInvitation(submission_id=1,invitation_id=3)); db.flush()
        db.add(FormatterInvitation(invitation_id=1,manuscript_id=1,formatter_id=6,invited_by=4,final_submission_id=1,status='accepted',invited_at=stamp,responded_at=stamp));db.flush()
        db.add(FormattingSubmission(submission_id=1,manuscript_id=1,invitation_id=1,file_path='synthetic.pdf',sha256='a'*64,status='pending_author',comments='PRIVATE FORMATTING',created_at=stamp));db.commit()
    result=client.get('/manuscripts/1/timeline'); assert result.status_code==200,result.text
    assert {e['stage'] for e in result.json()['events']} == {'Formatting'}
    assert 'PRIVATE' not in str(result.json())
    actor['id']=2; assert client.get('/manuscripts/1/timeline').status_code==404

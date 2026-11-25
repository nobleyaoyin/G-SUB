"""Invitation preview tests use only synthetic in-memory records and bearer tokens."""
import json
import os
os.environ.setdefault('SECRET_KEY', 'synthetic-test-secret-at-least-32-bytes')
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.models import User, Manuscript, InitialEditorInvitation, FinalEditorInvitation, EICDecision, AuthorAgreement
from app.security import create_access_token
from app.routers import eic, final_workflow
from app.ai_prescreening import analyze_txt
from app.editor_invitation_metadata import invitation_metadata


def test_scoped_bearer_invitation_preview_from_real_advisory_records():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.exec_driver_sql('CREATE TABLE manuscript_submission_snapshots (snapshot_id TEXT, manuscript_id INTEGER, submission_kind TEXT, review_round INTEGER, submission_sequence INTEGER, file_format TEXT, file_sha256 TEXT, submitted_at TEXT)')
        c.exec_driver_sql('CREATE TABLE ai_prescreening_jobs (job_id TEXT, snapshot_id TEXT, status TEXT)')
        c.exec_driver_sql('CREATE TABLE ai_prescreening_reports (job_id TEXT, snapshot_id TEXT, engine TEXT, findings_json TEXT, created_at TEXT)')
    session=sessionmaker(bind=engine,expire_on_commit=False)()
    people={role:User(name=role,email=role+'@example.invalid',password_hash='synthetic',role=('editor' if role=='other' else role)) for role in ('author','editor','other','reviewer','eic')}
    session.add_all(people.values());session.flush()
    a=Manuscript(title='Synthetic initial',abstract='private abstract',author_id=people['author'].user_id,status='initial_editor_invited',review_round=1,file_path='private/never-expose.txt')
    b=Manuscript(title='Synthetic final',abstract='private final abstract',author_id=people['author'].user_id,status='final_editing',review_round=1,file_path='private/never-expose.docx')
    session.add_all([a,b]);session.flush()
    decision=EICDecision(manuscript_id=b.manuscript_id,eic_id=people['eic'].user_id,review_round=1,decision='accept',comments='synthetic')
    session.add(decision);session.flush()
    from datetime import datetime, timezone
    agreement=AuthorAgreement(manuscript_id=b.manuscript_id,decision_id=decision.decision_id,author_id=people['author'].user_id,agreement_version='synthetic',agreement_text='synthetic',status='accepted',responded_at=datetime.now(timezone.utc))
    session.add(agreement)
    initial=InitialEditorInvitation(manuscript_id=a.manuscript_id,editor_id=people['editor'].user_id,invited_by=people['eic'].user_id,status='pending')
    final=FinalEditorInvitation(manuscript_id=b.manuscript_id,editor_id=people['editor'].user_id,invited_by=people['eic'].user_id,status='pending')
    session.add_all([initial,final]);session.flush()
    for m in (a,b):
        report=analyze_txt(b'One two three four')
        session.execute(text('INSERT INTO manuscript_submission_snapshots VALUES (:id,:mid,:kind,1,1,:fmt,:digest,:date)'),{'id':str(m.manuscript_id),'mid':m.manuscript_id,'kind':'initial','fmt':'txt','digest':'private-digest','date':'2026-01-01'})
        session.execute(text('INSERT INTO ai_prescreening_jobs VALUES (:id,:id,:status)'),{'id':str(m.manuscript_id),'status':'completed'})
        session.execute(text('INSERT INTO ai_prescreening_reports VALUES (:id,:id,:engine,:findings,:date)'),{'id':str(m.manuscript_id),'engine':'local_rules_v1','findings':json.dumps(report),'date':'2026-01-01'})
    session.commit()
    app=FastAPI();app.include_router(eic.router);app.include_router(final_workflow.router)
    app.dependency_overrides[get_db]=lambda:session
    headers=lambda user:{'Authorization':'Bearer '+create_access_token(user.user_id)}
    with TestClient(app) as client:
        for url in ('/eic/initial-editing/my','/final-workflow/my'):
            response=client.get(url,headers=headers(people['editor']));assert response.status_code==200
            row=response.json()[0]; meta=row['invitation_metadata']
            assert meta['word_count']==4 and 'TXT' in meta['word_count_source']
            assert meta['excerpt'] is None and meta['figure_count'] is None and meta['table_count'] is None
            assert row['invitation_abstract'] is None and row['submissions']==[]
            assert 'private-digest' not in response.text and 'never-expose' not in response.text and 'private abstract' not in response.text
            assert client.get(url,headers=headers(people['other'])).json()==[]
            assert client.get(url,headers=headers(people['reviewer'])).status_code==403
        # Authors retain their own existing list, but receive no editor metadata.
        assert all(row['invitation_metadata'] is None for row in client.get('/eic/initial-editing/my',headers=headers(people['author'])).json())
        agreement.status='declined';session.commit()
        assert client.get('/final-workflow/my',headers=headers(people['editor'])).json()[0]['invitation_metadata'] is None
        agreement.status='accepted';session.commit()
        initial.status='declined';final.status='declined';session.commit()
        assert client.get('/eic/initial-editing/my',headers=headers(people['editor'])).json()==[]
        assert client.get('/final-workflow/my',headers=headers(people['editor'])).json()[0]['invitation_metadata'] is None
    session.close();engine.dispose()


@pytest.mark.parametrize('change', ['stale','unsupported','pending','bad_count','wrong_engine','no_analysis'])
def test_unreliable_or_unsupported_counts_fail_closed(monkeypatch,change):
    report={'review_round':1,'status':'completed','file_format':'txt','analysis':{'engine':'local_rules_v1','advisory_only':True,'format':'txt','word_count':4}}
    if change=='stale':report['review_round']=2
    if change=='unsupported':report['file_format']='pdf'
    if change=='pending':report['status']='pending'
    if change=='bad_count':report['analysis']['word_count']=True
    if change=='wrong_engine':report['analysis']['engine']='unknown'
    if change=='no_analysis':report['analysis']=None
    monkeypatch.setattr('app.editor_invitation_metadata.list_manuscript_ai_reports',lambda *_:[report])
    assert invitation_metadata(None,Manuscript(manuscript_id=1,review_round=1))['word_count'] is None

"""Migration-free listing authorization checks in an isolated SQLite fixture."""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app import models
from tests.test_phase_2f_reviewer_projections import api_factory


def test_eic_list_excludes_drafts_and_editor_cannot_open_unassigned(api_factory):
    client, actor, engine = api_factory('missing')
    with Session(engine) as db:
        db.add_all([
            models.Manuscript(manuscript_id=2,author_id=1,title='Synthetic submitted',abstract='Synthetic',status='submitted',review_round=1,created_at=datetime.now(timezone.utc)),
            models.Manuscript(manuscript_id=3,author_id=1,title='Private draft',abstract='Synthetic',status='draft',review_round=1,created_at=datetime.now(timezone.utc)),
        ])
        db.commit()
    actor['id']=4
    response=client.get('/manuscripts/')
    assert response.status_code == 200
    assert {item['manuscript_id'] for item in response.json()} == {1,2}
    assert client.get('/manuscripts/2').status_code == 200
    assert client.get('/manuscripts/3').status_code == 404
    actor['id']=3
    assert {item['manuscript_id'] for item in client.get('/manuscripts/').json()} == {1}
    assert client.get('/manuscripts/1').status_code == 200
    assert client.get('/manuscripts/2').status_code == 404
    actor['id']=1
    assert client.get('/manuscripts/').status_code == 403


def test_status_filter_remains_within_authorized_non_draft_records(api_factory):
    client, actor, engine = api_factory('missing')
    with Session(engine) as db:
        db.add_all([
            models.Manuscript(manuscript_id=2, author_id=1, title='Synthetic submitted', abstract='Synthetic', status='submitted', review_round=1, created_at=datetime.now(timezone.utc)),
            models.Manuscript(manuscript_id=3, author_id=1, title='Synthetic draft', abstract='Synthetic', status='draft', review_round=1, created_at=datetime.now(timezone.utc)),
        ])
        db.commit()
    actor['id'] = 4
    result = client.get('/manuscripts/', params={'status': 'submitted'})
    assert result.status_code == 200
    assert {item['manuscript_id'] for item in result.json()} == {2}
    drafts = client.get('/manuscripts/', params={'status': 'draft'})
    assert drafts.status_code == 200 and drafts.json() == []
    actor['id'] = 1
    assert client.get('/manuscripts/', params={'status': 'submitted'}).status_code == 403

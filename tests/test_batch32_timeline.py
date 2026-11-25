"""Reviewer timeline boundaries on disposable synthetic SQLite."""
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.models import ReviewAssignment, ReviewerInvitation, ReviewerInvitationInvalidation
from test_batch29_timeline import timeline  # noqa: F401


def test_legacy_assignment_and_round_boundary(timeline):
    client, actor, engine, _ = timeline
    with Session(engine) as db:
        db.delete(db.get(ReviewerInvitation, 1))
        db.commit()
    actor['id'] = 2
    response = client.get('/manuscripts/1/timeline')
    assert response.status_code == 200
    assert all(e['review_round'] == 1 for e in response.json()['events'])
    assert 'PRIVATE' not in response.text and 'Person 5' not in response.text
    assert client.get('/manuscripts/2/timeline').status_code == 404
    actor['id'] = 5
    assert client.get('/manuscripts/1/timeline').status_code == 200


def test_superseded_assignment_is_denied(timeline):
    client, actor, engine, _ = timeline
    with Session(engine) as db:
        db.add(ReviewerInvitationInvalidation(invalidation_id='synthetic-replacement', assignment_id=1,
            kind='superseded', replacement_assignment_id=2, actor_user_id=4,
            occurred_at='2026-01-01T00:00:00.000000Z', reason_code='replacement_selected'))
        db.commit()
    actor['id'] = 2
    assert client.get('/manuscripts/1/timeline').status_code == 404
    actor['id'] = 5
    assert client.get('/manuscripts/1/timeline').status_code == 200


def test_invalidation_storage_failure_is_closed(timeline, monkeypatch):
    import app.manuscript_timeline as module
    client, actor, _, _ = timeline
    actor['id'] = 2
    assert client.get('/manuscripts/1/timeline').status_code == 200
    def unavailable(*_args):
        raise SQLAlchemyError('synthetic storage failure')
    monkeypatch.setattr(module, 'reviewer_timeline_assignments', unavailable)
    response = client.get('/manuscripts/1/timeline')
    assert response.status_code == 503
    assert 'synthetic storage failure' not in response.text

"""Timeline events and reviewer states; isolated synthetic SQLite only."""
from datetime import timedelta
import pytest
from sqlalchemy.orm import Session
from app.models import InitialEditingSubmission, Notification, ReviewAssignment, ReviewerInvitation, ReviewerInvitationInvalidation
from test_batch29_timeline import timeline  # noqa: F401


def test_transaction_recorded_submission_initial_revision_and_editing_reviews(timeline):
    client, actor, engine, stamp = timeline
    with Session(engine) as db:
        db.add_all([
            Notification(user_id=4, manuscript_id=1, notification_type='manuscript_submitted', message='PRIVATE', created_at=stamp),
            Notification(user_id=3, manuscript_id=1, notification_type='manuscript_submitted', message='PRIVATE', created_at=stamp + timedelta(seconds=1)),
            Notification(user_id=4, manuscript_id=1, notification_type='initial_resubmission', message='PRIVATE', created_at=stamp + timedelta(minutes=1)),
            InitialEditingSubmission(submission_id=1, manuscript_id=1, editor_id=3, file_path='private-file', comments='PRIVATE', status='author_revision_requested', created_at=stamp, reviewed_at=stamp + timedelta(minutes=2)),
        ])
        db.commit()
    response = client.get('/manuscripts/1/timeline')
    assert response.status_code == 200
    descriptions = [item['description'] for item in response.json()['events']]
    assert descriptions.count('Manuscript submitted') == 1
    assert descriptions.count('Manuscript resubmitted for initial screening') == 1
    assert descriptions.count('Author reviewed initial editing') == 1
    submitted = next(item for item in response.json()['events'] if item['description'] == 'Manuscript submitted')
    resubmitted = next(item for item in response.json()['events'] if item['description'] == 'Manuscript resubmitted for initial screening')
    assert submitted['timestamp'].startswith('2026-01-01T00:00:00')
    assert resubmitted['timestamp'].startswith('2026-01-01T00:01:00')
    assert 'PRIVATE' not in response.text and 'private-file' not in response.text
    actor['id'] = 3
    result = client.get('/manuscripts/1/timeline')
    assert result.status_code == 200
    assert any(e['description'] == 'Author reviewed initial editing' for e in result.json()['events'])
    assert not any(e['description'] == 'Manuscript submitted' for e in result.json()['events'])


@pytest.mark.parametrize(('invitation_status', 'assignment_status', 'expected'), [
    ('pending', 'assigned', 404), ('declined', 'assigned', 404),
    ('accepted', 'assigned', 200), ('accepted', 'completed', 200),
])
def test_reviewer_invitation_and_completion_states(timeline, invitation_status, assignment_status, expected):
    client, actor, engine, _ = timeline
    with Session(engine) as db:
        db.get(ReviewerInvitation, 1).status = invitation_status
        db.get(ReviewAssignment, 1).status = assignment_status
        db.commit()
    actor['id'] = 2
    result = client.get('/manuscripts/1/timeline')
    assert result.status_code == expected
    if expected == 200:
        assert 'PRIVATE' not in result.text and 'Person 5' not in result.text
    actor['id'] = 5
    assert client.get('/manuscripts/1/timeline').status_code == 200


def test_invalidated_reviewer_is_denied_with_other_reviewer_positive_control(timeline):
    client, actor, engine, _ = timeline
    with Session(engine) as db:
        db.add(ReviewerInvitationInvalidation(invalidation_id='synthetic-cancel', assignment_id=1,
            kind='cancelled', actor_user_id=4, occurred_at='2026-01-01T00:00:00.000000Z',
            reason_code='editorial_cancellation'))
        db.commit()
    actor['id'] = 2
    assert client.get('/manuscripts/1/timeline').status_code == 404
    actor['id'] = 5
    assert client.get('/manuscripts/1/timeline').status_code == 200

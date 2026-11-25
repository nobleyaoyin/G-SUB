"""Ordinary progress cannot be read through an invalidated assignment."""
from app import models
from tests import test_reviewer_download as fixtures


def test_ordinary_progress_rechecks_recorded_invalidation():
    f = fixtures.ReviewerDownloadsTest(); f.setUp()
    try:
        assignment = models.ReviewAssignment(manuscript_id=f.mid, reviewer_id=f.reviewer.user_id,
            assigned_by=f.editor.user_id, review_round=1, status='assigned')
        f.db.add(assignment); f.db.flush()
        f.db.add(models.ReviewerInvitation(assignment_id=assignment.assignment_id, status='accepted'))
        f.db.commit(); f.current = f.reviewer
        url = f'/manuscripts/{f.mid}/progress'
        response = f.client.get(url); assert response.status_code == 200
        assert all('steps' not in item for item in response.json()['stages'])
        # Corrupt/legacy fixture evidence is a starting state, not an application transition.
        f.db.add(models.ReviewerInvitationInvalidation(invalidation_id='sprint414-cancel', assignment_id=assignment.assignment_id,
            kind='cancelled', actor_user_id=f.editor.user_id,
            occurred_at='2026-01-01T00:00:00.000000Z', reason_code='editorial_cancellation'))
        f.db.commit()
        assert f.client.get(url).status_code == 404
        assert f.client.get(f'/manuscripts/{f.mid}/timeline').status_code == 404
        f.current = f.author
        author = f.client.get(url); assert author.status_code == 200
        assert len([item for item in author.json()['stages'] if item.get('steps')]) == 10
        assert next(item for item in author.json()['stages'] if item['name'] == 'Proofing')['steps'][0]['state'] == 'unknown'
        assert 'sprint414-cancel' not in author.text
    finally:
        f.tearDown()

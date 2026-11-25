"""The EIC task follows the existing round-bound invitation operation."""
from unittest.mock import patch
from app import models
from tests import test_reviewer_download as fixtures


def test_eic_invitation_task_is_scoped_and_clears():
    f = fixtures.ReviewerDownloadsTest()
    f.setUp()
    try:
        chief = models.User(name='Synthetic EIC', email='sprint412@example.com', password_hash='x', role='eic')
        f.db.add(chief); f.db.commit(); f.current = chief
        progress = f'/manuscripts/{f.mid}/progress'
        initial = f.client.get(progress).json()['participant_task']
        assert initial['action_label'] == 'View review policy'
        assert initial['permitted_action_target'] == f'#eic-reviewer-management-{f.mid}'
        response = f.client.put(f'/eic/manuscripts/{f.mid}/review-policy', json={'mode':'single_blind'})
        assert response.status_code == 200, response.text
        task = f.client.get(progress).json()['participant_task']
        assert task['task_state'] == 'action_required'
        assert task['permitted_action_target'] == f'#eic-reviewer-management-{f.mid}'
        with patch('app.review_files.validate_round_file', side_effect=OSError('unavailable')):
            assert f.client.get(progress).json()['participant_task']['permitted_action_target'] is None
        payload = {'manuscript_id':f.mid, 'reviewer_id':f.reviewer.user_id, 'review_round':1}
        f.current = f.author
        assert f.client.post('/assignments/', json=payload).status_code == 403
        assert f.client.get(progress).json()['participant_task']['permitted_action_target'] is None
        f.current = chief
        result = f.client.post('/assignments/', json=payload)
        assert result.status_code == 201, result.text
        task = f.client.get(progress).json()['participant_task']
        assert task['task_state'] == 'waiting' and task['permitted_action_target'] is None
        assert f.client.post('/assignments/', json=payload).status_code == 409
        f.db.expire_all(); f.manuscript.status = 'published'; f.db.commit()
        assert f.client.get(progress).json()['participant_task']['permitted_action_target'] is None
    finally:
        f.tearDown()


def test_protected_policy_and_missing_round_do_not_offer_invitation():
    f = fixtures.ReviewerDownloadsTest()
    f.setUp()
    try:
        chief = models.User(name='Synthetic EIC', email='sprint412b@example.com', password_hash='x', role='eic')
        f.db.add(chief); f.db.commit(); f.current = chief
        assert f.client.put(f'/eic/manuscripts/{f.mid}/review-policy', json={'mode':'double_blind'}).status_code == 200
        task = f.client.get(f'/manuscripts/{f.mid}/progress').json()['participant_task']
        assert task['permitted_action_target'] is None
        f.manuscript.review_round = 2; f.db.commit()
        task = f.client.get(f'/manuscripts/{f.mid}/progress').json()['participant_task']
        assert task['permitted_action_target'] is None
    finally:
        f.tearDown()

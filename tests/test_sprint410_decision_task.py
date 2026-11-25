"""Decision task uses the existing endpoint and current-round eligibility."""
from tests import test_two_reviewer_policy as policy_tests


def test_decision_task_and_round_precondition():
    f = policy_tests.TwoReviewerPolicyTest('test_editor_cannot_bypass_eic_after_reviews_complete')
    f.setUp()
    try:
        f.enable_new_submission()
        a = f.invite(f.reviewer)
        b = f.invite(f.other)
        f.current = f.reviewer
        assert f.client.get(f'/assignments/{a}/task').json()['task_state'] == 'pending'
        assert f.client.get(f'/assignments/{b}/task').status_code == 404
        f.respond(f.reviewer, a, 'accept')
        f.respond(f.other, b, 'accept')
        f.current = f.reviewer
        task = f.client.get(f'/assignments/{a}/task').json()
        assert task['task_state'] == 'action_required' and task['permitted_action_target'] == f'#review-action-{a}'
        f.submit_review(f.reviewer, a)
        f.current = f.reviewer
        task = f.client.get(f'/assignments/{a}/task').json()
        assert task['task_state'] == 'waiting' and task['permitted_action_target'] is None
        assert task['task_message'] == 'Your review was submitted. Waiting for other reviews.'
        f.current = f.other
        assert f.client.get(f'/assignments/{b}/task').json()['task_state'] == 'action_required'
        f.current = f.chief
        path = f'/eic/manuscripts/{f.mid}/decision'
        task = f.client.get(f'/manuscripts/{f.mid}/progress').json()['participant_task']
        assert task['task_state'] == 'waiting'
        f.submit_review(f.other, b)
        f.current = f.reviewer
        assert f.client.get(f'/assignments/{a}/task').json()['task_message'] == 'Your review was submitted. Waiting for editorial action.'
        f.current = f.chief
        task = f.client.get(f'/manuscripts/{f.mid}/progress').json()['participant_task']
        assert task['permitted_action_target'] == f'#eic-decision-{f.mid}'
        assert task['action_label'] == 'View editorial decision'
        payload = {'decision': 'revision_required', 'comments': 'Synthetic', 'expected_review_round': 2}
        assert f.client.post(path, json=payload).status_code == 409
        f.current = f.author
        payload['expected_review_round'] = 1
        assert f.client.post(path, json=payload).status_code == 403
        f.current = f.chief
        result = f.client.post(path, json=payload)
        assert result.status_code == 201, result.text
        task = f.client.get(f'/manuscripts/{f.mid}/progress').json()['participant_task']
        assert task['task_state'] == 'waiting' and task['permitted_action_target'] is None
        assert f.client.post(path, json=payload).status_code == 409
    finally:
        f.tearDown()

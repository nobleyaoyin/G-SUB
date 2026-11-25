"""Owner task guidance follows real synthetic Initial Editing approvals."""
from unittest.mock import patch
from app import models
from tests import test_reviewer_download as fixtures


def test_author_waits_for_actual_next_initial_editing_actor():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        # Synthetic starting state; decisions below use the application endpoints.
        f.manuscript.status='initial_editing'
        submission=models.InitialEditingSubmission(manuscript_id=f.mid,editor_id=f.editor.user_id,
            file_path=f.pdf,comments='Synthetic',status='pending_author')
        f.db.add(submission);f.db.commit(); sid=submission.submission_id
        f.current=f.author
        url=f'/manuscripts/{f.mid}/progress'
        initial=f.client.get(url).json()['participant_task']
        assert initial['task_state']=='action_required'
        response=f.client.post(f'/eic/initial-editing/submissions/{sid}/author-review',json={'decision':'approve','comments':'Synthetic'})
        assert response.status_code==200,response.text
        task=f.client.get(url).json()['participant_task']
        assert task['task_state']=='waiting' and 'initial editor' in task['task_message']
        assert task['permitted_action_target'] is None
        with patch('app.editor_invitation_revocation.effective_status',return_value='revoked'):
            assert f.client.get(url).json()['participant_task']['task_state']=='unavailable'
        f.current=f.other
        assert f.client.post(f'/eic/initial-editing/submissions/{sid}/editor-approval',json={'decision':'approve','comments':'Synthetic'}).status_code==403
        f.current=f.editor
        response=f.client.post(f'/eic/initial-editing/submissions/{sid}/editor-approval',json={'decision':'approve','comments':'Synthetic'})
        assert response.status_code==200,response.text
        f.current=f.author
        task=f.client.get(url).json()['participant_task']
        assert task['task_state']=='waiting' and 'EIC' in task['task_message']
        assert task['permitted_action_target'] is None
        f.current=f.other
        assert f.client.get(url).status_code==404
    finally:f.tearDown()

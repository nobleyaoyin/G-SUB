"""EIC task follows an actual Initial Editing approval sequence."""
from app import models
from tests import test_reviewer_download as fixtures


def test_eic_initial_edit_review_task_is_scoped_and_clears():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief=models.User(name='Synthetic EIC',email='sprint48-review@example.com',password_hash='x',role='eic')
        f.db.add(chief);f.manuscript.status='initial_editing'
        submission=models.InitialEditingSubmission(manuscript_id=f.mid,editor_id=f.editor.user_id,
            file_path=f.pdf,comments='Synthetic',status='pending_author')
        f.db.add(submission);f.db.commit();sid=submission.submission_id
        f.current=f.author
        response=f.client.post(f'/eic/initial-editing/submissions/{sid}/author-review',json={'decision':'approve','comments':'Synthetic'})
        assert response.status_code==200,response.text
        f.current=f.editor
        response=f.client.post(f'/eic/initial-editing/submissions/{sid}/editor-approval',json={'decision':'approve','comments':'Synthetic'})
        assert response.status_code==200,response.text
        f.current=chief
        progress=f.client.get(f'/manuscripts/{f.mid}/progress');assert progress.status_code==200
        task=progress.json()['participant_task']
        assert task['task_state']=='action_required' and task['permitted_action_target']==f'#eic-initial-review-{f.mid}'
        assert 'comments' not in str(task) and 'Synthetic' not in str(task)
        f.current=f.author
        assert f.client.post(f'/eic/initial-editing/submissions/{sid}/eic-approval',json={'decision':'approve','comments':'Synthetic'}).status_code==403
        f.current=chief
        response=f.client.post(f'/eic/initial-editing/submissions/{sid}/eic-approval',json={'decision':'approve','comments':'Synthetic'})
        assert response.status_code==200,response.text
        task=f.client.get(f'/manuscripts/{f.mid}/progress').json()['participant_task']
        assert task['permitted_action_target'] is None
        assert f.client.post(f'/eic/initial-editing/submissions/{sid}/eic-approval',json={'decision':'approve','comments':'Synthetic'}).status_code==409
    finally:f.tearDown()

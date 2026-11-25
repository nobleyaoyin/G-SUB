"""Author formatting task follows real proof review and correction operations."""
from unittest.mock import patch
from app import models
from app.routers import eic, formatting
from tests import test_formatting as fixtures


def test_author_proof_task_revalidates_and_refreshes():
    f=fixtures.FormattingTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root),patch.object(formatting,'BASE_DIR',f.root):
            f.prepare_final(); invitation=f.f_invite(f.formatter);assert invitation.status_code==201,invitation.text
            iid=invitation.json()['invitation_id']
            assert f.f_action(f.formatter,f'/formatting/invitations/{iid}/respond',{'decision':'accept'}).status_code==200
            f.current=f.formatter
            sent=f.client.post(f'/formatting/invitations/{iid}/submit',data={'comments':'Synthetic proof'},files={'file':('proof.pdf',b'%PDF-synthetic-proof','application/pdf')})
            assert sent.status_code==201,sent.text;sid=sent.json()['submission_id']
            f.current=f.author;url=f'/manuscripts/{f.mid}/progress'
            response=f.client.get(url);assert response.status_code==200,response.text
            task=response.json()['participant_task'];assert task['task_state']=='action_required'
            assert task['permitted_action_target']==f'#author-formatting-action-{f.mid}'
            assert 'Synthetic proof' not in response.text
            proof=f.db.get(models.FormattingSubmission,sid);path=f.root/proof.file_path
            path.write_bytes(b'%PDF-synthetic-tampered')
            assert f.client.get(url).json()['participant_task']['task_state']=='unavailable'
            path.write_bytes(b'%PDF-synthetic-proof')
            f.current=f.other_author;assert f.client.get(url).status_code==404
            denied=f.client.post(f'/formatting/submissions/{sid}/author-review',json={'decision':'approve','comments':'Synthetic'})
            assert denied.status_code==403
            f.current=f.author
            result=f.client.post(f'/formatting/submissions/{sid}/author-review',json={'decision':'request_revision','comments':'Synthetic'})
            assert result.status_code==200,result.text
            task=f.client.get(url).json()['participant_task'];assert task['task_state']=='waiting' and 'formatter' in task['task_message']
            f.current=f.formatter
            sent=f.client.post(f'/formatting/invitations/{iid}/submit',data={'comments':'Synthetic revision'},files={'file':('proof2.pdf',b'%PDF-synthetic-revision','application/pdf')})
            assert sent.status_code==201,sent.text;sid2=sent.json()['submission_id']
            f.current=f.author;assert f.client.get(url).json()['participant_task']['task_state']=='action_required'
            result=f.client.post(f'/formatting/submissions/{sid2}/author-review',json={'decision':'approve','comments':'Synthetic'})
            assert result.status_code==200,result.text
            task=f.client.get(url).json()['participant_task'];assert task['task_state']=='waiting' and 'EIC' in task['task_message']
            assert task['permitted_action_target'] is None
            f.current=f.chief
            assert f.client.post(f'/formatting/submissions/{sid2}/eic-review',json={'decision':'approve','comments':'Synthetic'}).status_code==200
            f.current=f.author;task=f.client.get(url).json()['participant_task']
            assert task['task_state']=='waiting' and 'publication' in task['task_message']
    finally:f.tearDown()

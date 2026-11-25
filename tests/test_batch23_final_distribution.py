"""Final-editor acceptance and grant authorization with isolated data."""
from tests.batch83_migration_support import bootstrap_prospective_distribution
import os
from unittest.mock import patch
from app.routers import eic, document_distribution as distribution
from tests.test_final_workflow import FinalWorkflowTest
from tests.test_batch17c_editor_distribution import migration


def test_final_editor_acceptance_notification_grant_and_revocation():
    f=FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement()
            f.current=f.author
            response=f.client.post(f"/agreements/{agreement['agreement_id']}/respond",json={'decision':'accept','agreement_version':agreement['agreement_version']})
            assert response.status_code==200,response.text
            invitation=f.invite(f.editor)
            assert invitation.status_code==201,invitation.text
            iid=invitation.json()['invitation_id']
            assert f.respond(f.alternate,iid,'accept').status_code==403
            assert f.respond(f.editor,iid,'accept').status_code==200
            assert f.respond(f.editor,iid,'accept').status_code==409
            f.current=f.chief
            notifications=[n for n in f.client.get('/notifications/my').json() if n['manuscript_id']==f.mid and n['notification_type']=='final_editor_response']
            assert len(notifications)==1
            assert 'Final editor accepted' in notifications[0]['message']
            assert f'invitation #{iid}' in notifications[0]['message']
            assert f'manuscript #{f.mid}' in notifications[0]['message']
            content=b'Synthetic final source\n'
            f.manuscript.file_path=f.write(f'uploads/manuscripts/{f.mid}/paper.txt',content)
            f.db.commit();bootstrap_prospective_distribution(f.db_path)
            private=f.root/'private-final';private.mkdir(mode=0o700)
            with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
                candidates=f.client.get(f'/document-distribution/manuscripts/{f.mid}/candidates')
                assert candidates.status_code==200,candidates.text
                request={'invitation_kind':'final','invitation_id':iid,'source_sha256':candidates.json()['document']['sha256'],'idempotency_key':'synthetic-final-test-23'}
                grant=f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants',json=request)
                assert grant.status_code==200,grant.text
                assert grant.json()['already_exists'] is False
                gid=grant.json()['grant_id']
                f.current=f.alternate
                assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==404
                f.current=f.editor
                assert f.client.get(f'/document-distribution/grants/{gid}/download').content==content
                f.current=f.chief
                assert f.client.post(f'/document-distribution/grants/{gid}/revoke',json={'reason':'Synthetic test'}).status_code==200
                f.current=f.editor
                assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==404
    finally:f.tearDown()

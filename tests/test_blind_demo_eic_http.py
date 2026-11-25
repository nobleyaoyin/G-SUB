"""Synthetic only: authenticated demo policy and atomic invitation HTTP tests."""
import unittest
from unittest.mock import patch
from app.security import create_access_token
from app.blind_policy_store import PolicyError
from tests import test_reviewer_metadata_gate as fixtures
from tests.test_reviewer_artifact_binding import T


class EICDemoHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.MetadataGateHTTPTests('test_double_blind_exact_allowlist_and_no_cache')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.db=self.f.db
        self.root=self.f.fx.fx.fx.path.parent.resolve()
        rel='uploads/initial_editing/3/source.pdf'
        path=self.root/rel; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'%PDF-synthetic')
        self.db.execute("INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,created_at) VALUES (3,'Sensitive synthetic title','Synthetic',1,'ready_for_peer_review',1,?)",(T,))
        self.db.execute("INSERT INTO initial_editing_submissions(submission_id,manuscript_id,editor_id,file_path,comments,status,created_at,eic_approved_by,eic_reviewed_at) VALUES (3,3,3,?,'Synthetic','eic_approved',?,5,?)",(rel,T,T))
        self.db.execute("INSERT INTO pre_review_confirmations(confirmation_id,manuscript_id,submission_id,author_id,file_path,decision,comments,confirmed_at) VALUES (3,3,3,1,?,'confirm','Synthetic',?)",(rel,T));self.db.commit()
        self.db.execute('UPDATE review_assignments SET reviewer_id=4 WHERE assignment_id IN (1,3)'); self.db.commit()
        self.p=patch('app.review_files.BASE_DIR',self.root);self.p.start();self.addCleanup(self.p.stop)

    def req(self,method,path,user=5,**kwargs):
        return self.f.client.request(method,path,headers={'Authorization':'Bearer '+create_access_token(user)},**kwargs)

    def test_disabled_and_authorization(self):
        self.assertEqual(self.req('GET','/assignments/demo-policy/3').status_code,404)
        self.f.enable()
        self.assertEqual(self.req('GET','/assignments/demo-policy/3',user=1).status_code,403)
        self.assertEqual(self.f.client.get('/assignments/demo-policy/3').status_code,401)
        self.assertEqual(self.req('GET','/assignments/demo-policy/999').status_code,404)

    def test_single_invitation_locks_and_notifies_atomically(self):
        self.f.enable()
        choice=self.req('PUT','/assignments/demo-policy/3',json={'mode':'single_blind'})
        self.assertEqual(choice.status_code,200,choice.text);self.assertEqual(choice.json()['locked'],False)
        data={'manuscript_id':3,'reviewer_id':2,'review_round':1}
        self.assertEqual(self.req('POST','/assignments/',json=data).status_code,409)
        result=self.req('POST','/assignments/demo-invitations',json=data)
        self.assertEqual(result.status_code,201,result.text);aid=result.json()['assignment_id']
        state=self.req('GET','/assignments/demo-policy/3').json();self.assertTrue(state['locked']);self.assertEqual(state['revision'],2)
        self.assertEqual(self.req('PUT','/assignments/demo-policy/3',json={'mode':'double_blind','expected_revision':2}).status_code,409)
        row=self.db.execute("SELECT message FROM notifications WHERE user_id=2 AND manuscript_id=3 AND notification_type='review_invitation'").fetchone()
        self.assertEqual(row[0],'You have a reviewer invitation.')
        pending=self.req('GET','/assignments/my',user=2);self.assertEqual(pending.status_code,200,pending.text)
        self.assertEqual(pending.json()[0]['invitation_status'],'pending');self.assertNotIn('author_id',pending.json()[0])
        self.assertEqual(self.req('POST',f'/assignments/{aid}/invitation-response',user=2,json={'decision':'accept'}).status_code,200)
        details=self.req('GET','/manuscripts/3',user=2);self.assertEqual(details.status_code,200,details.text)
        self.assertEqual(details.json(),{'manuscript_id':3,'review_round':1,'author_name':'Author'})
        self.assertNotIn('author_id',details.json())
        document=self.req('GET',f'/assignments/{aid}/download',user=2);self.assertEqual(document.status_code,200,document.text);self.assertEqual(document.content,b'%PDF-synthetic')
        review=self.req('POST','/reviews/',user=2,json={'assignment_id':aid,'comments':'Synthetic review','recommendation':'revision'});self.assertEqual(review.status_code,201,review.text)
        self.assertEqual(self.req('POST','/assignments/demo-invitations',json=data).status_code,409)

    def test_double_fails_without_partial_invitation_or_notification(self):
        self.f.enable()
        self.assertEqual(self.req('PUT','/assignments/demo-policy/3',json={'mode':'double_blind'}).status_code,200)
        result=self.req('POST','/assignments/demo-invitations',json={'manuscript_id':3,'reviewer_id':2,'review_round':1})
        self.assertEqual(result.status_code,409);self.assertIn('artifact readiness',result.json()['detail'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM review_assignments WHERE manuscript_id=3').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM notifications WHERE manuscript_id=3').fetchone()[0],0)
        self.assertFalse(self.req('GET','/assignments/demo-policy/3').json()['locked'])

    def test_missing_source_rolls_back_lock_and_assignment(self):
        self.f.enable();self.req('PUT','/assignments/demo-policy/3',json={'mode':'single_blind'})
        (self.root/'uploads/initial_editing/3/source.pdf').unlink()
        result=self.req('POST','/assignments/demo-invitations',json={'manuscript_id':3,'reviewer_id':2,'review_round':1})
        self.assertEqual(result.status_code,409)
        self.assertEqual(self.db.execute('SELECT count(*) FROM review_assignments WHERE manuscript_id=3').fetchone()[0],0)
        self.assertFalse(self.req('GET','/assignments/demo-policy/3').json()['locked'])

    def test_lock_failure_rolls_back_entire_invitation(self):
        self.f.enable();self.req('PUT','/assignments/demo-policy/3',json={'mode':'single_blind'})
        with patch('app.routers.assignments.lock_mode', side_effect=PolicyError('synthetic failure')):
            result=self.req('POST','/assignments/demo-invitations',json={'manuscript_id':3,'reviewer_id':2,'review_round':1})
        self.assertEqual(result.status_code,409)
        for table in ('review_assignments','review_round_files','notifications'):
            self.assertEqual(self.db.execute(f'SELECT count(*) FROM {table} WHERE manuscript_id=3').fetchone()[0],0)
        self.assertFalse(self.req('GET','/assignments/demo-policy/3').json()['locked'])

if __name__=='__main__': unittest.main()

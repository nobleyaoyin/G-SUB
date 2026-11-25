"""Transactional notification tests with disposable SQLite and synthetic users."""
import unittest
from unittest.mock import patch
from sqlalchemy import select
from app import models
from tests import test_reviewer_download as fixture, test_formatting as formatting_fixture
import app.routers.eic as eic
import app.routers.formatting as formatting


class WorkflowNotificationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ReviewerDownloadsTest('test_first_round_binding_and_access');self.f.setUp();self.addCleanup(self.f.tearDown)
        self.f.chief=models.User(name='Chief',email='chief@example.com',password_hash='x',role='eic')
        self.f.db.add(self.f.chief);self.f.db.commit()
    def notices(self,uid,kind):
        return self.f.db.scalars(select(models.Notification).where(models.Notification.user_id==uid,models.Notification.notification_type==kind)).all()
    def test_submission_notification_ownership_and_no_duplicate(self):
        f=self.f;draft=models.Manuscript(title='Synthetic draft',abstract='Synthetic',author_id=f.author.user_id,status='draft',review_round=1)
        f.db.add(draft);f.db.flush();draft.file_path=f.write(f'uploads/manuscripts/{draft.manuscript_id}/round_1_test.pdf',b'%PDF-synthetic');f.db.commit()
        f.current=f.author;r=f.client.post(f'/manuscripts/{draft.manuscript_id}/submit');self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(f.client.post(f'/manuscripts/{draft.manuscript_id}/submit').status_code,409)
        rows=self.notices(f.chief.user_id,'manuscript_submitted');self.assertEqual(len(rows),1);nid=rows[0].notification_id
        f.current=f.editor;self.assertEqual(f.client.patch(f'/notifications/{nid}/read').status_code,403)
        f.current=f.chief;self.assertEqual(f.client.get('/notifications/unread-count').json()['unread_count'],1)
        self.assertEqual(f.client.patch(f'/notifications/{nid}/read').status_code,200)
        self.assertEqual(f.client.get('/notifications/unread-count').json()['unread_count'],0)
        self.assertEqual(len(self.notices(f.chief.user_id,'manuscript_submitted')),1)
    def test_reviewer_invitation_response_and_review_are_neutral(self):
        f=self.f;f.current=f.chief
        policy=f.client.put(f'/eic/manuscripts/{f.mid}/review-policy',json={'mode':'single_blind'});self.assertEqual(policy.status_code,200,policy.text)
        r=f.client.post('/assignments/',json={'manuscript_id':f.mid,'reviewer_id':f.reviewer.user_id,'review_round':1});self.assertEqual(r.status_code,201,r.text);aid=r.json()['assignment_id']
        rows=self.notices(f.reviewer.user_id,'review_invitation');self.assertEqual(len(rows),1);self.assertNotIn('Title',rows[0].message)
        f.current=f.reviewer;self.assertEqual(f.client.post(f'/assignments/{aid}/invitation-response',json={'decision':'accept'}).status_code,200)
        self.assertEqual(f.client.post(f'/assignments/{aid}/invitation-response',json={'decision':'accept'}).status_code,409)
        self.assertEqual(f.client.post('/reviews/',json={'assignment_id':aid,'comments':'Synthetic','recommendation':'revision'}).status_code,201)
        self.assertEqual(f.client.post('/reviews/',json={'assignment_id':aid,'comments':'Synthetic','recommendation':'revision'}).status_code,409)
        for kind in ('review_invitation_response','review_submitted'):
            notices=self.notices(f.chief.user_id,kind);self.assertEqual(len(notices),1)
            for secret in ('Reviewer','Title',f.reviewer.email):self.assertNotIn(secret,notices[0].message)
    def test_revision_notifies_participating_editor_and_deciding_eic(self):
        f=self.f
        f.manuscript.status='revision_required'
        f.db.add(models.EICDecision(manuscript_id=f.mid,eic_id=f.chief.user_id,review_round=1,decision='revision_required',comments='Synthetic'))
        f.db.commit();f.current=f.author
        upload=f.client.post(f'/manuscripts/{f.mid}/upload',files={'file':('revision.pdf',b'%PDF-revision','application/pdf')})
        self.assertEqual(upload.status_code,200,upload.text)
        result=f.client.post(f'/manuscripts/{f.mid}/resubmit',json={'title':'Synthetic revision'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(f.client.post(f'/manuscripts/{f.mid}/resubmit',json={'title':'Synthetic revision'}).status_code,409)
        self.assertEqual(len(self.notices(f.chief.user_id,'revision_submitted')),1)
        self.assertEqual(len(self.notices(f.editor.user_id,'revision_submitted')),1)
        self.assertEqual(len(self.notices(f.other.user_id,'revision_submitted')),0)
    def test_eic_revision_decision_notifies_author_without_review_text(self):
        f=self.f;f.current=f.chief
        policy=f.client.put(f'/eic/manuscripts/{f.mid}/review-policy',json={'mode':'single_blind'});self.assertEqual(policy.status_code,200,policy.text)
        invited=f.client.post('/assignments/',json={'manuscript_id':f.mid,'reviewer_id':f.reviewer.user_id,'review_round':1});self.assertEqual(invited.status_code,201,invited.text);aid=invited.json()['assignment_id']
        f.current=f.reviewer;self.assertEqual(f.client.post(f'/assignments/{aid}/invitation-response',json={'decision':'accept'}).status_code,200)
        self.assertEqual(f.client.post('/reviews/',json={'assignment_id':aid,'comments':'Synthetic private review','recommendation':'revision'}).status_code,201)
        f.current=f.chief;decision=f.client.post(f'/eic/manuscripts/{f.mid}/decision',json={'decision':'revision_required','comments':'Reviewer identity must remain private'})
        self.assertEqual(decision.status_code,201,decision.text)
        self.assertEqual(f.client.post(f'/eic/manuscripts/{f.mid}/decision',json={'decision':'revision_required','comments':'repeat'}).status_code,409)
        rows=self.notices(f.author.user_id,'eic_decision');self.assertEqual(len(rows),1)
        self.assertIn('revision_required',rows[0].message);self.assertNotIn('Reviewer',rows[0].message);self.assertNotIn('private',rows[0].message)


class FormattingNotificationTests(unittest.TestCase):
    def setUp(self):
        self.f=formatting_fixture.FormattingTest('test_formatting_and_publication');self.f.setUp();self.addCleanup(self.f.tearDown)
    def notices(self,uid,kind):
        return self.f.db.scalars(select(models.Notification).where(models.Notification.user_id==uid,models.Notification.notification_type==kind)).all()
    def test_formatter_invitation_and_proof_review(self):
        f=self.f
        with patch.object(eic,'BASE_DIR',f.root),patch.object(formatting,'BASE_DIR',f.root):
            f.prepare_final();r=f.f_invite(f.formatter);self.assertEqual(r.status_code,201,r.text);iid=r.json()['invitation_id']
            self.assertEqual(len(self.notices(f.formatter.user_id,'formatter_invited')),1)
            self.assertEqual(f.f_invite(f.formatter).status_code,409)
            self.assertEqual(f.f_action(f.formatter,f'/formatting/invitations/{iid}/respond',{'decision':'accept'}).status_code,200)
            self.assertEqual(f.f_action(f.formatter,f'/formatting/invitations/{iid}/respond',{'decision':'accept'}).status_code,409)
            self.assertEqual(len(self.notices(f.chief.user_id,'formatter_response')),1)
            f.current=f.formatter;r=f.client.post(f'/formatting/invitations/{iid}/submit',data={'comments':'Synthetic'},files={'file':('proof.pdf',b'%PDF-proof','application/pdf')});self.assertEqual(r.status_code,201,r.text);sid=r.json()['submission_id']
            self.assertEqual(len(self.notices(f.author.user_id,'formatting_review_requested')),1)
            self.assertEqual(f.f_action(f.author,f'/formatting/submissions/{sid}/author-review',{'decision':'request_revision','comments':'Synthetic'}).status_code,200)
            self.assertEqual(len(self.notices(f.formatter.user_id,'formatting_review_update')),1)
            self.assertEqual(f.f_action(f.author,f'/formatting/submissions/{sid}/author-review',{'decision':'request_revision','comments':'Synthetic'}).status_code,409)
            self.assertEqual(len(self.notices(f.formatter.user_id,'formatting_review_update')),1)

if __name__=='__main__':unittest.main()

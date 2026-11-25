"""Role-safe progress with synthetic users and disposable SQLite fixtures."""
import unittest
from unittest.mock import patch
from app.security import create_access_token
from app import blind_policy_store as policy
import app.main as main
from app.reviewer_metadata_gate import reviewer_metadata_mode, MetadataMode
from tests import test_reviewer_metadata_gate as meta
from tests import test_formatting as formatting_fixture
from tests.test_reviewer_artifact_binding import T
import app.routers.eic as eic
import app.routers.formatting as formatting


class ReviewerProgressTests(unittest.TestCase):
    def setUp(self):
        self.f=meta.MetadataGateHTTPTests('test_double_blind_exact_allowlist_and_no_cache');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.db=self.f.db
    def get(self, user=2):
        return self.f.client.get('/manuscripts/2/progress',headers={'Authorization':'Bearer '+create_access_token(user)})
    def test_experimental_double_blind_and_other_roles(self):
        self.f.enable()
        self.db.execute("INSERT INTO initial_editor_invitations(manuscript_id,editor_id,invited_by,status,invited_at) VALUES (2,3,5,'accepted',?)",(T,));self.db.commit()
        response=self.get();self.assertEqual(response.status_code,200,response.text)
        data=response.json();self.assertEqual(response.headers['cache-control'],'no-store');self.assertNotIn('title',data)
        for text in ('author_id','author_name','reviewer_id','email','abstract','file_path','Synthetic'):
            self.assertNotIn(text,str(data))
        self.assertEqual(len(data['stages']),10)
        self.assertEqual([s['name'] for s in data['stages']][-3:], ['Formatting', 'Proofing', 'Publication'])
        for actor in (1,3,5):
            result=self.get(actor);self.assertEqual(result.status_code,200,result.text)
            self.assertNotIn('reviewer_id',str(result.json()))
        self.assertEqual(self.get(4).status_code,404)
        self.assertEqual(self.f.client.get('/manuscripts/2/progress').status_code,401)
    def test_stale_pending_invalidated_and_missing_schema(self):
        self.f.enable()
        self.db.execute("UPDATE reviewer_invitations SET status='pending' WHERE assignment_id=3");self.db.commit();self.assertEqual(self.get().status_code,404)
        self.db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=3")
        self.db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=2');self.db.commit();self.assertEqual(self.get().status_code,404)
        self.db.execute('UPDATE manuscripts SET review_round=1 WHERE manuscript_id=2')
        self.db.execute("INSERT INTO reviewer_invitation_invalidations VALUES ('test-revoke',3,'cancelled',NULL,5,?,'editorial_cancellation')",(T,));self.db.commit();self.assertEqual(self.get().status_code,404)
        self.db.execute("DELETE FROM schema_migrations WHERE migration_id='009_account_invitation_lifecycle'");self.db.commit();self.assertEqual(self.get().status_code,503)
    def test_default_omits_title(self):
        result=self.get();self.assertEqual(result.status_code,200,result.text)
        self.assertNotIn('title',result.json());self.assertEqual(result.headers['cache-control'],'no-store')
    def test_single_blind_progress_omits_unreviewed_title(self):
        self.db.execute("INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,created_at) VALUES (3,'Private title','Private abstract',1,'ready_for_peer_review',1,?)",(T,));self.db.commit()
        self.db.execute('BEGIN IMMEDIATE');policy.select_mode(self.db,3,'single_blind',5)
        self.db.execute("INSERT INTO review_assignments(assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (4,3,2,5,1,'assigned',?)",(T,))
        self.db.execute("INSERT INTO reviewer_invitations VALUES (4,'accepted',?,?)",(T,T));policy.lock_mode(self.db,3,4,5,1);self.db.commit()
        self.f.enable();response=self.f.client.get('/manuscripts/3/progress',headers={'Authorization':'Bearer '+create_access_token(2)})
        self.assertEqual(response.status_code,200,response.text);self.assertNotIn('title',response.json());self.assertNotIn('Private',str(response.json()))
    def test_experimental_formatter_requires_active_lifecycle_and_locked_policy(self):
        self.db.execute("INSERT INTO users(user_id,name,email,password_hash,role,created_at) VALUES (6,'Formatter','formatter@example.com','x','formatter',?)",(T,))
        self.db.execute("UPDATE manuscripts SET status='formatting' WHERE manuscript_id=2")
        self.db.execute("INSERT INTO final_editor_invitations(invitation_id,manuscript_id,editor_id,invited_by,status,invited_at) VALUES (8,2,3,5,'accepted',?)",(T,))
        self.db.execute("INSERT INTO final_editing_submissions(submission_id,manuscript_id,editor_id,file_path,comments,status,author_reviewed_at,eic_reviewed_at,eic_approved_by,created_at) VALUES (8,2,3,'synthetic.pdf','synthetic','author_approved',?,?,5,?)",(T,T,T))
        self.db.execute('INSERT INTO final_editing_submission_invitations VALUES (8,8)')
        self.db.execute("INSERT INTO formatter_invitations(invitation_id,manuscript_id,formatter_id,invited_by,final_submission_id,status,invited_at) VALUES (8,2,6,5,8,'accepted',?)",(T,));self.db.commit()
        self.f.enable();self.assertEqual(self.get(6).status_code,404)
        self.db.execute("INSERT INTO account_lifecycle_events VALUES ('fmt-active',6,1,NULL,'active',1,5,?,'initial_enrollment')",(T,))
        self.db.execute("INSERT INTO account_lifecycle VALUES (6,'active',1,1,'fmt-active')");self.db.commit()
        response=self.get(6);self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.headers['cache-control'],'no-store')


class FormatterProgressTests(unittest.TestCase):
    def setUp(self):
        self.f=formatting_fixture.FormattingTest('test_formatting_and_publication');self.f.setUp();self.addCleanup(self.f.tearDown)
    def test_only_accepted_current_formatter_can_view_progress(self):
        f=self.f
        with patch.object(eic,'BASE_DIR',f.root),patch.object(formatting,'BASE_DIR',f.root):
            f.prepare_final();iid=f.f_invite(f.formatter).json()['invitation_id']
            f.current=f.formatter;self.assertEqual(f.client.get(f'/manuscripts/{f.mid}/progress').status_code,404)
            self.assertEqual(f.f_action(f.formatter,f'/formatting/invitations/{iid}/respond',{'decision':'accept'}).status_code,200)
            result=f.client.get(f'/manuscripts/{f.mid}/progress');self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['current_stage'],'Formatting')
            main.app.dependency_overrides[reviewer_metadata_mode]=lambda:MetadataMode.EXPERIMENTAL
            self.assertEqual(f.client.get(f'/manuscripts/{f.mid}/progress').status_code,404)
            main.app.dependency_overrides.pop(reviewer_metadata_mode)
            f.current=f.other_formatter;self.assertEqual(f.client.get(f'/manuscripts/{f.mid}/progress').status_code,404)
            f.current=f.author;self.assertNotIn('reviewer_id',str(f.client.get(f'/manuscripts/{f.mid}/progress').json()))

if __name__=='__main__': unittest.main()

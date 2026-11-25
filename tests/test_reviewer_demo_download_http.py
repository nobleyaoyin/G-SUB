"""Synthetic-only HTTP tests of the default-disabled demo download boundary."""
import unittest
from unittest.mock import patch

import app.main as main
from app.security import create_access_token
from app.reviewer_demo_download import DemoArtifactContext, reviewer_demo_artifact_context
from app.reviewer_metadata_gate import reviewer_metadata_mode, MetadataMode
from app import blind_policy_store as policy
from tests import test_reviewer_metadata_gate as metadata_tests
from tests.test_reviewer_artifact_binding import T


class DemoDownloadHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f = metadata_tests.MetadataGateHTTPTests('test_double_blind_exact_allowlist_and_no_cache')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.db = self.f.db; self.b = self.f.fx
        self.f.enable()
        main.app.dependency_overrides[reviewer_demo_artifact_context] = lambda: DemoArtifactContext(self.b.proof,self.b.source,self.b.storage)

    def get(self, aid=3, user=2):
        return self.f.client.get(f'/assignments/{aid}/download',headers={'Authorization':'Bearer '+create_access_token(user)})

    def bind(self):
        self.b.begin(); self.b.bind(); self.db.commit()

    def test_double_artifact_http_and_no_fallback(self):
        self.assertEqual(self.get().status_code,409)
        self.bind()
        response = self.get()
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.content,b'synthetic reviewer artifact')
        self.assertEqual(response.headers['content-disposition'],'attachment; filename="review-document.txt"')
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(self.get(user=4).status_code,409)
        headers={'Authorization':'Bearer '+create_access_token(2)}
        for path in ('/manuscripts/2/download','/manuscripts/2/versions','/manuscripts/2/versions/source.pdf'):
            self.assertEqual(self.f.client.get(path,headers=headers).status_code,403)
        path=self.b.fx.fx.path.parent.resolve()/'artifact-private'/self.b.art.storage_id
        path.chmod(0o600); path.write_bytes(b'X'*len(b'synthetic reviewer artifact'))
        self.assertEqual(self.get().status_code,409)

    def test_missing_context_revoked_and_stale_fail_closed(self):
        self.bind()
        main.app.dependency_overrides.pop(reviewer_demo_artifact_context)
        self.assertEqual(self.get().status_code,409)
        main.app.dependency_overrides[reviewer_demo_artifact_context] = lambda: DemoArtifactContext(self.b.proof,self.b.source,self.b.storage)
        self.db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=2'); self.db.commit()
        self.assertEqual(self.get().status_code,409)
        self.db.execute('UPDATE manuscripts SET review_round=1 WHERE manuscript_id=2')
        self.db.execute("INSERT INTO reviewer_invitation_invalidations VALUES ('revoke',3,'cancelled',NULL,5,?,'editorial_cancellation')",(T,)); self.db.commit()
        self.assertEqual(self.get().status_code,409)

    def test_missing_policy_schema_and_pending_fail_closed(self):
        self.db.execute("UPDATE reviewer_invitations SET status='pending' WHERE assignment_id=3"); self.db.commit()
        self.assertEqual(self.get().status_code,409)
        self.db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=3")
        self.db.execute("DELETE FROM schema_migrations WHERE migration_id='011_blind_review_policy'"); self.db.commit()
        self.assertEqual(self.get().status_code,409)

    def test_single_blind_round_bound_source(self):
        root=self.b.fx.fx.path.parent.resolve()
        relative='uploads/initial_editing/3/source.pdf'
        path=root/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'%PDF-single-original')
        self.db.execute("INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,created_at) VALUES (3,'Synthetic','Synthetic',1,'ready_for_peer_review',1,?)",(T,))
        self.db.execute("INSERT INTO initial_editing_submissions(submission_id,manuscript_id,editor_id,file_path,comments,status,created_at,eic_approved_by,eic_reviewed_at) VALUES (3,3,3,?,'Synthetic','eic_approved',?,5,?)",(relative,T,T))
        self.db.execute("INSERT INTO pre_review_confirmations(confirmation_id,manuscript_id,submission_id,author_id,file_path,decision,comments,confirmed_at) VALUES (3,3,3,1,?,'confirm','Synthetic',?)",(relative,T))
        self.db.execute("INSERT INTO review_round_files(round_file_id,manuscript_id,review_round,source_kind,confirmation_id,file_path,created_at) VALUES (3,3,1,'initial_editing',3,?,?)",(relative,T)); self.db.commit()
        self.db.execute('BEGIN IMMEDIATE'); policy.select_mode(self.db,3,'single_blind',5)
        self.db.execute("INSERT INTO review_assignments(assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (4,3,2,5,1,'assigned',?)",(T,))
        self.db.execute("INSERT INTO reviewer_invitations VALUES (4,'accepted',?,?)",(T,T))
        self.db.execute('INSERT INTO review_assignment_files VALUES (4,3,?)',(T,)); policy.lock_mode(self.db,3,4,5,1); self.db.commit()
        with patch('app.review_files.BASE_DIR',root): response=self.get(aid=4)
        self.assertEqual(response.status_code,200,response.text); self.assertEqual(response.content,b'%PDF-single-original')
        self.assertEqual(response.headers['content-disposition'],'attachment; filename="review-document.pdf"')

    def test_default_mode_keeps_original_behavior(self):
        root=self.b.fx.fx.path.parent.resolve(); relative='uploads/initial_editing/2/source.pdf'
        path=root/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'%PDF-default-original')
        original_paths={table:self.db.execute(f'SELECT file_path FROM {table} WHERE manuscript_id=2').fetchone()[0]
                        for table in ('initial_editing_submissions','pre_review_confirmations','review_round_files')}
        for table in ('initial_editing_submissions','pre_review_confirmations','review_round_files'):
            self.db.execute(f'UPDATE {table} SET file_path=? WHERE manuscript_id=2',(relative,))
        self.db.commit()
        main.app.dependency_overrides[reviewer_metadata_mode]=lambda:MetadataMode.DISABLED
        with patch('app.review_files.BASE_DIR',root): response=self.get()
        self.assertEqual(response.status_code,409,response.text)
        self.assertNotIn(b'%PDF-default-original',response.content)
        headers={'Authorization':'Bearer '+create_access_token(2)}
        self.assertEqual(self.f.client.get('/manuscripts/2/download',headers=headers).status_code,403)
        self.assertEqual(path.read_bytes(),b'%PDF-default-original')
        for table, original_path in original_paths.items():
            self.db.execute(f'UPDATE {table} SET file_path=? WHERE manuscript_id=2',(original_path,))
        self.db.commit()
        self.bind()
        approved=self.get()
        self.assertEqual(approved.status_code,200,approved.text)
        self.assertEqual(approved.content,b'synthetic reviewer artifact')
        self.assertEqual(path.read_bytes(),b'%PDF-default-original')

if __name__=='__main__': unittest.main()

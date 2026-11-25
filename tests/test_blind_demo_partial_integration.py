"""Synthetic cross-component checks; this is not a deployable blind-review demo."""
import unittest
from unittest.mock import patch

from app.security import create_access_token
from app import reviewer_artifact_read as artifact_read
from app.reviewer_metadata_gate import MetadataMode, reviewer_metadata_mode
from app.reviewer_demo_download import DemoArtifactContext, reviewer_demo_artifact_context
import app.main as main
from tests import test_reviewer_metadata_gate as metadata_tests
from tests import test_reviewer_artifact_read as artifact_tests
from tests import test_reviewer_artifact_binding as binding_tests


class BlindDemoPartialIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.http = metadata_tests.MetadataGateHTTPTests('test_double_blind_exact_allowlist_and_no_cache')
        self.http.setUp()
        self.addCleanup(self.http.doCleanups)
        self.binding = self.http.fx
        self.db = self.http.db
        # Remove an unrelated synthetic pending assignment from this reviewer's list.
        self.db.execute('UPDATE review_assignments SET reviewer_id=4 WHERE assignment_id=1')
        # The fixture established prospective synthetic proof, approval and a locked
        # policy. Exercise the actual invitation-response endpoint from pending.
        self.db.execute("UPDATE reviewer_invitations SET status='pending', responded_at=NULL WHERE assignment_id=3")
        self.db.commit()
        self.http.enable()

    def request(self, method, path, user=2, **kwargs):
        headers = {'Authorization': 'Bearer ' + create_access_token(user)}
        return self.http.client.request(method, path, headers=headers, **kwargs)

    def test_locked_policy_accept_metadata_verified_artifact_and_review(self):
        p = self.db.execute('SELECT mode,revision,locked_at FROM blind_policies WHERE manuscript_id=2').fetchone()
        self.assertEqual(p[:2], ('double_blind', 2)); self.assertIsNotNone(p[2])
        pending=self.request('GET','/assignments/my')
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()[0]['invitation_status'], 'pending')
        self.assertNotIn('author_id', pending.json()[0])
        self.assertEqual(self.request('POST','/assignments/3/invitation-response',user=4,json={'decision':'accept'}).status_code, 403)
        accepted = self.request('POST','/assignments/3/invitation-response',json={'decision':'accept'})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.binding.begin(); self.binding.bind(); self.db.commit()
        metadata = self.request('GET','/assignments/my')
        self.assertEqual(metadata.status_code, 200, metadata.text)
        self.assertEqual(metadata.json(), [{'assignment_id':3,'manuscript_id':2,'review_round':1,'status':'assigned','invitation_status':'accepted','review_file_available':False,'review_file_status':'unavailable'}])
        details = self.request('GET','/manuscripts/2')
        self.assertEqual(details.status_code, 200, details.text)
        self.assertEqual(details.json(), {'manuscript_id':2,'review_round':1})
        authority = artifact_tests.ReviewerAuthority()
        self.db.execute('BEGIN')
        try:
            with self.assertRaises(artifact_read.ArtifactReadUnavailable):
                artifact_read.read_reviewer_artifact(self.db,authority.other,authority,self.binding.proof,self.binding.source,self.binding.storage,3)
            snapshot = artifact_read.read_reviewer_artifact(self.db,authority.reviewer,authority,self.binding.proof,self.binding.source,self.binding.storage,3)
        finally:
            self.db.rollback()
        self.assertEqual(snapshot.content,b'synthetic reviewer artifact')
        self.assertNotEqual(snapshot.content,self.binding.source.full.read_bytes())
        main.app.dependency_overrides[reviewer_demo_artifact_context] = lambda: DemoArtifactContext(self.binding.proof,self.binding.source,self.binding.storage)
        download = self.request('GET','/assignments/3/download')
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(download.content, b'synthetic reviewer artifact')
        self.assertEqual(self.request('GET','/assignments/3/download',user=4).status_code, 409)
        review = self.request('POST','/reviews/',json={'assignment_id':3,'comments':'Synthetic review','recommendation':'revision'})
        self.assertEqual(review.status_code, 201, review.text)
        self.assertEqual(self.db.execute('SELECT status FROM review_assignments WHERE assignment_id=3').fetchone()[0], 'completed')

    def test_missing_artifact_binding_never_returns_original(self):
        authority = artifact_tests.ReviewerAuthority()
        self.db.execute('BEGIN')
        try:
            with self.assertRaises(artifact_read.ArtifactReadUnavailable):
                artifact_read.read_reviewer_artifact(self.db,authority.reviewer,authority,self.binding.proof,self.binding.source,self.binding.storage,3)
        finally:
            self.db.rollback()

    def test_default_download_is_unchanged_and_experimental_fails_closed(self):
        root = self.binding.fx.fx.path.parent.resolve()
        relative = 'uploads/initial_editing/2/source.pdf'
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'%PDF-synthetic-original')
        original_paths = {table: self.db.execute(f'SELECT file_path FROM {table} WHERE manuscript_id=2').fetchone()[0]
                          for table in ('initial_editing_submissions', 'pre_review_confirmations', 'review_round_files')}
        for table in ('initial_editing_submissions', 'pre_review_confirmations', 'review_round_files'):
            self.db.execute(f'UPDATE {table} SET file_path=? WHERE manuscript_id=2', (relative,))
        self.db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=3")
        self.db.commit()
        with patch('app.review_files.BASE_DIR', root):
            self.assertEqual(self.request('GET', '/assignments/3/download').status_code, 409)
            main.app.dependency_overrides[reviewer_metadata_mode] = lambda: MetadataMode.DISABLED
            response = self.request('GET', '/assignments/3/download')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn(b'%PDF-synthetic-original', response.content)
        self.assertEqual(self.request('GET', '/manuscripts/2/download').status_code, 403)
        self.assertEqual(target.read_bytes(), b'%PDF-synthetic-original')
        for table, original_path in original_paths.items():
            self.db.execute(f'UPDATE {table} SET file_path=? WHERE manuscript_id=2', (original_path,))
        self.db.commit()
        self.binding.begin(); self.binding.bind(); self.db.commit()
        main.app.dependency_overrides[reviewer_demo_artifact_context] = lambda: DemoArtifactContext(self.binding.proof,self.binding.source,self.binding.storage)
        approved=self.request('GET', '/assignments/3/download')
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.content, b'synthetic reviewer artifact')
        self.assertEqual(target.read_bytes(), b'%PDF-synthetic-original')


if __name__ == '__main__': unittest.main()

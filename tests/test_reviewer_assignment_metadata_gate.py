"""Experimental assignment privacy: isolated synthetic SQLite and JWTs only."""
import unittest

import app.main as main
from app.security import create_access_token
from app.reviewer_metadata_gate import MetadataMode, reviewer_metadata_mode
from app import blind_policy_store as policy
from tests.test_reviewer_metadata_gate import MetadataGateHTTPTests, MetadataGateOldSchemaTests
from tests.test_reviewer_artifact_binding import T


class AssignmentMetadataTests(unittest.TestCase):
    def setUp(self):
        self.f = MetadataGateHTTPTests('test_double_blind_exact_allowlist_and_no_cache')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.db = self.f.db
        # Keep unrelated synthetic pending invitation out of this reviewer's list.
        self.db.execute('UPDATE review_assignments SET reviewer_id=4 WHERE assignment_id=1')
        self.db.commit()

    def request(self, user=2, **kwargs):
        return self.f.client.get('/assignments/my', headers={'Authorization': 'Bearer ' + create_access_token(user)}, **kwargs)

    def assert_unavailable(self):
        response = self.request()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json(), {'detail': 'Reviewer assignments unavailable'})
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_default_redacted_and_user_inputs_cannot_enable(self):
        response = self.request()
        self.assertEqual(response.status_code, 200, response.text)
        row = response.json()[0]
        self.assertNotIn('reviewer_id', row)
        self.assertNotIn('assigned_by', row)
        self.assertNotIn('manuscript_title', row)
        self.assertIn('assignment_id', row); self.assertIn('review_round', row)
        other = self.f.client.get('/assignments/my?metadata_mode=experimental', headers={'Authorization': 'Bearer ' + create_access_token(2), 'X-Reviewer-Metadata-Mode': 'experimental'})
        self.assertEqual(response.json(), other.json())
        self.assertEqual(self.f.client.get('/assignments/my').status_code, 401)
        self.assertEqual(self.request(1).status_code, 403)

    def test_double_blind_exact_allowlist_and_no_store(self):
        self.f.enable()
        response = self.request()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [{'assignment_id': 3, 'manuscript_id': 2, 'review_round': 1, 'status': 'assigned', 'invitation_status': 'accepted'}])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.request(1).status_code, 403)
        self.assertNotEqual(self.request(4).status_code, 200)

    def test_single_blind_assignment_omits_author_identity(self):
        self.db.execute('UPDATE review_assignments SET reviewer_id=4 WHERE assignment_id=3')
        self.db.execute("INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,created_at) VALUES (3,'Private title','Private abstract',1,'ready_for_peer_review',1,?)", (T,))
        self.db.commit()
        self.db.execute('BEGIN IMMEDIATE')
        policy.select_mode(self.db, 3, 'single_blind', 5)
        self.db.execute("INSERT INTO review_assignments(assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (4,3,2,5,1,'assigned',?)", (T,))
        self.db.execute("INSERT INTO reviewer_invitations VALUES (4,'accepted',?,?)", (T,T))
        policy.lock_mode(self.db,3,4,5,1)
        self.db.commit()
        self.f.enable()
        response = self.request()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [{'assignment_id':4,'manuscript_id':3,'review_round':1,'status':'assigned','invitation_status':'accepted'}])
        self.assertNotIn('author_id', response.json()[0])

    def test_pending_is_neutral_declined_fails_and_completed_is_visible(self):
        self.f.enable()
        self.db.execute("UPDATE reviewer_invitations SET status='pending' WHERE assignment_id=3")
        self.db.commit()
        self.assertEqual(self.request().json(), [{'assignment_id':3,'manuscript_id':2,'review_round':1,'status':'assigned','invitation_status':'pending'}])
        self.db.execute("UPDATE reviewer_invitations SET status='declined' WHERE assignment_id=3")
        self.db.commit(); self.assert_unavailable()
        self.db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=3")
        self.db.execute("UPDATE review_assignments SET status='completed' WHERE assignment_id=3")
        self.db.commit()
        self.assertEqual(self.request().json()[0]['status'], 'completed')

    def test_stale_round_and_invalidation(self):
        self.f.enable()
        self.db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=2')
        self.db.commit()
        self.assert_unavailable()
        self.db.execute('UPDATE manuscripts SET review_round=1 WHERE manuscript_id=2')
        self.db.execute("INSERT INTO reviewer_invitation_invalidations VALUES ('revoke',3,'cancelled',NULL,5,?,'editorial_cancellation')", (T,))
        self.db.commit()
        self.assert_unavailable()

    def test_inactive_or_missing_lifecycle(self):
        self.f.enable()
        self.db.execute("INSERT INTO account_lifecycle_events VALUES ('disabled',2,2,'active','disabled',2,5,?,'administrative_disable')", (T,))
        self.db.execute("UPDATE account_lifecycle SET state='disabled',sequence=2,auth_generation=2,last_event_id='disabled' WHERE user_id=2")
        self.db.commit()
        self.assert_unavailable()
        self.db.execute('DELETE FROM account_lifecycle WHERE user_id=2')
        self.db.commit()
        self.assert_unavailable()

    def test_missing_policy_and_incompatible_schema(self):
        self.f.enable()
        self.db.execute('DELETE FROM blind_policies WHERE manuscript_id=2')
        self.db.commit()
        self.assert_unavailable()
        self.db.execute("DELETE FROM schema_migrations WHERE migration_id='011_blind_review_policy'")
        self.db.commit()
        self.assert_unavailable()

    def test_unlocked_and_unclassified_fail_closed(self):
        self.db.execute('UPDATE review_assignments SET reviewer_id=4 WHERE assignment_id=3')
        self.db.commit()
        for mid, mode in ((6,None),(7,'double_blind')):
            self.db.execute("INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,created_at) VALUES (?,'Private','Private',1,'ready_for_peer_review',1,?)", (mid,T))
            self.db.commit()
            if mode:
                self.db.execute('BEGIN IMMEDIATE'); policy.select_mode(self.db,mid,mode,5); self.db.commit()
            self.db.execute("INSERT INTO review_assignments(assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (?,?,2,5,1,'assigned',?)", (mid,mid,T))
            self.db.execute("INSERT INTO reviewer_invitations VALUES (?,'accepted',?,?)", (mid,T,T))
            self.db.commit()
            self.f.enable(); self.assert_unavailable()
            self.db.execute("UPDATE reviewer_invitations SET status='pending' WHERE assignment_id=?", (mid,)); self.db.commit()
            self.assert_unavailable()
            self.db.execute('UPDATE review_assignments SET reviewer_id=4 WHERE assignment_id=?',(mid,)); self.db.commit()

    def test_mixed_eligible_and_pending_are_neutral(self):
        self.db.execute("INSERT INTO review_assignments(assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (10,2,2,5,1,'assigned',?)", (T,))
        self.db.execute("INSERT INTO reviewer_invitations VALUES (10,'pending',?,NULL)", (T,))
        self.db.commit()
        self.f.enable()
        response = self.request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([x['invitation_status'] for x in response.json()], ['accepted', 'pending'])
        self.assertNotIn('author_id', response.json()[1])

    def test_unknown_mode_and_existing_download(self):
        main.app.dependency_overrides[reviewer_metadata_mode] = lambda: 'experimental'
        self.assert_unavailable()
        self.f.enable()
        response = self.f.client.get('/assignments/3/download', headers={'Authorization': 'Bearer ' + create_access_token(2)})
        self.assertEqual(response.status_code, 409)


class AssignmentMetadataOldSchemaTests(unittest.TestCase):
    def test_default_legacy_and_experimental_failure(self):
        f = MetadataGateOldSchemaTests('test_reviewer_details_fail_closed_without_policy_schema')
        f.setUp(); self.addCleanup(f.doCleanups)
        f.f.current = f.f.reviewer
        response = f.f.client.get('/assignments/my')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('reviewer_id', response.json()[0])
        self.assertIn('assignment_id', response.json()[0])
        main.app.dependency_overrides[reviewer_metadata_mode] = lambda: MetadataMode.EXPERIMENTAL
        response = f.f.client.get('/assignments/my')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers['cache-control'], 'no-store')


if __name__ == '__main__': unittest.main()

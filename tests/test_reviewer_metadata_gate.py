"""HTTP privacy-gate tests: disposable SQLite, synthetic users and JWTs only."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.main as main
import app.routers.manuscripts as manuscripts
from app.database import get_db
from app.security import create_access_token
from app.reviewer_metadata_gate import MetadataMode, reviewer_metadata_mode
from app import blind_policy_store as policy
from tests import test_reviewer_artifact_binding, test_reviewer_download


class MetadataGateHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fx=test_reviewer_artifact_binding.BindingTests('test_valid_binding_and_no_original_mutation')
        self.fx.setUp(); self.addCleanup(self.fx.doCleanups)
        self.db=self.fx.db; path=self.fx.fx.fx.path
        self.engine=create_engine(f'sqlite:///{path}',connect_args={'check_same_thread':False})
        @event.listens_for(self.engine,'connect')
        def foreign_keys(connection,_): connection.execute('PRAGMA foreign_keys=ON')
        self.Session=sessionmaker(bind=self.engine)
        def isolated_db():
            session=self.Session()
            try: yield session
            finally: session.close()
        main.app.dependency_overrides[get_db]=isolated_db
        self.addCleanup(main.app.dependency_overrides.clear)
        self.addCleanup(self.engine.dispose)
        self.engine_patch=patch.object(main,'engine',self.engine); self.engine_patch.start(); self.addCleanup(self.engine_patch.stop)
        self.path_patch=patch.object(manuscripts,'BASE_DIR',path.parent); self.path_patch.start(); self.addCleanup(self.path_patch.stop)
        self.client=TestClient(main.app); self.client.__enter__(); self.addCleanup(self.client.__exit__,None,None,None)

    def request(self, user=2, mid=2, **kwargs):
        return self.client.get(f'/manuscripts/{mid}',headers={'Authorization':'Bearer '+create_access_token(user),**kwargs.pop('headers',{})},**kwargs)

    def enable(self): main.app.dependency_overrides[reviewer_metadata_mode]=lambda: MetadataMode.EXPERIMENTAL

    def test_default_disabled_and_request_inputs_cannot_enable(self):
        normal=self.request(); self.assertEqual(normal.status_code,200)
        self.assertEqual(normal.json(), {'manuscript_id':2,'review_round':1})
        self.assertNotIn('author_id',normal.json()); self.assertNotIn('abstract',normal.json())
        controlled=self.request(headers={'X-Reviewer-Metadata-Mode':'experimental'},params={'metadata_mode':'experimental'})
        self.assertEqual(controlled.json(),normal.json())
        self.assertEqual(self.client.get('/manuscripts/2').status_code,401)

    def test_double_blind_exact_allowlist_and_no_cache(self):
        self.enable(); result=self.request()
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json(),{'manuscript_id':2,'review_round':1})
        self.assertEqual(result.headers['cache-control'],'no-store')
        for forbidden in ('author_id','author','email','reviewer_id','assigned_by','abstract','title','file_path'):
            self.assertNotIn(forbidden,result.json())

    def test_single_blind_allowlist(self):
        self.db.execute("INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,created_at) VALUES (3,'Secret title','Secret abstract',1,'ready_for_peer_review',1,?)",(test_reviewer_artifact_binding.T,)); self.db.commit()
        self.db.execute('BEGIN IMMEDIATE'); policy.select_mode(self.db,3,'single_blind',5)
        self.db.execute("INSERT INTO review_assignments(assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (4,3,2,5,1,'assigned',?)",(test_reviewer_artifact_binding.T,))
        self.db.execute("INSERT INTO reviewer_invitations VALUES (4,'accepted',?,?)",(test_reviewer_artifact_binding.T,test_reviewer_artifact_binding.T)); policy.lock_mode(self.db,3,4,5,1); self.db.commit()
        self.enable(); result=self.request(mid=3)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json(),{'manuscript_id':3,'review_round':1,'author_name':'Author'})
        self.assertNotIn('author_id', result.json())

    def test_other_roles_preserve_existing_response(self):
        self.enable()
        for actor in (1,5):
            with self.subTest(actor=actor):
                response=self.request(actor); self.assertEqual(response.status_code,200,response.text); self.assertEqual(response.json()['author_id'],1)
        self.assertEqual(self.request(3).status_code,404)  # synthetic editor has no accepted editor invitation
        self.db.execute("INSERT INTO initial_editor_invitations(manuscript_id,editor_id,invited_by,status,invited_at) VALUES (2,3,5,'accepted',?)",(test_reviewer_artifact_binding.T,)); self.db.commit()
        self.assertEqual(self.request(3).status_code,200)
        self.assertEqual(self.request(4).status_code,404)
        self.db.execute("INSERT INTO users(user_id,name,email,password_hash,role,created_at) VALUES (6,'Formatter','formatter@example.test','x','formatter',?)",(test_reviewer_artifact_binding.T,)); self.db.commit()
        self.assertEqual(self.request(6).status_code,404)

    def test_stale_round_pending_declined_and_revoked(self):
        self.enable()
        for state in ('pending','declined'):
            self.db.execute('UPDATE reviewer_invitations SET status=? WHERE assignment_id=3',(state,)); self.db.commit(); self.assertEqual(self.request().status_code,404)
        self.db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=3")
        self.db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=2'); self.db.commit(); self.assertEqual(self.request().status_code,404)
        self.db.execute('UPDATE manuscripts SET review_round=1 WHERE manuscript_id=2')
        self.db.execute("INSERT INTO reviewer_invitation_invalidations VALUES ('revoke',3,'cancelled',NULL,5,?,'editorial_cancellation')",(test_reviewer_artifact_binding.T,)); self.db.commit()
        self.assertEqual(self.request().status_code,404)

    def test_disabled_missing_and_inconsistent_lifecycle(self):
        self.enable(); t=test_reviewer_artifact_binding.T
        self.db.execute("INSERT INTO account_lifecycle_events VALUES ('disabled',2,2,'active','disabled',2,5,?,'administrative_disable')",(t,))
        self.db.execute("UPDATE account_lifecycle SET state='disabled',sequence=2,auth_generation=2,last_event_id='disabled' WHERE user_id=2"); self.db.commit()
        self.assertEqual(self.request().status_code,404)
        self.db.execute('DELETE FROM account_lifecycle WHERE user_id=2'); self.db.commit()
        self.assertEqual(self.request().status_code,404)

    def test_missing_policy_and_incompatible_schema_fail_closed(self):
        self.enable()
        self.db.execute('DELETE FROM blind_policies WHERE manuscript_id=2'); self.db.commit()
        self.assertEqual(self.request().status_code,404)
        self.db.execute("DELETE FROM schema_migrations WHERE migration_id='011_blind_review_policy'"); self.db.commit()
        self.assertEqual(self.request().status_code,503)
        self.assertEqual(self.request(1).status_code,200)

    def test_unclassified_and_unlocked_policies_fail_closed(self):
        for mid,mode in ((6,None),(7,'double_blind')):
            self.db.execute("INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,created_at) VALUES (?,'Synthetic','Synthetic',1,'ready_for_peer_review',1,?)",(mid,test_reviewer_artifact_binding.T)); self.db.commit()
            if mode:
                self.db.execute('BEGIN IMMEDIATE'); policy.select_mode(self.db,mid,mode,5); self.db.commit()
            self.db.execute("INSERT INTO review_assignments(assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (?,?,2,5,1,'assigned',?)",(mid,mid,test_reviewer_artifact_binding.T))
            self.db.execute("INSERT INTO reviewer_invitations VALUES (?,'accepted',?,?)",(mid,test_reviewer_artifact_binding.T,test_reviewer_artifact_binding.T)); self.db.commit()
            self.enable(); self.assertEqual(self.request(mid=mid).status_code,404)

    def test_schema_drift_fails_closed(self):
        self.enable(); self.db.execute('DROP TRIGGER blind_events_no_delete'); self.db.commit()
        self.assertEqual(self.request().status_code,503)

    def test_unknown_mode_fails_closed_and_download_unchanged(self):
        main.app.dependency_overrides[reviewer_metadata_mode]=lambda:'experimental'
        self.assertEqual(self.request().status_code,503)
        self.enable()
        response=self.client.get('/assignments/3/download',headers={'Authorization':'Bearer '+create_access_token(2)})
        # Existing synthetic source path is deliberately outside upload roots, so
        # the existing download rejects it. The metadata gate must not change it.
        self.assertEqual(response.status_code,409)


class MetadataGateOldSchemaTests(unittest.TestCase):
    def setUp(self):
        self.f=test_reviewer_download.ReviewerDownloadsTest('test_first_round_binding_and_access')
        self.f.setUp(); self.addCleanup(self.f.tearDown)
        # Fixture-only migration-owned tables pre-created by metadata are removed;
        # the route's test authentication is explicitly overridden by the fixture.
        for table in ('email_delivery_attempts','email_outbox','notification_events','email_verification_challenges','user_email_verifications','reviewer_invitation_invalidations','account_lifecycle','account_lifecycle_events'):
            self.f.db.connection().exec_driver_sql(f'DROP TABLE IF EXISTS {table}')
        self.f.db.commit()
        # Simulate a genuinely old schema by removing migration 009.
        connection = self.f.db.connection()
        connection.exec_driver_sql(
            "DELETE FROM schema_migrations "
            "WHERE migration_id='009_account_invitation_lifecycle'"
        )
        self.f.db.commit()

        # Commit may release the previous SQLAlchemy connection.
        # Acquire a fresh connection before checking the old schema.
        connection = self.f.db.connection()

        self.assertIsNone(
            connection.exec_driver_sql(
                "SELECT migration_id FROM schema_migrations "
                "WHERE migration_id='009_account_invitation_lifecycle'"
            ).scalar()
        )
        self.assertEqual(self.f.assign(self.f.reviewer,1).status_code,201)

    def test_reviewer_details_fail_closed_without_policy_schema(self):
        self.f.current=self.f.reviewer
        before=self.f.client.get(f'/manuscripts/{self.f.mid}')
        self.assertEqual(before.status_code,503,before.text); self.assertNotIn('author_id',before.json())
        main.app.dependency_overrides[reviewer_metadata_mode]=lambda: MetadataMode.EXPERIMENTAL
        self.assertEqual(self.f.client.get(f'/manuscripts/{self.f.mid}').status_code,503)


if __name__=='__main__': unittest.main()

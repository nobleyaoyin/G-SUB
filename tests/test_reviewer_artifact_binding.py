"""Evidence-gated binding tests, synthetic data in disposable SQLite only."""
from importlib import import_module
import sqlite3
import unittest
from unittest.mock import patch

from app import blind_policy_store as policy, reviewer_artifact_binding as binding
from app import reviewer_artifact_evidence as evidence, reviewer_artifact_service as service
from app.reviewer_artifact_storage import ArtifactStorage, StorageError
from tests import test_lifecycle_migration_009, test_reviewer_artifact_service, test_artifact_evidence

T='2026-01-02T03:04:05.000000Z'


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.fx=test_lifecycle_migration_009.LifecycleMigrationTest('test_additive_idempotent_and_preserves_every_old_table')
        self.fx.setUp(); self.addCleanup(self.fx.doCleanups); self.fx.migrate()
        for name in (
            '010_reviewer_profiles',
            '011_blind_review_policy',
            '012_reviewer_artifacts',
            '013_artifact_evidence',
            '014_online_document_versions',
            '015_google_oidc',
            '016_onlyoffice_sessions',
            '017_ai_prescreening',
            '018_general_comments',
            '019_personal_notes',
        ):
            import_module('migrations.' + name).migrate(self.fx.fx.path)
        self.db=self.fx.connect(); self.addCleanup(self.db.close)
        root=self.fx.fx.path.parent.resolve(); private=root/'artifact-private'; private.mkdir(mode=0o700)
        (root/'source.pdf').write_bytes(b'%PDF-synthetic-source')
        self.storage=ArtifactStorage(private); self.addCleanup(self.storage.close)
        self.db.execute("INSERT INTO users(user_id,name,email,password_hash,role,created_at) VALUES (5,'EIC','eic@example.test','x','eic',?)",(T,))
        self.db.execute("INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,created_at) VALUES (2,'Synthetic','Synthetic',1,'ready_for_peer_review',1,?)",(T,))
        self.db.execute("INSERT INTO initial_editing_submissions(submission_id,manuscript_id,editor_id,file_path,comments,status,created_at,eic_approved_by,eic_reviewed_at) VALUES (1,2,3,'source.pdf','Synthetic','eic_approved',?,5,?)",(T,T))
        self.db.execute("INSERT INTO pre_review_confirmations(confirmation_id,manuscript_id,submission_id,author_id,file_path,decision,comments,confirmed_at) VALUES (1,2,1,1,'source.pdf','confirm','Synthetic',?)",(T,))
        self.db.execute("INSERT INTO review_round_files(round_file_id,manuscript_id,review_round,source_kind,confirmation_id,file_path,created_at) VALUES (1,2,1,'initial_editing',1,'source.pdf',?)",(T,))
        self.db.execute("INSERT INTO account_lifecycle_events VALUES ('synthetic-active',2,1,NULL,'active',1,5,?,'initial_enrollment')",(T,))
        self.db.execute("INSERT INTO account_lifecycle VALUES (2,'active',1,1,'synthetic-active')"); self.db.commit()
        self.auth=test_reviewer_artifact_service.SyntheticAuthority(3,5)
        self.source=test_reviewer_artifact_service.SyntheticProvenance(root,2,1,'source.pdf')
        self.proof=test_artifact_evidence.SyntheticPriorProof(self.source)
        self.db.execute('BEGIN IMMEDIATE'); policy.select_mode(self.db,2,'double_blind',5)
        self.sid=evidence.capture_source(self.db,self.auth.eic,self.auth,self.proof,self.source,2,1,0)
        self.art=service.prepare(self.db,self.auth.editor,self.auth,self.source,self.storage,2,1,b'synthetic reviewer artifact','txt',1)
        self.db.execute("INSERT INTO review_assignments(assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (3,2,2,5,1,'assigned',?)",(T,))
        self.db.execute("INSERT INTO reviewer_invitations VALUES (3,'accepted',?,?)",(T,T))
        self.db.execute('INSERT INTO review_assignment_files VALUES (3,1,?)',(T,))
        policy.lock_mode(self.db,2,3,5,1)
        evidence.approve_with_evidence(self.db,self.auth.eic,self.auth,self.source,self.storage,self.art.artifact_id,self.sid,1,checklist_acknowledged=True)
        self.db.commit()

    def begin(self): self.db.execute('BEGIN IMMEDIATE')
    def bind(self, **kwargs):
        values={'expected_policy_revision':2,'expected_artifact_revision':2,'expected_source_revision':1}; values.update(kwargs)
        return binding.bind(self.db,self.auth.eic,self.auth,self.proof,self.source,self.storage,3,self.art.artifact_id,**values)

    def test_valid_binding_and_no_original_mutation(self):
        before=self.source.full.read_bytes(); self.begin(); self.assertEqual(self.bind(),self.art.artifact_id); self.db.commit()
        self.assertEqual(self.db.execute('SELECT assignment_id,artifact_id FROM reviewer_artifact_assignments').fetchall(),[(3,self.art.artifact_id)])
        self.assertEqual(self.db.execute('SELECT round_file_id FROM review_assignment_files WHERE assignment_id=3').fetchone()[0],1)
        self.assertEqual(self.source.full.read_bytes(),before)

    def test_missing_evidence_and_unproven_generic_approval(self):
        self.begin()
        generic=service.prepare(self.db,self.auth.editor,self.auth,self.source,self.storage,2,1,b'generic artifact','txt',2)
        service.transition(self.db,self.auth.eic,self.auth,self.source,self.storage,generic.artifact_id,'approved',1,human_review_attested=True)
        self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError):
            binding.bind(self.db,self.auth.eic,self.auth,self.proof,self.source,self.storage,3,generic.artifact_id,expected_policy_revision=2,expected_artifact_revision=2,expected_source_revision=1)
        self.db.rollback()

    def test_invalid_proof_and_digest(self):
        self.proof.digest='0'*64; self.begin()
        with self.assertRaises(service.ArtifactError): self.bind()
        self.db.rollback(); self.proof.digest=self.source.digest
        path=self.fx.fx.path.parent.resolve()/'artifact-private'/self.art.storage_id; path.chmod(0o600); path.write_bytes(b'X'*len(b'synthetic reviewer artifact'))
        self.begin()
        with self.assertRaises(StorageError): self.bind()
        self.db.rollback()

    def test_wrong_assignment_and_round(self):
        self.begin()
        with self.assertRaises(service.ArtifactError): binding.bind(self.db,self.auth.eic,self.auth,self.proof,self.source,self.storage,999,self.art.artifact_id,expected_policy_revision=2,expected_artifact_revision=2,expected_source_revision=1)
        self.db.rollback(); self.db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=2'); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.bind()
        self.db.rollback()

    def test_wrong_artifact_and_policy_revision(self):
        self.begin()
        with self.assertRaises(service.ArtifactError): self.bind(expected_policy_revision=1)
        with self.assertRaises(service.ArtifactError): self.bind(expected_source_revision=2)
        with self.assertRaises(service.ArtifactError): binding.bind(self.db,self.auth.eic,self.auth,self.proof,self.source,self.storage,3,'f'*32,expected_policy_revision=2,expected_artifact_revision=2,expected_source_revision=1)
        self.db.rollback()

    def test_missing_unlocked_and_single_blind_policies_fail_closed(self):
        for fake in (None, {'mode':'single_blind','locked_at':T,'revision':2}, {'mode':'double_blind','locked_at':None,'revision':2}):
            self.begin()
            with patch.object(binding.blind_policy_store,'read_policy',return_value=fake):
                with self.assertRaises(service.ArtifactError): self.bind()
            self.db.rollback()

    def test_later_source_evidence_makes_approval_stale(self):
        self.proof.proof='b'*32; self.begin()
        evidence.capture_source(self.db,self.auth.eic,self.auth,self.proof,self.source,2,1,1); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.bind()
        self.db.rollback()

    def test_changed_source_and_wrong_manuscript_fail_closed(self):
        self.source.full.write_bytes(b'%PDF-other'); self.begin()
        with self.assertRaises(StorageError): self.bind()
        self.db.rollback()
        self.source.full.write_bytes(b'%PDF-synthetic-source')
        self.db.execute('UPDATE review_assignments SET manuscript_id=1 WHERE assignment_id=3'); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.bind()
        self.db.rollback()

    def test_invitation_pending_declined_and_invalidation(self):
        for state in ('pending','declined'):
            self.db.execute('UPDATE reviewer_invitations SET status=? WHERE assignment_id=3',(state,)); self.db.commit(); self.begin()
            with self.assertRaises(service.ArtifactError): self.bind()
            self.db.rollback()
        self.db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=3")
        self.db.execute("INSERT INTO reviewer_invitation_invalidations VALUES ('invalid',3,'cancelled',NULL,5,?,'editorial_cancellation')",(T,)); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.bind()
        self.db.rollback()

    def test_withdrawn_unverified_and_duplicate(self):
        self.begin(); service.transition(self.db,self.auth.eic,self.auth,self.source,self.storage,self.art.artifact_id,'withdrawn',2); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.bind(expected_artifact_revision=3)
        self.db.rollback()

    def test_duplicate_binding_rollback_and_unknown_ack(self):
        self.begin(); self.bind(); self.db.rollback()
        self.assertEqual(self.db.execute('SELECT count(*) FROM reviewer_artifact_assignments').fetchone()[0],0)
        self.begin(); self.bind(); self.db.commit()  # Synthetic lost acknowledgement after commit.
        self.assertEqual(self.db.execute('SELECT count(*) FROM reviewer_artifact_assignments').fetchone()[0],1)
        self.begin()
        with self.assertRaises(service.ArtifactError): self.bind()
        self.db.rollback()

    def test_competing_binding_transactions(self):
        other=self.fx.connect(); self.addCleanup(other.close); other.execute('PRAGMA busy_timeout=0')
        self.begin(); self.bind()
        with self.assertRaises(sqlite3.OperationalError): other.execute('BEGIN IMMEDIATE')
        self.db.commit(); other.execute('BEGIN IMMEDIATE')
        with self.assertRaises(service.ArtifactError):
            binding.bind(other,self.auth.eic,self.auth,self.proof,self.source,self.storage,3,self.art.artifact_id,expected_policy_revision=2,expected_artifact_revision=2,expected_source_revision=1)
        other.rollback()
        self.assertEqual(self.db.execute('SELECT count(*) FROM reviewer_artifact_assignments').fetchone()[0],1)

    def test_missing_schema_policy_and_auth(self):
        self.begin()
        with self.assertRaises(service.ArtifactError): binding.bind(self.db,5,self.auth,self.proof,self.source,self.storage,3,self.art.artifact_id,expected_policy_revision=2,expected_artifact_revision=2,expected_source_revision=1)
        self.db.rollback(); self.db.execute("DELETE FROM schema_migrations WHERE migration_id='009_account_invitation_lifecycle'"); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.bind()
        self.db.rollback()

    def test_explicit_legacy_lifecycle_and_lock_contention(self):
        self.db.execute('DELETE FROM account_lifecycle WHERE user_id=2'); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.bind()
        self.db.rollback()
        other=self.fx.connect(); self.addCleanup(other.close); other.execute('PRAGMA busy_timeout=0'); self.begin()
        with self.assertRaises(sqlite3.OperationalError): other.execute('BEGIN IMMEDIATE')
        self.db.rollback()


if __name__=='__main__': unittest.main()

"""Evidence tests with synthetic prior proof and disposable SQLite/files."""
from importlib import import_module
import sqlite3
import unittest
from unittest.mock import patch

from app import reviewer_artifact_evidence as evidence
from app import reviewer_artifact_service as service
from tests import test_reviewer_artifact_service

migration=import_module('migrations.013_artifact_evidence')


class SyntheticPriorProof:
    """Test-only prior approval proof; never used for actual environments."""
    def __init__(self, source): self.source=source; self.proof='a'*32; self.digest=source.digest
    def verify_prospective(self, db, manuscript_id, review_round, source_id, confirmation_id):
        if (manuscript_id,review_round,source_id)!=(self.source.mid,1,self.source.sid) or confirmation_id is None: raise service.ArtifactError('Synthetic proof unavailable')
        return self.proof,self.digest,self.source.size,'pdf'


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fx=test_reviewer_artifact_service.ArtifactServiceTests('test_prepare_approve_and_audit')
        self.fx.setUp(); self.addCleanup(self.fx.doCleanups)
        self.db=self.fx.db; self.f=self.fx.fixture
        self.db.execute("UPDATE initial_editing_submissions SET eic_approved_by=?,eic_reviewed_at='2026-01-01' WHERE manuscript_id=?",(self.f.actor,self.f.mid)); self.db.commit()
        migration.migrate(self.f.fx.f.db_path)
        self.proof=SyntheticPriorProof(self.fx.source)

    def begin(self): self.db.execute('BEGIN IMMEDIATE')
    def capture(self, revision=0):
        return evidence.capture_source(self.db,self.fx.auth.eic,self.fx.auth,self.proof,self.fx.source,self.f.mid,self.f.source,revision)
    def approve(self, artifact, source_id, revision=1, *, principal=None, ack=True, version=1):
        return evidence.approve_with_evidence(self.db,self.fx.auth.eic if principal is None else principal,self.fx.auth,self.fx.source,self.fx.storage,artifact.artifact_id,source_id,revision,checklist_acknowledged=ack,checklist_version=version)
    def setup_artifact(self):
        self.begin(); source_id=self.capture(); artifact=self.fx.prepare(); self.db.commit(); return source_id,artifact

    def test_migration_idempotency_empty_and_integrity(self):
        migration.migrate(self.f.fx.f.db_path)
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_provenance_evidence').fetchone()[0],0)
        self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_capture_and_durable_approval(self):
        sid,artifact=self.setup_artifact(); self.begin(); evid,rev=self.approve(artifact,sid); self.db.commit()
        self.assertEqual(rev,2)
        self.assertEqual(self.db.execute('SELECT checklist_key,checklist_version,acknowledged,approver_id FROM artifact_approval_evidence WHERE evidence_id=?',(evid,)).fetchone(),('reviewer_document',1,1,self.f.actor))
        self.assertEqual(self.db.execute('SELECT status FROM reviewer_artifacts').fetchone()[0],'approved')

    def test_missing_proof_wrong_source_and_digest(self):
        self.begin(); self.proof.digest='0'*64
        with self.assertRaises(service.ArtifactError): self.capture()
        with self.assertRaises(service.ArtifactError): evidence.capture_source(self.db,self.fx.auth.eic,self.fx.auth,self.proof,self.fx.source,999999,self.f.source,0)
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_provenance_evidence').fetchone()[0],0)

    def test_missing_eic_or_confirmation(self):
        self.db.execute('UPDATE initial_editing_submissions SET eic_approved_by=NULL WHERE manuscript_id=?',(self.f.mid,)); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.capture()
        self.db.rollback()
        self.db.execute("UPDATE pre_review_confirmations SET decision='reject' WHERE manuscript_id=?",(self.f.mid,)); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.capture()
        self.db.rollback()

    def test_acknowledgement_authorization_and_revision(self):
        sid,artifact=self.setup_artifact(); self.begin()
        for kwargs in ({'ack':False},{'version':2},{'principal':self.fx.auth.editor},{'revision':2}):
            with self.subTest(kwargs=kwargs),self.assertRaises(service.ArtifactError): self.approve(artifact,sid,**kwargs)
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT status FROM reviewer_artifacts').fetchone()[0],'prepared')

    def test_no_source_evidence_and_stale_source(self):
        self.begin(); artifact=self.fx.prepare(); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.approve(artifact,'f'*32)
        self.db.rollback()
        self.begin(); sid=self.capture(); self.db.commit()
        self.db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=?',(self.f.mid,)); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.approve(artifact,sid)
        self.db.rollback()

    def test_duplicate_proof_stale_revision_and_audit_immutability(self):
        sid,artifact=self.setup_artifact(); self.begin()
        with self.assertRaises(service.ArtifactError): self.capture(0)
        with self.assertRaises(sqlite3.IntegrityError): self.capture(1)
        self.db.rollback(); self.begin(); self.approve(artifact,sid); self.db.commit()
        for table in ('source_provenance_evidence','artifact_approval_evidence'):
            for sql in (f'DELETE FROM {table}',f'UPDATE {table} SET revision=revision'):
                with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)
                self.db.rollback()
        self.begin()
        with self.assertRaises(service.ArtifactError): self.approve(artifact,sid)
        self.db.rollback()

    def test_approval_evidence_failure_and_caller_rollback(self):
        sid,artifact=self.setup_artifact(); self.begin()
        with patch.object(evidence,'uuid4',side_effect=RuntimeError('synthetic evidence failure')):
            with self.assertRaises(RuntimeError): self.approve(artifact,sid)
        self.assertEqual(self.db.execute('SELECT status FROM reviewer_artifacts').fetchone()[0],'prepared')
        self.approve(artifact,sid); self.db.rollback()
        self.assertEqual(self.db.execute('SELECT status FROM reviewer_artifacts').fetchone()[0],'prepared')
        self.assertEqual(self.db.execute('SELECT count(*) FROM artifact_approval_evidence').fetchone()[0],0)

    def test_concurrency_and_unknown_commit(self):
        sid,artifact=self.setup_artifact(); other=self.f.fx.connect(); self.begin()
        with self.assertRaises(sqlite3.OperationalError): other.execute('BEGIN IMMEDIATE')
        evid,_=self.approve(artifact,sid); self.db.commit()  # Synthetic acknowledgement loss after commit.
        self.assertIsNotNone(other.execute('SELECT 1 FROM artifact_approval_evidence WHERE evidence_id=?',(evid,)).fetchone())
        self.begin()
        with self.assertRaises(service.ArtifactError): self.approve(artifact,sid)
        self.db.rollback()

    def test_missing_schema_and_legacy_unchanged(self):
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_provenance_evidence').fetchone()[0],0)
        self.db.execute("DELETE FROM schema_migrations WHERE migration_id='013_artifact_evidence'"); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.capture()
        self.db.rollback()

    def test_migration_failure_and_partial_conflict_roll_back(self):
        other=test_reviewer_artifact_service.ArtifactServiceTests('test_prepare_approve_and_audit'); other.setUp()
        try:
            db=other.db; path=other.fixture.fx.f.db_path

            # Reset Migration 013 only in this disposable test database.
            # Keep Migration 012 and all its prerequisite tables intact.
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("DROP TABLE IF EXISTS artifact_approval_evidence")
            db.execute("DROP TABLE IF EXISTS source_provenance_evidence")
            db.execute(
                "DELETE FROM schema_migrations "
                "WHERE migration_id='013_artifact_evidence'"
            )
            db.commit()
            db.execute("CREATE TRIGGER fail_evidence BEFORE INSERT ON schema_migrations WHEN NEW.migration_id='013_artifact_evidence' BEGIN SELECT RAISE(ABORT,'synthetic'); END"); db.commit()
            with self.assertRaises(sqlite3.IntegrityError): migration.migrate(path)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='source_provenance_evidence'").fetchone())
            db.execute('DROP TRIGGER fail_evidence'); db.execute('CREATE TABLE source_provenance_evidence(wrong TEXT)'); db.commit()
            with self.assertRaises(RuntimeError): migration.migrate(path)
            self.assertIsNone(db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='013_artifact_evidence'").fetchone())
        finally: other.doCleanups()

    def test_full_chain_including_optional_010(self):
        from tests.test_lifecycle_migration_009 import LifecycleMigrationTest
        other=LifecycleMigrationTest('test_additive_idempotent_and_preserves_every_old_table'); other.setUp()
        try:
            other.migrate()
            for name in ('010_reviewer_profiles','011_blind_review_policy','012_reviewer_artifacts','013_artifact_evidence'):
                import_module('migrations.'+name).migrate(other.fx.path)
            migration.migrate(other.fx.path)
            with other.connect() as db:
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
                self.assertEqual(db.execute('SELECT count(*) FROM artifact_approval_evidence').fetchone()[0],0)
        finally: other.doCleanups()


if __name__=='__main__': unittest.main()

"""Synthetic adapters, temporary SQLite and private filesystem only."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from app import reviewer_artifact_service as service
from app.reviewer_artifact_storage import ArtifactStorage, PublicationOutcomeUnknown, StorageError
from tests import test_reviewer_artifact_migration


class SyntheticAuthority:
    def __init__(self, editor, eic):
        self.editor, self.eic = object(), object()
        self.identities = {self.editor: editor, self.eic: eic}
    def authorize(self, db, principal, action, manuscript_id, *, prepared_by=None):
        actor = self.identities.get(principal)
        if actor is None or (action != 'prepare' and principal is not self.eic): raise service.ArtifactError('Unauthorized synthetic principal')
        if action == 'approved' and actor == prepared_by: raise service.ArtifactError('Independent synthetic approval required')
        if not db.execute('SELECT 1 FROM users WHERE user_id=?', (actor,)).fetchone(): raise service.ArtifactError('Actor unavailable')
        return actor


class SyntheticProvenance:
    def __init__(self, root, manuscript_id, source_id, path):
        self.mid, self.sid, self.path = manuscript_id, source_id, path
        self.full = root / path
        content = self.full.read_bytes()  # Synthetic approved fixture only.
        self.digest, self.size = hashlib.sha256(content).hexdigest(), len(content)
    @contextmanager
    def open_attested_source(self, db, manuscript_id, review_round, source_id, stored_path):
        if (manuscript_id, review_round, source_id, stored_path) != (self.mid, 1, self.sid, self.path): raise service.ArtifactError('No synthetic source attestation')
        fd = os.open(self.full, os.O_RDONLY | os.O_NOFOLLOW)
        try: yield fd, self.digest, self.size, 'pdf'
        finally: os.close(fd)


class ArtifactServiceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_reviewer_artifact_migration.ArtifactMigrationTests('test_additive_idempotent_preserves_legacy_and_integrity')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.migrate(); self.db = self.fixture.db
        f = self.fixture.fx.f
        self.root = f.root.resolve(); private = self.root / 'artifact-private'; private.mkdir(mode=0o700)
        self.storage = ArtifactStorage(private); self.addCleanup(self.storage.close)
        self.auth = SyntheticAuthority(f.editor.user_id, self.fixture.actor)
        self.source = SyntheticProvenance(f.root, self.fixture.mid, self.fixture.source, f.pdf)

    def prepare(self, revision=1, content=b'synthetic reviewer document', fmt='txt'):
        return service.prepare(self.db, self.auth.editor, self.auth, self.source, self.storage, self.fixture.mid, self.fixture.source, content, fmt, revision)

    def change(self, artifact, action, revision, *, principal=None, attested=False):
        return service.transition(self.db, self.auth.eic if principal is None else principal, self.auth, self.source, self.storage, artifact.artifact_id, action, revision, human_review_attested=attested)

    def begin(self): self.db.execute('BEGIN IMMEDIATE')

    def test_prepare_approve_and_audit(self):
        original = self.source.full.read_bytes(); self.begin(); artifact = self.prepare(); self.db.commit()
        row = self.db.execute('SELECT source_sha256,status,state_revision FROM reviewer_artifacts WHERE artifact_id=?',(artifact.artifact_id,)).fetchone()
        self.assertEqual(row,(hashlib.sha256(original).hexdigest(),'prepared',1))
        self.begin(); self.assertEqual(self.change(artifact,'approved',1,attested=True),2); self.db.commit()
        self.assertEqual(self.db.execute('SELECT status,approved_by FROM reviewer_artifacts').fetchone(),('approved',self.fixture.actor))
        self.assertEqual(self.db.execute('SELECT action,revision FROM reviewer_artifact_events ORDER BY revision').fetchall(), [('prepared',1),('approved',2)])
        self.assertEqual(self.source.full.read_bytes(),original)

    def test_untrusted_unauthorized_and_missing_attestation(self):
        self.begin()
        with self.assertRaises(service.ArtifactError): service.prepare(self.db, self.fixture.actor, self.auth, self.source, self.storage, self.fixture.mid, self.fixture.source,b'test','txt',1)
        artifact=self.prepare(); self.db.commit()
        self.begin()
        with self.assertRaises(service.ArtifactError): self.change(artifact,'approved',1,principal=self.auth.editor,attested=True)
        with self.assertRaises(service.ArtifactError): self.change(artifact,'approved',1,attested=False)
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT status FROM reviewer_artifacts').fetchone()[0],'prepared')

    def test_same_actor_cannot_approve(self):
        self.begin(); artifact=service.prepare(self.db,self.auth.eic,self.auth,self.source,self.storage,self.fixture.mid,self.fixture.source,b'test','txt',1); self.db.commit()
        self.begin()
        with self.assertRaises(service.ArtifactError): self.change(artifact,'approved',1,attested=True)
        self.db.rollback()

    def test_reject_and_withdraw_with_no_deletion(self):
        self.begin(); first=self.prepare(); self.db.commit()
        self.begin(); self.change(first,'rejected',1); self.db.commit()
        self.begin(); second=self.prepare(revision=2); self.db.commit()
        self.begin(); self.change(second,'approved',1,attested=True); self.db.commit()
        self.begin(); self.change(second,'withdrawn',2); self.db.commit()
        self.assertEqual(self.db.execute('SELECT status FROM reviewer_artifacts ORDER BY artifact_revision').fetchall(), [('rejected',),('withdrawn',)])
        self.begin()
        with self.assertRaises(service.ArtifactError): self.change(second,'approved',3,attested=True)
        self.db.rollback()
        self.assertTrue((self.root/'artifact-private'/second.storage_id).is_file())

    def test_unapproved_binding_denied_by_schema(self):
        self.begin(); artifact=self.prepare(); self.db.commit()
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('INSERT INTO reviewer_artifact_assignments VALUES (?,?,?,?)',(self.fixture.assignment,artifact.artifact_id,self.fixture.actor,'2026-01-01T00:00:00.000000Z'))
        self.db.rollback()

    def test_bad_file_wrong_source_and_source_mismatch(self):
        self.begin()
        with self.assertRaises(StorageError): self.prepare(content=b'invalid',fmt='pdf')
        with self.assertRaises(service.ArtifactError): service.prepare(self.db,self.auth.editor,self.auth,self.source,self.storage,999999,self.fixture.source,b'test','txt',1)
        self.source.digest='0'*64
        with self.assertRaises(StorageError): self.prepare()
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0],0)

    def test_changed_source_round_and_corrupt_artifact_block_approval(self):
        self.begin(); artifact=self.prepare(); self.db.commit()
        source=self.source.full; source.write_bytes(b'%PDF-other')
        self.begin()
        with self.assertRaises(StorageError): self.change(artifact,'approved',1,attested=True)
        self.db.rollback(); source.write_bytes(b'%PDF-first')
        path=self.root/'artifact-private'/artifact.storage_id; path.chmod(0o600); path.write_bytes(b'X'*len(b'synthetic reviewer document'))
        self.begin()
        with self.assertRaises(StorageError): self.change(artifact,'approved',1,attested=True)
        self.db.rollback()
        self.db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=?',(self.fixture.mid,)); self.db.commit()
        self.begin()
        with self.assertRaises(service.ArtifactError): self.change(artifact,'approved',1,attested=True)
        self.db.rollback()

    def test_duplicate_revision_leaves_published_unrecorded_file(self):
        self.begin(); self.prepare(); self.db.commit(); self.begin()
        with self.assertRaises(service.PublishedArtifactUnrecorded) as error: self.prepare()
        self.db.rollback()
        self.assertTrue((self.root/'artifact-private'/error.exception.storage_id).is_file())
        self.assertEqual(self.db.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0],1)

    def test_rollback_preserves_published_object_and_unknown_commit(self):
        self.begin(); artifact=self.prepare(); self.db.rollback()
        self.assertTrue((self.root/'artifact-private'/artifact.storage_id).is_file())
        self.assertEqual(self.db.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0],0)
        self.begin(); artifact=self.prepare(); self.db.commit()  # Synthetic successful commit, acknowledgement lost.
        try: raise OSError('synthetic lost acknowledgement')
        except OSError: pass
        self.assertIsNotNone(self.db.execute('SELECT 1 FROM reviewer_artifacts WHERE artifact_id=?',(artifact.artifact_id,)).fetchone())
        self.assertTrue((self.root/'artifact-private'/artifact.storage_id).is_file())

    def test_publication_failure_and_unknown_do_not_create_rows(self):
        self.begin()
        with patch.object(self.storage,'publish',side_effect=StorageError('synthetic staging failure')):
            with self.assertRaises(StorageError): self.prepare()
        with patch.object(self.storage,'publish',side_effect=PublicationOutcomeUnknown('a'*32)):
            with self.assertRaises(PublicationOutcomeUnknown): self.prepare()
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0],0)

    def test_concurrent_transition_and_stale_revision(self):
        import sqlite3
        self.begin(); artifact=self.prepare(); self.db.commit()
        second=self.fixture.fx.connect(); self.begin()
        with self.assertRaises(sqlite3.OperationalError): second.execute('BEGIN IMMEDIATE')
        self.change(artifact,'approved',1,attested=True); self.db.commit()
        self.begin()
        with self.assertRaises(service.ArtifactError): self.change(artifact,'approved',1,attested=True)
        self.db.rollback()

    def test_schema_missing_or_transaction_missing_fail_closed(self):
        with self.assertRaises(service.ArtifactError): self.prepare()
        self.db.execute("DELETE FROM schema_migrations WHERE migration_id='012_reviewer_artifacts'"); self.db.commit(); self.begin()
        with self.assertRaises(service.ArtifactError): self.prepare()
        self.db.rollback()


if __name__ == '__main__': unittest.main()

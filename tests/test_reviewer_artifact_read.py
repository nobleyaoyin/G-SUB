"""Synthetic evidence-gated read tests; no real environment or live server."""
import unittest
from unittest.mock import patch

from app import reviewer_artifact_binding as binding, reviewer_artifact_evidence as evidence
from app import reviewer_artifact_read as reader, reviewer_artifact_service as service
from tests import test_reviewer_artifact_binding


class ReviewerAuthority:
    def __init__(self): self.reviewer=object(); self.other=object()
    def authorize(self,db,principal,action,manuscript_id,*,prepared_by=None):
        if action!='read_artifact' or principal not in (self.reviewer,self.other): raise service.ArtifactError('Unauthenticated synthetic principal')
        return 2 if principal is self.reviewer else 4


class ArtifactReadTests(unittest.TestCase):
    def setUp(self):
        self.fx=test_reviewer_artifact_binding.BindingTests('test_valid_binding_and_no_original_mutation')
        self.fx.setUp(); self.addCleanup(self.fx.doCleanups)
        self.db=self.fx.db; self.fx.begin(); self.fx.bind(); self.db.commit()
        self.auth=ReviewerAuthority()

    def read(self, principal=None, assignment=3, *, db=None):
        return reader.read_reviewer_artifact(self.db if db is None else db,self.auth.reviewer if principal is None else principal,self.auth,self.fx.proof,self.fx.source,self.fx.storage,assignment)

    def denied(self):
        self.db.execute('BEGIN')
        try:
            with self.assertRaises(reader.ArtifactReadUnavailable) as caught: self.read()
            self.assertEqual(str(caught.exception),'Artifact unavailable')
        finally: self.db.rollback()

    def test_valid_snapshot_and_neutral_metadata(self):
        self.db.execute('BEGIN'); value=self.read(); self.db.rollback()
        self.assertEqual(value.content,b'synthetic reviewer artifact')
        self.assertEqual(value.filename,'review-document.txt'); self.assertEqual(value.media_type,'text/plain')
        self.assertEqual(set(value.__dict__),{'content','filename','media_type'})
        self.assertNotIn(b'%PDF',value.content)

    def test_untrusted_reviewer_wrong_assignment_and_transaction(self):
        with self.assertRaises(reader.ArtifactReadUnavailable): self.read()
        self.db.execute('BEGIN')
        for principal,assignment in ((self.auth.other,3),(2,3),(self.auth.reviewer,999)):
            with self.subTest(assignment=assignment),self.assertRaises(reader.ArtifactReadUnavailable): self.read(principal,assignment)
        self.db.rollback()

    def test_pending_declined_and_invalidated(self):
        for status in ('pending','declined'):
            self.db.execute('UPDATE reviewer_invitations SET status=? WHERE assignment_id=3',(status,)); self.db.commit(); self.denied()
        self.db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=3")
        self.db.execute("INSERT INTO reviewer_invitation_invalidations VALUES ('synthetic-revoked',3,'cancelled',NULL,5,?,'editorial_cancellation')",(test_reviewer_artifact_binding.T,)); self.db.commit(); self.denied()

    def test_disabled_or_missing_reviewer_lifecycle(self):
        t=test_reviewer_artifact_binding.T
        self.db.execute("INSERT INTO account_lifecycle_events VALUES ('synthetic-disabled',2,2,'active','disabled',2,5,?,'administrative_disable')",(t,))
        self.db.execute("UPDATE account_lifecycle SET state='disabled',sequence=2,auth_generation=2,last_event_id='synthetic-disabled' WHERE user_id=2"); self.db.commit(); self.denied()

    def test_stale_round_wrong_manuscript_and_role(self):
        self.db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=2'); self.db.commit(); self.denied()
        self.db.execute('UPDATE manuscripts SET review_round=1 WHERE manuscript_id=2')
        self.db.execute('UPDATE review_assignments SET manuscript_id=1 WHERE assignment_id=3'); self.db.commit(); self.denied()
        self.db.execute('UPDATE review_assignments SET manuscript_id=2 WHERE assignment_id=3')
        self.db.execute("UPDATE users SET role='author' WHERE user_id=2"); self.db.commit(); self.denied()

    def test_missing_unlocked_single_and_legacy_policy(self):
        for fake in (None, {'mode':'single_blind','locked_at':test_reviewer_artifact_binding.T,'revision':2}, {'mode':'double_blind','locked_at':None,'revision':2}):
            with patch.object(binding.blind_policy_store,'read_policy',return_value=fake): self.denied()
        self.db.execute("DELETE FROM schema_migrations WHERE migration_id='013_artifact_evidence'"); self.db.commit(); self.denied()

    def test_missing_binding(self):
        self.db.execute('BEGIN')
        with self.assertRaises(reader.ArtifactReadUnavailable): self.read(assignment=1)
        self.db.rollback()

    def test_generic_approval_and_direct_sql_binding_are_not_enough(self):
        self.fx.begin()
        generic=service.prepare(self.db,self.fx.auth.editor,self.fx.auth,self.fx.source,self.fx.storage,2,1,b'generic','txt',2)
        service.transition(self.db,self.fx.auth.eic,self.fx.auth,self.fx.source,self.fx.storage,generic.artifact_id,'approved',1,human_review_attested=True)
        self.db.execute("INSERT INTO review_assignments(assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (4,2,2,5,1,'assigned',?)",(test_reviewer_artifact_binding.T,))
        self.db.execute("INSERT INTO reviewer_invitations VALUES (4,'accepted',?,?)",(test_reviewer_artifact_binding.T,test_reviewer_artifact_binding.T))
        self.db.execute('INSERT INTO review_assignment_files VALUES (4,1,?)',(test_reviewer_artifact_binding.T,))
        self.db.execute('INSERT INTO reviewer_artifact_assignments VALUES (?,?,?,?)',(4,generic.artifact_id,5,test_reviewer_artifact_binding.T)); self.db.commit()
        self.db.execute('BEGIN')
        with self.assertRaises(reader.ArtifactReadUnavailable): self.read(assignment=4)
        self.db.rollback()

    def test_stale_provenance_and_source_corruption(self):
        self.fx.proof.proof='b'*32; self.fx.begin()
        evidence.capture_source(self.db,self.fx.auth.eic,self.fx.auth,self.fx.proof,self.fx.source,2,1,1); self.db.commit(); self.denied()

    def test_source_digest_mismatch(self):
        self.fx.source.full.write_bytes(b'%PDF-other'); self.denied()

    def test_withdrawn_artifact(self):
        self.fx.begin(); service.transition(self.db,self.fx.auth.eic,self.fx.auth,self.fx.source,self.fx.storage,self.fx.art.artifact_id,'withdrawn',2); self.db.commit(); self.denied()

    def test_corrupted_replaced_and_missing_artifact_no_fallback(self):
        path=self.fx.fx.fx.path.parent.resolve()/'artifact-private'/self.fx.art.storage_id
        path.chmod(0o600); path.write_bytes(b'X'*len(b'synthetic reviewer artifact')); self.denied()
        path.unlink(); self.denied()
        self.assertEqual(self.fx.source.full.read_bytes(),b'%PDF-synthetic-source')

    def test_read_snapshot_and_later_revocation(self):
        self.db.execute('PRAGMA journal_mode=WAL')
        other=self.fx.fx.connect(); self.addCleanup(other.close)
        self.db.execute('BEGIN'); self.db.execute('SELECT status FROM reviewer_invitations WHERE assignment_id=3').fetchone()
        other.execute("UPDATE reviewer_invitations SET status='declined' WHERE assignment_id=3"); other.commit()
        self.assertEqual(self.read().content,b'synthetic reviewer artifact')
        self.db.rollback(); self.denied()


if __name__=='__main__': unittest.main()

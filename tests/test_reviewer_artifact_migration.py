"""Migration-only tests with disposable SQLite and synthetic data."""
from importlib import import_module
import sqlite3
import unittest

from tests import test_blind_policy_store

migration = import_module('migrations.012_reviewer_artifacts')
T = '2026-01-01T00:00:00.000000Z'
H1, H2 = 'a' * 64, 'b' * 64


class ArtifactMigrationTests(unittest.TestCase):
    def setUp(self):
        self.fx = test_blind_policy_store.BlindPolicyTests('test_select_change_stale_and_invalid')
        self.fx.setUp(); self.addCleanup(self.fx.doCleanups)
        import_module('migrations.011_blind_review_policy').migrate(self.fx.f.db_path)

        # Reset Migration 012 objects in this disposable test database.
        # Migration 012 tests must start after 011 but before 012.
        with sqlite3.connect(self.fx.f.db_path) as db:
            db.execute("PRAGMA foreign_keys=OFF")

            # Remove Migration 013 dependent tables first.
            db.execute("DROP TABLE IF EXISTS artifact_approval_evidence")
            db.execute("DROP TABLE IF EXISTS source_provenance_evidence")

            # Reset Migration 012 tables.
            db.execute("DROP TABLE IF EXISTS reviewer_artifact_assignments")
            db.execute("DROP TABLE IF EXISTS reviewer_artifact_events")
            db.execute("DROP TABLE IF EXISTS reviewer_artifacts")

            # Both migrations must be absent in this pre-012 fixture.
            db.execute(
                "DELETE FROM schema_migrations "
                "WHERE migration_id IN "
                "('012_reviewer_artifacts', '013_artifact_evidence')"
            )
            db.commit()

        result = self.fx.f.assign(self.fx.f.reviewer, 1)
        self.assertEqual(result.status_code, 201)
        self.assignment = result.json()['assignment_id']
        self.db = self.fx.connect(); self.actor = self.fx.actor; self.mid = self.fx.mid
        self.source = self.db.execute('SELECT round_file_id FROM review_assignment_files WHERE assignment_id=?', (self.assignment,)).fetchone()[0]

    def migrate(self): migration.migrate(self.fx.f.db_path)

    def prepare(self, aid='1'*32, eid='2'*32, *, mid=None, review_round=1, source=None, artifact_revision=1, fmt='pdf', size=10, source_hash=H1, artifact_hash=H2):
        self.db.execute('INSERT INTO reviewer_artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (aid, self.mid if mid is None else mid, review_round, self.source if source is None else source, source_hash, artifact_hash, fmt, size, aid, self.actor, T, 'prepared', None, None, artifact_revision, 1, eid))
        self.db.execute('INSERT INTO reviewer_artifact_events VALUES (?,?,?,?,?,?,?)', (eid, aid, 1, 'prepared', self.actor, T, 'prepared'))

    def event(self, aid, eid, revision, action):
        self.db.execute('INSERT INTO reviewer_artifact_events VALUES (?,?,?,?,?,?,?)', (eid, aid, revision, action, self.actor, T, action))

    def test_additive_idempotent_preserves_legacy_and_integrity(self):
        before = {t:self.db.execute(f'SELECT * FROM {t}').fetchall() for t in ('manuscripts','review_assignments','review_round_files','review_assignment_files','reviewer_invitations')}
        self.migrate(); self.migrate()
        self.assertEqual(before, {t:self.db.execute(f'SELECT * FROM {t}').fetchall() for t in before})
        for t in ('reviewer_artifacts','reviewer_artifact_events','reviewer_artifact_assignments'):
            self.assertEqual(self.db.execute(f'SELECT count(*) FROM {t}').fetchone()[0],0)
        self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(self.db.execute('SELECT count(*) FROM schema_migrations WHERE migration_id=?',(migration.MIGRATION_ID,)).fetchone()[0],1)

    def test_prepared_approved_binding_withdrawn_and_audit(self):
        self.migrate(); self.prepare(); self.db.commit()
        self.event('1'*32,'5'*32,2,'approved'); self.db.commit()
        self.assertEqual(self.db.execute('SELECT status,state_revision,approved_by FROM reviewer_artifacts').fetchone(),('approved',2,self.actor))
        self.db.execute('INSERT INTO reviewer_artifact_assignments VALUES (?,?,?,?)',(self.assignment,'1'*32,self.actor,T)); self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('INSERT INTO reviewer_artifact_assignments VALUES (?,?,?,?)',(self.assignment,'1'*32,self.actor,T))
        self.db.rollback()
        for sql in ('DELETE FROM reviewer_artifact_events','UPDATE reviewer_artifact_events SET action=action','DELETE FROM reviewer_artifact_assignments','UPDATE reviewer_artifact_assignments SET bound_at=bound_at'):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)
            self.db.rollback()
        self.event('1'*32,'6'*32,3,'withdrawn'); self.db.commit()
        self.assertEqual(self.db.execute('SELECT status,state_revision,approved_by FROM reviewer_artifacts').fetchone(),('withdrawn',3,self.actor))
        self.assertEqual(self.db.execute('SELECT count(*) FROM reviewer_artifact_assignments').fetchone()[0],1)

    def test_invalid_fields_and_missing_initial_event(self):
        self.migrate()
        for params in ({'fmt':'exe'}, {'size':0}, {'size':10485761}, {'source_hash':'g'*64}, {'artifact_hash':'bad'}, {'review_round':2}, {'mid':999999}, {'source':999999}):
            with self.subTest(params=params), self.assertRaises(sqlite3.IntegrityError):
                self.prepare(**params); self.db.commit()
            self.db.rollback()
        self.db.execute('INSERT INTO reviewer_artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', ('1'*32,self.mid,1,self.source,H1,H2,'pdf',10,'3'*32,self.actor,T,'prepared',None,None,1,1,'2'*32))
        with self.assertRaises(sqlite3.IntegrityError): self.db.commit()
        self.db.rollback()

    def test_invalid_transitions_and_stale_event_revisions(self):
        self.migrate(); self.prepare(); self.db.commit()
        for revision, action in ((1,'approved'),(3,'approved'),(2,'prepared')):
            with self.subTest(revision=revision,action=action), self.assertRaises(sqlite3.IntegrityError): self.event('1'*32,'5'*32,revision,action)
            self.db.rollback()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute("UPDATE reviewer_artifacts SET status='approved'")
        self.db.rollback(); self.event('1'*32,'5'*32,2,'rejected'); self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError): self.event('1'*32,'6'*32,3,'approved')
        self.db.rollback()

    def test_binding_requires_approval_and_exact_source_and_round(self):
        self.migrate(); self.prepare(); self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('INSERT INTO reviewer_artifact_assignments VALUES (?,?,?,?)',(self.assignment,'1'*32,self.actor,T))
        self.db.rollback(); self.event('1'*32,'5'*32,2,'approved'); self.db.commit()
        # Same manuscript, different round/source cannot bind to this assignment.
        self.db.execute("INSERT INTO review_round_files(manuscript_id,review_round,source_kind,confirmation_id,file_path,created_at) VALUES (?,2,'author_revision',NULL,'synthetic.txt','2026-01-01')",(self.mid,))
        source2 = self.db.execute('SELECT last_insert_rowid()').fetchone()[0]
        self.prepare('7'*32,'8'*32,review_round=2,source=source2); self.db.commit()
        self.event('7'*32,'9'*32,2,'approved'); self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('INSERT INTO reviewer_artifact_assignments VALUES (?,?,?,?)',(self.assignment,'7'*32,self.actor,T))
        self.db.rollback()
        # Different manuscript source also cannot bind.
        self.db.execute("INSERT INTO manuscripts(title,abstract,author_id,status,review_round,created_at) VALUES ('Other','Synthetic',?,'revised',2,'2026-01-01')",(self.fx.f.author.user_id,))
        other_mid = self.db.execute('SELECT last_insert_rowid()').fetchone()[0]
        self.db.execute("INSERT INTO review_round_files(manuscript_id,review_round,source_kind,confirmation_id,file_path,created_at) VALUES (?,2,'author_revision',NULL,'synthetic.txt','2026-01-01')",(other_mid,))
        other_source = self.db.execute('SELECT last_insert_rowid()').fetchone()[0]
        self.prepare('a'*32,'b'*32,mid=other_mid,review_round=2,source=other_source); self.db.commit()
        self.event('a'*32,'c'*32,2,'approved'); self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('INSERT INTO reviewer_artifact_assignments VALUES (?,?,?,?)',(self.assignment,'a'*32,self.actor,T))
        self.db.rollback()

    def test_transaction_rollback_and_unique_version(self):
        self.migrate(); self.prepare(); self.db.rollback()
        self.assertEqual(self.db.execute('SELECT count(*) FROM reviewer_artifact_events').fetchone()[0],0)
        self.prepare(); self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError): self.prepare('7'*32,'8'*32)
        self.db.rollback()

    def test_separate_connections_serialize_and_reject_stale_revision(self):
        self.migrate(); self.prepare(); self.db.commit()
        second = self.fx.connect()
        self.db.execute('BEGIN IMMEDIATE')
        with self.assertRaises(sqlite3.OperationalError): second.execute('BEGIN IMMEDIATE')
        self.event('1'*32,'5'*32,2,'approved'); self.db.commit()
        second.execute('BEGIN IMMEDIATE')
        with self.assertRaises(sqlite3.IntegrityError):
            second.execute('INSERT INTO reviewer_artifact_events VALUES (?,?,?,?,?,?,?)', ('6'*32,'1'*32,2,'rejected',self.actor,T,'rejected'))
        second.rollback()
        self.assertEqual(self.db.execute('SELECT status,state_revision FROM reviewer_artifacts').fetchone(), ('approved',2))

    def test_foreign_key_actor_and_immutable_artifact(self):
        self.migrate(); self.prepare(); self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO reviewer_artifact_events VALUES (?,?,?,?,?,?,?)', ('5'*32,'1'*32,2,'approved',999999,T,'approved'))
        self.db.rollback()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute("UPDATE reviewer_artifacts SET artifact_sha256=?", ('c'*64,))
        self.db.rollback()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM reviewer_artifacts')
        self.db.rollback()

    def test_missing_011_conflicts_and_partial_schema(self):
        self.db.execute("DELETE FROM schema_migrations WHERE migration_id='011_blind_review_policy'"); self.db.commit()
        with self.assertRaises(RuntimeError): self.migrate()
        self.db.execute("INSERT INTO schema_migrations VALUES ('011_blind_review_policy',datetime('now'))")
        self.db.execute('CREATE TABLE reviewer_artifacts (wrong TEXT)'); self.db.commit()
        with self.assertRaises(RuntimeError): self.migrate()
        self.assertIsNone(self.db.execute("SELECT 1 FROM schema_migrations WHERE migration_id=?",(migration.MIGRATION_ID,)).fetchone())

    def test_ledger_failure_and_schema_drift(self):
        self.db.execute("CREATE TRIGGER fail_artifact BEFORE INSERT ON schema_migrations WHEN NEW.migration_id='012_reviewer_artifacts' BEGIN SELECT RAISE(ABORT,'synthetic'); END"); self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError): self.migrate()
        self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='reviewer_artifacts'").fetchone())
        self.db.execute('DROP TRIGGER fail_artifact'); self.db.commit(); self.migrate()
        self.db.execute('DROP TRIGGER artifact_no_delete'); self.db.commit()
        with self.assertRaises(RuntimeError): self.migrate()

    def test_with_010_and_full_migration_chain(self):
        from tests.test_lifecycle_migration_009 import LifecycleMigrationTest
        later = LifecycleMigrationTest('test_additive_idempotent_and_preserves_every_old_table'); later.setUp()
        try:
            later.migrate()
            import_module('migrations.010_reviewer_profiles').migrate(later.fx.path)
            import_module('migrations.011_blind_review_policy').migrate(later.fx.path)
            migration.migrate(later.fx.path); migration.migrate(later.fx.path)
            with later.connect() as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(db.execute('SELECT count(*) FROM reviewer_artifacts').fetchone()[0], 0)
        finally: later.doCleanups()


if __name__ == '__main__': unittest.main()

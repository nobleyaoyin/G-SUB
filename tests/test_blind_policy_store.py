"""Disconnected policy store tests; all SQLite files and users are disposable."""
from importlib import import_module
import sqlite3
import unittest
from unittest.mock import patch

from app import models
from app import blind_policy_store as store
from tests.test_reviewer_download import ReviewerDownloadsTest

migration = import_module('migrations.011_blind_review_policy')


class BlindPolicyTests(unittest.TestCase):
    def setUp(self):
        self.f = ReviewerDownloadsTest('test_first_round_binding_and_access')
        self.f.setUp(); self.addCleanup(self.f.tearDown)

        # Reset migration 011 state so migration tests start from
        # a genuine pre-011 disposable database.
        with sqlite3.connect(self.f.db_path) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("DROP TABLE IF EXISTS blind_policies")
            db.execute("DROP TABLE IF EXISTS blind_policy_events")
            db.execute(
                "DELETE FROM schema_migrations "
                "WHERE migration_id='011_blind_review_policy'"
            )
            db.commit()

        self.eic = models.User(name='Synthetic EIC', email='eic@example.test', password_hash='x', role='eic')
        self.f.db.add(self.eic); self.f.db.commit()
        self.actor = self.eic.user_id; self.mid = self.f.mid

    def connect(self):
        db = sqlite3.connect(self.f.db_path, timeout=0)
        db.execute('PRAGMA foreign_keys=ON')
        self.addCleanup(db.close)
        return db

    def migrated(self):
        migration.migrate(self.f.db_path)
        return self.connect()

    def write(self, db, fn, *args):
        store.begin_write(db)
        try:
            result = fn(db, *args); db.commit(); return result
        except Exception:
            db.rollback(); raise

    def invitation(self, db):
        db.execute("INSERT INTO review_assignments(manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (?,?,?,?,?,?)", (self.mid, self.f.reviewer.user_id, self.actor, 1, 'assigned', '2026-01-01'))
        aid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute("INSERT INTO reviewer_invitations(assignment_id,status,invited_at) VALUES (?,'pending','2026-01-01')", (aid,))
        db.commit(); return aid

    def test_additive_idempotent_legacy_and_integrity(self):
        db = self.connect(); before = db.execute('SELECT * FROM manuscripts').fetchall()
        migration.migrate(self.f.db_path); migration.migrate(self.f.db_path)
        self.assertEqual(before, db.execute('SELECT * FROM manuscripts').fetchall())
        self.assertIsNone(store.read_policy(db, self.mid))
        self.assertEqual(db.execute('SELECT count(*) FROM blind_policy_events').fetchone()[0], 0)
        self.assertEqual(db.execute('SELECT count(*) FROM schema_migrations WHERE migration_id=?', (migration.MIGRATION_ID,)).fetchone()[0], 1)
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_missing_and_incompatible_schema(self):
        db = self.connect()
        with self.assertRaises(store.SchemaUnavailable): store.read_policy(db, self.mid)
        migration.migrate(self.f.db_path)
        db.execute('DROP TRIGGER blind_events_no_delete'); db.commit()
        with self.assertRaises(store.SchemaUnavailable): store.read_policy(db, self.mid)

    def test_select_change_stale_and_invalid(self):
        db = self.migrated()
        for mode in ('invalid', '', None):
            with self.assertRaises(store.PolicyError): self.write(db, store.select_mode, self.mid, mode, self.actor)
        current = self.write(db, store.select_mode, self.mid, 'single_blind', self.actor)
        self.assertEqual((current['mode'], current['revision']), ('single_blind', 1))
        with self.assertRaises(store.PolicyError): self.write(db, store.select_mode, self.mid, 'double_blind', self.actor)
        current = self.write(db, store.change_mode, self.mid, 'double_blind', self.actor, 1)
        self.assertEqual((current['mode'], current['revision']), ('double_blind', 2))
        with self.assertRaises(store.PolicyError): self.write(db, store.change_mode, self.mid, 'single_blind', self.actor, 1)
        self.assertEqual(db.execute('SELECT revision,action FROM blind_policy_events ORDER BY revision').fetchall(), [(1,'selected'),(2,'changed')])

    def test_lock_and_audit_are_immutable(self):
        db = self.migrated(); self.write(db, store.select_mode, self.mid, 'single_blind', self.actor)
        aid = self.invitation(db)
        current = self.write(db, store.lock_mode, self.mid, aid, self.actor, 1)
        self.assertEqual((current['revision'], current['lock_invitation_id']), (2, aid))
        with self.assertRaises(store.PolicyError): self.write(db, store.change_mode, self.mid, 'double_blind', self.actor, 2)
        with self.assertRaises(sqlite3.IntegrityError): db.execute('DELETE FROM blind_policy_events')
        db.rollback()
        with self.assertRaises(sqlite3.IntegrityError): db.execute("UPDATE blind_policy_events SET mode='double_blind'")
        db.rollback()

    def test_invitation_must_match_manuscript(self):
        db = self.migrated(); self.write(db, store.select_mode, self.mid, 'single_blind', self.actor)
        with self.assertRaises(store.PolicyError): self.write(db, store.lock_mode, self.mid, 999999, self.actor, 1)
        db.execute("INSERT INTO manuscripts(title,abstract,author_id,status,review_round,created_at) VALUES ('Other','Abstract',?,'ready_for_peer_review',1,'2026-01-01')", (self.f.author.user_id,))
        other_mid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute("INSERT INTO review_assignments(manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (?,?,?,?,?,?)", (other_mid, self.f.reviewer.user_id, self.actor, 1, 'assigned', '2026-01-01'))
        other_aid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute("INSERT INTO reviewer_invitations(assignment_id,status,invited_at) VALUES (?,'pending','2026-01-01')", (other_aid,)); db.commit()
        with self.assertRaises(store.PolicyError): self.write(db, store.lock_mode, self.mid, other_aid, self.actor, 1)
        with self.assertRaises(sqlite3.IntegrityError): db.execute("INSERT INTO blind_policy_events VALUES ('synthetic',?,2,'single_blind','locked',?,'2026-01-01T00:00:00.000000Z',?)", (self.mid, self.actor, other_aid))
        db.rollback()
        self.assertEqual(store.read_policy(db, self.mid)['revision'], 1)

    def test_compatibility_with_migration_010(self):
        import_module('migrations.010_reviewer_profiles').migrate(self.f.db_path)
        db = self.migrated()
        self.assertIsNone(store.read_policy(db, self.mid))
        self.assertEqual(db.execute('SELECT count(*) FROM reviewer_profiles').fetchone()[0], 0)

    def test_compatibility_after_migrations_007_through_010(self):
        from tests.test_lifecycle_migration_009 import LifecycleMigrationTest
        later = LifecycleMigrationTest('test_additive_idempotent_and_preserves_every_old_table')
        later.setUp()
        try:
            later.migrate()
            import_module('migrations.010_reviewer_profiles').migrate(later.fx.path)
            migration.migrate(later.fx.path); migration.migrate(later.fx.path)
            with later.connect() as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(db.execute('SELECT count(*) FROM blind_policies').fetchone()[0], 0)
        finally:
            later.doCleanups()

    def test_inconsistent_orphan_event_is_rejected(self):
        db = self.migrated()
        db.execute("INSERT INTO blind_policy_events VALUES ('orphan',?,1,'single_blind','selected',?,'2026-01-01T00:00:00.000000Z',NULL)", (self.mid, self.actor)); db.commit()
        with self.assertRaises(store.PolicyError): store.read_policy(db, self.mid)

    def test_injected_failure_and_caller_rollback(self):
        db = self.migrated(); original = store._event
        def fail(*args, **kwargs):
            original(*args, **kwargs); raise RuntimeError('synthetic')
        store.begin_write(db)
        with patch.object(store, '_event', side_effect=fail):
            with self.assertRaises(RuntimeError): store.select_mode(db, self.mid, 'single_blind', self.actor)
        self.assertEqual(db.execute('SELECT count(*) FROM blind_policy_events').fetchone()[0], 0)
        store.select_mode(db, self.mid, 'single_blind', self.actor)
        db.rollback()
        self.assertIsNone(store.read_policy(db, self.mid))

    def test_eic_role_and_legacy_assignments(self):
        db = self.migrated()
        with self.assertRaises(store.PolicyError): self.write(db, store.select_mode, self.mid, 'single_blind', self.f.author.user_id)
        self.invitation(db)
        with self.assertRaises(store.PolicyError): self.write(db, store.select_mode, self.mid, 'single_blind', self.actor)
        self.assertIsNone(store.read_policy(db, self.mid))

    def test_separate_connections_busy_and_stale(self):
        db = self.migrated(); other = self.connect()
        self.write(db, store.select_mode, self.mid, 'single_blind', self.actor)
        store.begin_write(db)
        with self.assertRaises(sqlite3.OperationalError): store.begin_write(other)
        store.change_mode(db, self.mid, 'double_blind', self.actor, 1); db.commit()
        with self.assertRaises(store.PolicyError): self.write(other, store.change_mode, self.mid, 'single_blind', self.actor, 1)

    def test_conflict_missing_prerequisite_and_atomic_rollback(self):
        db = self.connect(); db.execute('CREATE TABLE blind_policies (wrong TEXT)'); db.commit()
        with self.assertRaises(RuntimeError): migration.migrate(self.f.db_path)
        db.execute('DROP TABLE blind_policies'); db.execute("DELETE FROM schema_migrations WHERE migration_id='006_formatter_publication'"); db.commit()
        with self.assertRaises(RuntimeError): migration.migrate(self.f.db_path)
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='blind_policy_events'").fetchone())

    def test_migration_ledger_failure_rolls_back(self):
        db = self.connect()
        db.execute("CREATE TRIGGER test_fail_blind BEFORE INSERT ON schema_migrations WHEN NEW.migration_id='011_blind_review_policy' BEGIN SELECT RAISE(ABORT, 'synthetic'); END"); db.commit()
        with self.assertRaises(sqlite3.IntegrityError): migration.migrate(self.f.db_path)
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='blind_policy_events'").fetchone())


if __name__ == '__main__': unittest.main()

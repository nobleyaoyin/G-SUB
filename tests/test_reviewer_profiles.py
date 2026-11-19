"""Optional profile migration and self-service in disposable SQLite only."""
from importlib import import_module
import sqlite3
import unittest

from app import models
from tests import test_reviewer_download

migration = import_module('migrations.010_reviewer_profiles')


class ReviewerProfileTests(unittest.TestCase):
    def setUp(self):
        self.f = test_reviewer_download.ReviewerDownloadsTest('test_first_round_binding_and_access')
        self.f.setUp(); self.addCleanup(self.f.tearDown)

        # Start Migration 010 tests from a genuine pre-010 schema.
        # This database is disposable and belongs only to this test fixture.
        with sqlite3.connect(self.f.db_path) as db:
            db.execute("DROP TABLE IF EXISTS reviewer_profiles")
            db.execute(
                "DELETE FROM schema_migrations "
                "WHERE migration_id='010_reviewer_profiles'"
            )
            db.commit()

        self.chief = models.User(name='Chief', email='chief@example.test', password_hash='x', role='eic')
        self.f.db.add(self.chief); self.f.db.commit()

    def migrate(self): migration.migrate(self.f.db_path)

    def test_migration_is_additive_empty_idempotent_and_integral(self):
        with sqlite3.connect(self.f.db_path) as db:
            before = {table: db.execute(f'SELECT * FROM {table}').fetchall() for table in ('users', 'manuscripts', 'review_assignments', 'notifications')}
        self.migrate(); self.migrate()
        with sqlite3.connect(self.f.db_path) as db:
            self.assertEqual(before, {table: db.execute(f'SELECT * FROM {table}').fetchall() for table in before})
            self.assertEqual(db.execute('SELECT count(*) FROM reviewer_profiles').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM schema_migrations WHERE migration_id=?', (migration.MIGRATION_ID,)).fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_no_migration_keeps_directory_available_and_self_edit_unavailable(self):
        f=self.f; f.current=self.chief
        result=f.client.get(f'/assignments/manuscript/{f.mid}/reviewer-directory', params={'q':'reviewer'})
        self.assertEqual(result.status_code, 200); self.assertIsNone(result.json()[0]['profile'])
        f.current=f.reviewer
        self.assertEqual(f.client.get('/users/me/reviewer-profile').status_code, 503)
        self.assertEqual(f.client.put('/users/me/reviewer-profile', json={'professional_title':'Synthetic'}).status_code, 503)
        with sqlite3.connect(f.db_path) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='reviewer_profiles'").fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (migration.MIGRATION_ID,)).fetchone())

    def test_self_report_visibility_and_role_permissions(self):
        self.migrate(); f=self.f; f.current=f.reviewer
        payload={'professional_title':'Professor', 'institution':'Synthetic University', 'department':'Computing', 'research_areas':['Systems'], 'expertise':['Security']}
        response=f.client.put('/users/me/reviewer-profile', json=payload)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(response.json()['profile']['provenance'],'self_reported')
        self.assertEqual(f.client.get('/users/me/reviewer-profile').json()['profile']['expertise'],['Security'])
        for actor in (self.chief, f.editor):
            f.current=actor
            result=f.client.get(f'/assignments/manuscript/{f.mid}/reviewer-directory',params={'q':'reviewer'})
            self.assertEqual(result.status_code,200,result.text)
            profile=next(x['profile'] for x in result.json() if x['reviewer_id']==f.reviewer.user_id)
            self.assertEqual(profile['institution'],'Synthetic University')
            self.assertEqual(profile['research_areas'],['Systems'])
            self.assertEqual(f.client.put('/users/me/reviewer-profile',json=payload).status_code,403)
        f.current=f.author
        self.assertEqual(f.client.get('/users/me/reviewer-profile').status_code,403)
        self.assertEqual(f.client.get(f'/assignments/manuscript/{f.mid}/reviewer-directory',params={'q':'reviewer'}).status_code,403)
        f.current=f.other
        self.assertIsNone(f.client.get('/users/me/reviewer-profile').json()['profile'])
        self.assertEqual(f.client.get(f'/assignments/manuscript/{f.mid}/reviewer-directory',params={'q':'reviewer'}).status_code,403)
        unrelated=models.User(name='Unassigned',email='unassigned@example.test',password_hash='x',role='editor')
        f.db.add(unrelated);f.db.commit();f.current=unrelated
        self.assertEqual(f.client.get(f'/assignments/manuscript/{f.mid}/reviewer-directory',params={'q':'reviewer'}).status_code,403)

    def test_profile_validation_and_no_actor_id_override(self):
        self.migrate();f=self.f;f.current=f.reviewer
        for invalid in ({'user_id':f.other.user_id}, {'professional_title':'X'*101}, {'institution':'bad\ntext'}, {'expertise':['x']*13}, {'research_areas':['x'*81]}):
            with self.subTest(kind=list(invalid)):
                self.assertEqual(f.client.put('/users/me/reviewer-profile',json=invalid).status_code,422)
        self.assertIsNone(f.client.get('/users/me/reviewer-profile').json()['profile'])
        self.assertEqual(f.client.put('/users/me/reviewer-profile',json={'professional_title':'  Research Scientist  '}).json()['profile']['professional_title'],'Research Scientist')

    def test_conflict_and_missing_prerequisites_do_not_write_ledger(self):
        with sqlite3.connect(self.f.db_path) as db:
            db.execute('CREATE TABLE reviewer_profiles (wrong TEXT)'); db.commit()
        with self.assertRaises(RuntimeError): self.migrate()
        with sqlite3.connect(self.f.db_path) as db:
            self.assertIsNone(db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(migration.MIGRATION_ID,)).fetchone())
            db.execute('DROP TABLE reviewer_profiles'); db.execute("DELETE FROM schema_migrations WHERE migration_id='006_formatter_publication'"); db.commit()
        with self.assertRaises(RuntimeError): self.migrate()
        with sqlite3.connect(self.f.db_path) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='reviewer_profiles'").fetchone())

    def test_migration_rolls_back_when_ledger_write_fails(self):
        with sqlite3.connect(self.f.db_path) as db:
            db.execute("CREATE TRIGGER fail_profile_ledger BEFORE INSERT ON schema_migrations WHEN NEW.migration_id='010_reviewer_profiles' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError): self.migrate()
        with sqlite3.connect(self.f.db_path) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='reviewer_profiles'").fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (migration.MIGRATION_ID,)).fetchone())

    def test_database_checks_and_foreign_key(self):
        self.migrate()
        with sqlite3.connect(self.f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            query = 'INSERT INTO reviewer_profiles (user_id,research_areas,expertise,updated_at,provenance) VALUES (?,?,?,?,?)'
            stamp = '2026-01-01T00:00:00.000000Z'
            with self.assertRaises(sqlite3.IntegrityError): db.execute(query, (999999,'[]','[]',stamp,'self_reported'))
            with self.assertRaises(sqlite3.IntegrityError): db.execute(query, (self.f.reviewer.user_id,'{}','[]',stamp,'self_reported'))
            with self.assertRaises(sqlite3.IntegrityError): db.execute(query, (self.f.reviewer.user_id,'[]','[]',stamp,'verified'))

    def test_migration_rejects_prerequisite_schema_drift(self):
        with sqlite3.connect(self.f.db_path) as db:
            db.execute('DROP INDEX uq_formatter_active');db.commit()
        with self.assertRaises(RuntimeError): self.migrate()
        with sqlite3.connect(self.f.db_path) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='reviewer_profiles'").fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(migration.MIGRATION_ID,)).fetchone())

    def test_unexpected_profile_trigger_fails_closed(self):
        self.migrate()
        with sqlite3.connect(self.f.db_path) as db:
            db.execute('CREATE TRIGGER unexpected_profile_trigger AFTER INSERT ON reviewer_profiles BEGIN SELECT 1; END');db.commit()
        self.f.current=self.f.reviewer
        self.assertEqual(self.f.client.put('/users/me/reviewer-profile',json={'professional_title':'Synthetic'}).status_code,503)
        self.f.current=self.chief
        self.assertEqual(self.f.client.get(f'/assignments/manuscript/{self.f.mid}/reviewer-directory',params={'q':'reviewer'}).status_code,503)

    def test_independent_upgrade_after_migrations_007_through_009(self):
        from tests.test_lifecycle_migration_009 import LifecycleMigrationTest
        later = LifecycleMigrationTest('test_additive_idempotent_and_preserves_every_old_table')
        later.setUp()
        try:
            later.migrate()
            migration.migrate(later.fx.path)
            migration.migrate(later.fx.path)
            with later.connect() as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(db.execute('SELECT count(*) FROM reviewer_profiles').fetchone()[0], 0)
        finally:
            later.doCleanups()


if __name__ == '__main__': unittest.main()

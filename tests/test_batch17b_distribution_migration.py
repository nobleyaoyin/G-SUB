"""Exercise actual migration only against synthetic SQLite files."""
import importlib.util
import sqlite3
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('batch17b_migration',Path(__file__).resolve().parents[1]/'migrations/021_document_distribution.py')
migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)

@pytest.fixture
def database(tmp_path):
    path=tmp_path/'synthetic.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript('''PRAGMA foreign_keys=ON;
        CREATE TABLE schema_migrations(migration_id TEXT PRIMARY KEY,applied_at TEXT NOT NULL);
        INSERT INTO schema_migrations VALUES('019_personal_notes','synthetic');
        CREATE TABLE users(user_id INTEGER PRIMARY KEY,role TEXT NOT NULL);
        CREATE TABLE manuscripts(manuscript_id INTEGER PRIMARY KEY,status TEXT NOT NULL);
        CREATE TABLE initial_editor_invitations(invitation_id INTEGER PRIMARY KEY,manuscript_id INTEGER,editor_id INTEGER,status TEXT);
        CREATE TABLE final_editor_invitations(invitation_id INTEGER PRIMARY KEY,manuscript_id INTEGER,editor_id INTEGER,status TEXT);
        CREATE TABLE review_assignments(assignment_id INTEGER PRIMARY KEY);
        INSERT INTO users VALUES(1,'eic'); INSERT INTO users VALUES(2,'editor');
        INSERT INTO manuscripts VALUES(1,'submitted'); INSERT INTO manuscripts VALUES(2,'submitted');
        INSERT INTO initial_editor_invitations VALUES(1,1,2,'accepted');
        ''')
    return path

def test_upgrade_idempotence_empty_downgrade_and_reupgrade(database):
    migration.migrate(database);migration.migrate(database)
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==2
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    migration.downgrade_empty(database);migration.migrate(database)
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT COUNT(*) FROM schema_migrations WHERE migration_id=?',(migration.MIGRATION_ID,)).fetchone()[0]==1

def test_immutable_rows_foreign_keys_and_idempotency(database):
    migration.migrate(database)
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('INSERT INTO distribution_reservations VALUES('+','.join('?'*12)+')',('b'*32,1,1,'editor_source',None,None,'c'*64,4,'txt','reserve-key-0001','f'*64,'2026-01-01T00:00:00.000000Z'))
        db.execute("INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",('a'*32,1,'editor_source',1,'b'*32,'c'*64,4,'txt',None,None,1,'2026-01-01T00:00:00.000000Z'))
        values=('d'*32,1,'a'*32,2,'editor',1,None,None,None,1,'manual','created','not_requested','idempotency-key-0001','e'*64,'2026-01-01T00:00:00.000000Z')
        db.execute('INSERT INTO distribution_grants VALUES('+','.join('?'*16)+')',values)
        with pytest.raises(sqlite3.IntegrityError): db.execute("UPDATE distribution_grants SET recipient_id=1")
        with pytest.raises(sqlite3.IntegrityError): db.execute("DELETE FROM distribution_artifacts")
        with pytest.raises(sqlite3.IntegrityError): db.execute('INSERT INTO distribution_grants VALUES('+','.join('?'*16)+')',('f'*32,*values[1:]))
        with pytest.raises(sqlite3.IntegrityError): db.execute('INSERT INTO distribution_grants VALUES('+','.join('?'*16)+')',('f'*32,2,*values[2:13],'different-key-00001',*values[14:]))
        db.commit()
    with pytest.raises(RuntimeError,match='retained'): migration.downgrade_empty(database)

def test_conflict_fails_without_partial_migration(database):
    with sqlite3.connect(database) as db: db.execute('CREATE TABLE distribution_artifacts(x)')
    with pytest.raises(RuntimeError,match='partial'): migration.migrate(database)
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(migration.MIGRATION_ID,)).fetchone() is None

def test_existing_001_to_019_fixture_and_validators_are_preserved():
    from tests.test_reviewer_download import ReviewerDownloadsTest
    fixture=ReviewerDownloadsTest()
    fixture.setUp()
    try:
        path=fixture.db_path
        with sqlite3.connect(path) as db:
            before=db.execute('SELECT manuscript_id,title,status FROM manuscripts ORDER BY manuscript_id').fetchall()
            assert db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='019_personal_notes'").fetchone()
        migration.migrate(path)
        with sqlite3.connect(path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            assert db.execute('SELECT manuscript_id,title,status FROM manuscripts ORDER BY manuscript_id').fetchall()==before
            assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
            for filename in ('011_blind_review_policy','012_reviewer_artifacts','013_artifact_evidence'):
                spec=importlib.util.spec_from_file_location('validator_'+filename,Path(__file__).resolve().parents[1]/'migrations'/f'{filename}.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                module.validate_schema(db)
        migration.downgrade_empty(path);migration.migrate(path)
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT manuscript_id,title,status FROM manuscripts ORDER BY manuscript_id').fetchall()==before
    finally:
        fixture.tearDown()

def test_direct_insert_requires_current_accepted_editor_and_eic(database):
    migration.migrate(database)
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('INSERT INTO distribution_reservations VALUES('+','.join('?'*12)+')',('b'*32,1,1,'editor_source',None,None,'c'*64,4,'txt','reserve-key-0001','f'*64,'2026-01-01T00:00:00.000000Z'))
        with pytest.raises(sqlite3.IntegrityError,match='Reservation mismatch'):
            db.execute('INSERT INTO distribution_artifacts VALUES('+','.join('?'*12)+')',('f'*32,1,'editor_source',1,'b'*32,'d'*64,4,'txt',None,None,1,'2026-01-01T00:00:00.000000Z'))
        db.execute('INSERT INTO distribution_artifacts VALUES('+','.join('?'*12)+')',('a'*32,1,'editor_source',1,'b'*32,'c'*64,4,'txt',None,None,1,'2026-01-01T00:00:00.000000Z'))
        base=['d'*32,1,'a'*32,2,'editor',1,None,None,None,1,'manual','created','not_requested','idempotency-key-0001','e'*64,'2026-01-01T00:00:00.000000Z']
        db.execute('INSERT INTO distribution_grants VALUES('+','.join('?'*16)+')',base)
        duplicate=base.copy();duplicate[0]='f'*32;duplicate[13]='different-idem-key-01'
        with pytest.raises(sqlite3.IntegrityError): db.execute('INSERT INTO distribution_grants VALUES('+','.join('?'*16)+')',duplicate)
        bad=base.copy();bad[0]='f'*32;bad[13]='other-idempotency-01';bad[9]=2
        with pytest.raises(sqlite3.IntegrityError,match='EIC required'): db.execute('INSERT INTO distribution_grants VALUES('+','.join('?'*16)+')',bad)
        bad=base.copy();bad[0]='f'*32;bad[13]='other-idempotency-02';bad[3]=1
        with pytest.raises(sqlite3.IntegrityError,match='Recipient role mismatch'): db.execute('INSERT INTO distribution_grants VALUES('+','.join('?'*16)+')',bad)
        db.execute("UPDATE initial_editor_invitations SET status='declined' WHERE invitation_id=1")
        bad=base.copy();bad[0]='f'*32;bad[13]='other-idempotency-03'
        with pytest.raises(sqlite3.IntegrityError,match='Initial invitation unavailable'): db.execute('INSERT INTO distribution_grants VALUES('+','.join('?'*16)+')',bad)

"""Test-only sidecar DDL rehearsal: never invoke on an existing database."""
import hashlib
import sqlite3
import pytest

PARENTS=('initial_editing_submissions','final_editing_submissions','formatting_submissions')
SIDECARS=('initial_editing_filename_metadata','final_editing_filename_metadata','formatting_filename_metadata')

def rehearsal(db, fail_after=None):
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('BEGIN IMMEDIATE')
    try:
        for i,(parent,sidecar) in enumerate(zip(PARENTS,SIDECARS)):
            db.execute(f'CREATE TABLE IF NOT EXISTS {sidecar} (submission_id INTEGER PRIMARY KEY REFERENCES {parent}(submission_id) ON DELETE RESTRICT, original_filename TEXT)')
            info=db.execute(f'PRAGMA table_info({sidecar})').fetchall()
            keys=db.execute(f'PRAGMA foreign_key_list({sidecar})').fetchall()
            if {r[1] for r in info}!={'submission_id','original_filename'} or not any(r[1]=='submission_id' and r[5]==1 for r in info) or not any(r[2:5]==(parent,'submission_id','submission_id') for r in keys):
                raise RuntimeError('Conflicting schema')
            if fail_after==i: raise RuntimeError('Synthetic injected failure')
        if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key failure')
        db.execute("INSERT OR IGNORE INTO schema_migrations VALUES ('test-only-sidecars')")
        db.commit()
    except Exception:
        db.rollback(); raise

@pytest.fixture
def synthetic(tmp_path):
    path=tmp_path/'fixture.sqlite'; doc=tmp_path/'synthetic.txt'; doc.write_bytes(b'protected synthetic version')
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE schema_migrations (migration_id TEXT PRIMARY KEY)')
    for parent in PARENTS:
        db.execute(f'CREATE TABLE {parent} (submission_id INTEGER PRIMARY KEY, file_path TEXT)')
        db.execute(f'INSERT INTO {parent} VALUES (1, ?)',(str(doc),))
    db.commit()
    yield db,doc
    db.close()

def test_forward_repeat_nullable_foreign_keys_and_file_integrity(synthetic):
    db,doc=synthetic; before=hashlib.sha256(doc.read_bytes()).digest()
    rehearsal(db); rehearsal(db)
    for parent,sidecar in zip(PARENTS,SIDECARS):
        assert db.execute(f'SELECT file_path FROM {parent}').fetchone()==(str(doc),)
        assert db.execute(f'SELECT COUNT(*) FROM {sidecar}').fetchone()==(0,)
        db.execute(f'INSERT INTO {sidecar} VALUES (1,NULL)')
        with pytest.raises(sqlite3.IntegrityError): db.execute(f'INSERT INTO {sidecar} VALUES (1,?)',('duplicate.txt',))
        with pytest.raises(sqlite3.IntegrityError): db.execute(f'INSERT INTO {sidecar} VALUES (99,?)',('orphan.txt',))
    db.commit()
    assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert hashlib.sha256(doc.read_bytes()).digest()==before

def test_failure_rolls_back_all_tables_and_marker(synthetic):
    db,doc=synthetic
    with pytest.raises(RuntimeError,match='injected'): rehearsal(db,fail_after=1)
    assert db.execute("SELECT name FROM sqlite_master WHERE name LIKE '%_filename_metadata'").fetchall()==[]
    assert db.execute('SELECT * FROM schema_migrations').fetchall()==[]
    assert doc.read_bytes()==b'protected synthetic version'

def test_conflict_rejects_without_partial_upgrade(synthetic):
    db,_=synthetic
    db.execute('CREATE TABLE final_editing_filename_metadata (unexpected TEXT)');db.commit()
    with pytest.raises(RuntimeError,match='Conflicting'): rehearsal(db)
    assert db.execute("SELECT name FROM sqlite_master WHERE name='initial_editing_filename_metadata'").fetchall()==[]
    assert db.execute('SELECT * FROM schema_migrations').fetchall()==[]

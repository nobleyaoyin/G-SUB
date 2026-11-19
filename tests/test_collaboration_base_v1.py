"""Candidate schema validation, disposable isolated SQLite only."""
import importlib.util
from pathlib import Path
import sqlite3
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / '.test-data'
SQL = ROOT / 'database/bootstrap/collaboration_base_v1.sql'
MIGRATIONS = sorted((ROOT / 'migrations').glob('0*.py'))

def safe_db(tmp_path):
    root = DATA.resolve(strict=True)
    assert root.is_relative_to(ROOT.resolve()) and not DATA.is_symlink()
    assert tmp_path.resolve(strict=True).is_relative_to(root) and not tmp_path.is_symlink()
    path = tmp_path / 'schema.sqlite'
    assert not path.exists() and not path.is_symlink()
    path.touch(exist_ok=False)
    return path

def load(path):
    spec = importlib.util.spec_from_file_location('collab_' + path.stem, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

def test_baseline_migration_chain_and_empty_downgrade(tmp_path):
    path = safe_db(tmp_path)
    with sqlite3.connect(path) as db:
        db.executescript(SQL.read_text())
        assert db.execute('SELECT version FROM collaboration_schema_version').fetchone() == (1,)
        with pytest.raises(sqlite3.DatabaseError): db.executescript(SQL.read_text())
        db.rollback()
    mods = [load(p) for p in MIGRATIONS]
    for mod in mods: mod.migrate(path)
    for mod in mods: mod.migrate(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM schema_migrations').fetchone() == (20,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        objects = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
        assert {'ix_users_email', 'distribution_artifacts_no_update', 'distribution_grants_validate_editor'} <= objects
    mods[-1].downgrade_empty(path)
    mods[-1].migrate(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM schema_migrations WHERE migration_id='021_document_distribution'").fetchone() == (1,)
        db.execute('PRAGMA foreign_keys=ON')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,created_at) VALUES (1,'Synthetic','Synthetic',999,'draft',1,'2020-01-01')")
        db.rollback()

def test_nonempty_distribution_history_cannot_be_downgraded(tmp_path):
    path = safe_db(tmp_path)
    with sqlite3.connect(path) as db: db.executescript(SQL.read_text())
    mods = [load(p) for p in MIGRATIONS]
    for mod in mods: mod.migrate(path)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute("INSERT INTO users(user_id,name,email,password_hash,role,created_at) VALUES (1,'E','e@example.invalid','x','eic','2020-01-01')")
        db.execute("INSERT INTO manuscripts(manuscript_id,title,abstract,author_id,status,review_round,created_at) VALUES (1,'Synthetic','Synthetic',1,'submitted',1,'2020-01-01')")
        db.execute('INSERT INTO distribution_reservations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', ('a'*32,1,1,'editor_source',None,None,'b'*64,4,'txt','idempotency-key-01','c'*64,'2020-01-01'))
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError, match='immutable distribution history'):
            db.execute("UPDATE distribution_reservations SET byte_size=5")
        db.rollback()
    with pytest.raises(RuntimeError, match='history must be retained'): mods[-1].downgrade_empty(path)
    with sqlite3.connect(path) as db: assert db.execute('SELECT count(*) FROM distribution_reservations').fetchone() == (1,)

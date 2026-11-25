"""Submission migration rehearsals; all writes are to pytest temporary files."""
import hashlib
import importlib
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

migration = importlib.import_module('migrations.046_main_submission_schema')


def test_schema_comparison_preserves_string_literals():
    assert migration._normal("CHECK (kind IN ('cover_letter', 'supplementary'))") == migration._normal("check(kind in('cover_letter','supplementary'))")
    assert migration._normal("CHECK (kind = 'cover_letter')") != migration._normal("CHECK (kind = 'COVER_LETTER')")
    assert migration._normal("DEFAULT 'a b'") != migration._normal("DEFAULT 'ab'")
    assert migration._normal("DEFAULT 'don''t'") != migration._normal("DEFAULT 'DON''T'")
    assert migration._normal("DEFAULT 'ifnotexists'") != migration._normal("DEFAULT ''")


def test_schema_comparison_preserves_token_boundaries_and_quoted_identifiers():
    assert migration._normal('CREATE TABLE sample (x INTEGER)') != migration._normal('CREATE TABLEsample (x INTEGER)')
    assert migration._normal('CHECK (x >= 0)') != migration._normal('CHECK (x > = 0)')
    assert migration._normal('CREATE TABLE "a b" (x TEXT)') != migration._normal('CREATE TABLE "ab" (x TEXT)')
    assert migration._normal('CREATE TABLE "Foo" (x TEXT)') != migration._normal('CREATE TABLE "foo" (x TEXT)')
    assert migration._normal('CREATE TABLE `a``b` (x TEXT)') != migration._normal('CREATE TABLE `ab` (x TEXT)')
    assert migration._normal('CREATE TABLE [a b] (x TEXT)') != migration._normal('CREATE TABLE [ab] (x TEXT)')
    with pytest.raises(ValueError, match='Unterminated'):
        migration._normal('CREATE TABLE "unterminated')
    with pytest.raises(ValueError, match='comments'):
        migration._normal('CREATE TABLE x(a TEXT) -- comment')


def base(path):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE users (user_id INTEGER PRIMARY KEY)')
        db.execute('CREATE TABLE manuscripts (manuscript_id INTEGER PRIMARY KEY, author_id INTEGER REFERENCES users(user_id), file_path TEXT)')
        db.execute('CREATE TABLE schema_migrations (migration_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)')
        db.execute('INSERT INTO users VALUES (1)')
        db.execute("INSERT INTO manuscripts VALUES (1,1,'legacy/example.docx')")


def snapshot(path):
    with sqlite3.connect(path) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        result = {}
        for name in tables:
            quoted = name.replace('"', '""')
            rows = db.execute(f'SELECT * FROM "{quoted}"').fetchall()
            result[name] = hashlib.sha256(repr(sorted(map(repr, rows))).encode()).hexdigest()
        return result


def test_fresh_install_repeat_constraints_and_foreign_keys(tmp_path):
    path = tmp_path / 'fresh.sqlite'; base(path)
    before = snapshot(path)
    assert migration.migrate(path) == 'applied'
    assert migration.migrate(path) == 'already applied'
    after = snapshot(path)
    assert all(after[name] == value for name, value in before.items() if name != 'schema_migrations')
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert len(db.execute("SELECT * FROM schema_migrations WHERE migration_id LIKE '04%'").fetchall()) == 6
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO author_submission_drafts(id,author_id,request_id,created_at,updated_at) VALUES('x',999,'r','a','a')")
        db.execute("INSERT INTO author_submission_drafts(id,author_id,request_id,created_at,updated_at) VALUES('x',1,'r','a','a')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO author_submission_drafts(id,author_id,request_id,created_at,updated_at) VALUES('y',1,'r','a','a')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('DELETE FROM users WHERE user_id=1')


def test_atomic_rollback_on_injected_failure(tmp_path):
    path = tmp_path / 'fail.sqlite'; base(path); before = snapshot(path)
    def failure(index, name):
        if index == 3:
            raise RuntimeError('injected')
    with pytest.raises(RuntimeError, match='injected'):
        migration.migrate(path, _after_create=failure)
    assert snapshot(path) == before
    assert migration.migrate(path) == 'applied'


def test_conflicting_and_partial_schema_fail_closed(tmp_path):
    path = tmp_path / 'conflict.sqlite'; base(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE author_submission_drafts(id INTEGER)')
    before = snapshot(path)
    with pytest.raises(RuntimeError, match='Partial'):
        migration.migrate(path)
    assert snapshot(path) == before


def test_base_and_ledger_rejected(tmp_path):
    path = tmp_path / 'invalid.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE users(user_id INTEGER PRIMARY KEY)')
    with pytest.raises(RuntimeError, match='base schema'):
        migration.migrate(path)


def test_non_temporary_path_rejected(tmp_path, monkeypatch):
    allowed = tmp_path / 'allowed'
    allowed.mkdir()
    outside = tmp_path / 'outside.sqlite'
    base(outside)
    before = snapshot(outside)
    monkeypatch.setattr(migration.tempfile, 'gettempdir', lambda: str(allowed))
    with pytest.raises(ValueError, match='disposable'):
        migration.migrate(outside)
    assert snapshot(outside) == before


def test_isolated_existing_main_backup_upgrade(tmp_path):
    source = os.environ.get('GSUB_MAIN_BACKUP_REHEARSAL')
    if not source:
        pytest.skip('explicit isolated backup source not supplied')
    path = tmp_path / 'backup-copy.sqlite'
    with sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(path) as dst:
            src.backup(dst)
    before = snapshot(path)
    assert migration.migrate(path) == 'applied'
    assert migration.migrate(path) == 'already applied'
    after = snapshot(path)
    assert all(after[name] == value for name, value in before.items() if name != 'schema_migrations')
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_schema_matches_rehearsal_migrations_and_rejects_partial_ledger(tmp_path):
    old = tmp_path / 'old.sqlite'; new = tmp_path / 'new.sqlite'
    base(old); base(new)
    for migration_id in migration.PRIOR_IDS:
        importlib.import_module('migrations.' + migration_id).migrate(old)
    migration.migrate(new)
    with sqlite3.connect(old) as original, sqlite3.connect(new) as candidate:
        for name in migration.TABLES:
            for pragma in ('table_info', 'foreign_key_list', 'index_list'):
                assert original.execute(f'PRAGMA {pragma}("{name}")').fetchall() == candidate.execute(f'PRAGMA {pragma}("{name}")').fetchall()
            old_sql = original.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
            new_sql = candidate.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
            assert migration._normal(old_sql) == migration._normal(new_sql)
    with pytest.raises(RuntimeError, match='Partial'):
        migration.migrate(old)


def test_restore_rehearsal_after_upgrade_of_backup_copy(tmp_path):
    source = os.environ.get('GSUB_MAIN_BACKUP_REHEARSAL')
    if not source:
        pytest.skip('explicit isolated backup source not supplied')
    database = tmp_path / 'upgrade.sqlite'
    with sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(database) as dst:
            src.backup(dst)
    baseline = snapshot(database)
    assert migration.migrate(database) == 'applied'
    restored = tmp_path / 'restored.sqlite'
    with sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(restored) as dst:
            src.backup(dst)
    assert snapshot(restored) == baseline
    with sqlite3.connect(restored) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_upgraded_backup_preserves_storage_and_recorded_version_bytes(tmp_path):
    source = os.environ.get('GSUB_MAIN_BACKUP_REHEARSAL')
    if not source:
        pytest.skip('explicit isolated backup source not supplied')
    backup = Path(source).resolve().parent
    database = tmp_path / 'upgrade.sqlite'
    with sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(database) as dst:
            src.backup(dst)
    for name in ('uploads', '.gsub_sample_storage'):
        shutil.copytree(backup / name, tmp_path / name)
    def file_inventory():
        return {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
                for root in ('uploads', '.gsub_sample_storage')
                for p in (tmp_path / root).rglob('*') if p.is_file()}
    before = file_inventory()
    db_before = snapshot(database)
    assert migration.migrate(database) == 'applied'
    assert file_inventory() == before
    after = snapshot(database)
    assert all(after[name] == value for name, value in db_before.items() if name != 'schema_migrations')
    with sqlite3.connect(database) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        total = 0
        for table in ('sample_document_versions', 'sample_initial_artifacts', 'sample_stage_artifacts'):
            for identity, digest, size in db.execute(f'SELECT storage_identity, sha256, byte_size FROM {table}'):
                assert identity.startswith('sample:v1/')
                parts = identity.removeprefix('sample:v1/').split('/')
                assert len(parts) == 3 and all(part not in ('', '.', '..') for part in parts)
                data = (tmp_path / '.gsub_sample_storage').joinpath(*parts).read_bytes()
                assert len(data) == size and hashlib.sha256(data).hexdigest() == digest
                total += 1
        assert total > 0

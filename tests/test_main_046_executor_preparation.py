"""Synthetic preparation tests; no persistent Main execution is permitted."""
import importlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from scripts import main_046_executor as candidate


@pytest.fixture
def isolated(tmp_path):
    project, backup, restore = (tmp_path / name for name in ('project', 'backup', 'restore'))
    for directory in (project, backup, restore):
        directory.mkdir()
    db_path = project / 'manuscript.db'
    with sqlite3.connect(db_path) as db:
        db.executescript('''CREATE TABLE users(user_id INTEGER PRIMARY KEY);
            CREATE TABLE manuscripts(manuscript_id INTEGER PRIMARY KEY);
            CREATE TABLE schema_migrations(migration_id TEXT PRIMARY KEY, applied_at TEXT);
            CREATE TRIGGER preserve_manuscripts BEFORE DELETE ON manuscripts
            BEGIN SELECT RAISE(ABORT, 'immutable'); END;
            INSERT INTO users VALUES(1); INSERT INTO manuscripts VALUES(1);''')
    for name in candidate.KNOWN_ROOTS:
        (project / name).mkdir()
        (project / name / 'synthetic.txt').write_bytes(b'synthetic')
    for directory in (backup, restore):
        shutil.copy2(db_path, directory / 'manuscript.db')
        for name, filename in (('uploads', 'upload-manifest.json'),
                               ('.gsub_sample_storage', 'sample-storage-manifest.json')):
            shutil.copytree(project / name, directory / name)
            (directory / filename).write_text(json.dumps(candidate.manifest(project / name)), encoding='utf-8')
    roots = [project / name for name in candidate.KNOWN_ROOTS]
    return project, db_path, roots, backup, restore


def check(data, **changes):
    project, database, roots, backup, restore = data
    params = {'database': database, 'roots': roots, 'backup': backup, 'restore': restore,
              'confirmation': candidate.CONFIRMATION, 'project': project}
    params.update(changes)
    return candidate.validate(**params)


def test_wrong_path_and_confirmation_rejected(isolated):
    with pytest.raises(ValueError, match='identity'):
        check(isolated, database=isolated[0] / 'other.sqlite')
    with pytest.raises(ValueError, match='identity'):
        check(isolated, confirmation='wrong')


def test_missing_root_or_backup_rejected(isolated):
    with pytest.raises(ValueError, match='storage roots'):
        check(isolated, roots=isolated[2][:1])
    with pytest.raises(ValueError, match='backup'):
        check(isolated, backup=isolated[0].parent / 'missing')


def test_unverified_restore_rejected(isolated):
    (isolated[4] / 'uploads' / 'synthetic.txt').write_bytes(b'changed')
    with pytest.raises(ValueError, match='storage differs'):
        check(isolated)


def test_missing_storage_manifest_rejected(isolated):
    (isolated[3] / 'upload-manifest.json').unlink()
    with pytest.raises(ValueError, match='manifest unavailable'):
        check(isolated)


def test_hardlinked_backup_is_not_an_independent_copy(isolated):
    original = isolated[0] / 'uploads' / 'synthetic.txt'
    backup_file = isolated[3] / 'uploads' / 'synthetic.txt'
    backup_file.unlink()
    os.link(original, backup_file)
    with pytest.raises(ValueError, match='not independent'):
        check(isolated)


def test_evidence_match_does_not_enable_persistent_execution(isolated, monkeypatch):
    assert check(isolated) == {'users': 1, 'manuscripts': 1}
    monkeypatch.setattr(candidate, 'validate', lambda *args: {})
    assert candidate.main(['--database', 'x', '--confirm-main', 'x', '--backup', 'x', '--restore', 'x']) == 2


def test_authoritative_migration_only_on_isolated_copy(isolated):
    migration = importlib.import_module('migrations.046_main_submission_schema')
    target = isolated[4] / 'manuscript.db'
    assert migration.migrate(target) == 'applied'
    assert migration.migrate(target) == 'already applied'
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone() == (1,)
        assert db.execute('SELECT COUNT(*) FROM manuscripts').fetchone() == (1,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_injected_failure_rolls_back_isolated_copy(isolated):
    migration = importlib.import_module('migrations.046_main_submission_schema')
    target = isolated[4] / 'manuscript.db'
    def fail(index, name):
        if index == 2:
            raise RuntimeError('synthetic failure')
    with pytest.raises(RuntimeError, match='synthetic failure'):
        migration.migrate(target, _after_create=fail)
    with sqlite3.connect(target) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not tables.intersection(migration.TABLES)
        assert db.execute('SELECT COUNT(*) FROM users').fetchone() == (1,)
        assert db.execute('SELECT COUNT(*) FROM manuscripts').fetchone() == (1,)


def run_isolated(data, **kwargs):
    project, database, roots, backup, restore = data
    lock = project.parent / 'operation-lock'
    lock.mkdir(mode=0o700, exist_ok=True)
    return candidate.execute_isolated(database, roots, backup, restore, lock, project=project, **kwargs)


def test_guarded_isolated_transaction_and_repeat(isolated):
    assert run_isolated(isolated) == 'applied'
    assert run_isolated(isolated) == 'already applied'
    assert (isolated[0] / 'uploads' / 'synthetic.txt').read_bytes() == b'synthetic'
    with sqlite3.connect(isolated[1]) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name='preserve_manuscripts'").fetchone() == (1,)


def test_missing_maintenance_directory_rejected_before_writes(isolated):
    project, database, roots, backup, restore = isolated
    with pytest.raises(ValueError, match='temporary directories'):
        candidate.execute_isolated(database, roots, backup, restore, project.parent / 'missing', project=project)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='author_submission_drafts'").fetchone() == (0,)


def test_isolated_transaction_refuses_persistent_project():
    with pytest.raises(ValueError, match='disposable'):
        candidate.execute_isolated(candidate.ROOT / 'manuscript.db', [], '/x', '/y', '/z', project=candidate.ROOT)


def test_transaction_layer_itself_rejects_main(tmp_path, monkeypatch):
    project = tmp_path / 'synthetic-main'; project.mkdir()
    database = project / 'manuscript.db'; database.touch()
    monkeypatch.setattr(candidate, 'ROOT', project)
    with pytest.raises(ValueError, match='disposable'):
        candidate._transaction_isolated(database)


def test_main_rejected_even_if_temporary_root_is_its_parent(tmp_path, monkeypatch):
    project = tmp_path / 'synthetic-main'; project.mkdir()
    database = project / 'manuscript.db'; database.touch()
    monkeypatch.setattr(candidate, 'ROOT', project)
    monkeypatch.setattr(candidate.tempfile, 'gettempdir', lambda: str(candidate.ROOT.parent))
    with pytest.raises(ValueError, match='disposable'):
        candidate._transaction_isolated(candidate.ROOT / 'manuscript.db')
    with pytest.raises(ValueError, match='disposable'):
        candidate.execute_isolated(candidate.ROOT / 'manuscript.db', [], '/x', '/y', '/z', project=candidate.ROOT)


def test_transaction_layer_uncertain_commit_does_not_retry(isolated):
    target = isolated[4] / 'manuscript.db'
    calls = []
    def commit_then_fail(connection):
        calls.append('commit')
        connection.commit()
        raise OSError('synthetic lost commit response')
    with pytest.raises(candidate.OutcomeUncertain):
        candidate._transaction_isolated(target, _commit=commit_then_fail)
    assert calls == ['commit']
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT count(*) FROM schema_migrations WHERE migration_id='046_main_submission_schema'").fetchone() == (1,)


def test_failed_isolated_transaction_reports_uncertain_and_rolls_back(isolated):
    def fail(index, name):
        if index == 2:
            raise RuntimeError('synthetic failure')
    with pytest.raises(candidate.OutcomeUncertain):
        run_isolated(isolated, _after_create=fail)
    with sqlite3.connect(isolated[1]) as db:
        assert db.execute('SELECT count(*) FROM users').fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='author_submission_drafts'").fetchone() == (0,)


def test_lost_post_commit_result_requires_inspection(isolated):
    def fail():
        raise RuntimeError('synthetic lost result')
    with pytest.raises(candidate.OutcomeUncertain):
        run_isolated(isolated, _after_commit=fail)
    with sqlite3.connect(isolated[1]) as db:
        assert db.execute("SELECT count(*) FROM schema_migrations WHERE migration_id='046_main_submission_schema'").fetchone() == (1,)


def test_concurrent_isolated_sqlite_writer_does_not_apply_migration(isolated):
    with sqlite3.connect(isolated[1]) as writer:
        writer.execute('BEGIN IMMEDIATE')
        with pytest.raises(candidate.OutcomeUncertain):
            run_isolated(isolated)
        writer.rollback()
    with sqlite3.connect(isolated[1]) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='author_submission_drafts'").fetchone() == (0,)

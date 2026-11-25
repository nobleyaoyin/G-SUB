"""Disposable initialization checks; no original data or external files."""
from pathlib import Path
import sqlite3
from uuid import uuid4
import pytest
from database.bootstrap import initialize as initializer


def fresh_name():
    return 'initializer-' + uuid4().hex + '.sqlite'


def test_fresh_initialization_and_existing_file_protection():
    name = fresh_name()
    path = initializer.initialize(name)
    assert path.parent == initializer.DATA.resolve()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        assert db.execute('SELECT version FROM collaboration_schema_version').fetchone() == (1,)
        ledger = {row[0] for row in db.execute('SELECT migration_id FROM schema_migrations')}
        assert ledger == set(initializer.MIGRATIONS + initializer.SUBMISSION_PRIOR_IDS)
        assert db.execute("SELECT name FROM sqlite_master WHERE name='manuscript_submission_requests'").fetchone()
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    before = path.read_bytes()
    with pytest.raises(FileExistsError): initializer.initialize(name)
    assert path.read_bytes() == before


@pytest.mark.parametrize('name', ['../escape.sqlite', '/tmp/escape.sqlite', 'escape.db', '..sqlite', 'x/y.sqlite'])
def test_unsafe_names_rejected(name):
    with pytest.raises(ValueError): initializer.initialize(name)


def test_symlink_directory_rejected_with_fresh_positive_control(monkeypatch):
    assert initializer.initialize(fresh_name()).is_file()
    link = initializer.DATA / ('link-' + uuid4().hex)
    link.symlink_to(initializer.DATA / 'tmp', target_is_directory=True)
    monkeypatch.setattr(initializer, 'DATA', link)
    with pytest.raises(ValueError): initializer.initialize(fresh_name())


def test_migration_failure_retains_partial_file(monkeypatch):
    assert initializer.initialize(fresh_name()).is_file()
    name = fresh_name()
    def fail(_name): raise RuntimeError('synthetic migration failure')
    monkeypatch.setattr(initializer.importlib, 'import_module', fail)
    with pytest.raises(RuntimeError, match='file retained'):
        initializer.initialize(name)
    assert (initializer.DATA / name).is_file()


def test_non_temporary_workspace_rejected_before_file_creation(monkeypatch, tmp_path):
    name = fresh_name()
    monkeypatch.setattr(initializer.tempfile, 'gettempdir', lambda: str(tmp_path))
    with pytest.raises(ValueError, match='system temporary directory'):
        initializer.initialize(name)
    assert not (initializer.DATA / name).exists()

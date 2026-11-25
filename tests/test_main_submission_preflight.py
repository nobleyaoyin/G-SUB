"""Preflight tests use only disposable synthetic files and database fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import pytest

spec = importlib.util.spec_from_file_location('main_submission_preflight', Path(__file__).resolve().parents[1] / 'scripts/main_submission_preflight.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('MANUSCRIPT_MODE', 'development')
    root = tmp_path / 'root'; backup = tmp_path / 'backup'; root.mkdir(); backup.mkdir()
    for name, manifest in [('uploads','upload-manifest.json'), ('.gsub_sample_storage','sample-storage-manifest.json')]:
        (root/name).mkdir(); (backup/name).mkdir()
        (root/name/'test.txt').write_bytes(b'synthetic')
        (backup/name/'test.txt').write_bytes(b'synthetic')
        (backup/manifest).write_text(json.dumps({'test.txt':{'bytes':9,'sha256':hashlib.sha256(b'synthetic').hexdigest()}}))
    with sqlite3.connect(root/'manuscript.db') as db:
        db.execute('CREATE TABLE users(user_id INTEGER PRIMARY KEY)')
        db.execute('CREATE TABLE manuscripts(manuscript_id INTEGER PRIMARY KEY, file_path TEXT)')
        db.execute('CREATE TABLE manuscript_submission_snapshots(id INTEGER PRIMARY KEY)')
        db.execute('CREATE TABLE schema_migrations(migration_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)')
        db.execute('INSERT INTO users VALUES (1)')
        db.execute("INSERT INTO manuscripts VALUES (1,'uploads/test.txt')")
    shutil.copy2(root/'manuscript.db', backup/'manuscript.db')
    return root,backup


def inspect(workspace):
    return p.inspect(*workspace, handle_check=lambda _: None)


def test_matching_fixture_and_unchanged_database(workspace):
    root, _ = workspace
    before = p._sha(root/'manuscript.db')
    result = inspect(workspace)
    assert result['users'] == result['manuscripts'] == 1
    assert p._sha(root/'manuscript.db') == before


def test_cli_never_declares_migration_ready_from_evidence_alone(monkeypatch):
    monkeypatch.setattr(p, 'inspect', lambda *args: {'users': 1})
    monkeypatch.setattr('sys.argv', ['preflight', '--backup', '/unused'])
    assert p.main() == 2


def test_changed_database_and_schema_fail_closed(workspace):
    root, _ = workspace
    with sqlite3.connect(root/'manuscript.db') as db:
        db.execute('INSERT INTO users VALUES (2)')
    with pytest.raises(ValueError, match='differs from backup'):
        inspect(workspace)


def test_changed_storage_and_missing_reference_fail_closed(workspace):
    root, _ = workspace
    (root/'uploads'/'test.txt').write_bytes(b'changed')
    with pytest.raises(ValueError, match='storage differs'):
        inspect(workspace)


def test_missing_document_reference_and_missing_manifest_fail_closed(workspace):
    root, backup = workspace
    with sqlite3.connect(root/'manuscript.db') as db:
        db.execute("UPDATE manuscripts SET file_path='uploads/missing.txt'")
    shutil.copy2(root/'manuscript.db', backup/'manuscript.db')
    with pytest.raises(ValueError, match='referenced file missing'):
        inspect(workspace)
    (backup/'upload-manifest.json').unlink()
    with pytest.raises(OSError):
        inspect(workspace)


def test_new_handle_after_read_is_rejected(workspace):
    calls = []
    def changed_handle(_):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError('database has open handles')
    with pytest.raises(ValueError, match='open handles'):
        p.inspect(*workspace, handle_check=changed_handle)


def test_recorded_version_digest_is_checked(workspace):
    root, backup = workspace
    with sqlite3.connect(root/'manuscript.db') as db:
        db.execute('CREATE TABLE versions(storage_identity TEXT, sha256 TEXT, byte_size INTEGER)')
        db.execute("INSERT INTO versions VALUES ('sample:v1/test.txt', 'incorrect', 9)")
    shutil.copy2(root/'manuscript.db', backup/'manuscript.db')
    with pytest.raises(ValueError, match='digest mismatch'):
        inspect(workspace)


def test_open_handles_or_unavailable_inspection_fail_closed(workspace):
    def open_handle(_):
        raise ValueError('database has open handles')
    with pytest.raises(ValueError, match='open handles'):
        p.inspect(*workspace, handle_check=open_handle)


def test_unsupported_mode_and_wal_fail_closed(workspace, monkeypatch):
    monkeypatch.setenv('MANUSCRIPT_MODE', 'unrecognized')
    with pytest.raises(ValueError, match='mode'):
        inspect(workspace)
    monkeypatch.setenv('MANUSCRIPT_MODE', 'development')
    (workspace[0]/'manuscript.db-wal').touch()
    with pytest.raises(ValueError, match='WAL'):
        inspect(workspace)

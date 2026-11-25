"""Synthetic backup and storage preflight; never opens persistent Main."""
import hashlib
import os
import sqlite3

import pytest

from scripts import main_046_executor as checks
from scripts import rehearse_current_main_snapshot as backupper


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    for name in checks.PRIVATE_ROOTS:
        monkeypatch.delenv(name, raising=False)
    project = tmp_path / 'project'
    project.mkdir()
    for name in checks.KNOWN_ROOTS:
        (project / name).mkdir()
    content = b'synthetic manuscript'
    (project / 'uploads' / 'file.txt').write_bytes(content)
    with sqlite3.connect(project / 'manuscript.db') as db:
        db.executescript('CREATE TABLE users(user_id INTEGER PRIMARY KEY); CREATE TABLE manuscripts(manuscript_id INTEGER PRIMARY KEY, file_path TEXT, sha256 TEXT, byte_size INTEGER); CREATE TABLE schema_migrations(migration_id TEXT PRIMARY KEY, applied_at TEXT);')
        db.execute('INSERT INTO manuscripts VALUES (1,?,?,?)', ('uploads/file.txt', hashlib.sha256(content).hexdigest(), len(content)))
    monkeypatch.setattr(backupper.tempfile, 'tempdir', str(tmp_path))
    backup, restore = backupper.create_verified_backup(project)
    roots = [project / name for name in checks.KNOWN_ROOTS]
    return project, roots, backup, restore


def validate(data):
    project, roots, backup, restore = data
    return checks.validate(project / 'manuscript.db', roots, backup, restore, checks.CONFIRMATION, project=project)


def test_canonical_backup_and_restore_end_to_end(evidence):
    project, _, backup, restore = evidence
    assert backup == backup.resolve() and restore == restore.resolve()
    assert not backup.is_relative_to(project) and not restore.is_relative_to(project)
    assert os.stat(backup / 'manuscript.db').st_ino != os.stat(restore / 'manuscript.db').st_ino
    assert validate(evidence)['manuscripts'] == 1


@pytest.mark.parametrize('name', checks.PRIVATE_ROOTS)
def test_configured_private_root_fails_closed(evidence, monkeypatch, name):
    monkeypatch.setenv(name, '/synthetic/private')
    with pytest.raises(ValueError, match='Configured private storage'):
        validate(evidence)


def test_missing_referenced_file_rejected_even_when_manifests_match(evidence):
    project, _, backup, restore = evidence
    # Keep all three trees internally consistent; the database reference is missing.
    for directory in (project, backup, restore):
        (directory / 'uploads' / 'file.txt').unlink()
    for directory in (backup, restore):
        (directory / 'upload-manifest.json').write_text('{}')
    with pytest.raises(ValueError, match='referenced file missing'):
        validate(evidence)


def test_symlink_rejected(evidence):
    project = evidence[0]
    (project / 'uploads' / 'alias').symlink_to(project / 'uploads' / 'file.txt')
    with pytest.raises(ValueError, match='symlink'):
        validate(evidence)


def test_restored_file_hash_mismatch_rejected(evidence):
    (evidence[3] / 'uploads' / 'file.txt').write_bytes(b'changed')
    with pytest.raises(ValueError, match='storage differs'):
        validate(evidence)

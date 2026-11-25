"""Synthetic checks for the Main read-only snapshot rehearsal helpers."""
from pathlib import Path
import sqlite3

import pytest

from scripts.rehearse_current_main_snapshot import backup_database, check_no_journal, manifest, snapshot


def test_manifest_detects_byte_changes_and_rejects_symlinks(tmp_path):
    file = tmp_path / 'synthetic.txt'
    file.write_bytes(b'original')
    first = manifest(tmp_path)
    file.write_bytes(b'changed')
    assert first != manifest(tmp_path)
    (tmp_path / 'link').symlink_to(file)
    with pytest.raises(ValueError, match='symlink'):
        manifest(tmp_path)


def test_refuses_any_sqlite_journal(tmp_path):
    db = tmp_path / 'test.sqlite'
    db.write_bytes(b'synthetic')
    check_no_journal(db)
    Path(str(db) + '-wal').write_bytes(b'synthetic')
    with pytest.raises(ValueError, match='journal'):
        check_no_journal(db)


def test_online_backup_and_read_only_fingerprints(tmp_path):
    source, backup = tmp_path / 'source.sqlite', tmp_path / 'backup.sqlite'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)')
        db.execute('INSERT INTO records VALUES (1, ?)', ('synthetic',))
    before = source.read_bytes()
    backup_database(source, backup)
    assert snapshot(source) == snapshot(backup)
    assert source.read_bytes() == before

#!/usr/bin/env python3
"""Copy known Main data to a private temporary directory and rehearse only there.

This is not an execution-time backup and cannot establish writer exclusion or
discover historical private roots. It never invokes a migration on Main.
"""
from contextlib import closing
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.main_submission_preflight import _snapshot

STORAGE = ('uploads', '.gsub_sample_storage')
APPLICATION = ('app/onlyoffice_docx.py', 'app/routers/onlyoffice.py',
               'app/online_versions.py', 'frontend/src/OnlineDocxEditor.jsx')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def manifest(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Missing or symlinked storage root')
    result = {}
    for directory, subdirs, files in os.walk(root, followlinks=False):
        for name in subdirs + files:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError('Storage symlink requires manual investigation')
        for name in files:
            path = Path(directory) / name
            if not path.is_file():
                raise ValueError('Storage contains a non-regular file')
            result[str(path.relative_to(root))] = {'bytes': path.stat().st_size, 'sha256': digest(path)}
    return result


def check_no_journal(path):
    if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Database journal present: do not take this rehearsal snapshot')


def snapshot(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('Database integrity failure')
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('Database foreign-key failure')
        return _snapshot(db)


def backup_database(source, target):
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as old:
        with closing(sqlite3.connect(target)) as new:
            old.backup(new)


def create_verified_backup(project):
    """Create independent snapshots of evidenced roots; caller must stop writers."""
    project = Path(project).resolve(strict=True)
    db = project / 'manuscript.db'
    if db.is_symlink() or not db.is_file() or db.stat().st_nlink != 1:
        raise ValueError('Database is not an independent regular file')
    check_no_journal(db)
    before = snapshot(db)
    source = {name: manifest(project / name) for name in STORAGE}
    base = Path(tempfile.mkdtemp(prefix='gsub-main-046-')).resolve(strict=True)
    if base == project or base.is_relative_to(project) or project.is_relative_to(base):
        raise ValueError('Backup must be independent of project')
    backup, restore = base / 'backup', base / 'restore'
    backup.mkdir(mode=0o700)
    backup_database(db, backup / 'manuscript.db')
    for name, index in (('uploads', 'upload-manifest.json'), ('.gsub_sample_storage', 'sample-storage-manifest.json')):
        shutil.copytree(project / name, backup / name)
        (backup / index).write_text(json.dumps(source[name], sort_keys=True), encoding='utf-8')
    shutil.copytree(backup, restore)
    check_no_journal(db)
    if not snapshot(db) == before == snapshot(backup / 'manuscript.db') == snapshot(restore / 'manuscript.db'):
        raise ValueError('Database backup or restore mismatch')
    if any(manifest(directory / name) != source[name] for directory in (project, backup, restore) for name in STORAGE):
        raise ValueError('Storage backup or restore mismatch')
    return backup, restore


def main():
    db = ROOT / 'manuscript.db'
    if db.is_symlink() or not db.is_file() or db.stat().st_nlink != 1:
        raise ValueError('Main database is not an independent regular file')
    check_no_journal(db)
    directory = Path(tempfile.mkdtemp(prefix='gsub-main-snapshot-')).resolve()
    backup = directory / 'backup'
    restore = directory / 'restore'
    backup.mkdir(mode=0o700)
    before_db_hash = digest(db)
    before_schema, before_rows = snapshot(db)
    originals = {name: manifest(ROOT / name) for name in STORAGE}
    for name in APPLICATION:
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT) or not path.is_file():
            raise ValueError('Application source unavailable or unsafe')
    source_code = {name: digest(ROOT / name) for name in APPLICATION}
    backup_database(db, backup / 'manuscript.db')
    for name in STORAGE:
        shutil.copytree(ROOT / name, backup / name, symlinks=True)
        if manifest(backup / name) != originals[name]:
            raise ValueError('Backup storage mismatch')
    for name in APPLICATION:
        path = backup / 'application' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, path)
        if digest(path) != source_code[name]:
            raise ValueError('Application file backup mismatch')
    (backup / 'sha256-manifests.json').write_text(json.dumps({'storage': originals, 'application': source_code}, sort_keys=True), encoding='utf-8')
    for name, filename in (('uploads', 'upload-manifest.json'),
                           ('.gsub_sample_storage', 'sample-storage-manifest.json')):
        (backup / filename).write_text(json.dumps(originals[name], sort_keys=True), encoding='utf-8')
    if snapshot(backup / 'manuscript.db') != (before_schema, before_rows):
        raise ValueError('Backup rows or schema differ')
    shutil.copytree(backup, restore)
    if snapshot(restore / 'manuscript.db') != (before_schema, before_rows):
        raise ValueError('Independent restoration differs')
    if any(manifest(restore / name) != originals[name] for name in STORAGE):
        raise ValueError('Independent storage restoration differs')
    if any(digest(restore / 'application' / name) != source_code[name] for name in APPLICATION):
        raise ValueError('Independent application restoration differs')
    migration = importlib.import_module('migrations.046_main_submission_schema')
    if migration.migrate(restore / 'manuscript.db') != 'applied':
        raise ValueError('Expected an unapplied isolated schema')
    if migration.migrate(restore / 'manuscript.db') != 'already applied':
        raise ValueError('Repeated isolated migration was not idempotent')
    after_schema, after_rows = snapshot(restore / 'manuscript.db')
    if not set(before_schema).issubset(set(after_schema)):
        raise ValueError('Original schema or triggers changed')
    if any(after_rows[k] != v for k, v in before_rows.items() if k != 'schema_migrations'):
        raise ValueError('Original rows changed')
    with closing(sqlite3.connect((restore / 'manuscript.db').resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        ledger = {row[0] for row in connection.execute('SELECT migration_id FROM schema_migrations')}
        if not set(migration.TABLES).issubset(names) or not set(migration.PRIOR_IDS + (migration.MIGRATION_ID,)).issubset(ledger):
            raise ValueError('Migration schema or ledger missing')
    failed = directory / 'rollback.sqlite'
    backup_database(backup / 'manuscript.db', failed)
    def inject(index, name):
        if index == 2:
            raise RuntimeError('injected rollback')
    try:
        migration.migrate(failed, _after_create=inject)
        raise AssertionError('Injected failure did not occur')
    except RuntimeError as exc:
        if str(exc) != 'injected rollback':
            raise
    if snapshot(failed) != (before_schema, before_rows):
        raise ValueError('Failed migration did not roll back')
    check_no_journal(db)
    if digest(db) != before_db_hash or snapshot(db) != (before_schema, before_rows):
        raise ValueError('Main database changed during rehearsal')
    if any(manifest(ROOT / name) != originals[name] or manifest(restore / name) != originals[name] for name in STORAGE):
        raise ValueError('Main or restored storage changed during rehearsal')
    if any(digest(ROOT / name) != source_code[name] for name in APPLICATION):
        raise ValueError('Application source changed during rehearsal')
    print(json.dumps({'rehearsal': str(directory), 'backup': str(backup), 'restore': str(restore),
                      'source_sha256': before_db_hash, 'backup_sha256': digest(backup / 'manuscript.db'),
                      'storage_files': {name: len(originals[name]) for name in STORAGE},
                      'users': before_rows['users'][0], 'manuscripts': before_rows['manuscripts'][0],
                      'result': 'isolated migration, repeat and rollback passed'}))


if __name__ == '__main__':
    main()

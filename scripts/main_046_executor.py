#!/usr/bin/env python3
"""Fail-closed Main 046 preparation. Persistent execution is not implemented.

This tool cannot verify exclusion of nonparticipating filesystem writers or
prove historical storage inventory. It never migrates a persistent database.
"""
import argparse
from contextlib import closing
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rehearse_current_main_snapshot import check_no_journal, manifest, snapshot
from scripts.main_submission_preflight import _check_files, _snapshot
from app.maintenance_barrier import MaintenanceBarrier

CONFIRMATION = 'original-main-development'
KNOWN_ROOTS = ('uploads', '.gsub_sample_storage')
PRIVATE_ROOTS = ('GSUB_SUBMISSION_ATTACHMENT_ROOT', 'GSUB_DISTRIBUTION_PRIVATE_ROOT', 'GSUB_EIC_PROOF_PRIVATE_ROOT')


class OutcomeUncertain(RuntimeError):
    """Stop and inspect the isolated target; do not retry automatically."""


def _transaction_isolated(database, *, _after_create=None, _commit=None):
    """Apply authoritative DDL under one transaction, only to temporary files.

    This independent transaction is a rehearsal implementation, not a path
    around the original migration's persistent-database restriction.
    """
    path = Path(database).resolve(strict=True)
    temporary = Path(tempfile.gettempdir()).resolve()
    if path.is_relative_to(ROOT) or not path.is_relative_to(temporary) or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('Only a standalone disposable temporary database is permitted')
    migration = importlib.import_module('migrations.046_main_submission_schema')
    connection = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    attempted_commit = False
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',) or connection.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Database integrity or foreign-key check failed')
        for table, column in (('users', 'user_id'), ('manuscripts', 'manuscript_id'),
                              ('schema_migrations', 'migration_id'), ('schema_migrations', 'applied_at')):
            if column not in {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}:
                raise ValueError('Required base schema is unavailable')
        existing = {name: connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() for name in migration.TABLES}
        old_ledger = set(connection.execute('SELECT migration_id, applied_at FROM schema_migrations'))
        ids = set(migration.PRIOR_IDS + (migration.MIGRATION_ID,))
        old_ids = {row[0] for row in old_ledger}
        if any(existing.values()):
            if not all(existing.values()) or not ids.issubset(old_ids):
                raise ValueError('Partial submission schema requires investigation')
            if any(migration._normal(existing[name][0]) != migration._normal(sql) for name, sql in migration.TABLES.items()):
                raise ValueError('Conflicting submission schema')
            connection.rollback()
            return 'already applied'
        if ids & old_ids:
            raise ValueError('Submission migration ledger conflicts with schema')
        old_schema, old_rows = _snapshot(connection)
        for index, (name, sql) in enumerate(migration.TABLES.items()):
            connection.execute(sql)
            if _after_create is not None:
                _after_create(index, name)
        for migration_id in migration.PRIOR_IDS + (migration.MIGRATION_ID,):
            connection.execute("INSERT INTO schema_migrations (migration_id, applied_at) VALUES (?, datetime('now'))", (migration_id,))
        new_schema, new_rows = _snapshot(connection)
        if not set(old_schema).issubset(set(new_schema)) or any(new_rows.get(k) != v for k, v in old_rows.items() if k != 'schema_migrations'):
            raise ValueError('Preexisting data or schema changed')
        ledger = set(connection.execute('SELECT migration_id, applied_at FROM schema_migrations'))
        if not old_ledger.issubset(ledger) or {row[0] for row in ledger} != old_ids | ids:
            raise ValueError('Migration ledger verification failed')
        if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',) or connection.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Post-migration integrity or foreign-key check failed')
        attempted_commit = True
        if _commit is None:
            connection.commit()
        else:
            _commit(connection)
        return 'applied'
    except Exception as exc:
        if attempted_commit:
            raise OutcomeUncertain('Commit outcome unavailable; inspect schema and ledger before retry') from exc
        connection.rollback()
        raise
    finally:
        connection.close()


def _verify_storage(project, backup, restore):
    for name, filename in (('uploads', 'upload-manifest.json'),
                           ('.gsub_sample_storage', 'sample-storage-manifest.json')):
        current = manifest(project / name)
        for directory in (backup, restore):
            storage_root = directory / name
            if storage_root.is_symlink() or not storage_root.is_dir():
                raise ValueError('Backup or restore storage is not independent')
            for path in storage_root.rglob('*'):
                if path.is_symlink() or (path.is_file() and path.stat().st_nlink != 1):
                    raise ValueError('Backup or restore storage is not independent')
            index = directory / filename
            if index.is_symlink() or not index.is_file():
                raise ValueError('Storage manifest unavailable')
            try:
                recorded = json.loads(index.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError) as exc:
                raise ValueError('Storage manifest invalid') from exc
            if recorded != current or manifest(storage_root) != current:
                raise ValueError('Backup or restore storage differs from Main')


def _verify_isolated_after(database, project, backup, restore):
    migration = importlib.import_module('migrations.046_main_submission_schema')
    old_schema, old_rows = snapshot(backup / 'manuscript.db')
    if snapshot(restore / 'manuscript.db') != (old_schema, old_rows):
        raise ValueError('Independent restore differs from backup')
    new_schema, new_rows = snapshot(database)
    if not set(old_schema).issubset(set(new_schema)):
        raise ValueError('Existing schema or trigger changed')
    added = set(new_schema) - set(old_schema)
    if {row[1] for row in added if row[0] == 'table'} != set(migration.TABLES) or any(row[0] != 'table' for row in added):
        raise ValueError('Unexpected schema objects')
    if any(new_rows.get(name) != value for name, value in old_rows.items() if name != 'schema_migrations'):
        raise ValueError('Existing rows changed')
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db, \
         closing(sqlite3.connect((backup / 'manuscript.db').resolve().as_uri() + '?mode=ro', uri=True)) as saved:
        for name, sql in migration.TABLES.items():
            row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            if not row or migration._normal(row[0]) != migration._normal(sql):
                raise ValueError('Authoritative schema differs')
        old_ledger = set(saved.execute('SELECT migration_id, applied_at FROM schema_migrations'))
        new_ledger = set(db.execute('SELECT migration_id, applied_at FROM schema_migrations'))
        new_ids = set(migration.PRIOR_IDS + (migration.MIGRATION_ID,))
        if not old_ledger.issubset(new_ledger) or {r[0] for r in new_ledger} != {r[0] for r in old_ledger} | new_ids:
            raise ValueError('Migration ledger differs')
    _verify_storage(project, backup, restore)


def execute_isolated(database, roots, backup, restore, lockdir, *, project, _after_create=None, _after_commit=None):
    """Exercise the existing guarded transaction on disposable copies only.

    Cooperative locking here is not proof of global filesystem exclusion.
    Never accepts Main or a path outside Python's configured temporary root.
    """
    project = Path(project)
    temporary = Path(tempfile.gettempdir()).resolve()
    if (not project.is_absolute() or project == ROOT or project.is_relative_to(ROOT)
            or project.is_symlink() or project.resolve() != project
            or not project.is_relative_to(temporary) or project == temporary):
        raise ValueError('Only a disposable temporary project is permitted')
    database, backup, restore = Path(database), Path(backup), Path(restore)
    if database != project / 'manuscript.db':
        raise ValueError('Exact isolated project database required')
    if database.is_symlink() or not database.is_file() or database.resolve() != database or database.stat().st_nlink != 1:
        raise ValueError('Isolated database path unavailable or unsafe')
    check_no_journal(database)
    if {Path(p) for p in roots} != {project / name for name in KNOWN_ROOTS} or len(roots) != len(KNOWN_ROOTS):
        raise ValueError('Exact isolated storage roots required')
    for path in (backup, restore, Path(lockdir)):
        if not path.is_absolute() or path.is_symlink() or not path.is_dir() or path.resolve() != path or not path.is_relative_to(temporary):
            raise ValueError('Independent temporary directories required')
    if any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for a, b in ((project, backup), (project, restore), (backup, restore))):
        raise ValueError('Independent project, backup and restore required')
    for saved in (backup / 'manuscript.db', restore / 'manuscript.db'):
        if saved.is_symlink() or not saved.is_file() or saved.stat().st_nlink != 1:
            raise ValueError('Independent backup and restored databases required')
        check_no_journal(saved)
    age = time.time() - (backup / 'manuscript.db').stat().st_mtime
    if age < 0 or age > 600:
        raise ValueError('A fresh isolated backup is required')
    migration = importlib.import_module('migrations.046_main_submission_schema')
    with MaintenanceBarrier(lockdir).maintenance():
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if present.intersection(migration.TABLES):
            _verify_isolated_after(database, project, backup, restore)
            return 'already applied'
        validate(database, roots, backup, restore, CONFIRMATION, project=project)
        try:
            result = _transaction_isolated(database, _after_create=_after_create)
            if _after_commit is not None:
                _after_commit()
            _verify_isolated_after(database, project, backup, restore)
            return result
        except Exception as exc:
            raise OutcomeUncertain('Stop: inspect the isolated schema, ledger and files before any retry') from exc


def validate(database, roots, backup, restore, confirmation, *, project=ROOT):
    """Read-only evidence checks; successful checks do not authorize migration."""
    project = Path(project)
    configured = [name for name in PRIVATE_ROOTS if os.environ.get(name)]
    if configured:
        raise ValueError('Configured private storage requires separate inventory and backup: ' + ', '.join(configured))
    expected = project / 'manuscript.db'
    database = Path(database)
    if confirmation != CONFIRMATION or not database.is_absolute() or database != expected:
        raise ValueError('Exact Main database and identity confirmation required')
    if database.is_symlink() or not database.is_file() or database.resolve() != database or database.stat().st_nlink != 1:
        raise ValueError('Main database path unavailable or unsafe')
    required_roots = {project / name for name in KNOWN_ROOTS}
    if {Path(path) for path in roots} != required_roots or len(roots) != len(required_roots):
        raise ValueError('Exactly the evidenced storage roots must be listed')
    backup, restore = Path(backup), Path(restore)
    for name, directory in (('backup', backup), ('restore', restore)):
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir() or directory.resolve() != directory:
            raise ValueError(f'{name} directory unavailable or unsafe')
        if directory == project or directory.is_relative_to(project) or project.is_relative_to(directory):
            raise ValueError(f'{name} must be independent of Main')
    if backup == restore or backup.is_relative_to(restore) or restore.is_relative_to(backup):
        raise ValueError('Backup and restore must be independent')
    saved, restored = backup / 'manuscript.db', restore / 'manuscript.db'
    for path in (saved, restored):
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError('Independent backup and restored databases required')
        check_no_journal(path)
    age = time.time() - saved.stat().st_mtime
    if age < 0 or age > 600:
        raise ValueError('A fresh backup is required')
    check_no_journal(database)
    state = snapshot(database)
    if snapshot(saved) != state or snapshot(restored) != state:
        raise ValueError('Backup or independent restore differs from Main')
    _verify_storage(project, backup, restore)
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        _check_files(project, db, backup)
    return {'users': state[1].get('users', (0,))[0], 'manuscripts': state[1].get('manuscripts', (0,))[0]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--confirm-main', required=True)
    parser.add_argument('--storage-root', action='append', default=[])
    parser.add_argument('--backup', required=True)
    parser.add_argument('--restore', required=True)
    args = parser.parse_args(argv)
    try:
        validate(args.database, args.storage_root, args.backup, args.restore, args.confirm_main)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 1
    print('REFUSED: persistent execution is unavailable; independent writer exclusion and historical storage are not verified.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

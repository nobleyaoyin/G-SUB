"""Disposable-only Migration 046 operator rehearsal; never targets persistent Main."""
import argparse
from contextlib import closing
import importlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.main_submission_preflight import _check_files, _handles, _open_database, _snapshot, inspect

migration = importlib.import_module('migrations.046_main_submission_schema')


def _paths(root, backup):
    original_root, original_backup = Path(root), Path(backup)
    if original_root.is_symlink() or original_backup.is_symlink():
        raise ValueError('symlink roots are not allowed')
    root, backup = original_root.resolve(strict=True), original_backup.resolve(strict=True)
    temporary = Path(tempfile.gettempdir()).resolve()
    if not root.is_relative_to(temporary) or not backup.is_relative_to(temporary):
        raise ValueError('only disposable temporary directories are allowed')
    if root == backup or root.is_relative_to(backup) or backup.is_relative_to(root):
        raise ValueError('target and backup must be independent')
    if not root.is_dir() or not backup.is_dir():
        raise ValueError('target and backup directories are required')
    age = time.time() - (backup / 'manuscript.db').stat().st_mtime
    if age < 0 or age > 600:
        raise ValueError('a fresh verified rehearsal backup is required')
    return root, backup


def _already_applied(root, backup):
    with closing(_open_database(root / 'manuscript.db')) as db, closing(_open_database(backup / 'manuscript.db')) as old:
        for conn in (db, old):
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('integrity check failed')
        schema, rows = _snapshot(db); old_schema, old_rows = _snapshot(old)
        new_names = set(migration.TABLES)
        for name, expected_sql in migration.TABLES.items():
            row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            if not row or migration._normal(row[0]) != migration._normal(expected_sql):
                raise ValueError('submission schema does not match the candidate')
        old_objects = {(r[0], r[1]): r for r in old_schema}
        objects = {(r[0], r[1]): r for r in schema if r[1] not in new_names and r[2] not in new_names}
        if objects != old_objects:
            raise ValueError('existing database schema differs from backup')
        if any(rows.get(k) != value for k, value in old_rows.items() if k != 'schema_migrations'):
            raise ValueError('existing database rows differ from backup')
        prior_rows = set(old.execute('SELECT migration_id, applied_at FROM schema_migrations'))
        current_rows = set(db.execute('SELECT migration_id, applied_at FROM schema_migrations'))
        prior = {r[0] for r in prior_rows}
        current = {r[0] for r in current_rows}
        if prior.intersection(migration.PRIOR_IDS + (migration.MIGRATION_ID,)) or not prior_rows.issubset(current_rows):
            raise ValueError('backup ledger is incompatible or historical entries changed')
        if current != prior | set(migration.PRIOR_IDS + (migration.MIGRATION_ID,)):
            raise ValueError('migration ledger conflicts with backup')
        _check_files(root, db, backup)


def rehearse(root, backup, *, _after_create=None):
    root, backup = _paths(root, backup)
    if os.environ.get('MANUSCRIPT_MODE', 'development') != 'development':
        raise ValueError('development mode required')
    target = root / 'manuscript.db'
    _handles(target)
    with closing(_open_database(target)) as db:
        present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='author_submission_drafts'").fetchone() is not None
    if present:
        _already_applied(root, backup)
    else:
        inspect(root, backup)
    _handles(target)
    # The original migration owns its BEGIN IMMEDIATE transaction and retains its
    # disposable path guard. No application data or files are copied or deleted.
    result = migration.migrate(target, _after_create=_after_create)
    _already_applied(root, backup)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-root', required=True)
    parser.add_argument('--backup', required=True)
    args = parser.parse_args()
    try:
        print('REHEARSAL:', rehearse(args.target_root, args.backup))
    except Exception as exc:
        print('REHEARSAL FAILED:', type(exc).__name__, str(exc), file=sys.stderr)
        print('Do not retry automatically: inspect the isolated database and ledger for uncertain commit outcomes.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

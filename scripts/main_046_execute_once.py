#!/usr/bin/env python3
"""One-time Main 046 transaction. Requires separately authorized offline maintenance.

Offline confirmation is an operator attestation, not filesystem writer exclusion.
On an uncertain outcome stop and inspect; never retry automatically.
"""
import argparse
from contextlib import closing
import importlib
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import main_046_executor as checks
from scripts.main_only_046_operator import MAIN_ROOT, validate_identity
from scripts.main_submission_preflight import _handles, _snapshot
from scripts.rehearse_current_main_snapshot import snapshot

OFFLINE = 'writers-stopped-documents-saved'


def _transaction(connection, expected, *, after_create=None, commit=None):
    """Apply the authoritative DDL with a locked snapshot and preservation checks."""
    migration = importlib.import_module('migrations.046_main_submission_schema')
    attempted_commit = False
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',) or connection.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Integrity or foreign-key check failed')
        if _snapshot(connection) != expected:
            raise ValueError('Database differs from independently restored backup')
        for table, column in (('users', 'user_id'), ('manuscripts', 'manuscript_id'),
                              ('schema_migrations', 'migration_id'), ('schema_migrations', 'applied_at')):
            if column not in {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}:
                raise ValueError('Required base schema is unavailable')
        existing = {name: connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() for name in migration.TABLES}
        old_ledger = set(connection.execute('SELECT migration_id, applied_at FROM schema_migrations'))
        old_ids = {row[0] for row in old_ledger}
        ids = set(migration.PRIOR_IDS + (migration.MIGRATION_ID,))
        if any(existing.values()) or ids & old_ids:
            raise ValueError('Migration already applied or partially present: inspect before proceeding')
        old_schema, old_rows = expected
        for index, (name, sql) in enumerate(migration.TABLES.items()):
            connection.execute(sql)
            if after_create:
                after_create(index, name)
        for identifier in migration.PRIOR_IDS + (migration.MIGRATION_ID,):
            connection.execute("INSERT INTO schema_migrations (migration_id, applied_at) VALUES (?, datetime('now'))", (identifier,))
        new_schema, new_rows = _snapshot(connection)
        if not set(old_schema).issubset(set(new_schema)) or any(new_rows.get(k) != v for k, v in old_rows.items() if k != 'schema_migrations'):
            raise ValueError('Pre-existing schema or records changed')
        ledger = set(connection.execute('SELECT migration_id, applied_at FROM schema_migrations'))
        if not old_ledger.issubset(ledger) or {row[0] for row in ledger} != old_ids | ids:
            raise ValueError('Migration ledger differs')
        if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',) or connection.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Post-migration integrity or foreign-key check failed')
        attempted_commit = True
        (commit or (lambda db: db.commit()))(connection)
    except Exception as exc:
        if attempted_commit:
            raise checks.OutcomeUncertain('Commit outcome uncertain: stop and inspect database, ledger and backup; do not retry') from exc
        connection.rollback()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--confirm-main', required=True)
    parser.add_argument('--confirm-offline', required=True)
    parser.add_argument('--storage-root', action='append', default=[])
    parser.add_argument('--backup', required=True)
    parser.add_argument('--restore', required=True)
    args = parser.parse_args(argv)
    try:
        validate_identity(args.project, args.database, args.confirm_main)
        if args.confirm_offline != OFFLINE:
            raise ValueError('Offline maintenance confirmation required')
        checks.validate(args.database, args.storage_root, args.backup, args.restore, args.confirm_main, project=MAIN_ROOT)
        expected = snapshot(Path(args.restore) / 'manuscript.db')
        _handles(Path(args.database))
        with closing(sqlite3.connect(Path(args.database).as_uri() + '?mode=rw', uri=True, timeout=0)) as db:
            _transaction(db, expected)
        try:
            checks._verify_isolated_after(Path(args.database), MAIN_ROOT, Path(args.backup), Path(args.restore))
        except Exception as exc:
            raise checks.OutcomeUncertain('Commit completed but post-verification failed: stop and inspect; do not retry') from exc
    except (ValueError, OSError, sqlite3.Error, checks.OutcomeUncertain) as exc:
        print(f'STOP: {exc}', file=sys.stderr)
        return 1
    print('Migration applied and verified. Maintain offline window until acceptance.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

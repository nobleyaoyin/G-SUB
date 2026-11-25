#!/usr/bin/env python3
"""Rehearse migration 038 in a private temporary workspace; NEVER deploy to Main.

This intentionally cannot target the project database. It is an operator-gated
rehearsal, not a production deployment or a workaround for migration 038's guard.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import pwd
import sqlite3
import stat
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = Path('/private/tmp').resolve(strict=True)
sys.path.insert(0, str(PROJECT_ROOT))
MIGRATIONS = [importlib.import_module('migrations.' + name) for name in (
    '022_eic_prospective_proof', '023_reviewer_candidate_intake',
    '024_reviewer_publication_audit', '038_candidate_preparation_provenance')]


def _private_file(path, directory):
    p = Path(path)
    if any(term in str(p).lower() for term in ('demo', 'upgrade-test', 'main-collaboration')):
        raise ValueError('Restricted environment path is not permitted')
    if not p.is_absolute() or p.parent != directory or p != p.resolve(strict=True):
        raise ValueError('File must be a canonical direct child of the private rehearsal directory')
    info = p.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('File must be private, regular, owned and not hard-linked')
    return p


def _schema_snapshot(db):
    objects = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    return objects, hashlib.sha256(json.dumps(objects, separators=(',', ':')).encode()).hexdigest()


def _snapshot(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',) or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Database integrity or foreign-key check failed')
        objects, schema = _schema_snapshot(db)
        migrations = db.execute('SELECT migration_id,applied_at FROM schema_migrations ORDER BY migration_id').fetchall()
        fingerprints = {}
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            quoted = '"' + table.replace('"', '""') + '"'
            rows = db.execute('SELECT * FROM ' + quoted).fetchall()
            hashes = sorted(hashlib.sha256(repr(row).encode()).hexdigest() for row in rows)
            fingerprints[table] = hashlib.sha256(''.join(hashes).encode()).hexdigest()
        return {'schema_sha256': schema, 'objects': objects, 'migrations': migrations, 'rows': fingerprints}


def _audit(directory, entry):
    path = directory / 'migration-038-audit.jsonl'
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise ValueError('Unsafe audit journal')
        data = (json.dumps(entry, sort_keys=True) + '\n').encode()
        if os.write(fd, data) != len(data):
            raise OSError('Incomplete audit record')
        os.fsync(fd)
    finally:
        os.close(fd)


def rehearse(*, workspace, target, backup, manifest, backup_sha256, operator, confirm_target, application_stopped):
    workspace = Path(workspace)
    if (not workspace.is_absolute() or not workspace.is_dir() or workspace != workspace.resolve(strict=True)
            or not workspace.is_relative_to(TEMP_ROOT) or workspace == TEMP_ROOT
            or workspace.is_relative_to(PROJECT_ROOT) or workspace.stat().st_uid != os.getuid()
            or stat.S_IMODE(workspace.stat().st_mode) & 0o077):
        raise ValueError('A private canonical temporary rehearsal workspace is required')
    event = {'operator': operator, 'target': str(target), 'backup': str(backup),
             'migration': MIGRATIONS[-1].MIGRATION_ID, 'time': datetime.now(timezone.utc).isoformat()}
    _audit(workspace, {**event, 'event': 'attempt'})
    try:
        if operator != pwd.getpwuid(os.getuid()).pw_name or not operator:
            raise ValueError('Operator must match the current local account')
        if not application_stopped or target != confirm_target:
            raise ValueError('Explicit stopped-writer and exact-target confirmations required')
        target = _private_file(target, workspace)
        backup = _private_file(backup, workspace)
        manifest = _private_file(manifest, workspace)
        if len({target, backup, manifest}) != 3 or target == PROJECT_ROOT / 'manuscript.db':
            raise ValueError('Distinct rehearsal target, backup and manifest required')
        for file in (target, backup):
            if any(Path(str(file) + suffix).exists() for suffix in ('-wal', '-journal')):
                raise ValueError('Database has an active or unreconciled journal')
        if hashlib.sha256(backup.read_bytes()).hexdigest() != backup_sha256:
            raise ValueError('Backup SHA-256 mismatch')
        plan = json.loads(manifest.read_text())
        if set(plan) != {'schema_sha256', 'migration_ids'} or not isinstance(plan['migration_ids'], list):
            raise ValueError('Invalid expected schema/history manifest')
        before = _snapshot(target)
        if before != _snapshot(backup):
            raise ValueError('Backup does not represent the exact target state')
        if plan['schema_sha256'] != before['schema_sha256'] or plan['migration_ids'] != [r[0] for r in before['migrations']]:
            raise ValueError('Unexpected target schema or migration history')
        if MIGRATIONS[-1].MIGRATION_ID in plan['migration_ids']:
            raise ValueError('Migration 038 is already applied')
        prerequisites = {'001_reviewer_file_bindings', '011_blind_review_policy',
                         '013_artifact_evidence', '019_personal_notes'}
        if not prerequisites.issubset(plan['migration_ids']):
            raise ValueError('Missing prerequisite migration')
        with sqlite3.connect(target.as_uri() + '?mode=ro', uri=True) as db:
            for migration in MIGRATIONS[:-1]:
                if migration.MIGRATION_ID not in plan['migration_ids']:
                    raise ValueError('Missing prerequisite migration')
                migration.validate_schema(db)
        _audit(workspace, {**event, 'event': 'preflight_passed', 'backup_sha256': backup_sha256,
                           'schema_sha256': before['schema_sha256'], 'migration_ids': plan['migration_ids']})
        MIGRATIONS[-1].migrate(target)  # Its original Main guard remains in force.
        after = _snapshot(target)
        with sqlite3.connect(target.as_uri() + '?mode=ro', uri=True) as db:
            for migration in MIGRATIONS:
                migration.validate_schema(db)
        before_objects = {item[1]: item for item in before['objects']}
        after_objects = {item[1]: item for item in after['objects']}
        if (any(after_objects.get(k) != v for k, v in before_objects.items())
                or set(after_objects) - set(before_objects) != set(MIGRATIONS[-1].DDL)
                or any(after['rows'].get(k) != v for k, v in before['rows'].items() if k != 'schema_migrations')
                or not set(before['migrations']).issubset(after['migrations'])
                or len(after['migrations']) != len(before['migrations']) + 1
                or MIGRATIONS[-1].MIGRATION_ID not in [r[0] for r in after['migrations']]):
            raise RuntimeError('Post-migration verification failed; stop for investigation')
        _audit(workspace, {**event, 'event': 'verified', 'result': 'success'})
        return 'verified'
    except Exception as exc:
        _audit(workspace, {**event, 'event': 'failed_or_unknown', 'error_type': type(exc).__name__})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('workspace', 'target', 'backup', 'manifest', 'backup-sha256', 'operator', 'confirm-target'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--confirm-application-stopped', action='store_true')
    args = parser.parse_args()
    try:
        print(rehearse(workspace=args.workspace, target=args.target, backup=args.backup, manifest=args.manifest,
                       backup_sha256=args.backup_sha256, operator=args.operator, confirm_target=args.confirm_target,
                       application_stopped=args.confirm_application_stopped))
    except Exception as exc:
        print(f'Rehearsal refused or failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

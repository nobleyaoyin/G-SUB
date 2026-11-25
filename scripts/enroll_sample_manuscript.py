"""Explicit local-operator enrollment of a new, empty development draft.

No public API, client-provided path, authentication bypass, or file upload.
Run with --help for the required confirmations.  The audit journal has an
intent and a final outcome; an interrupted operation is reconciled against
the authoritative registry row and its registration timestamp.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import importlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from uuid import uuid4

# Do not import application configuration in any non-development mode: doing
# so could otherwise inspect a separate environment before the CLI guard runs.
if os.environ.get('MANUSCRIPT_MODE') not in (None, 'development'):
    raise SystemExit('Sample enrollment is available only in development mode')

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.sample_storage import SampleStorage
from scripts.maintenance_participation import run_guarded

RESERVED_ID = 1000000001
AUDIT_NAME = '.gsub_sample_enrollment_audit.jsonl'


class EnrollmentError(Exception):
    pass


def _audit_fd(root: Path) -> int:
    if not root.is_absolute() or root.is_symlink() or root.resolve() != root:
        raise EnrollmentError('Unsafe development root')
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(AUDIT_NAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    finally:
        os.close(directory)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        raise EnrollmentError('Unsafe operator audit journal')
    return fd


def _record(fd: int, entry: dict) -> None:
    encoded = (json.dumps(entry, sort_keys=True, separators=(',', ':')) + '\n').encode()
    view = memoryview(encoded)
    while view:
        count = os.write(fd, view)
        if count <= 0:
            raise OSError('Audit journal write failed')
        view = view[count:]
    os.fsync(fd)


def _verify_storage(root: Path) -> SampleStorage:
    storage = SampleStorage(root / '.gsub_sample_storage', root / 'uploads')
    if storage.root != root / '.gsub_sample_storage':
        raise EnrollmentError('Unsafe sample storage root')
    # If the root already exists, check its ownership, permissions and type
    # using the same no-follow directory open used for sample files.
    if storage.root.exists():
        fd = storage._root_fd(False)
        os.close(fd)
    return storage


def _check_schema(db: sqlite3.Connection) -> None:
    migration = importlib.import_module('migrations.035_sample_document_storage')
    if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (migration.MIGRATION_ID,)).fetchone():
        raise EnrollmentError('Required sample registry migration is unavailable')
    for name, expected in migration.DDL.items():
        row = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        if not row or not row[0] or migration.normalize(row[0]) != migration.normalize(expected):
            raise EnrollmentError('Sample registry schema is incompatible')


def _check_unused_namespace(storage: SampleStorage, manuscript_id: int) -> None:
    """Do not adopt unreferenced objects left by any earlier operation."""
    if not storage.root.exists():
        return
    root_fd = storage._root_fd(False)
    try:
        try:
            manuscripts_fd = os.open('manuscripts', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        except FileNotFoundError:
            return
        try:
            try:
                os.stat(str(manuscript_id), dir_fd=manuscripts_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise EnrollmentError('Sample manuscript namespace already exists')
        finally:
            os.close(manuscripts_fd)
    finally:
        os.close(root_fd)


def _enroll(db_path: Path, root: Path, manuscript_id: int) -> dict:
    """Internal operation; CLI is the only supported entry point for Main."""
    if not isinstance(manuscript_id, int) or isinstance(manuscript_id, bool) or not 0 < manuscript_id < 10**18:
        raise EnrollmentError('Invalid manuscript ID')
    if manuscript_id == RESERVED_ID:
        raise EnrollmentError('Reserved manuscript cannot be enrolled')
    root = Path(root)
    if not root.is_absolute() or root.is_symlink() or root.resolve() != root:
        raise EnrollmentError('Unsafe development root')
    db_path = Path(db_path)
    if db_path != root / 'manuscript.db' or db_path.is_symlink() or not db_path.is_file():
        raise EnrollmentError('Unsafe development database')
    _verify_storage(root)
    fd = _audit_fd(root)
    attempt = uuid4().hex
    base = {'attempt_id': attempt, 'manuscript_id': manuscript_id,
            'operator_context': {'kind': 'local_os_uid', 'uid': os.geteuid()},
            'storage_namespace': f'sample:v1/manuscripts/{manuscript_id}/'}
    fcntl.flock(fd, fcntl.LOCK_EX)
    committed = False
    try:
        _record(fd, {**base, 'outcome': 'started', 'recorded_at': datetime.now(timezone.utc).isoformat()})
        with sqlite3.connect(db_path.as_uri() + '?mode=rw', uri=True) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            _check_schema(db)
            if db.execute('PRAGMA foreign_key_check').fetchone():
                raise EnrollmentError('Database foreign keys are inconsistent')
            row = db.execute('''SELECT m.author_id,m.status,m.file_path,m.review_round,u.role
                FROM manuscripts m LEFT JOIN users u ON u.user_id=m.author_id WHERE m.manuscript_id=?''', (manuscript_id,)).fetchone()
            if not row:
                raise EnrollmentError('Manuscript not found')
            author, status, file_path, review_round, role = row
            base['author_id'] = author
            if role != 'author':
                raise EnrollmentError('Author owner is unavailable')
            if status != 'draft' or file_path is not None or review_round != 1:
                raise EnrollmentError('Manuscript must be an empty first-round draft')
            if db.execute('SELECT 1 FROM sample_manuscripts WHERE manuscript_id=?', (manuscript_id,)).fetchone():
                raise EnrollmentError('Manuscript is already registered')
            # Fail closed for every installed manuscript-scoped table, including
            # future artifact/history tables. Linked rows require their parent
            # manuscript-scoped row, and foreign_key_check above rejects orphans.
            names = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            for (name,) in names:
                if name in ('manuscripts', 'sample_manuscripts'):
                    continue
                quoted = '"' + name.replace('"', '""') + '"'
                columns = [item[1] for item in db.execute('PRAGMA table_info(' + quoted + ')')]
                if 'manuscript_id' in columns and db.execute('SELECT 1 FROM ' + quoted + ' WHERE manuscript_id=? LIMIT 1', (manuscript_id,)).fetchone():
                    raise EnrollmentError('Manuscript has existing related records')
            storage = _verify_storage(root)
            _check_unused_namespace(storage, manuscript_id)
            timestamp = datetime.now(timezone.utc).isoformat()
            db.execute('INSERT INTO sample_manuscripts(manuscript_id,registered_at) VALUES (?,?)', (manuscript_id, timestamp))
            _record(fd, {**base, 'outcome': 'prepared', 'registered_at': timestamp,
                         'recorded_at': datetime.now(timezone.utc).isoformat()})
            db.commit()
            committed = True
        result = {**base, 'outcome': 'registered', 'registered_at': timestamp,
                  'recorded_at': datetime.now(timezone.utc).isoformat()}
        try:
            _record(fd, result)
        except OSError:
            # The durable prepared record and database timestamp allow recovery;
            # never report a rolled-back failure after the commit succeeded.
            result['audit_outcome'] = 'pending_reconciliation'
        return result
    except Exception:
        if not committed:
            try:
                _record(fd, {**base, 'outcome': 'rejected', 'recorded_at': datetime.now(timezone.utc).isoformat()})
            except OSError:
                pass
        raise
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manuscript-id', type=int, required=True)
    parser.add_argument('--confirm-main-development', action='store_true')
    parser.add_argument('--confirm-application-stopped', action='store_true',
                        help='Confirm all Main application writers are stopped during enrollment')
    parser.add_argument('--confirm-manuscript-id', type=int, required=True)
    args = parser.parse_args(argv)
    if (os.environ.get('MANUSCRIPT_MODE') != 'development' or not args.confirm_main_development
            or not args.confirm_application_stopped
            or args.confirm_manuscript_id != args.manuscript_id):
        parser.error('Explicit development mode, stopped application, and matching Main/manuscript confirmations are required')
    try:
        result = _enroll(PROJECT_ROOT / 'manuscript.db', PROJECT_ROOT, args.manuscript_id)
    except (EnrollmentError, OSError, sqlite3.Error, ValueError) as exc:
        print('Enrollment failed:', str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


def main(argv=None) -> int:
    return run_guarded(_main, argv)


if __name__ == '__main__':
    raise SystemExit(main())

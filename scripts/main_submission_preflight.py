"""Read-only migration evidence collection. Never migrates or authorizes migration."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
NEW_TABLES = ('author_submission_drafts', 'author_submission_links', 'author_submission_attachments',
              'manuscript_upload_names', 'manuscript_upload_requests', 'manuscript_submission_requests')


def _sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _open_database(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        raise ValueError('database must be an existing standalone file')
    # Avoid creating a shared-memory file on a live WAL database.
    if Path(str(path) + '-wal').exists() or Path(str(path) + '-shm').exists():
        raise ValueError('WAL/SHM present: coordinate writers and use an operator-reviewed snapshot')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    return db


def _handles(path):
    try:
        result = subprocess.run(['/usr/sbin/lsof', '-nP', '-Fpc', '--', str(path)], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('open-handle inspection unavailable') from exc
    if result.stderr.strip() or result.returncode not in (0, 1):
        raise ValueError('open-handle inspection incomplete')
    if result.returncode == 0 or result.stdout.strip():
        raise ValueError('database has open handles; coordinate all writers and readers')


def _snapshot(db):
    schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    fingerprints = {}
    for kind, name, _, _ in schema:
        if kind != 'table':
            continue
        escaped = name.replace('"', '""')
        rows = db.execute(f'SELECT * FROM "{escaped}"').fetchall()
        fingerprints[name] = (len(rows), hashlib.sha256(repr(sorted(map(repr, rows))).encode()).hexdigest())
    return schema, fingerprints


def _check_files(root, db, backup):
    for directory, manifest_name in (('uploads', 'upload-manifest.json'), ('.gsub_sample_storage', 'sample-storage-manifest.json')):
        current = root / directory
        if not current.is_dir() or current.is_symlink():
            raise ValueError('storage root missing or unsafe')
        archive = backup / directory
        if not archive.is_dir() or archive.is_symlink() or any(p.is_symlink() for p in archive.rglob('*')):
            raise ValueError('backup storage root missing or unsafe')
        manifest = json.loads((backup / manifest_name).read_text(encoding='utf-8'))
        files = [p for p in current.rglob('*') if p.is_file()]
        if any(p.is_symlink() for p in current.rglob('*')):
            raise ValueError('storage contains a symlink')
        if {str(p.relative_to(current)) for p in files} != set(manifest):
            raise ValueError('storage does not match backup manifest')
        if {str(p.relative_to(archive)) for p in archive.rglob('*') if p.is_file()} != set(manifest):
            raise ValueError('backup storage does not match manifest')
        for path in files:
            meta = manifest[str(path.relative_to(current))]
            if path.stat().st_size != meta['bytes'] or _sha(path) != meta['sha256']:
                raise ValueError('storage differs from backup manifest')
            archived = backup / directory / path.relative_to(current)
            if not archived.is_file() or archived.is_symlink() or _sha(archived) != meta['sha256']:
                raise ValueError('backup storage differs from manifest')
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        escaped = table.replace('"', '""')
        columns = [r[1] for r in db.execute(f'PRAGMA table_info("{escaped}")')]
        for column in (c for c in columns if c.endswith(('_path', 'storage_identity'))):
            col = column.replace('"', '""')
            digest_column = 'sha256' if 'sha256' in columns else None
            size_column = 'byte_size' if 'byte_size' in columns else None
            select = f'"{col}"' + (', "sha256"' if digest_column else ', NULL') + (', "byte_size"' if size_column else ', NULL')
            for value, digest, size in db.execute(f'SELECT {select} FROM "{escaped}" WHERE "{col}" IS NOT NULL'):
                if not isinstance(value, str):
                    raise ValueError('unrecognized storage reference')
                if value.startswith('sample:v1/'):
                    parts = value[len('sample:v1/'):].split('/')
                    base = root / '.gsub_sample_storage'
                elif value.startswith('uploads/'):
                    parts = value.split('/')[1:]
                    base = root / 'uploads'
                else:
                    raise ValueError('unrecognized storage reference')
                if not parts or any(part in ('', '.', '..') or '\\' in part for part in parts):
                    raise ValueError('unsafe storage reference')
                target = base.joinpath(*parts)
                if not target.is_file() or not target.resolve().is_relative_to(base.resolve()):
                    raise ValueError('referenced file missing or unsafe')
                if digest is not None and _sha(target) != digest:
                    raise ValueError('referenced file digest mismatch')
                if size is not None and target.stat().st_size != size:
                    raise ValueError('referenced file size mismatch')


def inspect(root, backup, *, handle_check=_handles):
    root = Path(root).resolve(); backup = Path(backup).resolve()
    if os.environ.get('MANUSCRIPT_MODE', 'development') != 'development':
        raise ValueError('runtime mode is not development')
    path = root / 'manuscript.db'; saved = backup / 'manuscript.db'
    handle_check(path)
    with closing(_open_database(path)) as db, closing(_open_database(saved)) as old:
        for connection in (db, old):
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or connection.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('database integrity or foreign-key check failed')
        if _snapshot(db) != _snapshot(old):
            raise ValueError('database differs from backup')
        schema, rows = _snapshot(db)
        existing = {row[1] for row in schema if row[0] == 'table'}
        if not {'users', 'manuscripts', 'schema_migrations', 'manuscript_submission_snapshots'}.issubset(existing):
            raise ValueError('required base schema missing')
        if existing.intersection(NEW_TABLES):
            raise ValueError('submission tables exist; inspect state manually')
        ledger = {row[0] for row in db.execute('SELECT migration_id FROM schema_migrations')}
        if any(v.startswith(('041_', '042_', '043_', '044_', '045_', '046_')) for v in ledger):
            raise ValueError('submission migration ledger conflicts')
        _check_files(root, db, backup)
        result = {'database': str(path), 'existing_tables': len(rows), 'users': rows['users'][0], 'manuscripts': rows['manuscripts'][0], 'migration_ledger_entries': len(ledger)}
    handle_check(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True, help='directory containing a freshly verified backup and manifests')
    args = parser.parse_args()
    try:
        result = inspect(PROJECT, args.backup)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print('PREFLIGHT FAILED:', str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    print('NOT READY: evidence alone cannot establish writer quiescence, a fresh independently verified backup, or an approved Main operator.')
    return 2


if __name__ == '__main__':
    sys.exit(main())

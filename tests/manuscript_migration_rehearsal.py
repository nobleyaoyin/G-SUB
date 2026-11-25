"""Rehearse additive migrations on an explicit read-only database snapshot."""
import hashlib
import importlib
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def counts(db):
    names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {name: db.execute('SELECT count(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0] for name in names}


def paths(db):
    rows = db.execute('SELECT manuscript_id, file_path FROM manuscripts ORDER BY manuscript_id').fetchall()
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def main(source):
    source = Path(source).resolve(strict=True)
    wal = Path(str(source) + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise RuntimeError('An active WAL requires a separately coordinated snapshot.')
    before_hash = checksum(source)
    with tempfile.TemporaryDirectory(prefix='gsub-migration-rehearsal-') as temporary:
        copy = Path(temporary) / 'copy.sqlite'
        with sqlite3.connect(source.as_uri() + '?mode=ro&immutable=1', uri=True) as reader:
            with sqlite3.connect(copy) as target:
                reader.backup(target)
        with sqlite3.connect(copy) as db:
            old_counts, old_paths = counts(db), paths(db)
            old_fk = len(db.execute('PRAGMA foreign_key_check').fetchall())
        for name in ('041_author_submission_drafts','042_author_submission_linkage','043_author_submission_attachments','044_manuscript_upload_names','045_manuscript_upload_requests'):
            migration = importlib.import_module('migrations.' + name)
            migration.migrate(copy)
            migration.migrate(copy)
        with sqlite3.connect(copy) as db:
            new_counts = counts(db)
            assert all(new_counts[name] == count for name, count in old_counts.items() if name != 'schema_migrations')
            assert paths(db) == old_paths
            assert len(db.execute('PRAGMA foreign_key_check').fetchall()) == old_fk == 0
        assert checksum(source) == before_hash
        print(f'PASS: disposable snapshot inventoried {len(old_counts)} existing tables, preserved non-ledger row counts and manuscript paths; migrations reapplied successfully; source checksum unchanged.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Supply one explicit read-only source database path.')
    main(sys.argv[1])

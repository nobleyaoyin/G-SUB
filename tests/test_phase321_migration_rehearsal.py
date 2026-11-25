"""Migration rehearsal using synthetic, disposable databases and files only."""
import importlib
import sqlite3

import pytest

from app import models
from tests import test_reviewer_download as fixtures

M044 = importlib.import_module('migrations.044_manuscript_upload_names')
M045 = importlib.import_module('migrations.045_manuscript_upload_requests')


@pytest.fixture
def legacy():
    case = fixtures.ReviewerDownloadsTest()
    case.setUp()
    try:
        for name in ('041_author_submission_drafts', '042_author_submission_linkage', '043_author_submission_attachments'):
            importlib.import_module('migrations.' + name).migrate(case.db_path)
        manuscript = models.Manuscript(title='Synthetic legacy', abstract='Synthetic abstract', author_id=case.author.user_id, status='draft', review_round=1)
        case.db.add(manuscript)
        case.db.commit()
        directory = case.root / 'uploads' / 'manuscripts' / str(manuscript.manuscript_id)
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / 'legacy.txt'
        source.write_bytes(b'synthetic legacy version')
        manuscript.file_path = str(source.relative_to(case.root))
        case.db.commit()
        yield case, manuscript.manuscript_id, source
    finally:
        case.tearDown()


def test_upgrade_and_repeat_preserve_legacy_records_and_bytes(legacy):
    case, mid, source = legacy
    with sqlite3.connect(case.db_path) as db:
        before = db.execute('SELECT manuscript_id, title, file_path FROM manuscripts WHERE manuscript_id=?', (mid,)).fetchone()
    for _ in range(2):
        M044.migrate(case.db_path)
        M045.migrate(case.db_path)
    with sqlite3.connect(case.db_path) as db:
        assert db.execute('SELECT manuscript_id, title, file_path FROM manuscripts WHERE manuscript_id=?', (mid,)).fetchone() == before
        assert db.execute('SELECT * FROM manuscript_upload_names WHERE manuscript_id=?', (mid,)).fetchall() == []
        assert db.execute('SELECT * FROM manuscript_upload_requests WHERE manuscript_id=?', (mid,)).fetchall() == []
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert len(db.execute("SELECT * FROM schema_migrations WHERE migration_id IN ('044_manuscript_upload_names','045_manuscript_upload_requests')").fetchall()) == 2
        assert len(db.execute('PRAGMA foreign_key_list(manuscript_upload_requests)').fetchall()) == 2
        assert any(row[2] for row in db.execute('PRAGMA index_list(manuscript_submission_requests)'))
    assert source.read_bytes() == b'synthetic legacy version'


def test_conflicting_ledger_rolls_back_without_marker_or_new_tables(legacy):
    case, _, source = legacy
    M044.migrate(case.db_path)
    with sqlite3.connect(case.db_path) as db:
        db.execute('CREATE TABLE manuscript_upload_requests (unexpected TEXT)')
    with pytest.raises(RuntimeError, match='Conflicting upload request schema'):
        M045.migrate(case.db_path)
    with sqlite3.connect(case.db_path) as db:
        assert not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='045_manuscript_upload_requests'").fetchone()
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='manuscript_submission_requests'").fetchone()
    assert source.read_bytes() == b'synthetic legacy version'


def test_dependency_and_missing_migration_ledger_fail_closed(tmp_path):
    dbpath = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(dbpath) as db:
        db.execute('CREATE TABLE schema_migrations (migration_id TEXT PRIMARY KEY, applied_at TEXT)')
    with pytest.raises(RuntimeError, match='Attachment migration required'):
        M044.migrate(dbpath)
    with pytest.raises(RuntimeError, match='Upload name migration required'):
        M045.migrate(dbpath)
    with sqlite3.connect(dbpath) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='manuscript_upload_names'").fetchone()
    missing = tmp_path / 'no-ledger.sqlite'
    sqlite3.connect(missing).close()
    with pytest.raises(sqlite3.OperationalError):
        M044.migrate(missing)

"""Isolated upload ledger tests; no persistent data or protected environments."""
import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from tests.test_reviewer_download import ReviewerDownloadsTest


@pytest.fixture
def isolated():
    case = ReviewerDownloadsTest()
    case.setUp()
    try:
        for name in ('041_author_submission_drafts', '042_author_submission_linkage', '043_author_submission_attachments', '044_manuscript_upload_names', '045_manuscript_upload_requests'):
            migration = importlib.import_module('migrations.' + name)
            migration.migrate(case.db_path)
            migration.migrate(case.db_path)
        manuscript = models.Manuscript(title='Synthetic', abstract='Synthetic', author_id=case.author.user_id, status='draft', review_round=1)
        case.db.add(manuscript)
        case.db.commit()
        case.mid = manuscript.manuscript_id
        case.current = case.author
        yield case
    finally:
        case.tearDown()


def upload(case, key, content=b'Private synthetic document'):
    return case.client.post(f'/manuscripts/{case.mid}/upload', data={'request_id': key}, files={'file': ('synthetic.txt', content, 'text/plain')})


def test_idempotent_retry_ownership_and_history(isolated):
    case = isolated
    key = str(uuid4())
    first = upload(case, key)
    assert first.status_code == 200, first.text
    receipt = case.client.get(f'/manuscripts/{case.mid}/upload-requests/{key}')
    assert receipt.status_code == 200 and receipt.json()['is_current']
    assert upload(case, key).status_code == 200
    assert upload(case, key, b'different content').status_code == 409
    assert len(case.client.get(f'/manuscripts/{case.mid}/versions').json()) == 1
    assert case.client.get(f'/manuscripts/{case.mid}/download').content == b'Private synthetic document'
    other = models.User(name='Other synthetic author', email='upload-other@example.com', password_hash='x', role='author')
    case.db.add(other);case.db.commit();case.current=other
    assert case.client.get(f'/manuscripts/{case.mid}/upload-requests/{key}').status_code == 404
    assert upload(case, key).status_code == 403
    case.current = case.reviewer
    assert case.client.get(f'/manuscripts/{case.mid}/upload-requests/{key}').status_code == 403


def test_commit_then_error_retains_confirmed_file(isolated):
    case = isolated
    key = str(uuid4())
    commit = Session.commit
    def commit_then_fail(session):
        commit(session)
        raise RuntimeError('synthetic uncertain commit')
    with patch.object(Session, 'commit', commit_then_fail):
        with pytest.raises(RuntimeError, match='synthetic uncertain commit'):
            upload(case, key)
    receipt = case.client.get(f'/manuscripts/{case.mid}/upload-requests/{key}')
    assert receipt.status_code == 200
    assert upload(case, key).status_code == 200
    versions = case.client.get(f'/manuscripts/{case.mid}/versions').json()
    assert len(versions) == 1 and versions[0]['original_filename'] == 'synthetic.txt'
    assert case.client.get(f'/manuscripts/{case.mid}/download').content == b'Private synthetic document'


def test_receipt_rejects_tampered_bytes(isolated):
    case = isolated
    key = str(uuid4())
    assert upload(case, key).status_code == 200
    manuscript = case.db.get(models.Manuscript, case.mid)
    (case.root / manuscript.file_path).write_bytes(b'tampered synthetic data')
    assert case.client.get(f'/manuscripts/{case.mid}/upload-requests/{key}').status_code == 409
    assert upload(case, key).status_code == 409


def test_concurrent_retry_commits_one_version(isolated):
    case = isolated
    def session_override():
        with case.Session() as session:
            yield session
    case.client.app.dependency_overrides[get_db] = session_override
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: upload(case, key), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    with case.Session() as db:
        assert db.execute(text('SELECT count(*) FROM manuscript_upload_requests WHERE request_id=:id'), {'id': key}).scalar_one() == 1
        manuscript = db.scalar(select(models.Manuscript).where(models.Manuscript.manuscript_id==case.mid))
        assert (case.root / manuscript.file_path).read_bytes() == b'Private synthetic document'
    assert len(case.client.get(f'/manuscripts/{case.mid}/versions').json()) == 1


def test_failed_insert_cleans_uncommitted_file(isolated):
    case = isolated
    execute = Session.execute
    def fail_ledger(session, statement, *args, **kwargs):
        if str(statement).startswith('INSERT INTO manuscript_upload_requests'):
            raise OperationalError('synthetic failure', {}, Exception('synthetic'))
        return execute(session, statement, *args, **kwargs)
    with patch.object(Session, 'execute', fail_ledger):
        with pytest.raises(OperationalError):
            upload(case, str(uuid4()))
    directory = case.root / 'uploads' / 'manuscripts' / str(case.mid)
    assert not list(directory.iterdir())
    assert case.db.execute(text('SELECT count(*) FROM manuscript_upload_requests')).scalar_one() == 0


def test_failed_file_publish_cleans_temporary_file(isolated):
    case = isolated
    with patch('app.routers.manuscripts.os.replace', side_effect=OSError('synthetic failure')):
        assert upload(case, str(uuid4())).status_code == 500
    directory = case.root / 'uploads' / 'manuscripts' / str(case.mid)
    assert not list(directory.iterdir())
    assert case.db.execute(text('SELECT count(*) FROM manuscript_upload_requests')).scalar_one() == 0


def test_legacy_upload_remains_available_without_request_ledger():
    case = ReviewerDownloadsTest()
    case.setUp()
    try:
        for name in ('041_author_submission_drafts','042_author_submission_linkage','043_author_submission_attachments','044_manuscript_upload_names'):
            importlib.import_module('migrations.' + name).migrate(case.db_path)
        manuscript = models.Manuscript(title='Synthetic', abstract='Synthetic', author_id=case.author.user_id, status='draft', review_round=1)
        case.db.add(manuscript);case.db.commit();case.mid=manuscript.manuscript_id;case.current=case.author
        assert case.client.get(f'/manuscripts/{case.mid}/upload-recovery').json() == {'available': False}
        assert upload(case, str(uuid4())).status_code == 503
        result=case.client.post(f'/manuscripts/{case.mid}/upload', files={'file': ('legacy.txt', b'legacy content', 'text/plain')})
        assert result.status_code == 200
    finally:
        case.tearDown()


def test_concurrent_submission_request_replays_one_transition(isolated):
    case = isolated
    case.db.add(models.User(name='Synthetic EIC', email='recovery-eic@example.com', password_hash='x', role='eic'))
    case.db.commit()
    assert upload(case, str(uuid4())).status_code == 200
    def session_override():
        with case.Session() as session:
            yield session
    case.client.app.dependency_overrides[get_db] = session_override
    request_id = str(uuid4())
    def submit(_):
        return case.client.post(f'/manuscripts/{case.mid}/submit', headers={'X-Submission-Request-ID': request_id})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(submit, range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert case.client.post(f'/manuscripts/{case.mid}/submit', headers={'X-Submission-Request-ID':str(uuid4())}).status_code == 409
    with case.Session() as db:
        assert db.get(models.Manuscript,case.mid).status == 'submitted'
        assert db.execute(text('SELECT count(*) FROM manuscript_submission_requests WHERE manuscript_id=:id'),{'id':case.mid}).scalar_one()==1
        assert db.execute(text('SELECT count(*) FROM manuscript_submission_snapshots WHERE manuscript_id=:id'),{'id':case.mid}).scalar_one()==1
        assert db.execute(text("SELECT count(*) FROM notifications WHERE manuscript_id=:id AND notification_type='manuscript_submitted'"),{'id':case.mid}).scalar_one()==1
        assert db.scalar(select(models.ManuscriptReviewPolicy).where(models.ManuscriptReviewPolicy.manuscript_id==case.mid)).minimum_completed_reviewers==2


def test_044_fails_closed_when_migration_ledger_is_missing(tmp_path):
    path = tmp_path / 'missing-ledger.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE manuscripts (manuscript_id INTEGER PRIMARY KEY)')
    with pytest.raises(sqlite3.OperationalError):
        importlib.import_module('migrations.044_manuscript_upload_names').migrate(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='manuscript_upload_names'").fetchone() is None


def test_045_rejects_conflicting_request_schema():
    case = ReviewerDownloadsTest();case.setUp()
    try:
        for name in ('041_author_submission_drafts','042_author_submission_linkage','043_author_submission_attachments','044_manuscript_upload_names'):
            importlib.import_module('migrations.' + name).migrate(case.db_path)
        case.db.execute(text('CREATE TABLE manuscript_upload_requests (unexpected TEXT)'));case.db.commit()
        with pytest.raises(RuntimeError, match='Conflicting upload request schema'):
            importlib.import_module('migrations.045_manuscript_upload_requests').migrate(case.db_path)
        assert case.db.execute(text('PRAGMA table_info(manuscript_upload_requests)')).first()[1] == 'unexpected'
    finally:
        case.tearDown()

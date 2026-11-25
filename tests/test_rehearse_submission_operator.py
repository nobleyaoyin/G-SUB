"""Operator rehearsal tests: only isolated copies and fresh temporary backups."""
import os
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import pytest
from scripts import rehearse_submission_operator as operator
from scripts.main_submission_preflight import _snapshot


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    source = os.environ.get('GSUB_MAIN_BACKUP_REHEARSAL')
    if not source:
        pytest.skip('explicit verified backup source not supplied')
    monkeypatch.setenv('MANUSCRIPT_MODE', 'development')
    original = Path(source).resolve().parent
    root = tmp_path / 'target'; backup = tmp_path / 'fresh-backup'
    root.mkdir(); backup.mkdir()
    for destination in (root / 'manuscript.db', backup / 'manuscript.db'):
        with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
    for name in ('uploads', '.gsub_sample_storage'):
        shutil.copytree(original/name, root/name)
        shutil.copytree(original/name, backup/name)
    for name in ('upload-manifest.json', 'sample-storage-manifest.json'):
        shutil.copy2(original/name, backup/name)
    return root, backup


def db_snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        return _snapshot(db)


def test_full_rehearsal_repeat_and_base_preservation(isolated):
    root, backup = isolated
    before_schema, before_rows = db_snapshot(root/'manuscript.db')
    assert operator.rehearse(root, backup) == 'applied'
    assert operator.rehearse(root, backup) == 'already applied'
    after_schema, after_rows = db_snapshot(root/'manuscript.db')
    assert all(after_rows[name] == value for name, value in before_rows.items() if name != 'schema_migrations')
    assert set(before_schema).issubset(set(after_schema))
    with closing(sqlite3.connect(root/'manuscript.db')) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_injected_failure_is_atomic_and_no_files_removed(isolated):
    root, backup = isolated
    before = db_snapshot(root/'manuscript.db')
    def fail(index, _name):
        if index == 2:
            raise RuntimeError('injected')
    with pytest.raises(RuntimeError, match='injected'):
        operator.rehearse(root, backup, _after_create=fail)
    assert db_snapshot(root/'manuscript.db') == before
    assert operator.rehearse(root, backup) == 'applied'


def test_fresh_backup_restores_to_separate_directory(isolated):
    from scripts.main_submission_preflight import inspect
    root, backup = isolated
    assert operator.rehearse(root, backup) == 'applied'
    restored = root.parent / 'restore-rehearsal'
    restored.mkdir()
    with closing(sqlite3.connect((backup/'manuscript.db').resolve().as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(restored/'manuscript.db')) as dst:
            src.backup(dst)
    for name in ('uploads', '.gsub_sample_storage'):
        shutil.copytree(backup/name, restored/name)
    assert inspect(restored, backup)['users'] > 0


def test_changed_storage_and_backup_fail_closed(isolated):
    root, backup = isolated
    file = next(p for p in (root/'uploads').rglob('*') if p.is_file())
    file.write_bytes(file.read_bytes() + b'synthetic mutation')
    before = db_snapshot(root/'manuscript.db')
    with pytest.raises(ValueError, match='storage differs'):
        operator.rehearse(root, backup)
    assert db_snapshot(root/'manuscript.db') == before


def test_main_and_overlapping_roots_are_rejected(isolated):
    root, backup = isolated
    with pytest.raises(ValueError, match='independent'):
        operator.rehearse(root, root)
    with pytest.raises(ValueError, match='disposable'):
        operator.rehearse(Path(__file__).resolve().parents[1], backup)


def test_busy_database_is_rejected_without_changes(isolated):
    root, backup = isolated
    before = db_snapshot(root/'manuscript.db')
    with closing(sqlite3.connect(root/'manuscript.db')) as active:
        active.execute('BEGIN IMMEDIATE')
        with pytest.raises(ValueError, match='open handles'):
            operator.rehearse(root, backup)
        active.rollback()
    assert db_snapshot(root/'manuscript.db') == before


def test_failed_post_commit_verification_requires_explicit_retry(isolated, monkeypatch):
    root, backup = isolated
    original = operator._already_applied
    def fail_verification(*_args):
        raise RuntimeError('injected post-commit verification failure')
    monkeypatch.setattr(operator, '_already_applied', fail_verification)
    with pytest.raises(RuntimeError, match='post-commit'):
        operator.rehearse(root, backup)
    with closing(sqlite3.connect(root/'manuscript.db')) as db:
        assert db.execute("SELECT count(*) FROM schema_migrations WHERE migration_id='046_main_submission_schema'").fetchone()[0] == 1
    monkeypatch.setattr(operator, '_already_applied', original)
    assert operator.rehearse(root, backup) == 'already applied'


def test_operator_then_draft_upload_and_submit_http(isolated, monkeypatch):
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import sessionmaker
    from app import models
    from app.database import get_db
    from app.routers import manuscripts
    from app.routers.users import get_current_user
    import app.main as main

    root, backup = isolated
    assert operator.rehearse(root, backup) == 'applied'
    engine = create_engine(f'sqlite:///{root / "manuscript.db"}', connect_args={'check_same_thread': False})
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session.begin() as db:
            author = models.User(name='Synthetic Author', email=f'{uuid4().hex}@example.com', password_hash='synthetic', role='author')
            db.add(author)
            db.flush()
            author_id = author.user_id
        def db_session():
            with Session() as db:
                yield db
        main.app.dependency_overrides[get_db] = db_session
        main.app.dependency_overrides[get_current_user] = lambda: author
        monkeypatch.setattr(main, 'engine', engine)
        monkeypatch.setattr(manuscripts, 'BASE_DIR', root)
        monkeypatch.setattr(manuscripts, 'AI_PRESCREENING_ENABLED', False)
        monkeypatch.setenv('GSUB_SUBMISSION_ATTACHMENT_ROOT', str(root / 'private-attachments'))
        with TestClient(main.app) as client:
            created = client.post('/author/submission-drafts', json={'request_id': str(uuid4())})
            assert created.status_code == 201, created.text
            draft = created.json()['id']
            payload = {'title': 'Synthetic operator rehearsal', 'abstract': 'Synthetic abstract for isolated testing.', 'submission_type': 'Review Article', 'keywords': ['synthetic'], 'corresponding_author': {'first_name':'Synthetic', 'last_name':'Author', 'email':'author@example.com', 'institutions':[{'name':'Synthetic institution','country':'Example'}]}, 'corresponding_author_position': 0}
            update = client.put(f'/author/submission-drafts/{draft}', json={'revision':0, 'current_step':10, 'payload':payload})
            assert update.status_code == 200, update.text
            assert any(item['id'] == draft for item in client.get('/author/submission-drafts').json())
            link = client.post(f'/author/submission-drafts/{draft}/link', json={'revision':1})
            assert link.status_code == 200, link.text
            mid = link.json()['manuscript_id']
            uploaded = client.post(f'/manuscripts/{mid}/upload', files={'file':('synthetic.txt', b'Synthetic manuscript content.\n', 'text/plain')})
            assert uploaded.status_code == 200, uploaded.text
            submitted = client.post(f'/manuscripts/{mid}/submit', headers={'X-Expected-Submission-Revision':'1'})
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()['status'] == 'submitted'
        with Session() as db:
            assert db.get(models.Manuscript, mid).author_id == author_id
            assert db.execute(text('SELECT count(*) FROM manuscript_submission_snapshots WHERE manuscript_id=:id'), {'id':mid}).scalar_one() == 1
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()

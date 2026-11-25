"""HTTP checks use a temporary database and sample root, never Main files."""
import importlib
import hashlib
import os
from pathlib import Path
import tempfile

os.environ.setdefault('SECRET_KEY', 'synthetic-sample-route-test-key-0000000000000000')

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Manuscript, User
from app.routers.users import get_current_user
from app.sample_storage import SampleStorage
from tests.test_secure_word_uploads import doc_bytes, docx_bytes


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    assert root.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert not root.is_relative_to(Path(__file__).resolve().parents[1])
    db_path = root / 'synthetic.sqlite'
    engine = create_engine(f'sqlite:///{db_path}', connect_args={'check_same_thread': False})
    @event.listens_for(engine, 'connect')
    def foreign_keys(conn, _):
        conn.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE schema_migrations (migration_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)'))
        conn.execute(text("INSERT INTO schema_migrations VALUES ('fixture',datetime('now'))"))
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        owner = User(name='Synthetic Author', email='author@example.com', role='author', password_hash='x')
        other = User(name='Other Author', email='other@example.com', role='author', password_hash='x')
        reviewer = User(name='Reviewer', email='reviewer@example.com', role='reviewer', password_hash='x')
        db.add_all([owner, other, reviewer]); db.flush()
        manuscript = Manuscript(title='Synthetic draft', abstract='A synthetic abstract.', author_id=owner.user_id, status='draft', review_round=1)
        db.add(manuscript); db.flush()
        mid = manuscript.manuscript_id
        ids = [owner.user_id, other.user_id, reviewer.user_id]
    migration = importlib.import_module('migrations.035_sample_document_storage')
    migration.migrate(db_path)
    migration.migrate(db_path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO sample_manuscripts VALUES (:mid,datetime('now'))"), {'mid': mid})
    storage = SampleStorage(root / 'samples', root / 'uploads')
    monkeypatch.setattr(SampleStorage, 'for_development', classmethod(lambda cls: storage))
    current = {'id': ids[0]}
    def get_session():
        with Session() as db:
            yield db
    def get_user():
        with Session() as db:
            return db.get(User, current['id'])
    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[get_current_user] = get_user
    yield TestClient(app), current, ids, mid, root, Session
    app.dependency_overrides.clear()
    engine.dispose()


def test_http_sample_upload_history_and_authorization(setup):
    client, current, ids, mid, root, Session = setup
    first = client.post(f'/manuscripts/{mid}/upload', files={'file': ('first.txt', b'First synthetic version', 'text/plain')})
    assert first.status_code == 200, first.text
    second = client.post(f'/manuscripts/{mid}/upload', files={'file': ('second.txt', b'Second synthetic version', 'text/plain')})
    assert second.status_code == 200, second.text
    assert first.json()['version_id'] != second.json()['version_id']
    assert 'file_path' not in first.json()
    history = client.get(f'/manuscripts/{mid}/versions')
    assert history.status_code == 200 and len(history.json()) == 2
    assert client.get(f'/manuscripts/{mid}/download').content == b'Second synthetic version'
    listing = client.get('/manuscripts/my')
    assert listing.status_code == 200
    visible = next(item for item in listing.json() if item['manuscript_id'] == mid)
    assert visible['has_pdf'] is True and visible['file_type'] == 'txt'
    assert client.get(f"/manuscripts/{mid}/versions/{first.json()['filename']}").content == b'First synthetic version'
    with Session() as db:
        row = db.get(Manuscript, mid)
        assert row.file_path.startswith('sample:v1/')
        assert db.execute(text('SELECT count(*) FROM sample_document_versions WHERE manuscript_id=:mid'), {'mid': mid}).scalar_one() == 2
        assert db.execute(text('SELECT sha256 FROM sample_document_versions WHERE version_id=:version'), {'version': first.json()['version_id']}).scalar_one() == hashlib.sha256(b'First synthetic version').hexdigest()
    assert not (root / 'uploads').exists()
    current['id'] = ids[1]
    assert client.get(f'/manuscripts/{mid}/download').status_code == 403
    assert client.post(f'/manuscripts/{mid}/upload', files={'file': ('x.txt', b'forged', 'text/plain')}).status_code == 403
    current['id'] = ids[2]
    assert client.get(f'/manuscripts/{mid}/versions').status_code == 403
    current['id'] = ids[0]
    assert client.post(f'/manuscripts/{mid}/submit').status_code == 503
    assert client.get(f'/manuscripts/{mid + 100}/versions/{first.json()["filename"]}').status_code == 404


def test_failed_database_update_retains_unreferenced_object_without_committing(setup):
    client, _, _, mid, root, Session = setup
    engine = Session.kw['bind']
    def fail_update(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith('UPDATE MANUSCRIPTS SET FILE_PATH'):
            raise RuntimeError('synthetic database failure')
    event.listen(engine, 'before_cursor_execute', fail_update)
    try:
        result = client.post(f'/manuscripts/{mid}/upload', files={'file': ('first.txt', b'Synthetic orphan', 'text/plain')})
        assert result.status_code == 503
    finally:
        event.remove(engine, 'before_cursor_execute', fail_update)
    with Session() as db:
        assert db.get(Manuscript, mid).file_path is None
        assert db.execute(text('SELECT count(*) FROM sample_document_versions')).scalar_one() == 0
    assert len(list((root / 'samples' / 'manuscripts' / str(mid)).iterdir())) == 1


def test_registered_sample_never_falls_back_to_a_legacy_reference(setup):
    client, _, _, mid, _, Session = setup
    # Deliberately corrupt a synthetic fixture reference; do not create a file.
    with Session.begin() as db:
        db.get(Manuscript, mid).file_path = f'uploads/manuscripts/{mid}/legacy.txt'
    assert client.get(f'/manuscripts/{mid}/download').status_code == 409


def test_registry_and_version_bindings_are_immutable(setup):
    client, _, _, mid, _, Session = setup
    result = client.post(f'/manuscripts/{mid}/upload', files={'file': ('first.txt', b'Protected version', 'text/plain')})
    assert result.status_code == 200
    with Session() as db:
        with pytest.raises(IntegrityError):
            db.execute(text('UPDATE sample_document_versions SET sha256=:value WHERE manuscript_id=:mid'), {'value': '0' * 64, 'mid': mid})
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(text('DELETE FROM sample_manuscripts WHERE manuscript_id=:mid'), {'mid': mid})
        db.rollback()


def test_reserved_sample_without_registration_fails_closed(setup):
    client, _, ids, _, root, Session = setup
    with Session.begin() as db:
        db.add(Manuscript(manuscript_id=1000000001, title='Reserved sample', abstract='Synthetic abstract',
                          author_id=ids[0], status='draft', review_round=1))
    response = client.post('/manuscripts/1000000001/upload', files={'file': ('x.txt', b'synthetic', 'text/plain')})
    assert response.status_code == 503
    assert not (root / 'uploads').exists()


@pytest.mark.parametrize('name,content', [('test.pdf',b'%PDF-synthetic'), ('test.docx',docx_bytes()), ('test.doc',doc_bytes()), ('test.txt',b'Synthetic manuscript')])
def test_http_supported_formats_and_malformed_denial(setup, name, content):
    client, _, _, mid, _, _ = setup
    response = client.post(f'/manuscripts/{mid}/upload', files={'file': (name, content, 'application/octet-stream')})
    assert response.status_code == 200, response.text
    assert client.get(f'/manuscripts/{mid}/download').content == content
    invalid = client.post(f'/manuscripts/{mid}/upload', files={'file': ('invalid.docx', b'not-a-docx', 'application/octet-stream')})
    assert invalid.status_code == 400

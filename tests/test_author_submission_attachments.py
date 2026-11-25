import importlib
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.models import Manuscript, User
from app.routers.author_submission_drafts import router as drafts
from app.routers.author_submission_attachments import router as attachments
from app.routers.users import get_current_user


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "attachments.db"
    store = tmp_path / "private"
    store.mkdir(mode=0o700)
    monkeypatch.setenv("GSUB_SUBMISSION_ATTACHMENT_ROOT", str(store))
    monkeypatch.setenv("GSUB_SUBMISSION_ATTACHMENT_FORMATS", "txt")
    monkeypatch.setenv("GSUB_SUBMISSION_ATTACHMENT_MAX_BYTES", "100")
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    User.__table__.create(engine)
    Manuscript.__table__.create(engine)
    with engine.begin() as conn:
        conn.execute(User.__table__.insert(), [{"user_id": 1, "name": "Author", "email": "a@example.invalid", "password_hash": "x", "role": "author"}, {"user_id": 2, "name": "Other", "email": "b@example.invalid", "password_hash": "x", "role": "author"}])
    for name in ("041_author_submission_drafts", "042_author_submission_linkage", "043_author_submission_attachments"):
        migration = importlib.import_module(f"migrations.{name}")
        migration.migrate(path)
        migration.migrate(path)
    sessions = sessionmaker(bind=engine)
    state = {"user": User(user_id=1, role="author")}
    app = FastAPI()
    app.include_router(drafts)
    app.include_router(attachments)

    def db_override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    with TestClient(app) as http:
        yield http, state, store, sessions
    engine.dispose()


def test_upload_replace_download_remove_preserves_versions_and_ownership(client):
    http, state, _, _ = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}/attachments"
    first = http.post(url, data={"kind": "cover_letter"}, files={"file": ("letter.txt", b"First version", "text/plain")})
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    assert http.get(f"{url}/{first_id}").content == b"First version"
    second = http.post(url, data={"kind": "cover_letter", "replaces": first_id}, files={"file": ("letter.txt", b"Second version", "text/plain")})
    assert second.status_code == 201
    second_id = second.json()["id"]
    assert http.get(f"{url}/{first_id}").content == b"First version"
    assert http.get(f"{url}/{second_id}").content == b"Second version"
    assert http.delete(f"{url}/{second_id}").status_code == 204
    assert http.get(f"{url}/{second_id}").content == b"Second version"
    assert len(http.get(url).json()) == 2
    state["user"] = User(user_id=2, role="author")
    assert http.get(url).status_code == 404
    assert http.get(f"{url}/{first_id}").status_code == 404
    assert http.delete(f"{url}/{second_id}").status_code == 404
    state["user"] = User(user_id=2, role="reviewer")
    assert http.get(f"{url}/{first_id}").status_code == 403


def test_private_store_rejects_insecure_permissions_and_symlink_ancestors(client, monkeypatch):
    http, _, store, _ = client
    draft_id = http.post('/author/submission-drafts', json={'request_id': str(uuid4())}).json()['id']
    url = f'/author/submission-drafts/{draft_id}/attachments'
    def upload():
        return http.post(url, data={'kind': 'supplementary'}, files={'file': ('item.txt', b'synthetic', 'text/plain')})
    first = upload()
    assert first.status_code == 201
    store.chmod(0o755)
    try:
        assert upload().status_code == 503
        assert http.get(f"{url}/{first.json()['id']}").status_code == 503
    finally:
        store.chmod(0o700)
    alias = store.parent / 'alias'
    alias.symlink_to(store, target_is_directory=True)
    monkeypatch.setenv('GSUB_SUBMISSION_ATTACHMENT_ROOT', str(alias))
    assert upload().status_code == 503
    monkeypatch.setenv('GSUB_SUBMISSION_ATTACHMENT_ROOT', str(store))
    assert http.get(f"{url}/{first.json()['id']}").content == b'synthetic'


def test_validation_and_tamper_detection(client, monkeypatch):
    http, _, store, _ = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}/attachments"
    assert http.post(url, data={"kind": "supplementary"}, files={"file": ("bad.pdf", b"bad", "application/pdf")}).status_code == 400
    monkeypatch.setenv("GSUB_SUBMISSION_ATTACHMENT_FORMATS", "txt,pdf")
    assert http.post(url, data={"kind": "supplementary"}, files={"file": ("bad.pdf", b"bad", "application/pdf")}).status_code == 400
    assert http.post(url, data={"kind": "supplementary"}, files={"file": ("large.txt", b"a" * 101, "text/plain")}).status_code == 413
    uploaded = http.post(url, data={"kind": "supplementary"}, files={"file": ("item.txt", b"valid", "text/plain")})
    assert uploaded.status_code == 201
    attachment_id = uploaded.json()["id"]
    (store / attachment_id).write_bytes(b"changed")
    assert http.get(f"{url}/{attachment_id}").status_code == 409
    monkeypatch.delenv("GSUB_SUBMISSION_ATTACHMENT_FORMATS")
    assert http.post(url, data={"kind": "supplementary"}, files={"file": ("other.txt", b"valid", "text/plain")}).status_code == 503


def test_submission_locks_attachment_mutations_and_multiple_supplements(client):
    http, _, _, sessions = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}/attachments"
    one = http.post(url, data={"kind": "supplementary"}, files={"file": ("one.txt", b"one", "text/plain")})
    two = http.post(url, data={"kind": "supplementary"}, files={"file": ("two.txt", b"two", "text/plain")})
    assert one.status_code == two.status_code == 201
    with sessions.begin() as db:
        manuscript = Manuscript(title="Synthetic", abstract="Synthetic", author_id=1, status="submitted", review_round=1)
        db.add(manuscript)
        db.flush()
        db.execute(text("INSERT INTO author_submission_links VALUES (:draft, :manuscript, 'now')"), {"draft": draft_id, "manuscript": manuscript.manuscript_id})
    assert http.delete(f"{url}/{one.json()['id']}").status_code == 409
    assert http.patch(f"/author/submission-drafts/{draft_id}", json={"revision": 0, "current_step": 2, "payload": {"title": "Changed"}}).status_code == 409
    assert http.post(url, data={"kind": "supplementary"}, files={"file": ("three.txt", b"three", "text/plain")}).status_code == 409
    assert http.get(f"{url}/{two.json()['id']}").content == b"two"


def test_reconciliation_reports_without_deleting_valid_or_unrecorded_files(client):
    from app.author_submission_attachment_reconciliation import reconcile
    http, _, store, sessions = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}/attachments"
    uploaded = http.post(url, data={"kind": "supplementary"}, files={"file": ("item.txt", b"valid", "text/plain")})
    recorded = uploaded.json()["id"]
    orphan = str(uuid4())
    (store / orphan).write_bytes(b"unrecorded")
    with sessions() as db:
        result = reconcile(db)
    assert result == {"unrecorded_file_ids": [orphan], "missing_file_ids": []}
    assert (store / orphan).read_bytes() == b"unrecorded"
    assert (store / recorded).read_bytes() == b"valid"


def test_concurrent_http_linkage_and_cross_account_denial(client):
    http, state, _, sessions = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}"
    assert http.put(url, json={"revision": 0, "current_step": 4, "payload": {"title": "Synthetic", "abstract": "Synthetic"}}).status_code == 200
    state["user"] = User(user_id=2, role="author")
    assert http.post(f"{url}/link", json={"revision": 1}).status_code == 404
    state["user"] = User(user_id=1, role="author")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: http.post(f"{url}/link", json={"revision": 1}), range(2)))
    assert all(item.status_code == 200 for item in responses)
    assert responses[0].json() == responses[1].json()
    with sessions() as db:
        assert db.query(Manuscript).count() == 1


def test_storage_failure_is_reported_without_recording_attachment(client):
    http, _, _, _ = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}/attachments"
    with patch("app.routers.author_submission_attachments.os.open", side_effect=OSError("synthetic failure")):
        result = http.post(url, data={"kind": "supplementary"}, files={"file": ("file.txt", b"valid", "text/plain")})
    assert result.status_code == 503
    assert http.get(url).json() == []


def test_upload_request_id_makes_retries_idempotent(client):
    http, _, _, _ = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}/attachments"
    key = str(uuid4())
    def upload(content):
        return http.post(url, data={"kind": "supplementary", "request_id": key}, files={"file": ("file.txt", content, "text/plain")})
    assert upload(b"same").status_code == 201
    assert upload(b"same").status_code == 200
    assert upload(b"different").status_code == 409
    assert len(http.get(url).json()) == 1
    another = str(uuid4())
    def concurrent_upload(_):
        return http.post(url, data={"kind": "supplementary", "request_id": another}, files={"file": ("two.txt", b"same", "text/plain")})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(concurrent_upload, range(2)))
    assert sorted(item.status_code for item in results) == [200, 201]
    assert len(http.get(url).json()) == 2


def test_uncertain_commit_retains_valid_file_and_retry_recovers(client):
    http, _, store, sessions = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}/attachments"
    key = str(uuid4())
    original_commit = Session.commit
    def commit_then_error(session):
        original_commit(session)
        raise RuntimeError("synthetic uncertain outcome")
    def upload():
        return http.post(url, data={"kind": "supplementary", "request_id": key}, files={"file": ("file.txt", b"valid", "text/plain")})
    with patch.object(Session, "commit", commit_then_error):
        with pytest.raises(RuntimeError, match="uncertain outcome"):
            upload()
    assert (store / key).read_bytes() == b"valid"
    from app.author_submission_attachment_reconciliation import reconcile
    with sessions() as db:
        assert reconcile(db) == {"unrecorded_file_ids": [], "missing_file_ids": []}
    assert upload().status_code == 200
    assert len(http.get(url).json()) == 1


def test_database_insert_failure_does_not_leave_record_or_file(client):
    http, _, store, _ = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}/attachments"
    key = str(uuid4())
    original_execute = Session.execute
    def fail_insert(session, statement, *args, **kwargs):
        if str(statement).startswith("INSERT INTO author_submission_attachments"):
            raise OperationalError("synthetic", {}, Exception("synthetic"))
        return original_execute(session, statement, *args, **kwargs)
    with patch.object(Session, "execute", fail_insert):
        result = http.post(url, data={"kind": "supplementary", "request_id": key}, files={"file": ("file.txt", b"valid", "text/plain")})
    assert result.status_code == 503
    assert not (store / key).exists()
    assert http.get(url).json() == []


def test_concurrent_replacement_keeps_one_active_and_old_bytes(client):
    http, _, _, _ = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}/attachments"
    original = http.post(url, data={"kind": "cover_letter"}, files={"file": ("old.txt", b"old", "text/plain")}).json()["id"]
    def replace(value):
        return http.post(url, data={"kind": "cover_letter", "replaces": original}, files={"file": ("new.txt", value, "text/plain")})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(replace, [b"first", b"second"]))
    assert sorted(item.status_code for item in results) == [201, 409]
    assert http.get(f"{url}/{original}").content == b"old"
    rows = http.get(url).json()
    assert len([row for row in rows if row["removed_at"] is None]) == 1


def test_failed_replacement_rolls_back_old_active_version(client):
    http, _, store, _ = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}/attachments"
    original = http.post(url, data={"kind": "cover_letter"}, files={"file": ("old.txt", b"old", "text/plain")}).json()["id"]
    replacement = str(uuid4())
    original_execute = Session.execute
    def fail_insert(session, statement, *args, **kwargs):
        if str(statement).startswith("INSERT INTO author_submission_attachments"):
            raise OperationalError("synthetic", {}, Exception("synthetic"))
        return original_execute(session, statement, *args, **kwargs)
    with patch.object(Session, "execute", fail_insert):
        result = http.post(url, data={"kind": "cover_letter", "replaces": original, "request_id": replacement}, files={"file": ("new.txt", b"new", "text/plain")})
    assert result.status_code == 503
    assert not (store / replacement).exists()
    assert http.get(f"{url}/{original}").content == b"old"
    assert http.get(url).json()[0]["removed_at"] is None


def test_missing_file_reconciliation_is_read_only_and_abandoned_draft_retained(client):
    from app.author_submission_attachment_reconciliation import reconcile
    http, _, store, sessions = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}/attachments"
    attachment_id = http.post(url, data={"kind": "supplementary"}, files={"file": ("item.txt", b"valid", "text/plain")}).json()["id"]
    displaced = store / "temporarily-displaced"
    (store / attachment_id).rename(displaced)
    assert http.get(f"{url}/{attachment_id}").status_code == 404
    with sessions() as db:
        assert attachment_id in reconcile(db)["missing_file_ids"]
    assert displaced.read_bytes() == b"valid"
    displaced.rename(store / attachment_id)
    assert http.get(f"{url}/{attachment_id}").content == b"valid"
    assert http.get(f"/author/submission-drafts/{draft_id}").status_code == 200

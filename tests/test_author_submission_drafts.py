import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.models import User
from app.routers.author_submission_drafts import router
from app.routers.users import get_current_user


@pytest.fixture
def client(tmp_path):
    database = tmp_path / "test.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY)")
        db.executemany("INSERT INTO users VALUES (?)", [(1,), (2,), (3,)])
    migration = importlib.import_module("migrations.041_author_submission_drafts")
    migration.migrate(database)
    migration.migrate(database)
    engine = create_engine(f"sqlite:///{database}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(router)
    state = {"user": User(user_id=1, role="author")}

    def db_override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    with TestClient(app) as test_client:
        yield test_client, state
    engine.dispose()


def test_create_resume_update_and_idempotency(client):
    http, _ = client
    request_id = str(uuid4())
    first = http.post("/author/submission-drafts", json={"request_id": request_id})
    assert first.status_code == 201
    draft = first.json()
    assert draft["payload"] == {} and draft["current_step"] == 1
    duplicate = http.post("/author/submission-drafts", json={"request_id": request_id})
    assert duplicate.status_code == 200 and duplicate.json()["id"] == draft["id"]
    payload = {"keywords": ["one", "two"], "coauthors": [{"first_name": "Example", "institutions": [{"name": "Institute"}]}]}
    saved = http.put(f"/author/submission-drafts/{draft['id']}", json={"revision": 0, "current_step": 8, "payload": payload})
    assert saved.status_code == 200 and saved.json()["revision"] == 1
    resumed = http.get(f"/author/submission-drafts/{draft['id']}")
    assert resumed.json()["payload"] == payload and resumed.json()["current_step"] == 8
    stale = http.put(f"/author/submission-drafts/{draft['id']}", json={"revision": 0, "current_step": 2, "payload": {}})
    assert stale.status_code == 409
    assert http.get(f"/author/submission-drafts/{draft['id']}").json()["payload"] == payload
    assert len(http.get("/author/submission-drafts").json()) == 1


def test_owner_and_role_isolation(client):
    http, state = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    state["user"] = User(user_id=2, role="author")
    assert http.get(f"/author/submission-drafts/{draft_id}").status_code == 404
    assert http.put(f"/author/submission-drafts/{draft_id}", json={"revision": 0, "current_step": 1, "payload": {}}).status_code == 404
    assert http.get("/author/submission-drafts").json() == []
    state["user"] = User(user_id=3, role="reviewer")
    assert http.get(f"/author/submission-drafts/{draft_id}").status_code == 403
    assert http.get("/author/submission-drafts").status_code == 403


def test_partial_update_preserves_nested_fields_and_detects_stale_revision(client):
    http, _ = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}"
    original = {"keywords": ["alpha", "beta"], "corresponding_author": {"first_name": "A", "last_name": "B", "institutions": [{"name": "First"}, {"name": "Second"}]}}
    assert http.put(url, json={"revision": 0, "current_step": 7, "payload": original}).status_code == 200
    patch = {"revision": 1, "current_step": 7, "payload": {"corresponding_author": {"first_name": "Changed"}}}
    changed = http.patch(url, json=patch)
    assert changed.status_code == 200
    assert changed.json()["payload"]["keywords"] == original["keywords"]
    assert changed.json()["payload"]["corresponding_author"] == {**original["corresponding_author"], "first_name": "Changed"}
    assert http.patch(url, json=patch).status_code == 409
    assert http.get(url).json()["revision"] == 2


def test_configuration_defaults_and_administrator_override(client, monkeypatch):
    http, _ = client
    monkeypatch.delenv("GSUB_SUBMISSION_TYPES", raising=False)
    assert http.get("/author/submission-drafts/configuration").json() == {"submission_types": ["Original Research Article", "Review Article", "Short Communication", "Case Report", "Methods / Technical Note", "Perspective / Commentary", "Letter to the Editor"]}
    monkeypatch.setenv("GSUB_SUBMISSION_TYPES", "Configured one, Configured two,Configured one")
    assert http.get("/author/submission-drafts/configuration").json() == {"submission_types": ["Configured one", "Configured two"]}
    monkeypatch.setenv("GSUB_SUBMISSION_TYPES", "")
    assert http.get("/author/submission-drafts/configuration").json() == {"submission_types": []}


def test_submission_type_persists_can_be_edited_and_rejects_unsupported(client, monkeypatch):
    http, _ = client
    monkeypatch.delenv("GSUB_SUBMISSION_TYPES", raising=False)
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]
    url = f"/author/submission-drafts/{draft_id}"
    assert http.put(url, json={"revision": 0, "current_step": 2, "payload": {"submission_type": "Unsupported"}}).status_code == 422
    saved = http.put(url, json={"revision": 0, "current_step": 2, "payload": {"submission_type": "Review Article"}})
    assert saved.status_code == 200
    assert http.get(url).json()["payload"]["submission_type"] == "Review Article"
    updated = http.put(url, json={"revision": 1, "current_step": 2, "payload": {"submission_type": "Case Report"}})
    assert updated.status_code == 200
    monkeypatch.setenv("GSUB_SUBMISSION_TYPES", "Original Research Article")
    assert http.put(url, json={"revision": 2, "current_step": 3, "payload": {"submission_type": "Case Report", "title": "Draft"}}).status_code == 200
    assert http.put(url, json={"revision": 3, "current_step": 2, "payload": {"submission_type": "Original Research Article"}}).status_code == 200


def test_input_validation_and_private_response_headers(client):
    http, _ = client
    missing = http.post("/author/submission-drafts", json={})
    assert missing.status_code == 422
    assert missing.json()["detail"]["errors"][0]["step"] == 1
    assert missing.json()["detail"]["errors"][0]["field"] == "request_id"
    created = http.post("/author/submission-drafts", json={"request_id": str(uuid4())})
    assert created.headers["cache-control"] == "no-store"
    draft_id = created.json()["id"]
    assert http.put(f"/author/submission-drafts/{draft_id}", json={"revision": 0, "current_step": 11, "payload": {}}).status_code == 422
    invalid = http.put(f"/author/submission-drafts/{draft_id}", json={"revision": 0, "current_step": 10, "payload": {"manuscript_information": {"figures": -1}}})
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["errors"][0]["step"] == 10
    assert invalid.json()["detail"]["errors"][0]["field"] == "manuscript_information.figures"
    assert http.put(f"/author/submission-drafts/{draft_id}", json={"revision": 0, "current_step": 1, "payload": {"unrecognized": "value"}}).status_code == 422
    assert http.put(f"/author/submission-drafts/{draft_id}", json={"revision": 0, "current_step": 1, "payload": {"abstract": "a" * (1024 * 1024)}}).status_code == 413
    assert http.get(f"/author/submission-drafts/{draft_id}").json()["revision"] == 0


@pytest.mark.parametrize('payload,step,field', [
    ({'submission_type': 'Unsupported'}, 2, 'submission_type'),
    ({'corresponding_author': {'institutions': 'invalid'}}, 7, 'corresponding_author.institutions'),
    ({'coauthors': 'invalid'}, 8, 'coauthors'),
    ({'funding': 'invalid'}, 10, 'funding'),
])
def test_draft_validation_identifies_step_and_field(client, payload, step, field):
    http, _ = client
    draft = http.post('/author/submission-drafts', json={'request_id': str(uuid4())}).json()['id']
    result = http.patch(f'/author/submission-drafts/{draft}', json={'revision': 0, 'current_step': step, 'payload': payload})
    assert result.status_code == 422
    assert result.json()['detail']['errors'][0]['step'] == step
    assert result.json()['detail']['errors'][0]['field'] == field


def test_migration_rejects_conflicting_existing_table(tmp_path):
    database = tmp_path / "conflict.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE author_submission_drafts (id TEXT PRIMARY KEY)")
    migration = importlib.import_module("migrations.041_author_submission_drafts")
    with pytest.raises(RuntimeError, match="Conflicting"):
        migration.migrate(database)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone() is None


def test_concurrent_saves_do_not_overwrite_each_other(client):
    http, _ = client
    draft_id = http.post("/author/submission-drafts", json={"request_id": str(uuid4())}).json()["id"]

    def save(title):
        return http.put(f"/author/submission-drafts/{draft_id}", json={"revision": 0, "current_step": 3, "payload": {"title": title}})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["First version", "Second version"]))
    assert sorted(result.status_code for result in results) == [200, 409]
    saved = http.get(f"/author/submission-drafts/{draft_id}").json()
    assert saved["revision"] == 1
    assert saved["payload"]["title"] == next(result.json()["payload"]["title"] for result in results if result.status_code == 200)

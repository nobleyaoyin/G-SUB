"""Request limits and access behavior for the stage-dialogue route wrapper."""
import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.requests import Request

from app.routers import stage_dialogue
from app.routers.stage_dialogue import NoStoreRoute


class Payload(BaseModel):
    body: str


def authorized(x_test_role: str = Header(default="")):
    if x_test_role != "authorized":
        raise HTTPException(403, "Not authorized")


def make_app(*, return_router=False):
    app = FastAPI()
    router = APIRouter(route_class=NoStoreRoute)

    @router.post("/dialogue", dependencies=[Depends(authorized)])
    async def post(payload: Payload):
        return {"body": payload.body}

    app.include_router(router)
    return (app, router) if return_router else app


def test_allowed_json_body_is_preserved_and_no_store():
    client = TestClient(make_app())
    result = client.post("/dialogue", json={"body": "synthetic message"},
                         headers={"X-Test-Role": "authorized"})
    assert result.status_code == 200
    assert result.json() == {"body": "synthetic message"}
    assert result.headers["cache-control"] == "no-store"


def test_role_denial_and_validation_are_preserved():
    client = TestClient(make_app())
    denied = client.post("/dialogue", json={"body": "synthetic message"})
    assert denied.status_code == 403
    assert denied.headers["cache-control"] == "no-store"
    invalid = client.post("/dialogue", json={}, headers={"X-Test-Role": "authorized"})
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "no-store"


def test_declared_oversize_is_rejected_with_no_store():
    client = TestClient(make_app())
    result = client.post("/dialogue", content=b"{}", headers={
        "X-Test-Role": "authorized", "Content-Length": "32769",
    })
    assert result.status_code == 413
    assert result.headers["cache-control"] == "no-store"


def test_exact_limit_is_accepted():
    client = TestClient(make_app())
    content = b'{"body":"ok"}' + b' ' * (32768 - len(b'{"body":"ok"}'))
    result = client.post("/dialogue", content=content, headers={
        "X-Test-Role": "authorized", "Content-Type": "application/json",
    })
    assert result.status_code == 200
    assert result.json() == {"body": "ok"}
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("length,expected", [("-1", 413), ("not-a-number", 400)])
def test_invalid_declared_length_fails_closed(length, expected):
    client = TestClient(make_app())
    result = client.post("/dialogue", content=b"{}", headers={
        "X-Test-Role": "authorized", "Content-Length": length,
    })
    assert result.status_code == expected
    assert result.headers["cache-control"] == "no-store"


def test_stream_stops_when_actual_size_exceeds_limit():
    _, router = make_app(return_router=True)
    route = next(route for route in router.routes if getattr(route, "path", None) == "/dialogue")
    handler = route.get_route_handler()
    chunks = [b"a" * 16384, b"b" * 16385, b"unread"]
    received = []

    async def receive():
        index = len(received)
        received.append(index)
        return {"type": "http.request", "body": chunks[index], "more_body": True}

    scope = {"type": "http", "method": "POST", "path": "/dialogue", "headers": []}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(Request(scope, receive)))
    assert exc.value.status_code == 413
    assert exc.value.headers["Cache-Control"] == "no-store"
    assert received == [0, 1]


@pytest.fixture
def synthetic_dialogue(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE users (user_id INTEGER PRIMARY KEY, role TEXT);
        CREATE TABLE manuscripts (manuscript_id INTEGER PRIMARY KEY, author_id INTEGER);
        CREATE TABLE initial_editor_invitations (
            invitation_id INTEGER PRIMARY KEY, manuscript_id INTEGER,
            editor_id INTEGER, invited_by INTEGER, status TEXT
        );
        CREATE TABLE stage_dialogue_threads (
            thread_id TEXT, manuscript_id INTEGER, stage TEXT, round_kind TEXT,
            review_round INTEGER, agreement_id INTEGER, decision_id INTEGER,
            invitation_kind TEXT, invitation_id INTEGER, author_id INTEGER,
            editor_id INTEGER, eic_id INTEGER, created_by INTEGER, created_at TEXT
        );
        INSERT INTO users VALUES (1, 'author'), (2, 'editor'), (3, 'eic'),
                                 (4, 'reviewer'), (5, 'author');
        INSERT INTO manuscripts VALUES (10, 1);
        INSERT INTO initial_editor_invitations VALUES (20, 10, 2, 3, 'accepted');
        INSERT INTO stage_dialogue_threads VALUES (
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 10, 'initial_editing', 'initial',
            1, NULL, NULL, 'initial', 20, 1, 2, 3, 1, 'synthetic'
        );
    """)
    monkeypatch.setattr(stage_dialogue, "resolve", lambda *args: ("initial", 1, None, None))
    yield db
    db.close()


@pytest.mark.parametrize("user_id", [1, 2, 3])
def test_current_author_editor_and_inviting_eic_are_in_audience(synthetic_dialogue, user_id):
    result = stage_dialogue._context(synthetic_dialogue, 10, "initial_editing", user_id)
    assert result[2:5] == (1, 2, 3)


@pytest.mark.parametrize("user_id", [4, 5])
def test_reviewer_and_other_author_cannot_access_audience(synthetic_dialogue, user_id):
    with pytest.raises(HTTPException) as exc:
        stage_dialogue._context(synthetic_dialogue, 10, "initial_editing", user_id)
    assert exc.value.status_code == 403


def test_reviewer_cannot_read_thread(synthetic_dialogue):
    reviewer = SimpleNamespace(user_id=4, role="reviewer")
    with pytest.raises(HTTPException) as exc:
        stage_dialogue._thread(synthetic_dialogue, 10, "a" * 32, reviewer)
    assert exc.value.status_code == 404


def test_revoked_editor_cannot_read_historical_thread(synthetic_dialogue, monkeypatch):
    monkeypatch.setattr(stage_dialogue, "is_revoked_raw", lambda *_: True)
    editor = SimpleNamespace(user_id=2, role="editor")
    with pytest.raises(HTTPException) as exc:
        stage_dialogue._thread(synthetic_dialogue, 10, "a" * 32, editor)
    assert exc.value.status_code == 403


def test_author_can_read_historical_thread_after_revocation(synthetic_dialogue, monkeypatch):
    monkeypatch.setattr(stage_dialogue, "is_revoked_raw", lambda *_: True)
    author = SimpleNamespace(user_id=1, role="author")
    assert stage_dialogue._thread(synthetic_dialogue, 10, "a" * 32, author)[9] == 1

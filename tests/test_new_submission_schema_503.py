"""Reproduce the draft 503 and check the existing repair on a disposable copy."""
import importlib
import os
from pathlib import Path
import sqlite3
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


def test_missing_schema_503_then_existing_schema_repairs_drafts(tmp_path, caplog):
    configured = os.environ.get('GSUB_MAIN_BACKUP_REHEARSAL')
    if not configured:
        pytest.skip('Explicit verified backup source is required')
    source = Path(configured).resolve(strict=True)
    assert source != (Path(__file__).resolve().parents[1] / 'manuscript.db').resolve()
    database = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as old:
        with sqlite3.connect(database) as new:
            old.backup(new)
    engine = create_engine(f'sqlite:///{database}', connect_args={'check_same_thread': False})
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with sessions.begin() as db:
            author = User(name='Synthetic Author', email=f'{uuid4().hex}@example.com', password_hash='synthetic', role='author')
            db.add(author)
            db.flush()
            author_id = author.user_id
        app = FastAPI()
        app.include_router(router)
        def session():
            with sessions() as db:
                yield db
        app.dependency_overrides[get_db] = session
        app.dependency_overrides[get_current_user] = lambda: User(user_id=author_id, role='author')
        with TestClient(app) as client:
            assert client.get('/author/submission-drafts/configuration').status_code == 200
            assert client.get('/author/submission-drafts/requirements').status_code == 200
            listing = client.get('/author/submission-drafts')
            assert listing.status_code == 503
            assert 'no such table: author_submission_drafts' in caplog.text
            assert client.post('/author/submission-drafts', json={'request_id': str(uuid4())}).status_code == 503
            assert 'no such table' not in listing.text

            # The authoritative migration retains its temporary-only guard.
            migration = importlib.import_module('migrations.046_main_submission_schema')
            assert migration.migrate(database) == 'applied'
            created = client.post('/author/submission-drafts', json={'request_id': str(uuid4())})
            assert created.status_code == 201
            draft = created.json()['id']
            saved = client.put(f'/author/submission-drafts/{draft}', json={
                'revision': 0, 'current_step': 3, 'payload': {'title': 'Synthetic draft'}
            })
            assert saved.status_code == 200
            resumed = client.get(f'/author/submission-drafts/{draft}')
            assert resumed.status_code == 200
            assert resumed.json()['current_step'] == 3
            assert resumed.json()['payload']['title'] == 'Synthetic draft'
            assert any(row['id'] == draft for row in client.get('/author/submission-drafts').json())
    finally:
        engine.dispose()

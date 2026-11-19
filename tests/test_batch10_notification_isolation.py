"""Synthetic migration-free HTTP check of notification ownership."""
from datetime import datetime, timezone

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, engine as configured_engine, get_db
from app.routers.notifications import router
from app.routers.users import get_current_user


def test_notification_reads_and_updates_are_scoped_to_owner(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Configured database access is forbidden')
    monkeypatch.setattr(configured_engine, 'connect', deny)
    monkeypatch.setattr(configured_engine, 'raw_connection', deny)
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[models.User.__table__, models.Manuscript.__table__, models.Notification.__table__])
    with Session(engine) as db:
        db.add_all([models.User(user_id=i,name=f'Synthetic {i}',email=f'{i}@example.invalid',password_hash='x',role='author') for i in (1,2)])
        db.add_all([models.Notification(notification_id=i,user_id=i,notification_type='synthetic',message=f'Notice {i}',is_read=False,created_at=datetime.now(timezone.utc)) for i in (1,2)])
        db.commit()
    app=FastAPI(); app.include_router(router)
    def test_db():
        with Session(engine) as db:
            yield db
    def test_actor(x_synthetic_user: int = Header()):
        return models.User(user_id=x_synthetic_user,role='author')
    app.dependency_overrides[get_db]=test_db
    app.dependency_overrides[get_current_user]=test_actor
    with TestClient(app) as client:
        one={'X-Synthetic-User':'1'}; two={'X-Synthetic-User':'2'}
        assert [n['message'] for n in client.get('/notifications/my',headers=one).json()] == ['Notice 1']
        assert [n['message'] for n in client.get('/notifications/my',headers=two).json()] == ['Notice 2']
        assert client.patch('/notifications/2/read',headers=one).status_code == 403
        assert client.get('/notifications/unread-count',headers=two).json() == {'unread_count':1}
        assert client.patch('/notifications/2/read',headers=two).status_code == 200
        assert client.get('/notifications/unread-count',headers=two).json() == {'unread_count':0}
        assert client.get('/notifications/unread-count',headers=one).json() == {'unread_count':1}
    engine.dispose()

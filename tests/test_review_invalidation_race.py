"""Serialize existing invalidations with review submission, using isolated fixtures."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from tests import test_lifecycle_security_review as fixture
from app.routers import reviews


def test_review_write_lock_excludes_concurrent_invalidation():
    case = fixture.RouteSecurityReview('test_preexisting_invalidation_denies_an_accepted_assignment')
    case.setUp()
    try:
        fx = case.fx
        invited = fx.invite(); assert invited.status_code == 201
        aid = invited.json()['assignment_id']
        fx.actor = SimpleNamespace(user_id=fx.ids['Reviewer'], role='reviewer', name='Reviewer')
        assert fx.client.post(f'/assignments/{aid}/invitation-response', json={'decision':'accept'}).status_code == 200
        entered, resume = Event(), Event()
        original = reviews.may_review
        def paused(*args):
            entered.set()
            assert resume.wait(8)
            return original(*args)
        def submit():
            return fx.client.post('/reviews/', json={'assignment_id':aid, 'comments':'Synthetic', 'recommendation':'accept'})
        with patch.object(reviews, 'may_review', side_effect=paused), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(submit)
            try:
                assert entered.wait(8)
                with sqlite3.connect(fx.path, timeout=.1) as db:
                    db.execute('PRAGMA foreign_keys=ON')
                    with pytest.raises(sqlite3.OperationalError, match='locked'):
                        db.execute("INSERT INTO reviewer_invitation_invalidations VALUES ('race-synthetic',?,'cancelled',NULL,?,?,'editorial_cancellation')", (aid, fx.ids['Eic'], fixture.STAMP))
            finally:
                resume.set()
            assert future.result(timeout=8).status_code == 201
        with sqlite3.connect(fx.path) as db:
            assert db.execute('SELECT count(*) FROM reviews WHERE assignment_id=?', (aid,)).fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM reviewer_invitation_invalidations WHERE assignment_id=?', (aid,)).fetchone()[0] == 0
            assert db.execute('SELECT status FROM review_assignments WHERE assignment_id=?', (aid,)).fetchone()[0] == 'completed'
    finally:
        case.doCleanups()


def test_invalidation_committed_first_denies_submission():
    case = fixture.RouteSecurityReview('test_preexisting_invalidation_denies_an_accepted_assignment')
    case.setUp()
    try:
        case.test_preexisting_invalidation_denies_an_accepted_assignment()
    finally:
        case.doCleanups()

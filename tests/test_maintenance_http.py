"""Isolated process tests of HTTP participation; not proof of global exclusion."""
import multiprocessing
import os
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.maintenance_barrier import MaintenanceActive, MaintenanceBarrier
from app.maintenance_http import MaintenanceHTTPMiddleware


def application(root, started=None, release=None):
    app = FastAPI()
    app.add_middleware(MaintenanceHTTPMiddleware)

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.post('/upload')
    def upload():
        if started is not None:
            started.set()
            if not release.wait(10):
                raise RuntimeError('test timed out')
        Path(root, 'document').write_bytes(b'synthetic')
        with sqlite3.connect(Path(root, 'test.db')) as db:
            db.execute('INSERT INTO writes VALUES (1)')
        return {'ok': True}

    @app.post('/onlyoffice/callbacks/session')
    def callback():
        Path(root, 'callback').write_bytes(b'callback')
        return {'error': 0}

    return app


def worker(root, lock, out, started=None, release=None):
    os.environ['GSUB_MAINTENANCE_ROOT'] = lock
    with TestClient(application(root, started, release)) as client:
        out.put((client.post('/upload').status_code,
                 client.post('/onlyoffice/callbacks/session').json(),
                 client.get('/health').status_code))


def test_two_processes_drain_block_and_resume(tmp_path):
    lock = tmp_path / 'lock'
    lock.mkdir(mode=0o700)
    with sqlite3.connect(tmp_path / 'test.db') as db:
        db.execute('CREATE TABLE writes (value INTEGER)')
    ctx = multiprocessing.get_context('spawn')
    started, release = ctx.Event(), ctx.Event()
    queue = ctx.Queue()
    first = ctx.Process(target=worker, args=(str(tmp_path), str(lock), queue, started, release))
    first.start()
    maintenance_entered = threading.Event()
    maintenance_release = threading.Event()

    def maintain():
        with MaintenanceBarrier(lock).maintenance():
            maintenance_entered.set()
            assert maintenance_release.wait(15)

    thread = threading.Thread(target=maintain)
    try:
        assert started.wait(10)
        thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with MaintenanceBarrier(lock).operation():
                    pass
            except MaintenanceActive:
                break
            time.sleep(.02)
        else:
            raise AssertionError('maintenance flag not set')
        assert not maintenance_entered.is_set()
        second = ctx.Process(target=worker, args=(str(tmp_path), str(lock), queue))
        second.start()
        second.join(10)
        assert second.exitcode == 0
        assert queue.get(timeout=2) == (503, {'error': 1}, 200)
        assert not (tmp_path / 'document').exists()
        release.set()
        assert maintenance_entered.wait(10)
        first.join(10)
        assert first.exitcode == 0
        assert queue.get(timeout=2) == (200, {'error': 1}, 200)
        assert (tmp_path / 'document').read_bytes() == b'synthetic'
        assert not (tmp_path / 'callback').exists()
        with sqlite3.connect(tmp_path / 'test.db') as db:
            assert db.execute('SELECT count(*) FROM writes').fetchone()[0] == 1
        maintenance_release.set()
        thread.join(10)
        restarted = ctx.Process(target=worker, args=(str(tmp_path), str(lock), queue))
        restarted.start()
        restarted.join(10)
        assert restarted.exitcode == 0
        assert queue.get(timeout=2) == (200, {'error': 0}, 200)
    finally:
        release.set()
        maintenance_release.set()
        if thread.ident:
            thread.join(15)
        first.join(15)


def test_invalid_lock_directory_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv('GSUB_MAINTENANCE_ROOT', str(tmp_path / 'missing'))
    with TestClient(application(str(tmp_path))) as client:
        assert client.post('/upload').status_code == 503
        assert client.get('/health').status_code == 200
    assert not (tmp_path / 'document').exists()


def test_main_upload_and_callback_are_blocked_before_storage(monkeypatch, tmp_path):
    from tests.test_reviewer_download import ReviewerDownloadsTest
    import app.main as main

    lock = tmp_path / 'lock'
    lock.mkdir(mode=0o700)
    monkeypatch.setenv('GSUB_MAINTENANCE_ROOT', str(lock))
    # Rebuild the app stack so this isolated test uses its own lock directory.
    old_stack = main.app.middleware_stack
    main.app.middleware_stack = None
    fixture = ReviewerDownloadsTest()
    try:
        fixture.setUp()
        fixture.current = fixture.author
        fixture.manuscript.status = 'draft'
        fixture.db.commit()
        directory = fixture.root / 'uploads' / 'manuscripts' / str(fixture.mid)
        before = set(directory.iterdir()) if directory.exists() else set()
        with sqlite3.connect(fixture.db_path, timeout=.1) as database_lock:
            database_lock.execute('BEGIN IMMEDIATE')
            try:
                with MaintenanceBarrier(lock).maintenance():
                    upload = fixture.client.post(f'/manuscripts/{fixture.mid}/upload', files={
                        'file': ('synthetic.txt', b'synthetic content', 'text/plain')
                    })
                    callback = fixture.client.post('/onlyoffice/callbacks/test', json={})
                    assert upload.status_code == callback.status_code == 503
                    assert callback.json() == {'error': 1}
                    assert (set(directory.iterdir()) if directory.exists() else set()) == before
            finally:
                database_lock.rollback()
    finally:
        fixture.tearDown()
        main.app.middleware_stack = old_stack

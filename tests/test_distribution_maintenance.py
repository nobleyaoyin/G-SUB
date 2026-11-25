"""Distribution worker participation, using only synthetic files and data."""
import multiprocessing
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.maintenance_barrier import MaintenanceActive, MaintenanceBarrier
from app import automatic_distribution_processor as processor


def distribution_worker(lock, root, entered, release, result):
    os.environ['GSUB_MAINTENANCE_ROOT'] = lock

    def synthetic_processing(db, intent_id):
        entered.set()
        if not release.wait(10):
            raise RuntimeError('test timed out')
        Path(root, 'artifact').write_bytes(b'synthetic artifact')
        return {'status': 'granted'}

    processor._process_intent = synthetic_processing
    result.put(processor.process_intent(None, 'synthetic'))


def test_active_maintenance_blocks_direct_distribution(monkeypatch, tmp_path):
    monkeypatch.setenv('GSUB_MAINTENANCE_ROOT', str(tmp_path))
    monkeypatch.setattr(processor, '_process_intent', lambda *args: pytest.fail('writer entered'))
    with MaintenanceBarrier(tmp_path).maintenance():
        with pytest.raises(HTTPException) as error:
            processor.process_intent(None, 'synthetic')
        assert error.value.status_code == 503


def test_invalid_coordination_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv('GSUB_MAINTENANCE_ROOT', str(tmp_path / 'missing'))
    monkeypatch.setattr(processor, '_process_intent', lambda *args: pytest.fail('writer entered'))
    with pytest.raises(HTTPException) as error:
        processor.process_intent(None, 'synthetic')
    assert error.value.status_code == 503


def test_distribution_in_admitted_request_defers_when_maintenance_starts(monkeypatch, tmp_path):
    monkeypatch.setenv('GSUB_MAINTENANCE_ROOT', str(tmp_path))
    monkeypatch.setattr(processor, '_process_intent', lambda *args: pytest.fail('writer entered'))
    barrier = MaintenanceBarrier(tmp_path)
    done = threading.Event()

    def maintain():
        with barrier.maintenance():
            done.set()

    thread = threading.Thread(target=maintain)
    with barrier.operation():
        thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with barrier.operation():
                    pass
            except MaintenanceActive:
                break
            time.sleep(.02)
        else:
            raise AssertionError('maintenance did not activate')
        assert not done.is_set()
        with pytest.raises(HTTPException) as error:
            processor.process_intent(None, 'synthetic')
        assert error.value.status_code == 503
    thread.join(10)
    assert done.is_set()


def test_maintenance_drains_cross_process_distribution(tmp_path):
    lock = tmp_path / 'lock'
    lock.mkdir(mode=0o700)
    context = multiprocessing.get_context('spawn')
    entered, release = context.Event(), context.Event()
    result = context.Queue()
    worker = context.Process(target=distribution_worker, args=(str(lock), str(tmp_path), entered, release, result))
    active, finish = threading.Event(), threading.Event()

    def maintain():
        with MaintenanceBarrier(lock).maintenance():
            active.set()
            if not finish.wait(10):
                raise RuntimeError('test timed out')

    thread = threading.Thread(target=maintain)
    worker.start()
    try:
        assert entered.wait(10)
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
            raise AssertionError('maintenance did not activate')
        assert not active.is_set()
        assert not (tmp_path / 'artifact').exists()
        release.set()
        assert active.wait(10)
        worker.join(10)
        assert worker.exitcode == 0
        assert result.get(timeout=2) == {'status': 'granted'}
        assert (tmp_path / 'artifact').read_bytes() == b'synthetic artifact'
    finally:
        release.set()
        finish.set()
        if thread.ident:
            thread.join(15)
        worker.join(15)

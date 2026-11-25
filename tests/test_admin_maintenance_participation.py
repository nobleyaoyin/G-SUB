"""Isolated maintenance participation for the three operator entry points."""
import importlib
import multiprocessing
import os
import threading
import time

import pytest

from app.maintenance_barrier import MaintenanceActive, MaintenanceBarrier


MODULES = ('scripts.enroll_sample_manuscript', 'scripts.bootstrap_lifecycle_admin',
           'scripts.succeed_lifecycle_admin')


@pytest.mark.parametrize('module_name', MODULES)
def test_each_command_blocks_during_maintenance_and_resumes(module_name, monkeypatch, tmp_path):
    module = importlib.import_module(module_name)
    lock = tmp_path / 'lock'
    lock.mkdir(mode=0o700)
    monkeypatch.setenv('GSUB_MAINTENANCE_ROOT', str(lock))
    writes = []
    monkeypatch.setattr(module, '_main', lambda *args: writes.append('synthetic') or 0)
    with MaintenanceBarrier(lock).maintenance():
        assert module.main() == 1
        assert writes == []
    assert module.main() == 0
    assert writes == ['synthetic']


@pytest.mark.parametrize('module_name', MODULES)
def test_invalid_coordination_fails_before_command(module_name, monkeypatch, tmp_path):
    module = importlib.import_module(module_name)
    monkeypatch.setenv('GSUB_MAINTENANCE_ROOT', str(tmp_path / 'missing'))
    monkeypatch.setattr(module, '_main', lambda *args: pytest.fail('command ran'))
    assert module.main() == 1


def worker(lock, entered, release, result):
    os.environ['GSUB_MAINTENANCE_ROOT'] = lock
    module = importlib.import_module('scripts.enroll_sample_manuscript')
    def synthetic(argv):
        entered.set()
        return 0 if release.wait(10) else 2
    module._main = synthetic
    result.put(module.main())


def test_maintenance_waits_for_independent_operator_process(tmp_path):
    lock = tmp_path / 'lock'
    lock.mkdir(mode=0o700)
    ctx = multiprocessing.get_context('spawn')
    entered, release, result = ctx.Event(), ctx.Event(), ctx.Queue()
    process = ctx.Process(target=worker, args=(str(lock), entered, release, result))
    active, finish = threading.Event(), threading.Event()

    def maintain():
        with MaintenanceBarrier(lock).maintenance():
            active.set()
            if not finish.wait(10):
                raise RuntimeError('synthetic test timed out')

    thread = threading.Thread(target=maintain)
    process.start()
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
        release.set()
        assert active.wait(10)
        process.join(10)
        assert process.exitcode == 0
        assert result.get(timeout=2) == 0
    finally:
        release.set()
        finish.set()
        if thread.ident:
            thread.join(15)
        process.join(15)

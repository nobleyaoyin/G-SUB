"""Cross-process tests for the isolated coordination primitive only."""
import multiprocessing
import os
import time

import pytest

from app.maintenance_barrier import MaintenanceActive, MaintenanceBarrier


def hold_operation(directory, entered, release):
    with MaintenanceBarrier(directory).operation():
        entered.set()
        release.wait(15)


def hold_maintenance(directory, entered, release):
    with MaintenanceBarrier(directory).maintenance():
        entered.set()
        release.wait(15)


def wait_for_active(barrier):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with barrier.operation():
                pass
        except MaintenanceActive:
            return
        time.sleep(.02)
    raise AssertionError('maintenance did not activate')


def stop_child(process):
    if process.is_alive():
        process.terminate()  # Only the synthetic child created by this test.
    process.join(5)


def test_cross_process_drain_blocks_new_operations(tmp_path):
    context = multiprocessing.get_context('spawn')
    op_entered, op_release = context.Event(), context.Event()
    maintenance_entered, maintenance_release = context.Event(), context.Event()
    barrier = MaintenanceBarrier(str(tmp_path))
    worker = context.Process(target=hold_operation, args=(str(tmp_path), op_entered, op_release))
    maintainer = context.Process(target=hold_maintenance, args=(str(tmp_path), maintenance_entered, maintenance_release))
    worker.start()
    try:
        assert op_entered.wait(10)
        maintainer.start()
        wait_for_active(barrier)
        assert not maintenance_entered.is_set()
        with pytest.raises(MaintenanceActive):
            barrier.recover_interrupted()
        op_release.set()
        assert maintenance_entered.wait(10)
        with pytest.raises(MaintenanceActive):
            with barrier.maintenance():
                pass
        maintenance_release.set()
        maintainer.join(10)
        worker.join(10)
        assert worker.exitcode == maintainer.exitcode == 0
        with barrier.operation():
            pass
    finally:
        op_release.set(); maintenance_release.set()
        stop_child(worker)
        if maintainer.pid is not None:
            stop_child(maintainer)


def test_crashed_owner_fails_closed_until_explicit_recovery(tmp_path):
    context = multiprocessing.get_context('spawn')
    entered, release = context.Event(), context.Event()
    process = context.Process(target=hold_maintenance, args=(str(tmp_path), entered, release))
    process.start()
    try:
        assert entered.wait(10)
        stop_child(process)
        barrier = MaintenanceBarrier(str(tmp_path))
        with pytest.raises(MaintenanceActive):
            with barrier.operation():
                pass
        barrier.recover_interrupted()
        with barrier.operation():
            pass
    finally:
        stop_child(process)


def test_exception_retains_maintenance_flag(tmp_path):
    barrier = MaintenanceBarrier(str(tmp_path))
    with pytest.raises(RuntimeError, match='injected'):
        with barrier.maintenance():
            raise RuntimeError('injected')
    with pytest.raises(MaintenanceActive):
        with barrier.operation():
            pass
    barrier.recover_interrupted()
    with barrier.operation():
        pass


def test_rejects_symlinked_lock_file(tmp_path):
    target = tmp_path / 'elsewhere'
    target.write_bytes(b'0')
    (tmp_path / 'gate.lock').symlink_to(target)
    with pytest.raises(OSError):
        with MaintenanceBarrier(str(tmp_path)).operation():
            pass

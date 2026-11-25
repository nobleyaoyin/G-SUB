"""Demonstrate the boundary of advisory maintenance locks on synthetic data."""
import multiprocessing
from pathlib import Path
import sqlite3

import pytest

from app.maintenance_barrier import MaintenanceActive, MaintenanceBarrier


def uncooperative_writer(db_path, file_path, result):
    with sqlite3.connect(db_path) as db:
        db.execute('INSERT INTO records VALUES (1)')
    Path(file_path).write_bytes(b'synthetic')
    result.put('written')


def test_maintenance_does_not_exclude_nonparticipating_db_or_file_writer(tmp_path):
    lock = tmp_path / 'lock'
    lock.mkdir(mode=0o700)
    db_path, file_path = tmp_path / 'test.sqlite', tmp_path / 'file.txt'
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE records (id INTEGER)')
    context = multiprocessing.get_context('spawn')
    result = context.Queue()
    process = context.Process(target=uncooperative_writer, args=(str(db_path), str(file_path), result))
    with MaintenanceBarrier(lock).maintenance():
        with pytest.raises(MaintenanceActive):
            with MaintenanceBarrier(lock).operation():
                pass
        process.start()
        process.join(10)
        assert process.exitcode == 0
        assert result.get(timeout=2) == 'written'
        assert file_path.read_bytes() == b'synthetic'
        with sqlite3.connect(db_path) as db:
            assert db.execute('SELECT count(*) FROM records').fetchone() == (1,)

"""Exercise the new transaction on disposable synthetic databases only."""
import importlib
import sqlite3

import pytest

from scripts import main_046_execute_once as operator
from scripts import main_046_executor as checks
from scripts.rehearse_current_main_snapshot import snapshot
from tests.test_main_046_executor_preparation import isolated


def test_transaction_preserves_records_and_refuses_repeat(isolated):
    project, database, roots, backup, restore = isolated
    expected = snapshot(restore / 'manuscript.db')
    with sqlite3.connect(database) as db:
        operator._transaction(db, expected)
    checks._verify_isolated_after(database, project, backup, restore)
    with sqlite3.connect(database) as db:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert set(importlib.import_module('migrations.046_main_submission_schema').TABLES) <= names
        assert db.execute('SELECT COUNT(*) FROM schema_migrations').fetchone() == (6,)
        with pytest.raises(ValueError, match='differs|already applied'):
            operator._transaction(db, expected)


def test_precommit_failure_rolls_back(isolated):
    database, restore = isolated[1], isolated[4]
    expected = snapshot(restore / 'manuscript.db')
    def fail(index, name):
        if index == 2:
            raise RuntimeError('injected')
    with sqlite3.connect(database) as db:
        with pytest.raises(RuntimeError, match='injected'):
            operator._transaction(db, expected, after_create=fail)
    assert snapshot(database) == expected


def test_commit_uncertainty_is_not_retried(isolated):
    database, restore = isolated[1], isolated[4]
    calls = []
    def commit_then_fail(db):
        calls.append(1)
        db.commit()
        raise OSError('lost response')
    with sqlite3.connect(database) as db:
        with pytest.raises(checks.OutcomeUncertain):
            operator._transaction(db, snapshot(restore / 'manuscript.db'), commit=commit_then_fail)
    assert calls == [1]


def test_identity_and_offline_confirmation_reject_before_open(monkeypatch):
    args = ['--project', str(operator.MAIN_ROOT), '--database', str(operator.MAIN_ROOT / 'manuscript.db'),
            '--confirm-main', checks.CONFIRMATION, '--confirm-offline', 'wrong',
            '--backup', '/absent', '--restore', '/absent']
    monkeypatch.setattr(checks, 'validate', lambda *a, **k: pytest.fail('must not inspect backup'))
    assert operator.main(args) == 1
    args[1] = '/different/project'
    assert operator.main(args) == 1


def test_operator_flow_with_disposable_paths(isolated, monkeypatch):
    project, database, roots, backup, restore = isolated
    assert project.is_relative_to(isolated[0].parent)
    def identity(p, d, confirmation):
        if p != str(project) or d != str(database) or confirmation != checks.CONFIRMATION:
            raise ValueError('identity')
    monkeypatch.setattr(operator, 'MAIN_ROOT', project)
    monkeypatch.setattr(operator, 'validate_identity', identity)
    # lsof may not be available to the test runner; this does not prove exclusion.
    monkeypatch.setattr(operator, '_handles', lambda path: None)
    args = ['--project', str(project), '--database', str(database), '--confirm-main', checks.CONFIRMATION,
            '--confirm-offline', operator.OFFLINE, '--backup', str(backup), '--restore', str(restore)]
    for root in roots:
        args += ['--storage-root', str(root)]
    assert operator.main(args) == 0
    assert operator.main(args) == 1

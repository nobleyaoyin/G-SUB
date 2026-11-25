"""Only synthetic SQLite files: the new ledger is inert until integration."""
import importlib.util
from pathlib import Path
import sqlite3

import pytest

from tests.test_batch17b_distribution_migration import database, migration as manual

spec = importlib.util.spec_from_file_location(
    'migration25', Path(__file__).resolve().parents[1] / 'migrations/025_automatic_distribution.py')
auto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto)


def test_additive_upgrade_empty_rollback_and_manual_compatibility(database):
    manual.migrate(database)
    auto.migrate(database)
    auto.migrate(database)
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()[0] == 0
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        manual_sql = db.execute("SELECT sql FROM sqlite_master WHERE name='distribution_grants'").fetchone()[0]
        assert "mode='manual'" in manual_sql
    auto.downgrade_empty(database)
    auto.migrate(database)
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT COUNT(*) FROM schema_migrations WHERE migration_id=?', (auto.MIGRATION_ID,)).fetchone()[0] == 1


def test_config_scope_and_assignment_checks(database):
    manual.migrate(database)
    auto.migrate(database)
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        config = ('c1', 1, 'initial', 'current_author_manuscript', 'a' * 64, 1, 1, '2026-01-01')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO automatic_distribution_configurations VALUES(?,?,?,?,?,?,?,?)', ('bad', 1, 'reviewer', *config[3:]))
        with pytest.raises(sqlite3.IntegrityError, match='EIC required'):
            db.execute('INSERT INTO automatic_distribution_configurations VALUES(?,?,?,?,?,?,?,?)', (*config[:6], 2, config[7]))
        db.execute('INSERT INTO automatic_distribution_configurations VALUES(?,?,?,?,?,?,?,?)', config)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE automatic_distribution_configurations SET source_sha256=? WHERE configuration_id='c1'", ('b' * 64,))
        with pytest.raises(sqlite3.IntegrityError, match='Eligible editor'):
            db.execute('INSERT INTO automatic_distribution_intents VALUES(?,?,?,?,?,?,?,?)', ('i0', 'c1', 'initial', 1, 1, 'intent-key-0000001', 'e' * 64, '2026-01-02'))
        db.execute('INSERT INTO automatic_distribution_intents VALUES(?,?,?,?,?,?,?,?)', ('i1', 'c1', 'initial', 1, 2, 'intent-key-0000001', 'e' * 64, '2026-01-02'))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO automatic_distribution_intents VALUES(?,?,?,?,?,?,?,?)', ('i2', 'c1', 'initial', 1, 2, 'intent-key-0000002', 'e' * 64, '2026-01-02'))
        db.execute('INSERT INTO automatic_distribution_configuration_revocations VALUES(?,?,?,?)', ('c1', 1, 'Synthetic', '2026-01-03'))
        with pytest.raises(sqlite3.IntegrityError, match='Eligible editor'):
            db.execute('INSERT INTO automatic_distribution_intents VALUES(?,?,?,?,?,?,?,?)', ('i3', 'c1', 'initial', 1, 2, 'intent-key-0000003', 'e' * 64, '2026-01-04'))
        db.commit()
    with pytest.raises(RuntimeError, match='retained'):
        auto.downgrade_empty(database)


def test_requires_existing_manual_schema_and_rejects_partial_schema(database):
    with pytest.raises(RuntimeError, match='021'):
        auto.migrate(database)
    manual.migrate(database)
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE automatic_distribution_intents(x)')
    with pytest.raises(RuntimeError, match='partial'):
        auto.migrate(database)
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (auto.MIGRATION_ID,)).fetchone() is None


def test_result_cannot_claim_unrelated_grant(database):
    manual.migrate(database)
    auto.migrate(database)
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('INSERT INTO automatic_distribution_configurations VALUES(?,?,?,?,?,?,?,?)', ('c1', 1, 'initial', 'current_author_manuscript', 'a' * 64, 1, 1, '2026-01-01'))
        db.execute('INSERT INTO automatic_distribution_intents VALUES(?,?,?,?,?,?,?,?)', ('i1', 'c1', 'initial', 1, 2, 'intent-key-0000001', 'e' * 64, '2026-01-02'))
        with pytest.raises(sqlite3.IntegrityError, match='Grant evidence mismatch'):
            db.execute('INSERT INTO automatic_distribution_results VALUES(?,?,?,?,?,?)', ('r1', 'i1', 'granted', 'fake', None, '2026-01-02'))
        db.execute('INSERT INTO automatic_distribution_results VALUES(?,?,?,?,?,?)', ('r2', 'i1', 'failed', None, 'source_changed', '2026-01-02'))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM automatic_distribution_results WHERE result_id='r2'")

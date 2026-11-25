"""Exercise the candidate 025 migration over populated synthetic 021 data."""
import sqlite3

from tests.test_batch17b_distribution_migration import database, migration as manual
from tests.test_batch67_auto_migration import auto


def test_existing_manual_grant_and_021_schema_survive_upgrade_and_empty_rollback(database):
    manual.migrate(database)
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        now = '2026-01-01T00:00:00.000000Z'
        db.execute('INSERT INTO distribution_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('b'*32, 1, 1, 'editor_source', None, None, 'c'*64, 4, 'txt', 'reserve-key-0001', 'f'*64, now))
        db.execute('INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('a'*32, 1, 'editor_source', 1, 'b'*32, 'c'*64, 4, 'txt', None, None, 1, now))
        db.execute('INSERT INTO distribution_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('d'*32, 1, 'a'*32, 2, 'editor', 1, None, None, None, 1, 'manual', 'created', 'not_requested', 'idempotency-key-0001', 'e'*64, now))
        before = db.execute("SELECT type,name,sql FROM sqlite_master WHERE tbl_name LIKE 'distribution_%' AND sql IS NOT NULL ORDER BY name").fetchall()
        grant = db.execute('SELECT * FROM distribution_grants').fetchone()
    auto.migrate(database)
    auto.migrate(database)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT type,name,sql FROM sqlite_master WHERE tbl_name LIKE 'distribution_%' AND sql IS NOT NULL ORDER BY name").fetchall() == before
        assert db.execute('SELECT * FROM distribution_grants').fetchone() == grant
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    auto.downgrade_empty(database)
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT * FROM distribution_grants').fetchone() == grant
        assert db.execute("SELECT type,name,sql FROM sqlite_master WHERE tbl_name LIKE 'distribution_%' AND sql IS NOT NULL ORDER BY name").fetchall() == before

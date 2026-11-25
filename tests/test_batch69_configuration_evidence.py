"""Characterize candidate 025 limitations on disposable SQLite databases.

These tests establish why 025 evidence alone is not an authorization decision.
They are not acceptance tests for configured document access.
"""
import sqlite3

from tests.test_batch17b_distribution_migration import database, migration as manual
from tests.test_batch67_auto_migration import auto


def test_configuration_schema_cannot_express_manual_mode_or_exclusive_activation(database):
    manual.migrate(database)
    auto.migrate(database)
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        cols = {row[1] for row in db.execute('PRAGMA table_info(automatic_distribution_configurations)')}
        assert 'mode' not in cols and 'active' not in cols
        rows = [
            ('conf1', 1, 'initial', 'current_author_manuscript', 'a'*64, 1, 1, '2026-01-01'),
            ('conf2', 1, 'initial', 'current_author_manuscript', 'b'*64, 2, 1, '2026-01-02'),
        ]
        db.executemany('INSERT INTO automatic_distribution_configurations VALUES(?,?,?,?,?,?,?,?)', rows)
        assert db.execute('SELECT count(*) FROM automatic_distribution_configurations').fetchone()[0] == 2


def test_candidate_result_evidence_does_not_itself_check_grant_revocation(database):
    manual.migrate(database)
    auto.migrate(database)
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        now = '2026-01-01T00:00:00.000000Z'
        db.execute('INSERT INTO distribution_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('b'*32, 1, 1, 'editor_source', None, None, 'c'*64, 4, 'txt', 'reserve-key-0001', 'f'*64, now))
        db.execute('INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('a'*32, 1, 'editor_source', 1, 'b'*32, 'c'*64, 4, 'txt', None, None, 1, now))
        db.execute('INSERT INTO distribution_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('d'*32, 1, 'a'*32, 2, 'editor', 1, None, None, None, 1, 'manual', 'created', 'not_requested', 'idempotency-key-0001', 'e'*64, now))
        db.execute('INSERT INTO distribution_revocations VALUES(?,?,?,?)', ('d'*32, 1, 'Synthetic', now))
        db.execute('INSERT INTO automatic_distribution_configurations VALUES(?,?,?,?,?,?,?,?)',
                   ('conf', 1, 'initial', 'current_author_manuscript', 'c'*64, 1, 1, now))
        db.execute('INSERT INTO automatic_distribution_intents VALUES(?,?,?,?,?,?,?,?)',
                   ('intent', 'conf', 'initial', 1, 2, 'intent-key-0000001', 'e'*64, now))
        db.execute('INSERT INTO automatic_distribution_results VALUES(?,?,?,?,?,?)',
                   ('result', 'intent', 'granted', 'd'*32, None, now))
        assert db.execute('SELECT state FROM automatic_distribution_results').fetchone()[0] == 'granted'
        assert db.execute('SELECT count(*) FROM distribution_revocations').fetchone()[0] == 1

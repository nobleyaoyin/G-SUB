"""Freshness checks with distinct SQLite connections and disposable files."""
import sqlite3

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app import blind_policy_store as store, models, source_policy_foundation
from app.database import engine as configured_engine
from app.source_policy_foundation import FoundationUnavailable, capture, revalidate
from tests.test_phase_2f_4f2a_foundation import context
from tests.test_phase_2f_policy_management import policy_api
from tests.test_phase_2f_reviewer_projections import api_factory


@pytest.fixture(params=['WAL', 'DELETE'])
def two_connections(context, tmp_path, request):
    _, source_engine, path, content, proof = context
    target = tmp_path / 'synthetic-isolated.sqlite'
    anchor = sqlite3.connect(str(target), timeout=0.05)
    source = source_engine.raw_connection()
    source.driver_connection.backup(anchor)
    source.close()
    assert anchor.execute('PRAGMA journal_mode=' + request.param).fetchone()[0].upper() == request.param
    anchor.close()
    engine = create_engine('sqlite:///' + str(target), connect_args={'timeout': 0.05})
    @event.listens_for(engine, 'connect')
    def foreign_keys(dbapi, _):
        dbapi.execute('PRAGMA foreign_keys=ON')
    with engine.connect() as a, engine.connect() as b:
        assert a.connection.driver_connection is not b.connection.driver_connection
        assert a.exec_driver_sql('PRAGMA database_list').all()[0][2] == str(target)
    yield engine, request.param, path, content, proof
    engine.dispose()


def policy_change(engine, mode, revision):
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        store.begin_write(raw)
        try:
            store.change_mode(raw, 2, mode, 4, revision)
            raw.commit()
        except Exception:
            raw.rollback()
            raise


def test_old_read_snapshot_rejected_and_aba_checked(two_connections):
    engine, journal, _, _, proof = two_connections
    with Session(engine) as reader:
        user = reader.get(models.User, 4)
        old = capture(reader, user, 2, 2, 1, proof_adapter=proof)
        if journal == 'WAL':
            policy_change(engine, 'single_blind', 1)
            policy_change(engine, 'double_blind', 2)
        else:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                policy_change(engine, 'single_blind', 1)
        with pytest.raises(FoundationUnavailable, match='Fresh read transaction'):
            revalidate(reader, user, old, proof_adapter=proof)
        assert reader.connection().connection.driver_connection.in_transaction
        reader.rollback()
        if journal == 'DELETE':
            policy_change(engine, 'single_blind', 1)
            policy_change(engine, 'double_blind', 2)
        user = reader.get(models.User, 4)
        with pytest.raises(FoundationUnavailable, match='stale'):
            revalidate(reader, user, old, proof_adapter=proof)
        reader.rollback()
        assert capture(reader, reader.get(models.User, 4), 2, 2, 3, proof_adapter=proof).policy_revision == 3
    with pytest.raises(AssertionError):
        configured_engine.connect()


def test_caller_owned_transaction_and_same_size_file_change(two_connections):
    engine, _, path, content, proof = two_connections
    with Session(engine) as db:
        with db.begin():
            user = db.get(models.User, 4)
            with pytest.raises(FoundationUnavailable, match='Caller-owned'):
                capture(db, user, 2, 2, 1, proof_adapter=proof)
            assert db.in_transaction()
        user = db.get(models.User, 4)
        old = capture(db, user, 2, 2, 1, proof_adapter=proof)
        db.rollback()
        path.write_bytes(content.upper())
        with pytest.raises(FoundationUnavailable, match='proof mismatch'):
            revalidate(db, db.get(models.User, 4), old, proof_adapter=proof)


def test_adapter_receives_no_database_and_changed_proof_is_denied(two_connections, monkeypatch):
    engine, _, _, _, proof = two_connections
    class ChangingProof:
        calls = 0
        def verify_prospective(self, *args):
            assert len(args) == 4 and all(not isinstance(x, sqlite3.Connection) for x in args)
            self.calls += 1
            value = proof.verify_prospective(*args)
            return value if self.calls == 1 else ('different-proof', *value[1:])
    adapter = ChangingProof()
    monkeypatch.setattr(source_policy_foundation, '_server_proof_adapter', lambda: adapter)
    with Session(engine) as db:
        with pytest.raises(FoundationUnavailable, match='proof changed'):
            capture(db, db.get(models.User, 4), 2, 2, 1, proof_adapter=adapter)


def test_source_revision_change_cannot_be_hidden_by_old_snapshot(two_connections):
    engine, journal, _, _, proof = two_connections
    with Session(engine) as reader:
        user = reader.get(models.User, 4)
        old = capture(reader, user, 2, 2, 1, proof_adapter=proof)
        def update_round():
            with engine.begin() as connection:
                connection.exec_driver_sql('UPDATE manuscripts SET review_round=3 WHERE manuscript_id=2')
        if journal == 'WAL':
            update_round()
        else:
            with pytest.raises(Exception) as failure:
                update_round()
            assert 'locked' in str(failure.value).lower()
        with pytest.raises(FoundationUnavailable, match='Fresh read'):
            revalidate(reader, user, old, proof_adapter=proof)
        reader.rollback()
        if journal == 'DELETE':
            update_round()
        with pytest.raises(FoundationUnavailable, match='Source verification unavailable'):
            revalidate(reader, reader.get(models.User, 4), old, proof_adapter=proof)


def test_actual_lock_transition_requires_new_snapshot(two_connections):
    engine, journal, _, _, proof = two_connections
    with Session(engine) as reader:
        user = reader.get(models.User, 4)
        old = capture(reader, user, 2, 2, 1, proof_adapter=proof)
        def invite_and_lock():
            with engine.connect() as connection:
                raw = connection.connection.driver_connection
                store.begin_write(raw)
                try:
                    raw.execute("INSERT INTO review_assignments (manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at) VALUES (2,5,4,2,'assigned','2026-01-01')")
                    assignment_id = raw.execute('SELECT last_insert_rowid()').fetchone()[0]
                    raw.execute("INSERT INTO reviewer_invitations (assignment_id,status,invited_at) VALUES (?, 'pending', '2026-01-01')", (assignment_id,))
                    store.lock_mode(raw, 2, assignment_id, 4, 1)
                    raw.commit()
                except Exception:
                    raw.rollback()
                    raise
        if journal == 'WAL':
            invite_and_lock()
        else:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                invite_and_lock()
        with pytest.raises(FoundationUnavailable, match='Fresh read'):
            revalidate(reader, user, old, proof_adapter=proof)
        reader.rollback()
        if journal == 'DELETE':
            invite_and_lock()
        with pytest.raises(FoundationUnavailable, match='policy'):
            revalidate(reader, reader.get(models.User, 4), old, proof_adapter=proof)

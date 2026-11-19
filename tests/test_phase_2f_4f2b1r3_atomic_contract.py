"""Synthetic SQLite contract only: no application DB, files, or migrations."""
import sqlite3

import pytest


DDL = '''
PRAGMA foreign_keys=ON;
CREATE TABLE operations(
  operation_id TEXT PRIMARY KEY NOT NULL,
  storage_id TEXT UNIQUE NOT NULL,
  fingerprint TEXT NOT NULL,
  initial_revision INTEGER NOT NULL DEFAULT 1 CHECK(initial_revision=1),
  UNIQUE(operation_id, storage_id),
  FOREIGN KEY(operation_id,initial_revision) REFERENCES operation_events(operation_id,revision) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE operation_events(
  operation_id TEXT NOT NULL REFERENCES operations(operation_id) ON DELETE RESTRICT,
  revision INTEGER NOT NULL CHECK(revision > 0),
  state TEXT NOT NULL CHECK(state IN ('requested','storage_pending','published','recorded','failed','outcome_unknown')),
  actor_id INTEGER NOT NULL CHECK(actor_id > 0),
  PRIMARY KEY(operation_id, revision)
);
CREATE VIEW current_operations AS
SELECT o.*, e.revision, e.state, e.actor_id FROM operations o
JOIN operation_events e ON e.operation_id=o.operation_id
WHERE e.revision=(SELECT MAX(e2.revision) FROM operation_events e2 WHERE e2.operation_id=o.operation_id);
CREATE TRIGGER operation_immutable BEFORE UPDATE ON operations BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER operation_no_delete BEFORE DELETE ON operations BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER event_immutable BEFORE UPDATE ON operation_events BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER event_no_delete BEFORE DELETE ON operation_events BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER event_sequence BEFORE INSERT ON operation_events
BEGIN
 SELECT CASE WHEN NEW.revision != COALESCE((SELECT MAX(revision)+1 FROM operation_events WHERE operation_id=NEW.operation_id),1) THEN RAISE(ABORT,'stale revision') END;
 SELECT CASE WHEN NEW.revision=1 AND NEW.state!='requested' THEN RAISE(ABORT,'invalid initial state') END;
 SELECT CASE WHEN NEW.revision>1 AND NOT EXISTS (
   SELECT 1 FROM operation_events p WHERE p.operation_id=NEW.operation_id AND p.revision=NEW.revision-1 AND (
    (p.state='requested' AND NEW.state IN ('storage_pending','failed')) OR
    (p.state='storage_pending' AND NEW.state IN ('published','failed','outcome_unknown')) OR
    (p.state='outcome_unknown' AND NEW.state IN ('published','failed')) OR
    (p.state='published' AND NEW.state IN ('recorded','outcome_unknown'))))
 THEN RAISE(ABORT,'invalid transition') END;
END;
'''


@pytest.fixture(params=['WAL', 'DELETE'])
def db(tmp_path, request):
    path = tmp_path / 'synthetic.sqlite'
    con = sqlite3.connect(path)
    assert con.execute('PRAGMA journal_mode=' + request.param).fetchone()[0].upper() == request.param
    con.executescript(DDL)
    yield con, path
    con.close()


def start(con):
    con.execute("INSERT INTO operations(operation_id,storage_id,fingerprint) VALUES ('op','storage','fingerprint')")
    con.execute("INSERT INTO operation_events VALUES ('op',1,'requested',1)")
    con.commit()


def test_atomic_state_is_derived_from_event_and_rollback(db):
    con, _ = db
    start(con)
    con.execute("INSERT INTO operation_events VALUES ('op',2,'storage_pending',1)")
    assert con.execute('SELECT revision,state FROM current_operations').fetchone() == (2, 'storage_pending')
    con.rollback()
    assert con.execute('SELECT revision,state FROM current_operations').fetchone() == (1, 'requested')
    con.execute("INSERT INTO operation_events VALUES ('op',2,'storage_pending',1)")
    con.commit()
    assert con.execute('SELECT revision,state FROM current_operations').fetchone() == (2, 'storage_pending')


def test_bypass_and_stale_revisions_rejected(db):
    con, _ = db
    start(con)
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE operations SET fingerprint='other'")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE current_operations SET state='recorded'")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("INSERT INTO operation_events VALUES ('op',3,'published',1)")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("INSERT INTO operation_events VALUES ('op',2,'recorded',1)")
    con.execute("INSERT INTO operation_events VALUES ('op',2,'storage_pending',1)")
    con.commit()
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("INSERT INTO operation_events VALUES ('op',2,'storage_pending',1)")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE operation_events SET state='recorded'")


def test_independent_connection_stale_writer(db):
    con, path = db
    start(con)
    other = sqlite3.connect(path, timeout=1)
    try:
        other.execute('PRAGMA foreign_keys=ON')
        assert other.execute('SELECT revision FROM current_operations').fetchone() == (1,)
        con.execute("INSERT INTO operation_events VALUES ('op',2,'storage_pending',1)")
        con.commit()
        with pytest.raises(sqlite3.DatabaseError):
            other.execute("INSERT INTO operation_events VALUES ('op',2,'storage_pending',1)")
        other.rollback()
        assert other.execute('SELECT revision FROM current_operations').fetchone() == (2,)
    finally:
        other.close()


def test_orphan_operation_cannot_commit(db):
    con, _ = db
    con.execute("INSERT INTO operations(operation_id,storage_id,fingerprint) VALUES ('orphan','reserved','fingerprint')")
    with pytest.raises(sqlite3.IntegrityError):
        con.commit()
    con.rollback()
    start(con)
    assert con.execute('SELECT revision FROM current_operations').fetchone() == (1,)

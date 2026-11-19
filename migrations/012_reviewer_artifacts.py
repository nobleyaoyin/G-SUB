"""Add inactive reviewer-artifact schema to an explicitly supplied SQLite file."""
import argparse
from importlib import import_module
from pathlib import Path
import sqlite3

MIGRATION_ID = '012_reviewer_artifacts'
prior = import_module('migrations.011_blind_review_policy')
normalize = prior.normalize

DDL = {
    'reviewer_artifacts': """CREATE TABLE reviewer_artifacts (
        artifact_id TEXT NOT NULL PRIMARY KEY CHECK(length(artifact_id)=32 AND artifact_id NOT GLOB '*[^0-9a-f]*'),
        manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
        review_round INTEGER NOT NULL CHECK(typeof(review_round)='integer' AND review_round>=1),
        source_round_file_id INTEGER NOT NULL REFERENCES review_round_files(round_file_id) ON DELETE RESTRICT,
        source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
        artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64 AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'),
        format TEXT NOT NULL CHECK(format IN ('pdf','docx','doc','txt')),
        byte_size INTEGER NOT NULL CHECK(typeof(byte_size)='integer' AND byte_size BETWEEN 1 AND 10485760),
        storage_id TEXT NOT NULL UNIQUE CHECK(length(storage_id)=32 AND storage_id NOT GLOB '*[^0-9a-f]*'),
        prepared_by INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        prepared_at TEXT NOT NULL CHECK(length(prepared_at)=27),
        status TEXT NOT NULL CHECK(status IN ('prepared','approved','rejected','withdrawn')),
        approved_by INTEGER REFERENCES users(user_id) ON DELETE RESTRICT,
        approved_at TEXT CHECK(approved_at IS NULL OR length(approved_at)=27),
        artifact_revision INTEGER NOT NULL CHECK(typeof(artifact_revision)='integer' AND artifact_revision>=1),
        state_revision INTEGER NOT NULL CHECK(typeof(state_revision)='integer' AND state_revision>=1),
        current_event_id TEXT NOT NULL,
        CHECK((approved_by IS NULL AND approved_at IS NULL) OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)),
        CHECK((status='approved' AND approved_by IS NOT NULL) OR (status IN ('prepared','rejected') AND approved_by IS NULL) OR status='withdrawn'),
        UNIQUE(manuscript_id,review_round,artifact_revision),
        FOREIGN KEY(current_event_id,artifact_id,state_revision,status) REFERENCES reviewer_artifact_events(event_id,artifact_id,revision,action) DEFERRABLE INITIALLY DEFERRED
    )""",
    'reviewer_artifact_events': """CREATE TABLE reviewer_artifact_events (
        event_id TEXT NOT NULL PRIMARY KEY CHECK(length(event_id)=32 AND event_id NOT GLOB '*[^0-9a-f]*'),
        artifact_id TEXT NOT NULL REFERENCES reviewer_artifacts(artifact_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>=1),
        action TEXT NOT NULL CHECK(action IN ('prepared','approved','rejected','withdrawn')),
        actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        occurred_at TEXT NOT NULL CHECK(length(occurred_at)=27),
        reason_code TEXT NOT NULL CHECK(reason_code IN ('prepared','approved','rejected','withdrawn')),
        CHECK(reason_code=action),
        UNIQUE(artifact_id,revision),
        UNIQUE(event_id,artifact_id,revision,action)
    )""",
    'reviewer_artifact_assignments': """CREATE TABLE reviewer_artifact_assignments (
        assignment_id INTEGER NOT NULL PRIMARY KEY REFERENCES review_assignments(assignment_id) ON DELETE RESTRICT,
        artifact_id TEXT NOT NULL REFERENCES reviewer_artifacts(artifact_id) ON DELETE RESTRICT,
        bound_by INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        bound_at TEXT NOT NULL CHECK(length(bound_at)=27)
    )""",
    'ix_artifact_source': 'CREATE INDEX ix_artifact_source ON reviewer_artifacts(source_round_file_id)',
    'ix_artifact_events_actor_time': 'CREATE INDEX ix_artifact_events_actor_time ON reviewer_artifact_events(actor_id,occurred_at)',
    'ix_artifact_assignment_artifact': 'CREATE INDEX ix_artifact_assignment_artifact ON reviewer_artifact_assignments(artifact_id)',
    'artifact_initial_check': """CREATE TRIGGER artifact_initial_check BEFORE INSERT ON reviewer_artifacts
        WHEN NEW.status<>'prepared' OR NEW.state_revision<>1 OR NEW.approved_by IS NOT NULL OR NEW.approved_at IS NOT NULL
          OR NOT EXISTS (SELECT 1 FROM review_round_files r WHERE r.round_file_id=NEW.source_round_file_id AND r.manuscript_id=NEW.manuscript_id AND r.review_round=NEW.review_round)
        BEGIN SELECT RAISE(ABORT,'invalid artifact source or initial state'); END""",
    'artifact_event_transition': """CREATE TRIGGER artifact_event_transition BEFORE INSERT ON reviewer_artifact_events
        WHEN NOT EXISTS (SELECT 1 FROM reviewer_artifacts a WHERE a.artifact_id=NEW.artifact_id AND (
          (NEW.revision=1 AND NEW.action='prepared' AND a.state_revision=1 AND a.status='prepared' AND a.current_event_id=NEW.event_id AND a.prepared_by=NEW.actor_id AND a.prepared_at=NEW.occurred_at)
          OR (NEW.revision=a.state_revision+1 AND ((a.status='prepared' AND NEW.action IN ('approved','rejected','withdrawn')) OR (a.status='approved' AND NEW.action='withdrawn')))))
        BEGIN SELECT RAISE(ABORT,'invalid artifact event transition'); END""",
    'artifact_event_apply': """CREATE TRIGGER artifact_event_apply AFTER INSERT ON reviewer_artifact_events WHEN NEW.revision>1
        BEGIN UPDATE reviewer_artifacts SET status=NEW.action, state_revision=NEW.revision, current_event_id=NEW.event_id,
          approved_by=CASE WHEN NEW.action='approved' THEN NEW.actor_id ELSE approved_by END,
          approved_at=CASE WHEN NEW.action='approved' THEN NEW.occurred_at ELSE approved_at END
          WHERE artifact_id=NEW.artifact_id; END""",
    'artifact_update_guard': """CREATE TRIGGER artifact_update_guard BEFORE UPDATE ON reviewer_artifacts
        WHEN NEW.artifact_id IS NOT OLD.artifact_id OR NEW.manuscript_id IS NOT OLD.manuscript_id OR NEW.review_round IS NOT OLD.review_round
          OR NEW.source_round_file_id IS NOT OLD.source_round_file_id OR NEW.source_sha256 IS NOT OLD.source_sha256 OR NEW.artifact_sha256 IS NOT OLD.artifact_sha256
          OR NEW.format IS NOT OLD.format OR NEW.byte_size IS NOT OLD.byte_size OR NEW.storage_id IS NOT OLD.storage_id
          OR NEW.prepared_by IS NOT OLD.prepared_by OR NEW.prepared_at IS NOT OLD.prepared_at OR NEW.artifact_revision IS NOT OLD.artifact_revision
          OR NEW.state_revision<>OLD.state_revision+1 OR NOT EXISTS (SELECT 1 FROM reviewer_artifact_events e WHERE e.event_id=NEW.current_event_id AND e.artifact_id=NEW.artifact_id AND e.revision=NEW.state_revision AND e.action=NEW.status
            AND ((e.action='approved' AND NEW.approved_by=e.actor_id AND NEW.approved_at=e.occurred_at) OR (e.action<>'approved' AND NEW.approved_by IS OLD.approved_by AND NEW.approved_at IS OLD.approved_at)))
        BEGIN SELECT RAISE(ABORT,'invalid artifact update'); END""",
    'artifact_no_delete': "CREATE TRIGGER artifact_no_delete BEFORE DELETE ON reviewer_artifacts BEGIN SELECT RAISE(ABORT,'artifacts are immutable'); END",
    'artifact_events_no_update': "CREATE TRIGGER artifact_events_no_update BEFORE UPDATE ON reviewer_artifact_events BEGIN SELECT RAISE(ABORT,'artifact events are append-only'); END",
    'artifact_events_no_delete': "CREATE TRIGGER artifact_events_no_delete BEFORE DELETE ON reviewer_artifact_events BEGIN SELECT RAISE(ABORT,'artifact events are append-only'); END",
    'artifact_assignment_check': """CREATE TRIGGER artifact_assignment_check BEFORE INSERT ON reviewer_artifact_assignments
        WHEN NOT EXISTS (SELECT 1 FROM reviewer_artifacts a JOIN review_assignments x ON x.assignment_id=NEW.assignment_id
          JOIN review_assignment_files f ON f.assignment_id=x.assignment_id
          JOIN review_round_files r ON r.round_file_id=f.round_file_id
          WHERE a.artifact_id=NEW.artifact_id AND a.status='approved' AND a.manuscript_id=x.manuscript_id
            AND a.review_round=x.review_round AND a.source_round_file_id=f.round_file_id
            AND r.manuscript_id=x.manuscript_id AND r.review_round=x.review_round)
        BEGIN SELECT RAISE(ABORT,'artifact does not match assignment'); END""",
    'artifact_assignment_no_update': "CREATE TRIGGER artifact_assignment_no_update BEFORE UPDATE ON reviewer_artifact_assignments BEGIN SELECT RAISE(ABORT,'artifact bindings are immutable'); END",
    'artifact_assignment_no_delete': "CREATE TRIGGER artifact_assignment_no_delete BEFORE DELETE ON reviewer_artifact_assignments BEGIN SELECT RAISE(ABORT,'artifact bindings are immutable'); END",
}


def validate_schema(db):
    objects = {name: (kind, sql) for name, kind, sql in db.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view','index','trigger')")}
    for name, expected in DDL.items():
        kind = 'trigger' if expected.startswith('CREATE TRIGGER') else 'index' if expected.startswith('CREATE INDEX') else 'table'
        actual = objects.get(name)
        if not actual or actual[0] != kind or not actual[1] or normalize(actual[1]) != normalize(expected): raise RuntimeError('Reviewer artifact schema incompatible')
    extras = db.execute("SELECT name FROM sqlite_master WHERE tbl_name IN ('reviewer_artifacts','reviewer_artifact_events','reviewer_artifact_assignments') AND type IN ('trigger','index') AND sql IS NOT NULL").fetchall()
    if any(row[0] not in DDL for row in extras): raise RuntimeError('Unexpected reviewer artifact schema object')


def migrate(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file(): raise ValueError('Database must be an existing file')
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
        objects = {name: (kind, sql) for name, kind, sql in db.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view','index','trigger')")}
        if objects.get('schema_migrations', (None,))[0] != 'table' or {r[1] for r in db.execute('PRAGMA table_info(schema_migrations)')} != {'migration_id','applied_at'}: raise RuntimeError('Missing or incompatible migration ledger')
        ledger = {r[0] for r in db.execute('SELECT migration_id FROM schema_migrations')}
        if not set(prior.PREREQUISITES + (prior.MIGRATION_ID,)).issubset(ledger): raise RuntimeError('Required migrations 001–006 and 011 are missing')
        for name in prior.PREREQUISITES:
            declared = import_module('migrations.' + name).DDL
            if isinstance(declared, str): declared = {{'002_reviewer_invitations':'reviewer_invitations','003_two_reviewer_policy':'manuscript_review_policies','004_author_agreements':'author_agreements'}[name]: declared}
            for obj, expected in declared.items():
                actual = objects.get(obj)
                if not actual or not actual[1] or normalize(actual[1]) != normalize(expected): raise RuntimeError('Incompatible prerequisite schema')
        prior.validate_schema(db)
        if '010_reviewer_profiles' in ledger:
            actual = objects.get('reviewer_profiles'); expected = import_module('migrations.010_reviewer_profiles').DDL
            if not actual or actual[0] != 'table' or not actual[1] or normalize(actual[1]) != normalize(expected): raise RuntimeError('Incompatible optional profile schema')
        for table, columns in {'users':{'user_id'},'manuscripts':{'manuscript_id','review_round'},'review_assignments':{'assignment_id','manuscript_id','review_round'}}.items():
            if not columns.issubset({r[1] for r in db.execute(f'PRAGMA table_info({table})')}): raise RuntimeError('Incompatible base schema')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Integrity check failed')
        if MIGRATION_ID not in ledger:
            if any(name in objects for name in DDL): raise RuntimeError('Conflicting or partial reviewer artifact schema')
            for sql in DDL.values(): db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))", (MIGRATION_ID,))
        validate_schema(db)
        if db.execute('PRAGMA foreign_key_check').fetchone() or db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]: raise RuntimeError('Integrity check failed')
        db.commit()
    except Exception:
        db.rollback(); raise
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', help='Explicit existing SQLite database path')
    migrate(parser.parse_args().database)

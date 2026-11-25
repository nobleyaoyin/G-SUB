"""Add immutable lifecycle-administration evidence; never migrate persistent Main."""
try:
    from migrations._target_safety import checked_database_target
except ModuleNotFoundError as exc:
    if exc.name != 'migrations':
        raise
    from _target_safety import checked_database_target
from importlib import import_module
from pathlib import Path
import sqlite3

MIGRATION_ID = '039_lifecycle_administration'
previous = import_module('migrations.009_account_invitation_lifecycle')
DDL = {
 'lifecycle_admin_bootstrap': '''CREATE TABLE lifecycle_admin_bootstrap (
   singleton INTEGER PRIMARY KEY CHECK(singleton=1), admin_user_id INTEGER NOT NULL UNIQUE REFERENCES users(user_id),
   lifecycle_event_id TEXT NOT NULL UNIQUE REFERENCES account_lifecycle_events(event_id),
   operator_key_sha256 TEXT NOT NULL CHECK(length(operator_key_sha256)=64 AND operator_key_sha256 NOT GLOB '*[^0-9a-f]*'),
   owner_key_sha256 TEXT NOT NULL CHECK(length(owner_key_sha256)=64 AND owner_key_sha256 NOT GLOB '*[^0-9a-f]*'),
   approval_ref TEXT NOT NULL CHECK(length(trim(approval_ref)) BETWEEN 1 AND 200),
   approval_sha256 TEXT NOT NULL UNIQUE CHECK(length(approval_sha256)=64 AND approval_sha256 NOT GLOB '*[^0-9a-f]*'),
   approval_bundle TEXT NOT NULL CHECK(length(approval_bundle) BETWEEN 1 AND 16384),
   created_at TEXT NOT NULL)''',
 'lifecycle_eic_enrollments': '''CREATE TABLE lifecycle_eic_enrollments (
   target_user_id INTEGER PRIMARY KEY REFERENCES users(user_id),
   actor_user_id INTEGER NOT NULL REFERENCES lifecycle_admin_bootstrap(admin_user_id),
   request_id TEXT NOT NULL UNIQUE CHECK(length(request_id) BETWEEN 1 AND 64),
   reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000), created_at TEXT NOT NULL)''',
 'lifecycle_administration_actions': '''CREATE TABLE lifecycle_administration_actions (
   event_id TEXT PRIMARY KEY REFERENCES account_lifecycle_events(event_id),
   target_user_id INTEGER NOT NULL REFERENCES users(user_id),
   actor_user_id INTEGER NOT NULL REFERENCES lifecycle_admin_bootstrap(admin_user_id),
   request_id TEXT NOT NULL UNIQUE CHECK(length(request_id) BETWEEN 1 AND 64),
   action TEXT NOT NULL CHECK(action IN ('activate','disable','reactivate')),
   reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000), created_at TEXT NOT NULL)''',
 'lifecycle_bootstrap_match': '''CREATE TRIGGER lifecycle_bootstrap_match BEFORE INSERT ON lifecycle_admin_bootstrap
   WHEN NOT EXISTS(SELECT 1 FROM account_lifecycle_events e JOIN users u ON u.user_id=e.user_id
    WHERE e.event_id=NEW.lifecycle_event_id AND e.user_id=NEW.admin_user_id AND e.sequence=1
    AND e.from_state IS NULL AND e.to_state='active' AND e.auth_generation=1
    AND u.role='eic') BEGIN SELECT RAISE(ABORT,'bootstrap event mismatch'); END''',
 'lifecycle_admin_action_match': '''CREATE TRIGGER lifecycle_admin_action_match BEFORE INSERT ON lifecycle_administration_actions
   WHEN NOT EXISTS(SELECT 1 FROM account_lifecycle_events e WHERE e.event_id=NEW.event_id
     AND e.user_id=NEW.target_user_id AND e.actor_user_id=NEW.actor_user_id
     AND ((NEW.action='activate' AND e.from_state IS NULL AND e.to_state='active')
       OR (NEW.action='disable' AND e.from_state='active' AND e.to_state='disabled')
       OR (NEW.action='reactivate' AND e.from_state='disabled' AND e.to_state='active')))
   BEGIN SELECT RAISE(ABORT,'administrative event mismatch'); END''',
}
for table in ('lifecycle_admin_bootstrap','lifecycle_eic_enrollments','lifecycle_administration_actions'):
 for op in ('UPDATE','DELETE'):
  DDL[f'{table}_no_{op.lower()}'] = f"CREATE TRIGGER {table}_no_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable administration history'); END"


def validate_schema(db):
 objects=previous._objects(db)
 for name, expected in DDL.items():
  if name not in objects or not objects[name][1] or previous._normalize(objects[name][1]) != previous._normalize(expected):
   raise RuntimeError('Lifecycle administration schema unavailable')
 tables={'lifecycle_admin_bootstrap','lifecycle_eic_enrollments','lifecycle_administration_actions'}
 if any(kind in ('trigger','index') and sql is not None and table in tables and name not in DDL
        for name,(kind,sql,table) in objects.items()):
  raise RuntimeError('Unexpected lifecycle administration schema object')


def migrate(path):
 path=checked_database_target(path)
 if path==(Path(__file__).resolve().parents[1]/'manuscript.db').resolve():
  raise ValueError('Persistent project database is not permitted')
 with sqlite3.connect(path.as_uri()+'?mode=rw',uri=True) as db:
  db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
  if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(previous.MIGRATION_ID,)).fetchone():raise RuntimeError('Lifecycle migration required')
  previous._validate_own_schema(previous._objects(db))
  if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone():
   if any(db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone() for name in DDL):raise RuntimeError('Conflicting administration schema')
   for statement in DDL.values():db.execute(statement)
   db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",(MIGRATION_ID,))
  validate_schema(db)
  if db.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('Foreign key violation')
  db.commit()

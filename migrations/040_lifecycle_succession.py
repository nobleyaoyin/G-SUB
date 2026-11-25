"""Append-only administrator succession; never migrates persistent Main."""
try:
    from migrations._target_safety import checked_database_target
except ModuleNotFoundError as exc:
    if exc.name != 'migrations':
        raise
    from _target_safety import checked_database_target
from importlib import import_module
from pathlib import Path
import sqlite3

MIGRATION_ID='040_lifecycle_succession'
old=import_module('migrations.039_lifecycle_administration')
normalize=import_module('migrations.009_account_invitation_lifecycle')._normalize
DDL={
 'lifecycle_admin_successions': '''CREATE TABLE lifecycle_admin_successions (
   sequence INTEGER PRIMARY KEY CHECK(sequence>0), previous_user_id INTEGER NOT NULL REFERENCES users(user_id),
   next_user_id INTEGER NOT NULL REFERENCES users(user_id), previous_digest TEXT NOT NULL,
   event_digest TEXT NOT NULL UNIQUE, owner_public_key TEXT NOT NULL, operator_key_sha256 TEXT NOT NULL,
   successor_lifecycle_event_id TEXT UNIQUE REFERENCES account_lifecycle_events(event_id),
   approval_bundle TEXT NOT NULL, created_at TEXT NOT NULL,
   CHECK(previous_user_id!=next_user_id), CHECK(length(previous_digest)=64), CHECK(length(event_digest)=64),
   CHECK(length(owner_public_key)=64), CHECK(length(operator_key_sha256)=64))''',
 'lifecycle_eic_enrollments_v2': '''CREATE TABLE lifecycle_eic_enrollments_v2 (
   target_user_id INTEGER PRIMARY KEY REFERENCES users(user_id), actor_user_id INTEGER NOT NULL REFERENCES users(user_id),
   admin_sequence INTEGER NOT NULL REFERENCES lifecycle_admin_successions(sequence),
   request_id TEXT NOT NULL UNIQUE, reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000), created_at TEXT NOT NULL)''',
 'lifecycle_administration_actions_v2': '''CREATE TABLE lifecycle_administration_actions_v2 (
   event_id TEXT PRIMARY KEY REFERENCES account_lifecycle_events(event_id), target_user_id INTEGER NOT NULL REFERENCES users(user_id),
   actor_user_id INTEGER NOT NULL REFERENCES users(user_id), admin_sequence INTEGER NOT NULL REFERENCES lifecycle_admin_successions(sequence),
   request_id TEXT NOT NULL UNIQUE, action TEXT NOT NULL CHECK(action IN ('activate','disable','reactivate')),
   reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000), created_at TEXT NOT NULL)''',
 'lifecycle_succession_enrollment_match': '''CREATE TRIGGER lifecycle_succession_enrollment_match BEFORE INSERT ON lifecycle_eic_enrollments_v2
   WHEN NOT EXISTS (SELECT 1 FROM lifecycle_admin_successions s WHERE s.sequence=NEW.admin_sequence AND s.next_user_id=NEW.actor_user_id)
   BEGIN SELECT RAISE(ABORT,'successor actor mismatch'); END''',
 'lifecycle_succession_event_match': '''CREATE TRIGGER lifecycle_succession_event_match BEFORE INSERT ON lifecycle_admin_successions
   WHEN NEW.successor_lifecycle_event_id IS NOT NULL AND NOT EXISTS (
     SELECT 1 FROM account_lifecycle_events e WHERE e.event_id=NEW.successor_lifecycle_event_id AND e.user_id=NEW.next_user_id
       AND e.to_state='active' AND e.reason_code IN ('initial_enrollment','administrative_reactivation'))
   BEGIN SELECT RAISE(ABORT,'successor lifecycle mismatch'); END''',
 'lifecycle_succession_action_match': '''CREATE TRIGGER lifecycle_succession_action_match BEFORE INSERT ON lifecycle_administration_actions_v2
   WHEN NOT EXISTS (SELECT 1 FROM account_lifecycle_events e JOIN lifecycle_admin_successions s ON s.sequence=NEW.admin_sequence
     WHERE e.event_id=NEW.event_id AND e.user_id=NEW.target_user_id AND e.actor_user_id=NEW.actor_user_id AND s.next_user_id=NEW.actor_user_id
       AND ((NEW.action='activate' AND e.from_state IS NULL AND e.to_state='active')
         OR (NEW.action='disable' AND e.from_state='active' AND e.to_state='disabled')
         OR (NEW.action='reactivate' AND e.from_state='disabled' AND e.to_state='active')))
   BEGIN SELECT RAISE(ABORT,'successor action mismatch'); END''',
}
for table in ('lifecycle_admin_successions','lifecycle_eic_enrollments_v2','lifecycle_administration_actions_v2'):
 for op in ('UPDATE','DELETE'):
  DDL[f'{table}_no_{op.lower()}']=f"CREATE TRIGGER {table}_no_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable succession history'); END"

def validate_schema(db):
 objects=import_module('migrations.009_account_invitation_lifecycle')._objects(db)
 for name,expected in DDL.items():
  if name not in objects or not objects[name][1] or normalize(objects[name][1])!=normalize(expected):raise RuntimeError('Succession schema unavailable')
 tables={'lifecycle_admin_successions','lifecycle_eic_enrollments_v2','lifecycle_administration_actions_v2'}
 if any(kind in ('trigger','index') and sql is not None and table in tables and name not in DDL for name,(kind,sql,table) in objects.items()):raise RuntimeError('Unexpected succession schema object')

def migrate(path):
 path=checked_database_target(path)
 if path==(Path(__file__).resolve().parents[1]/'manuscript.db').resolve():raise ValueError('Persistent project database is not permitted')
 with sqlite3.connect(path.as_uri()+'?mode=rw',uri=True) as db:
  db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
  if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(old.MIGRATION_ID,)).fetchone():raise RuntimeError('Administration migration required')
  old.validate_schema(db)
  if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone():
   if any(db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone() for name in DDL):raise RuntimeError('Conflicting succession schema')
   for sql in DDL.values():db.execute(sql)
   db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",(MIGRATION_ID,))
  validate_schema(db)
  if db.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('Foreign key violation')
  db.commit()

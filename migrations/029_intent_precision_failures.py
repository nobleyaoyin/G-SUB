"""Forward-only microsecond ordering and capture-failure evidence for 028."""
import argparse
from importlib import import_module
from pathlib import Path
import sqlite3

MIGRATION_ID='029_intent_precision_failures'
TIMESTAMP_GLOB='[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]Z'
DDL={
 'controlled_automatic_intents_check': f'''CREATE TRIGGER controlled_automatic_intents_check BEFORE INSERT ON controlled_automatic_intents BEGIN
    SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controlled_source_policies p JOIN users u ON u.user_id=NEW.recipient_id
      WHERE p.policy_id=NEW.policy_id AND p.mode='automatic' AND p.manuscript_id=NEW.manuscript_id
      AND p.invitation_kind=NEW.invitation_kind AND p.version=NEW.policy_version
      AND p.source_ref=NEW.source_ref AND p.source_sha256=NEW.source_sha256 AND u.role='editor'
      AND NOT EXISTS(SELECT 1 FROM controlled_source_policy_revocations r WHERE r.policy_id=p.policy_id)
      AND p.authorized_at GLOB '{TIMESTAMP_GLOB}' AND NEW.accepted_at GLOB '{TIMESTAMP_GLOB}'
      AND julianday(p.authorized_at) IS NOT NULL AND julianday(NEW.accepted_at) IS NOT NULL
      AND p.authorized_at < NEW.accepted_at COLLATE BINARY
      AND ((NEW.invitation_kind='initial' AND EXISTS(SELECT 1 FROM initial_editor_invitations i WHERE i.invitation_id=NEW.invitation_id AND i.manuscript_id=NEW.manuscript_id AND i.editor_id=NEW.recipient_id AND i.status='accepted' AND replace(i.responded_at,' ','T')||'Z'=NEW.accepted_at))
        OR (NEW.invitation_kind='final' AND EXISTS(SELECT 1 FROM final_editor_invitations i WHERE i.invitation_id=NEW.invitation_id AND i.manuscript_id=NEW.manuscript_id AND i.editor_id=NEW.recipient_id AND i.status='accepted' AND replace(i.responded_at,' ','T')||'Z'=NEW.accepted_at))))
    THEN RAISE(ABORT,'Automatic intent evidence unavailable') END;
 END''',
 'controlled_automatic_capture_failures': '''CREATE TABLE controlled_automatic_capture_failures (
    failure_id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES controlled_source_policies(policy_id) ON DELETE RESTRICT,
    manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
    invitation_kind TEXT NOT NULL CHECK(invitation_kind IN ('initial','final')),
    invitation_id INTEGER NOT NULL CHECK(invitation_id>0),
    reason_code TEXT NOT NULL CHECK(reason_code='capture_unavailable'),
    occurred_at TEXT NOT NULL,
    UNIQUE(invitation_kind,invitation_id)
 )''',
 'controlled_automatic_capture_failures_check': '''CREATE TRIGGER controlled_automatic_capture_failures_check BEFORE INSERT ON controlled_automatic_capture_failures BEGIN
    SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controlled_source_policies p
      WHERE p.policy_id=NEW.policy_id AND p.manuscript_id=NEW.manuscript_id AND p.invitation_kind=NEW.invitation_kind AND p.mode='automatic'
      AND ((NEW.invitation_kind='initial' AND EXISTS(SELECT 1 FROM initial_editor_invitations i WHERE i.invitation_id=NEW.invitation_id AND i.manuscript_id=NEW.manuscript_id AND i.status='accepted'))
        OR (NEW.invitation_kind='final' AND EXISTS(SELECT 1 FROM final_editor_invitations i WHERE i.invitation_id=NEW.invitation_id AND i.manuscript_id=NEW.manuscript_id AND i.status='accepted'))))
    THEN RAISE(ABORT,'Capture failure context unavailable') END;
 END''',
 'controlled_automatic_capture_failures_no_update': "CREATE TRIGGER controlled_automatic_capture_failures_no_update BEFORE UPDATE ON controlled_automatic_capture_failures BEGIN SELECT RAISE(ABORT,'immutable capture failure'); END",
 'controlled_automatic_capture_failures_no_delete': "CREATE TRIGGER controlled_automatic_capture_failures_no_delete BEFORE DELETE ON controlled_automatic_capture_failures BEGIN SELECT RAISE(ABORT,'immutable capture failure'); END",
}


def normalize(sql): return ' '.join(sql.strip().rstrip(';').lower().split())


def migrate(database_path):
 path=Path(database_path).resolve(strict=True)
 if not path.is_file(): raise ValueError('Existing SQLite database required')
 db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
 try:
  db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
  if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='028_automatic_distribution_intents'").fetchone(): raise RuntimeError('Migration 028 required')
  old=import_module('migrations.028_automatic_distribution_intents')
  installed=db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone()
  for name,expected in old.DDL.items():
   row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
   required=DDL[name] if installed and name=='controlled_automatic_intents_check' else expected
   if not row or normalize(row[0])!=normalize(required): raise RuntimeError('Incompatible automatic intent schema: '+name)
  if not installed:
   new_names=set(DDL)-{'controlled_automatic_intents_check'}
   if {r[0] for r in db.execute('SELECT name FROM sqlite_master')}.intersection(new_names): raise RuntimeError('Conflicting or partial precision schema')
   db.execute('DROP TRIGGER controlled_automatic_intents_check')
   for sql in DDL.values(): db.execute(sql)
   db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",(MIGRATION_ID,))
  for name,expected in DDL.items():
   row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
   if not row or normalize(row[0])!=normalize(expected): raise RuntimeError('Incompatible precision schema: '+name)
  if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key violation')
  db.commit()
 except Exception:
  db.rollback();raise
 finally: db.close()


def downgrade_empty(database_path):
 path=Path(database_path).resolve(strict=True);db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
 try:
  db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
  if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone(): raise RuntimeError('Migration not installed')
  for name,expected in DDL.items():
   row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
   if not row or normalize(row[0])!=normalize(expected): raise RuntimeError('Incompatible precision schema: '+name)
  if db.execute('SELECT 1 FROM controlled_automatic_intents LIMIT 1').fetchone() or db.execute('SELECT 1 FROM controlled_automatic_capture_failures LIMIT 1').fetchone():
   raise RuntimeError('Automatic evidence must be retained')
  db.execute('DROP TABLE controlled_automatic_capture_failures')
  db.execute('DROP TRIGGER controlled_automatic_intents_check')
  db.execute(import_module('migrations.028_automatic_distribution_intents').DDL['controlled_automatic_intents_check'])
  db.execute('DELETE FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,));db.commit()
 except Exception:
  db.rollback();raise
 finally: db.close()


if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('database');parser.add_argument('--downgrade-empty',action='store_true');args=parser.parse_args()
 (downgrade_empty if args.downgrade_empty else migrate)(args.database)

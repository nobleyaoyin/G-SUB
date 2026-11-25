"""Add isolated automatic processing evidence; preserve 021--029 objects."""
import argparse
from importlib import import_module
from pathlib import Path
import sqlite3

MIGRATION_ID='030_automatic_processing'
DDL={
 'controlled_automatic_claims': '''CREATE TABLE controlled_automatic_claims (
   intent_id TEXT PRIMARY KEY REFERENCES controlled_automatic_intents(intent_id) ON DELETE RESTRICT,
   lease_token TEXT NOT NULL, expires_us INTEGER NOT NULL CHECK(expires_us>0)
 )''',
 'controlled_automatic_processing_events': '''CREATE TABLE controlled_automatic_processing_events (
   event_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL REFERENCES controlled_automatic_intents(intent_id) ON DELETE RESTRICT,
   sequence INTEGER NOT NULL CHECK(sequence>0), state TEXT NOT NULL CHECK(state IN ('processing','failed','granted')),
   reason_code TEXT, grant_id TEXT REFERENCES distribution_grants(grant_id) ON DELETE RESTRICT,
   occurred_at TEXT NOT NULL, UNIQUE(intent_id,sequence),
   CHECK((state='processing' AND reason_code IS NULL AND grant_id IS NULL) OR
         (state='failed' AND reason_code IS NOT NULL AND grant_id IS NULL) OR
         (state='granted' AND reason_code IS NULL AND grant_id IS NOT NULL))
 )''',
 'controlled_automatic_processing_transition': '''CREATE TRIGGER controlled_automatic_processing_transition BEFORE INSERT ON controlled_automatic_processing_events BEGIN
   SELECT CASE WHEN NEW.sequence != 1+COALESCE((SELECT MAX(sequence) FROM controlled_automatic_processing_events WHERE intent_id=NEW.intent_id),0)
     THEN RAISE(ABORT,'Invalid processing sequence') END;
   SELECT CASE WHEN NEW.sequence=1 AND NEW.state!='processing' THEN RAISE(ABORT,'Processing must start first') END;
   SELECT CASE WHEN NEW.sequence>1 AND NOT EXISTS(SELECT 1 FROM controlled_automatic_processing_events e WHERE e.intent_id=NEW.intent_id AND e.sequence=NEW.sequence-1 AND ((e.state='processing' AND NEW.state IN ('processing','failed','granted')) OR (e.state='failed' AND NEW.state='processing')))
     THEN RAISE(ABORT,'Invalid processing transition') END;
 END''',
 'controlled_automatic_grant_provenance': '''CREATE TABLE controlled_automatic_grant_provenance (
   intent_id TEXT PRIMARY KEY REFERENCES controlled_automatic_intents(intent_id) ON DELETE RESTRICT,
   grant_id TEXT NOT NULL UNIQUE REFERENCES distribution_grants(grant_id) ON DELETE RESTRICT,
   manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
   policy_id TEXT NOT NULL REFERENCES controlled_source_policies(policy_id) ON DELETE RESTRICT,
   policy_version INTEGER NOT NULL CHECK(policy_version>0), source_ref TEXT NOT NULL,
   source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
   invitation_kind TEXT NOT NULL CHECK(invitation_kind IN ('initial','final')),
   invitation_id INTEGER NOT NULL, recipient_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
   authorizing_actor INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
   authorized_at TEXT NOT NULL, accepted_at TEXT NOT NULL, processed_at TEXT NOT NULL
 )''',
 'controlled_automatic_grant_provenance_check': '''CREATE TRIGGER controlled_automatic_grant_provenance_check BEFORE INSERT ON controlled_automatic_grant_provenance BEGIN
   SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controlled_automatic_intents i
     JOIN controlled_source_policies p ON p.policy_id=i.policy_id
     JOIN manuscripts m ON m.manuscript_id=i.manuscript_id
     JOIN distribution_grants g ON g.grant_id=NEW.grant_id
     JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id
     WHERE i.intent_id=NEW.intent_id AND i.manuscript_id=NEW.manuscript_id AND i.policy_id=NEW.policy_id
       AND i.policy_version=NEW.policy_version AND p.version=NEW.policy_version AND p.mode='automatic'
       AND p.actor_id=NEW.authorizing_actor AND p.authorized_at=NEW.authorized_at AND i.accepted_at=NEW.accepted_at
       AND p.authorized_at<i.accepted_at COLLATE BINARY AND p.source_ref=NEW.source_ref AND i.source_ref=NEW.source_ref
       AND m.file_path=NEW.source_ref AND p.source_sha256=NEW.source_sha256 AND i.source_sha256=NEW.source_sha256
       AND i.recipient_id=NEW.recipient_id AND i.invitation_kind=NEW.invitation_kind AND i.invitation_id=NEW.invitation_id
       AND g.manuscript_id=NEW.manuscript_id AND g.recipient_id=NEW.recipient_id AND g.actor_id=NEW.authorizing_actor
       AND a.manuscript_id=NEW.manuscript_id AND a.kind='editor_source' AND a.sha256=NEW.source_sha256
       AND ((NEW.invitation_kind='initial' AND g.initial_invitation_id=NEW.invitation_id) OR (NEW.invitation_kind='final' AND g.final_invitation_id=NEW.invitation_id))
       AND NOT EXISTS(SELECT 1 FROM controlled_source_policy_revocations r WHERE r.policy_id=p.policy_id)
       AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=g.grant_id))
     THEN RAISE(ABORT,'Automatic grant provenance mismatch') END;
 END''',
 'controlled_automatic_processing_granted_check': '''CREATE TRIGGER controlled_automatic_processing_granted_check BEFORE INSERT ON controlled_automatic_processing_events WHEN NEW.state='granted' BEGIN
   SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controlled_automatic_grant_provenance p
     WHERE p.intent_id=NEW.intent_id AND p.grant_id=NEW.grant_id
       AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=p.grant_id)
       AND NOT EXISTS(SELECT 1 FROM controlled_source_policy_revocations r WHERE r.policy_id=p.policy_id))
     THEN RAISE(ABORT,'Automatic grant evidence unavailable') END;
 END''',
}
for table in ('controlled_automatic_processing_events','controlled_automatic_grant_provenance'):
 for operation in ('UPDATE','DELETE'):
  name=f'{table}_no_{operation.lower()}'
  DDL[name]=f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable automatic processing evidence'); END"


def normalize(sql): return ' '.join(sql.strip().rstrip(';').lower().split())


def migrate(database_path):
 path=Path(database_path).resolve(strict=True)
 if not path.is_file(): raise ValueError('Existing SQLite database required')
 db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
 try:
  db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
  if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='029_intent_precision_failures'").fetchone(): raise RuntimeError('Migration 029 required')
  for source in ('028_automatic_distribution_intents','029_intent_precision_failures'):
   module=import_module('migrations.'+source)
   for name,expected in module.DDL.items():
    if source.startswith('028') and name=='controlled_automatic_intents_check': expected=import_module('migrations.029_intent_precision_failures').DDL[name]
    row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
    if not row or normalize(row[0])!=normalize(expected): raise RuntimeError('Incompatible prior schema: '+name)
  if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone():
   if {r[0] for r in db.execute('SELECT name FROM sqlite_master')}.intersection(DDL): raise RuntimeError('Conflicting processing schema')
   for sql in DDL.values(): db.execute(sql)
   db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",(MIGRATION_ID,))
  for name,expected in DDL.items():
   row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
   if not row or normalize(row[0])!=normalize(expected): raise RuntimeError('Incompatible processing schema: '+name)
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
   if not row or normalize(row[0])!=normalize(expected): raise RuntimeError('Incompatible processing schema: '+name)
  for table in ('controlled_automatic_grant_provenance','controlled_automatic_processing_events','controlled_automatic_claims'):
   if db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone(): raise RuntimeError('Automatic processing evidence must be retained')
  for table in ('controlled_automatic_grant_provenance','controlled_automatic_processing_events','controlled_automatic_claims'): db.execute('DROP TABLE '+table)
  db.execute('DELETE FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,));db.commit()
 except Exception:
  db.rollback();raise
 finally: db.close()


if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('database');parser.add_argument('--downgrade-empty',action='store_true');args=parser.parse_args()
 (downgrade_empty if args.downgrade_empty else migrate)(args.database)

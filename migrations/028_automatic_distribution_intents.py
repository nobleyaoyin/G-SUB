"""Durable prospective acceptance intents; this migration grants no access."""
import argparse
from pathlib import Path
import sqlite3

MIGRATION_ID='028_automatic_distribution_intents'
DDL={
 'controlled_automatic_intents': '''CREATE TABLE controlled_automatic_intents (
    intent_id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES controlled_source_policies(policy_id) ON DELETE RESTRICT,
    manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
    invitation_kind TEXT NOT NULL CHECK(invitation_kind IN ('initial','final')),
    invitation_id INTEGER NOT NULL CHECK(invitation_id>0),
    recipient_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    policy_version INTEGER NOT NULL CHECK(policy_version>0),
    source_ref TEXT NOT NULL CHECK(length(source_ref)>0),
    source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
    idempotency_key TEXT NOT NULL UNIQUE,
    fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64 AND fingerprint NOT GLOB '*[^0-9a-f]*'),
    accepted_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(invitation_kind,invitation_id)
 )''',
 'controlled_automatic_intents_check': '''CREATE TRIGGER controlled_automatic_intents_check BEFORE INSERT ON controlled_automatic_intents BEGIN
    SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controlled_source_policies p JOIN users u ON u.user_id=NEW.recipient_id
      WHERE p.policy_id=NEW.policy_id AND p.mode='automatic' AND p.manuscript_id=NEW.manuscript_id
      AND p.invitation_kind=NEW.invitation_kind AND p.version=NEW.policy_version
      AND p.source_ref=NEW.source_ref AND p.source_sha256=NEW.source_sha256 AND u.role='editor'
      AND NOT EXISTS(SELECT 1 FROM controlled_source_policy_revocations r WHERE r.policy_id=p.policy_id)
      AND julianday(p.authorized_at)<julianday(NEW.accepted_at)
      AND ((NEW.invitation_kind='initial' AND EXISTS(SELECT 1 FROM initial_editor_invitations i WHERE i.invitation_id=NEW.invitation_id AND i.manuscript_id=NEW.manuscript_id AND i.editor_id=NEW.recipient_id AND i.status='accepted' AND julianday(i.responded_at)=julianday(NEW.accepted_at)))
        OR (NEW.invitation_kind='final' AND EXISTS(SELECT 1 FROM final_editor_invitations i WHERE i.invitation_id=NEW.invitation_id AND i.manuscript_id=NEW.manuscript_id AND i.editor_id=NEW.recipient_id AND i.status='accepted' AND julianday(i.responded_at)=julianday(NEW.accepted_at)))))
    THEN RAISE(ABORT,'Automatic intent evidence unavailable') END;
 END''',
 'controlled_automatic_events': '''CREATE TABLE controlled_automatic_events (
    event_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES controlled_automatic_intents(intent_id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL CHECK(sequence>0),
    state TEXT NOT NULL CHECK(state IN ('pending','processing','granted','failed','revoked')),
    reason_code TEXT,
    occurred_at TEXT NOT NULL,
    UNIQUE(intent_id,sequence)
 )''',
 'controlled_automatic_events_check': '''CREATE TRIGGER controlled_automatic_events_check BEFORE INSERT ON controlled_automatic_events BEGIN
    SELECT CASE WHEN NEW.sequence!=1 OR NEW.state!='pending' OR NEW.reason_code IS NOT NULL
      THEN RAISE(ABORT,'Automatic processing is not yet available') END;
 END''',
}
for table in ('controlled_automatic_intents','controlled_automatic_events'):
 for operation in ('UPDATE','DELETE'):
  name=f'{table}_no_{operation.lower()}'
  DDL[name]=f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable automatic evidence'); END"


def normalize(sql): return ' '.join(sql.strip().rstrip(';').lower().split())


def migrate(database_path):
 path=Path(database_path).resolve(strict=True)
 if not path.is_file(): raise ValueError('Existing SQLite database required')
 db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
 try:
  db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
  if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='027_source_grant_provenance'").fetchone(): raise RuntimeError('Migration 027 required')
  if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone():
   if {r[0] for r in db.execute('SELECT name FROM sqlite_master')}.intersection(DDL): raise RuntimeError('Conflicting or partial automatic intent schema')
   for sql in DDL.values(): db.execute(sql)
   db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",(MIGRATION_ID,))
  for name,expected in DDL.items():
   row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
   if not row or normalize(row[0])!=normalize(expected): raise RuntimeError('Incompatible automatic intent schema: '+name)
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
  if db.execute('SELECT 1 FROM controlled_automatic_intents LIMIT 1').fetchone(): raise RuntimeError('Automatic intent evidence must be retained')
  db.execute('DROP TABLE controlled_automatic_events');db.execute('DROP TABLE controlled_automatic_intents')
  db.execute('DELETE FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,));db.commit()
 except Exception:
  db.rollback();raise
 finally: db.close()


if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('database');parser.add_argument('--downgrade-empty',action='store_true');args=parser.parse_args()
 (downgrade_empty if args.downgrade_empty else migrate)(args.database)

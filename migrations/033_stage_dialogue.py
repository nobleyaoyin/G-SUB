"""Append-only stage dialogue for an explicitly scoped editorial audience."""
try:
    from migrations._target_safety import checked_database_target
except ModuleNotFoundError as exc:
    if exc.name != 'migrations':
        raise
    from _target_safety import checked_database_target
import sqlite3
from pathlib import Path

MIGRATION_ID = '033_stage_dialogue'
DDL = {
 'stage_dialogue_threads': '''CREATE TABLE stage_dialogue_threads (
 thread_id TEXT PRIMARY KEY, manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id),
 stage TEXT NOT NULL CHECK(stage IN ('initial_editing','final_editing')),
 round_kind TEXT NOT NULL CHECK(round_kind IN ('pre_review','review_round')),
 review_round INTEGER, agreement_id INTEGER REFERENCES author_agreements(agreement_id),
 decision_id INTEGER REFERENCES eic_decisions(decision_id),
 invitation_kind TEXT NOT NULL CHECK(invitation_kind IN ('initial','final')),
 invitation_id INTEGER NOT NULL, author_id INTEGER NOT NULL REFERENCES users(user_id),
 editor_id INTEGER NOT NULL REFERENCES users(user_id), eic_id INTEGER REFERENCES users(user_id),
 created_by INTEGER NOT NULL REFERENCES users(user_id), created_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open' CHECK(status='open'),
 UNIQUE(manuscript_id,invitation_kind,invitation_id),
 CHECK((stage='initial_editing' AND invitation_kind='initial' AND round_kind='pre_review' AND review_round IS NULL AND agreement_id IS NULL AND decision_id IS NULL) OR
 (stage='final_editing' AND invitation_kind='final' AND round_kind='review_round' AND review_round>0 AND agreement_id IS NOT NULL AND decision_id IS NOT NULL)))''',
 'stage_dialogue_messages': '''CREATE TABLE stage_dialogue_messages (
 message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES stage_dialogue_threads(thread_id),
 manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id), sender_id INTEGER NOT NULL REFERENCES users(user_id),
 body TEXT NOT NULL CHECK(length(trim(body)) BETWEEN 1 AND 5000), idempotency_key TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(thread_id,sender_id,idempotency_key))''',
 'stage_dialogue_thread_check': '''CREATE TRIGGER stage_dialogue_thread_check BEFORE INSERT ON stage_dialogue_threads BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM manuscripts m JOIN users a ON a.user_id=m.author_id JOIN users e ON e.user_id=NEW.editor_id
 WHERE m.manuscript_id=NEW.manuscript_id AND m.author_id=NEW.author_id AND a.role='author' AND e.role='editor'
 AND NEW.created_by IN (NEW.author_id,NEW.editor_id,NEW.eic_id) AND
 ((NEW.invitation_kind='initial' AND m.status='initial_editing' AND m.review_round=1 AND NOT EXISTS(SELECT 1 FROM review_round_files r WHERE r.manuscript_id=m.manuscript_id) AND NOT EXISTS(SELECT 1 FROM review_assignments r WHERE r.manuscript_id=m.manuscript_id)
 AND EXISTS(SELECT 1 FROM initial_editor_invitations i WHERE i.invitation_id=NEW.invitation_id AND i.manuscript_id=m.manuscript_id AND i.editor_id=NEW.editor_id AND i.status='accepted' AND (NEW.eic_id IS NULL OR i.invited_by=NEW.eic_id)))
 OR (NEW.invitation_kind='final' AND m.status='final_editing' AND m.review_round=NEW.review_round
 AND EXISTS(SELECT 1 FROM final_editor_invitations i WHERE i.invitation_id=NEW.invitation_id AND i.manuscript_id=m.manuscript_id AND i.editor_id=NEW.editor_id AND i.status='accepted' AND (NEW.eic_id IS NULL OR i.invited_by=NEW.eic_id))
 AND EXISTS(SELECT 1 FROM author_agreements a JOIN eic_decisions d ON d.decision_id=a.decision_id WHERE a.agreement_id=NEW.agreement_id AND a.agreement_id=(SELECT MAX(z.agreement_id) FROM author_agreements z WHERE z.manuscript_id=m.manuscript_id) AND a.manuscript_id=m.manuscript_id AND a.author_id=m.author_id AND a.status='accepted' AND d.decision_id=NEW.decision_id AND d.manuscript_id=m.manuscript_id AND d.decision='accept' AND d.review_round=NEW.review_round)))
 AND NOT EXISTS(SELECT 1 FROM editor_invitation_revocations r WHERE r.invitation_kind=NEW.invitation_kind AND r.invitation_id=NEW.invitation_id)
 AND (NEW.eic_id IS NULL OR EXISTS(SELECT 1 FROM users u WHERE u.user_id=NEW.eic_id AND u.role IN ('eic','chief_editor','editor_in_chief')))) THEN RAISE(ABORT,'Dialogue assignment unavailable') END; END''',
 'stage_dialogue_message_check': '''CREATE TRIGGER stage_dialogue_message_check BEFORE INSERT ON stage_dialogue_messages BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM stage_dialogue_threads t WHERE t.thread_id=NEW.thread_id AND t.manuscript_id=NEW.manuscript_id AND NEW.sender_id IN (t.author_id,t.editor_id,t.eic_id)) THEN RAISE(ABORT,'Dialogue audience unavailable') END; END''',
 'stage_dialogue_thread_index': 'CREATE INDEX stage_dialogue_thread_index ON stage_dialogue_threads(manuscript_id,stage,review_round)',
 'stage_dialogue_message_index': 'CREATE INDEX stage_dialogue_message_index ON stage_dialogue_messages(thread_id,created_at,message_id)',
}
for table in ('stage_dialogue_threads','stage_dialogue_messages'):
 for op in ('UPDATE','DELETE'):
  name=f'{table}_no_{op.lower()}'
  DDL[name]=f"CREATE TRIGGER {name} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable dialogue evidence'); END"

def normalize(sql):
 return ' '.join(sql.strip().rstrip(';').lower().split())

def migrate(database):
 path=checked_database_target(database)
 if path == (Path(__file__).resolve().parents[1]/'manuscript.db').resolve():
  raise ValueError('Persistent Main database is not permitted')
 with sqlite3.connect(path.as_uri()+'?mode=rw',uri=True) as db:
  db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
  if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='031_editor_invitation_revocation'").fetchone():raise RuntimeError('Migration 031 required')
  if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone():
   if any(db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone() for name in DDL):raise RuntimeError('Partial dialogue schema')
   for sql in DDL.values():db.execute(sql)
   db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",(MIGRATION_ID,))
  for name,sql in DDL.items():
   row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
   if not row or not row[0] or normalize(row[0])!=normalize(sql):raise RuntimeError('Incompatible dialogue schema')
  if db.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('Foreign key violation')
  db.commit()

def downgrade_empty(database):
 path=checked_database_target(database)
 if path==(Path(__file__).resolve().parents[1]/'manuscript.db').resolve():raise ValueError('Persistent Main database is not permitted')
 with sqlite3.connect(path.as_uri()+'?mode=rw',uri=True) as db:
  db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
  if db.execute('SELECT 1 FROM stage_dialogue_threads LIMIT 1').fetchone():raise RuntimeError('Dialogue history must be retained')
  db.execute('DROP TABLE stage_dialogue_messages');db.execute('DROP TABLE stage_dialogue_threads')
  db.execute('DELETE FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,));db.commit()

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('database');p.add_argument('--downgrade-empty',action='store_true');a=p.parse_args()
 (downgrade_empty if a.downgrade_empty else migrate)(a.database)

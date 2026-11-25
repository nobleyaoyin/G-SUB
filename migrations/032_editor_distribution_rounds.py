"""Add prospective editor round evidence without rewriting existing grants."""
import sqlite3
from pathlib import Path
MIGRATION_ID='032_editor_distribution_rounds'
DDL={
 'editor_distribution_legacy_grants':'''CREATE TABLE editor_distribution_legacy_grants (
 grant_id TEXT PRIMARY KEY REFERENCES distribution_grants(grant_id) ON DELETE RESTRICT)''',
 'editor_distribution_legacy_grants_no_insert':"CREATE TRIGGER editor_distribution_legacy_grants_no_insert BEFORE INSERT ON editor_distribution_legacy_grants BEGIN SELECT RAISE(ABORT,'legacy grant set is sealed'); END",
 'editor_distribution_intent_rounds':'''CREATE TABLE editor_distribution_intent_rounds (
 intent_id TEXT PRIMARY KEY REFERENCES controlled_automatic_intents(intent_id) ON DELETE RESTRICT,
 manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
 round_kind TEXT NOT NULL CHECK(round_kind IN ('pre_review','review_round')),
 review_round INTEGER CHECK(review_round>0),
 agreement_id INTEGER REFERENCES author_agreements(agreement_id) ON DELETE RESTRICT,
 decision_id INTEGER REFERENCES eic_decisions(decision_id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL,
 CHECK((round_kind='pre_review' AND review_round IS NULL AND agreement_id IS NULL AND decision_id IS NULL) OR
 (round_kind='review_round' AND review_round IS NOT NULL AND agreement_id IS NOT NULL AND decision_id IS NOT NULL)))''',
 'editor_distribution_grant_rounds':'''CREATE TABLE editor_distribution_grant_rounds (
 grant_id TEXT PRIMARY KEY REFERENCES distribution_grants(grant_id) ON DELETE RESTRICT,
 intent_id TEXT UNIQUE REFERENCES controlled_automatic_intents(intent_id) ON DELETE RESTRICT,
 manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
 round_kind TEXT NOT NULL CHECK(round_kind IN ('pre_review','review_round')),
 review_round INTEGER CHECK(review_round>0),
 agreement_id INTEGER REFERENCES author_agreements(agreement_id) ON DELETE RESTRICT,
 decision_id INTEGER REFERENCES eic_decisions(decision_id) ON DELETE RESTRICT,
 source_ref TEXT NOT NULL, source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 artifact_version INTEGER NOT NULL CHECK(artifact_version>0),
 recipient_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
 invitation_kind TEXT NOT NULL CHECK(invitation_kind IN ('initial','final')),
 invitation_id INTEGER NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('manual','automatic')),
 actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
 idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL,
 CHECK((round_kind='pre_review' AND review_round IS NULL AND agreement_id IS NULL AND decision_id IS NULL) OR
 (round_kind='review_round' AND review_round IS NOT NULL AND agreement_id IS NOT NULL AND decision_id IS NOT NULL)),
 CHECK((mode='manual' AND intent_id IS NULL) OR (mode='automatic' AND intent_id IS NOT NULL)))''',
 'editor_distribution_intent_rounds_check':'''CREATE TRIGGER editor_distribution_intent_rounds_check BEFORE INSERT ON editor_distribution_intent_rounds BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM controlled_automatic_intents i JOIN manuscripts m ON m.manuscript_id=i.manuscript_id WHERE i.intent_id=NEW.intent_id AND i.manuscript_id=NEW.manuscript_id AND
 ((i.invitation_kind='initial' AND m.status='initial_editing' AND m.review_round=1 AND NEW.round_kind='pre_review' AND NOT EXISTS(SELECT 1 FROM review_round_files r WHERE r.manuscript_id=m.manuscript_id) AND NOT EXISTS(SELECT 1 FROM review_assignments a WHERE a.manuscript_id=m.manuscript_id)) OR
 (i.invitation_kind='final' AND m.status='final_editing' AND NEW.round_kind='review_round' AND EXISTS(SELECT 1 FROM author_agreements a JOIN eic_decisions d ON d.decision_id=a.decision_id WHERE a.agreement_id=NEW.agreement_id AND a.agreement_id=(SELECT MAX(z.agreement_id) FROM author_agreements z WHERE z.manuscript_id=m.manuscript_id) AND a.manuscript_id=m.manuscript_id AND a.author_id=m.author_id AND a.status='accepted' AND d.decision_id=NEW.decision_id AND d.manuscript_id=m.manuscript_id AND d.decision='accept' AND d.review_round=NEW.review_round AND m.review_round=NEW.review_round)))) THEN RAISE(ABORT,'Intent round unavailable') END; END''',
 'editor_distribution_grant_rounds_check':'''CREATE TRIGGER editor_distribution_grant_rounds_check BEFORE INSERT ON editor_distribution_grant_rounds BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id JOIN manuscripts m ON m.manuscript_id=g.manuscript_id WHERE g.grant_id=NEW.grant_id AND g.manuscript_id=NEW.manuscript_id AND g.recipient_id=NEW.recipient_id AND g.actor_id=NEW.actor_id AND g.idempotency_key=NEW.idempotency_key AND a.version=NEW.artifact_version AND a.sha256=NEW.source_sha256 AND m.file_path=NEW.source_ref AND
 ((NEW.invitation_kind='initial' AND m.status='initial_editing' AND m.review_round=1 AND g.initial_invitation_id=NEW.invitation_id AND NEW.round_kind='pre_review' AND NOT EXISTS(SELECT 1 FROM review_round_files r WHERE r.manuscript_id=m.manuscript_id) AND NOT EXISTS(SELECT 1 FROM review_assignments x WHERE x.manuscript_id=m.manuscript_id)) OR
 (NEW.invitation_kind='final' AND m.status='final_editing' AND g.final_invitation_id=NEW.invitation_id AND NEW.round_kind='review_round' AND EXISTS(SELECT 1 FROM author_agreements x JOIN eic_decisions d ON d.decision_id=x.decision_id WHERE x.agreement_id=NEW.agreement_id AND x.agreement_id=(SELECT MAX(z.agreement_id) FROM author_agreements z WHERE z.manuscript_id=m.manuscript_id) AND x.manuscript_id=m.manuscript_id AND x.author_id=m.author_id AND x.status='accepted' AND d.decision_id=NEW.decision_id AND d.manuscript_id=m.manuscript_id AND d.decision='accept' AND d.review_round=NEW.review_round AND m.review_round=NEW.review_round))) AND
 ((NEW.mode='manual' AND NEW.intent_id IS NULL) OR (NEW.mode='automatic' AND EXISTS(SELECT 1 FROM controlled_automatic_grant_provenance p JOIN editor_distribution_intent_rounds ir ON ir.intent_id=p.intent_id WHERE p.grant_id=g.grant_id AND p.intent_id=NEW.intent_id AND ir.manuscript_id=NEW.manuscript_id AND ir.round_kind=NEW.round_kind AND ir.review_round IS NEW.review_round AND ir.agreement_id IS NEW.agreement_id AND ir.decision_id IS NEW.decision_id)))) THEN RAISE(ABORT,'Grant round unavailable') END; END''',
}
for table in ('editor_distribution_legacy_grants','editor_distribution_intent_rounds','editor_distribution_grant_rounds'):
 for op in ('UPDATE','DELETE'):
  name=f'{table}_no_{op.lower()}'
  DDL[name]=f"CREATE TRIGGER {name} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable round evidence'); END"
def normalize(sql):return ' '.join(sql.strip().rstrip(';').lower().split())
def migrate(database):
 path=Path(database).resolve(strict=True)
 with sqlite3.connect(path.as_uri()+'?mode=rw',uri=True) as db:
  db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
  if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='031_editor_invitation_revocation'").fetchone():raise RuntimeError('Migration 031 required')
  if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone():
   if any(db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone() for name in DDL):raise RuntimeError('Partial round schema')
   for name,sql in DDL.items():
    if name!='editor_distribution_legacy_grants_no_insert':db.execute(sql)
   db.execute('INSERT INTO editor_distribution_legacy_grants SELECT grant_id FROM distribution_grants')
   db.execute(DDL['editor_distribution_legacy_grants_no_insert'])
   db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",(MIGRATION_ID,))
  for name,expected in DDL.items():
   row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
   if not row or normalize(row[0])!=normalize(expected):raise RuntimeError('Incompatible round schema')
  if db.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('Foreign key violation')
  db.commit()
def downgrade_empty(database):
 with sqlite3.connect(Path(database).resolve(strict=True).as_uri()+'?mode=rw',uri=True) as db:
  db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
  if db.execute('SELECT 1 FROM editor_distribution_grant_rounds LIMIT 1').fetchone() or db.execute('SELECT 1 FROM editor_distribution_intent_rounds LIMIT 1').fetchone():raise RuntimeError('Round evidence must be retained')
  for table in ('editor_distribution_grant_rounds','editor_distribution_intent_rounds','editor_distribution_legacy_grants'):db.execute('DROP TABLE '+table)
  db.execute('DELETE FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,));db.commit()

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description='Explicit editor distribution round evidence migration')
 parser.add_argument('database');parser.add_argument('--downgrade-empty',action='store_true')
 args=parser.parse_args()
 (downgrade_empty if args.downgrade_empty else migrate)(args.database)

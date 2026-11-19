"""Distribution schema; do not apply to persistent databases without review.

The connected service has isolated coverage but still needs independent security
and migration review before deployment. Never runs at application startup.
"""
import argparse
import sqlite3
from pathlib import Path

MIGRATION_ID = '021_document_distribution'
DDL = {
 'distribution_reservations': '''CREATE TABLE distribution_reservations (
    storage_id TEXT PRIMARY KEY CHECK(length(storage_id)=32 AND storage_id NOT GLOB '*[^0-9a-f]*'),
    manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
    actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK(kind IN ('editor_source','reviewed_document')),
    review_assignment_id INTEGER REFERENCES review_assignments(assignment_id) ON DELETE RESTRICT,
    review_round INTEGER CHECK(review_round>0),
    sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    byte_size INTEGER NOT NULL CHECK(byte_size BETWEEN 1 AND 10485760),
    format TEXT NOT NULL CHECK(format IN ('pdf','docx','doc','txt')),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 16 AND 128),
    request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint)=64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'),
    created_at TEXT NOT NULL,
    UNIQUE(actor_id,idempotency_key),
    CHECK((kind='editor_source' AND review_assignment_id IS NULL AND review_round IS NULL) OR
          (kind='reviewed_document' AND review_assignment_id IS NOT NULL AND review_round IS NOT NULL))
 )''',
 'distribution_artifacts': '''CREATE TABLE distribution_artifacts (
    artifact_id TEXT PRIMARY KEY CHECK(length(artifact_id)=32 AND artifact_id NOT GLOB '*[^0-9a-f]*'),
    manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK(kind IN ('editor_source','reviewed_document')),
    version INTEGER NOT NULL CHECK(version>0),
    storage_id TEXT NOT NULL UNIQUE REFERENCES distribution_reservations(storage_id) ON DELETE RESTRICT CHECK(length(storage_id)=32 AND storage_id NOT GLOB '*[^0-9a-f]*'),
    sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    byte_size INTEGER NOT NULL CHECK(byte_size BETWEEN 1 AND 10485760),
    format TEXT NOT NULL CHECK(format IN ('pdf','docx','doc','txt')),
    review_assignment_id INTEGER REFERENCES review_assignments(assignment_id) ON DELETE RESTRICT,
    review_round INTEGER CHECK(review_round>0),
    created_by INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    CHECK((kind='editor_source' AND review_assignment_id IS NULL AND review_round IS NULL) OR
          (kind='reviewed_document' AND review_assignment_id IS NOT NULL AND review_round IS NOT NULL)),
    UNIQUE(manuscript_id,kind,review_assignment_id,version),
    UNIQUE(artifact_id,manuscript_id)
 )''',
 'distribution_grants': '''CREATE TABLE distribution_grants (
    grant_id TEXT PRIMARY KEY CHECK(length(grant_id)=32 AND grant_id NOT GLOB '*[^0-9a-f]*'),
    manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
    artifact_id TEXT NOT NULL,
    recipient_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    recipient_role TEXT NOT NULL CHECK(recipient_role IN ('editor','reviewer')),
    initial_invitation_id INTEGER REFERENCES initial_editor_invitations(invitation_id) ON DELETE RESTRICT,
    final_invitation_id INTEGER REFERENCES final_editor_invitations(invitation_id) ON DELETE RESTRICT,
    review_assignment_id INTEGER REFERENCES review_assignments(assignment_id) ON DELETE RESTRICT,
    review_round INTEGER CHECK(review_round>0),
    actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    mode TEXT NOT NULL CHECK(mode='manual'),
    notification_state TEXT NOT NULL CHECK(notification_state IN ('created','not_requested')),
    email_state TEXT NOT NULL CHECK(email_state='not_requested'),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 16 AND 128),
    fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64 AND fingerprint NOT GLOB '*[^0-9a-f]*'),
    created_at TEXT NOT NULL,
    CHECK((recipient_role='editor' AND review_assignment_id IS NULL AND review_round IS NULL AND
           ((initial_invitation_id IS NOT NULL AND final_invitation_id IS NULL) OR
            (initial_invitation_id IS NULL AND final_invitation_id IS NOT NULL))) OR
          (recipient_role='reviewer' AND review_assignment_id IS NOT NULL AND review_round IS NOT NULL AND initial_invitation_id IS NULL AND final_invitation_id IS NULL)),
    UNIQUE(actor_id,idempotency_key),
    FOREIGN KEY(artifact_id,manuscript_id) REFERENCES distribution_artifacts(artifact_id,manuscript_id) ON DELETE RESTRICT
 )''',
 'distribution_revocations': '''CREATE TABLE distribution_revocations (
    grant_id TEXT PRIMARY KEY REFERENCES distribution_grants(grant_id) ON DELETE RESTRICT,
    actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000),
    created_at TEXT NOT NULL
 )''',
 'ix_distribution_grants_manuscript': 'CREATE INDEX ix_distribution_grants_manuscript ON distribution_grants(manuscript_id,created_at,grant_id)',
 'ix_distribution_grants_recipient': 'CREATE INDEX ix_distribution_grants_recipient ON distribution_grants(recipient_id,created_at,grant_id)',
 'uq_distribution_editor_version': "CREATE UNIQUE INDEX uq_distribution_editor_version ON distribution_artifacts(manuscript_id,version) WHERE kind='editor_source'",
 'uq_distribution_initial_grant': 'CREATE UNIQUE INDEX uq_distribution_initial_grant ON distribution_grants(artifact_id,recipient_id,initial_invitation_id) WHERE initial_invitation_id IS NOT NULL',
 'uq_distribution_final_grant': 'CREATE UNIQUE INDEX uq_distribution_final_grant ON distribution_grants(artifact_id,recipient_id,final_invitation_id) WHERE final_invitation_id IS NOT NULL',
 'uq_distribution_reviewer_grant': 'CREATE UNIQUE INDEX uq_distribution_reviewer_grant ON distribution_grants(artifact_id,recipient_id,review_assignment_id) WHERE review_assignment_id IS NOT NULL',
 'distribution_artifacts_validate_reservation': '''CREATE TRIGGER distribution_artifacts_validate_reservation BEFORE INSERT ON distribution_artifacts BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM distribution_reservations r WHERE r.storage_id=NEW.storage_id
      AND r.manuscript_id=NEW.manuscript_id AND r.actor_id=NEW.created_by AND r.kind=NEW.kind
      AND r.review_assignment_id IS NEW.review_assignment_id AND r.review_round IS NEW.review_round
      AND r.sha256=NEW.sha256 AND r.byte_size=NEW.byte_size AND r.format=NEW.format)
      THEN RAISE(ABORT,'Reservation mismatch') END;
 END''',
 'distribution_grants_validate_editor': '''CREATE TRIGGER distribution_grants_validate_editor BEFORE INSERT ON distribution_grants BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM users WHERE user_id=NEW.actor_id AND role='eic')
      THEN RAISE(ABORT,'EIC required') END;
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM users WHERE user_id=NEW.recipient_id AND role=NEW.recipient_role)
      THEN RAISE(ABORT,'Recipient role mismatch') END;
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM manuscripts WHERE manuscript_id=NEW.manuscript_id AND status!='draft')
      THEN RAISE(ABORT,'Manuscript unavailable') END;
    SELECT CASE WHEN NEW.recipient_role='reviewer' THEN RAISE(ABORT,'Reviewer grants unavailable') END;
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM distribution_artifacts WHERE artifact_id=NEW.artifact_id AND manuscript_id=NEW.manuscript_id AND kind='editor_source')
      THEN RAISE(ABORT,'Artifact unavailable') END;
    SELECT CASE WHEN NEW.initial_invitation_id IS NOT NULL AND NOT EXISTS
      (SELECT 1 FROM initial_editor_invitations WHERE invitation_id=NEW.initial_invitation_id AND manuscript_id=NEW.manuscript_id AND editor_id=NEW.recipient_id AND status='accepted')
      THEN RAISE(ABORT,'Initial invitation unavailable') END;
    SELECT CASE WHEN NEW.final_invitation_id IS NOT NULL AND NOT EXISTS
      (SELECT 1 FROM final_editor_invitations WHERE invitation_id=NEW.final_invitation_id AND manuscript_id=NEW.manuscript_id AND editor_id=NEW.recipient_id AND status='accepted')
      THEN RAISE(ABORT,'Final invitation unavailable') END;
 END''',
}
for table in ('distribution_reservations','distribution_artifacts','distribution_grants','distribution_revocations'):
 for operation in ('UPDATE','DELETE'):
  name=f'{table}_no_{operation.lower()}'
  DDL[name]=f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable distribution history'); END"


def _normalize(sql): return ' '.join(sql.strip().rstrip(';').lower().split())


def migrate(database_path):
 path=Path(database_path).resolve(strict=True)
 if not path.is_file(): raise ValueError('Existing SQLite database required')
 db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
 try:
  db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
  tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  required={'schema_migrations','users','manuscripts','initial_editor_invitations','final_editor_invitations','review_assignments'}
  if not required.issubset(tables): raise RuntimeError('Required schema unavailable')
  if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='019_personal_notes'").fetchone(): raise RuntimeError('Migration 019 required')
  applied=db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone()
  existing={r[0] for r in db.execute("SELECT name FROM sqlite_master")}.intersection(DDL)
  if not applied:
   if existing: raise RuntimeError('Conflicting or partial distribution schema')
   for sql in DDL.values(): db.execute(sql)
   db.execute("INSERT INTO schema_migrations (migration_id,applied_at) VALUES (?,datetime('now'))",(MIGRATION_ID,))
  for name,sql in DDL.items():
   found=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
   if not found or _normalize(found[0])!=_normalize(sql): raise RuntimeError('Incompatible distribution schema: '+name)
  if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key violation')
  db.commit()
 except Exception:
  db.rollback(); raise
 finally: db.close()


def downgrade_empty(database_path):
 """Remove only an unused schema; once evidence exists disable feature instead."""
 path=Path(database_path).resolve(strict=True); db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
 try:
  db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
  if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone(): raise RuntimeError('Migration not installed')
  for table in ('distribution_reservations','distribution_artifacts','distribution_grants','distribution_revocations'):
   if db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone(): raise RuntimeError('Distribution history must be retained')
  for table in ('distribution_revocations','distribution_grants','distribution_artifacts','distribution_reservations'): db.execute('DROP TABLE '+table)
  db.execute('DELETE FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)); db.commit()
 except Exception:
  db.rollback(); raise
 finally: db.close()

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('database');parser.add_argument('--downgrade-empty',action='store_true');args=parser.parse_args()
 (downgrade_empty if args.downgrade_empty else migrate)(args.database)

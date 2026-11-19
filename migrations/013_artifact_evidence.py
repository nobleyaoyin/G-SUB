"""Add disconnected artifact evidence; explicit existing SQLite path only."""
import argparse
from importlib import import_module
from pathlib import Path
import sqlite3

MIGRATION_ID = '013_artifact_evidence'
prior = import_module('migrations.012_reviewer_artifacts')
normalize = prior.normalize
DDL = {
    'source_provenance_evidence': """CREATE TABLE source_provenance_evidence (
        evidence_id TEXT NOT NULL PRIMARY KEY CHECK(length(evidence_id)=32 AND evidence_id NOT GLOB '*[^0-9a-f]*'),
        manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id),
        review_round INTEGER NOT NULL CHECK(typeof(review_round)='integer' AND review_round>=1),
        source_round_file_id INTEGER NOT NULL REFERENCES review_round_files(round_file_id),
        source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
        byte_size INTEGER NOT NULL CHECK(typeof(byte_size)='integer' AND byte_size BETWEEN 1 AND 10485760),
        format TEXT NOT NULL CHECK(format IN ('pdf','docx','doc','txt')),
        confirmation_id INTEGER REFERENCES pre_review_confirmations(confirmation_id),
        submission_id INTEGER REFERENCES initial_editing_submissions(submission_id),
        eic_approver_id INTEGER REFERENCES users(user_id),
        proof_reference TEXT NOT NULL UNIQUE CHECK(length(proof_reference)=32 AND proof_reference NOT GLOB '*[^0-9a-f]*'),
        captured_by INTEGER NOT NULL REFERENCES users(user_id),
        captured_at TEXT NOT NULL CHECK(length(captured_at)=27),
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>=1),
        CHECK((review_round=1 AND confirmation_id IS NOT NULL AND submission_id IS NOT NULL AND eic_approver_id IS NOT NULL) OR (review_round>1 AND confirmation_id IS NULL AND submission_id IS NULL AND eic_approver_id IS NULL)),
        UNIQUE(source_round_file_id,revision)
    )""",
    'artifact_approval_evidence': """CREATE TABLE artifact_approval_evidence (
        evidence_id TEXT NOT NULL PRIMARY KEY CHECK(length(evidence_id)=32 AND evidence_id NOT GLOB '*[^0-9a-f]*'),
        artifact_id TEXT NOT NULL REFERENCES reviewer_artifacts(artifact_id),
        approval_event_id TEXT NOT NULL UNIQUE REFERENCES reviewer_artifact_events(event_id),
        source_evidence_id TEXT NOT NULL REFERENCES source_provenance_evidence(evidence_id),
        artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64 AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'),
        artifact_state_revision INTEGER NOT NULL CHECK(typeof(artifact_state_revision)='integer' AND artifact_state_revision>=2),
        approver_id INTEGER NOT NULL REFERENCES users(user_id),
        attested_at TEXT NOT NULL CHECK(length(attested_at)=27),
        checklist_key TEXT NOT NULL CHECK(checklist_key='reviewer_document'),
        checklist_version INTEGER NOT NULL CHECK(typeof(checklist_version)='integer' AND checklist_version=1),
        acknowledged INTEGER NOT NULL CHECK(acknowledged=1),
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>=1),
        UNIQUE(artifact_id,revision)
    )""",
    'ix_source_evidence_source': 'CREATE INDEX ix_source_evidence_source ON source_provenance_evidence(source_round_file_id,revision)',
    'ix_approval_evidence_source': 'CREATE INDEX ix_approval_evidence_source ON artifact_approval_evidence(source_evidence_id)',
    'source_evidence_check': """CREATE TRIGGER source_evidence_check BEFORE INSERT ON source_provenance_evidence
      WHEN NEW.revision<>COALESCE((SELECT MAX(revision)+1 FROM source_provenance_evidence WHERE source_round_file_id=NEW.source_round_file_id),1)
      OR NOT EXISTS (SELECT 1 FROM review_round_files r WHERE r.round_file_id=NEW.source_round_file_id AND r.manuscript_id=NEW.manuscript_id AND r.review_round=NEW.review_round
       AND ((r.review_round=1 AND r.source_kind='initial_editing' AND r.confirmation_id=NEW.confirmation_id AND EXISTS
         (SELECT 1 FROM pre_review_confirmations c JOIN initial_editing_submissions s ON s.submission_id=c.submission_id JOIN manuscripts m ON m.manuscript_id=c.manuscript_id
          WHERE c.confirmation_id=NEW.confirmation_id AND c.submission_id=NEW.submission_id AND c.manuscript_id=r.manuscript_id AND c.author_id=m.author_id AND c.decision='confirm' AND c.confirmed_at IS NOT NULL AND c.file_path=r.file_path AND s.file_path=r.file_path AND s.manuscript_id=r.manuscript_id AND s.status='eic_approved' AND s.eic_approved_by=NEW.eic_approver_id AND s.eic_reviewed_at IS NOT NULL))
       OR (r.review_round>1 AND r.source_kind='author_revision' AND r.confirmation_id IS NULL)))
      BEGIN SELECT RAISE(ABORT,'source evidence mismatch'); END""",
    'approval_evidence_check': """CREATE TRIGGER approval_evidence_check BEFORE INSERT ON artifact_approval_evidence
      WHEN NEW.revision<>1 OR NOT EXISTS (SELECT 1 FROM reviewer_artifacts a JOIN reviewer_artifact_events e ON e.event_id=NEW.approval_event_id
        JOIN source_provenance_evidence s ON s.evidence_id=NEW.source_evidence_id
        WHERE a.artifact_id=NEW.artifact_id AND a.status='approved' AND a.current_event_id=e.event_id AND e.artifact_id=a.artifact_id AND e.action='approved'
        AND e.actor_id=NEW.approver_id AND e.occurred_at=NEW.attested_at AND e.revision=NEW.artifact_state_revision AND a.artifact_sha256=NEW.artifact_sha256
        AND s.source_round_file_id=a.source_round_file_id AND s.manuscript_id=a.manuscript_id AND s.review_round=a.review_round AND s.source_sha256=a.source_sha256
        AND s.revision=(SELECT MAX(x.revision) FROM source_provenance_evidence x WHERE x.source_round_file_id=s.source_round_file_id))
      BEGIN SELECT RAISE(ABORT,'approval evidence mismatch'); END""",
    'source_evidence_no_update': "CREATE TRIGGER source_evidence_no_update BEFORE UPDATE ON source_provenance_evidence BEGIN SELECT RAISE(ABORT,'source evidence is append-only'); END",
    'source_evidence_no_delete': "CREATE TRIGGER source_evidence_no_delete BEFORE DELETE ON source_provenance_evidence BEGIN SELECT RAISE(ABORT,'source evidence is append-only'); END",
    'approval_evidence_no_update': "CREATE TRIGGER approval_evidence_no_update BEFORE UPDATE ON artifact_approval_evidence BEGIN SELECT RAISE(ABORT,'approval evidence is append-only'); END",
    'approval_evidence_no_delete': "CREATE TRIGGER approval_evidence_no_delete BEFORE DELETE ON artifact_approval_evidence BEGIN SELECT RAISE(ABORT,'approval evidence is append-only'); END",
}


def validate_schema(db):
    objects = {n:(k,s) for n,k,s in db.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view','index','trigger')")}
    for name, sql in DDL.items():
        kind='trigger' if sql.startswith('CREATE TRIGGER') else 'index' if sql.startswith('CREATE INDEX') else 'table'
        actual=objects.get(name)
        if not actual or actual[0]!=kind or not actual[1] or normalize(actual[1])!=normalize(sql): raise RuntimeError('Evidence schema incompatible')
    extra=db.execute("SELECT name FROM sqlite_master WHERE tbl_name IN ('source_provenance_evidence','artifact_approval_evidence') AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
    if any(r[0] not in DDL for r in extra): raise RuntimeError('Unexpected evidence schema object')


def migrate(path):
    path=Path(path).resolve(strict=True)
    if not path.is_file(): raise ValueError('Existing SQLite file required')
    db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
        objects={n:(k,s) for n,k,s in db.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view','index','trigger')")}
        if objects.get('schema_migrations',(None,))[0]!='table' or {r[1] for r in db.execute('PRAGMA table_info(schema_migrations)')}!={'migration_id','applied_at'}: raise RuntimeError('Invalid migration ledger')
        ledger={r[0] for r in db.execute('SELECT migration_id FROM schema_migrations')}
        required=set(prior.prior.PREREQUISITES+(prior.prior.MIGRATION_ID,prior.MIGRATION_ID))
        if not required.issubset(ledger): raise RuntimeError('Required migrations missing')
        for name in prior.prior.PREREQUISITES:
            declared=import_module('migrations.'+name).DDL
            if isinstance(declared,str): declared={{'002_reviewer_invitations':'reviewer_invitations','003_two_reviewer_policy':'manuscript_review_policies','004_author_agreements':'author_agreements'}[name]:declared}
            for obj,expected in declared.items():
                if obj not in objects or not objects[obj][1] or normalize(objects[obj][1])!=normalize(expected): raise RuntimeError('Incompatible prerequisite')
        prior.prior.validate_schema(db); prior.validate_schema(db)
        if '010_reviewer_profiles' in ledger:
            actual=objects.get('reviewer_profiles'); expected=import_module('migrations.010_reviewer_profiles').DDL
            if not actual or actual[0]!='table' or not actual[1] or normalize(actual[1])!=normalize(expected): raise RuntimeError('Incompatible optional profile schema')
        for table,cols in {'manuscripts':{'manuscript_id','author_id','review_round','status'},'initial_editing_submissions':{'submission_id','manuscript_id','status','eic_approved_by','eic_reviewed_at','file_path'},'pre_review_confirmations':{'confirmation_id','submission_id','author_id','manuscript_id','decision','confirmed_at','file_path'}}.items():
            if not cols.issubset({r[1] for r in db.execute(f'PRAGMA table_info({table})')}): raise RuntimeError('Incompatible base schema')
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)] or db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Integrity check failed')
        if MIGRATION_ID not in ledger:
            if any(n in objects for n in DDL): raise RuntimeError('Conflicting or partial evidence schema')
            for sql in DDL.values(): db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",(MIGRATION_ID,))
        validate_schema(db)
        if db.execute('PRAGMA foreign_key_check').fetchone() or db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]: raise RuntimeError('Integrity check failed')
        db.commit()
    except Exception:
        db.rollback(); raise
    finally: db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('database'); migrate(parser.parse_args().database)

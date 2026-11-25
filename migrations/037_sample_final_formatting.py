"""Add immutable sample Final Editing and Formatting artifact bindings."""
try:
    from migrations._target_safety import checked_database_target
except ModuleNotFoundError as exc:
    if exc.name != 'migrations':
        raise
    from _target_safety import checked_database_target
from pathlib import Path
import sqlite3

MIGRATION_ID = '037_sample_final_formatting'
DDL = {
    'sample_stage_artifacts': '''CREATE TABLE sample_stage_artifacts (
        kind TEXT NOT NULL CHECK(kind IN ('final_editing','formatting')),
        submission_id INTEGER NOT NULL,
        manuscript_id INTEGER NOT NULL REFERENCES sample_manuscripts(manuscript_id),
        actor_id INTEGER NOT NULL REFERENCES users(user_id),
        version_id TEXT NOT NULL UNIQUE, storage_identity TEXT NOT NULL UNIQUE,
        sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL CHECK(byte_size > 0 AND byte_size <= 10485760),
        file_format TEXT NOT NULL CHECK(file_format IN ('pdf','docx','doc','txt')),
        created_at TEXT NOT NULL, PRIMARY KEY(kind,submission_id))''',
    'sample_stage_artifact_binding': '''CREATE TRIGGER sample_stage_artifact_binding BEFORE INSERT ON sample_stage_artifacts
      WHEN NEW.storage_identity != ('sample:v1/' || NEW.kind || '/' || NEW.manuscript_id || '/' || NEW.version_id || '.' || NEW.file_format)
        OR (NEW.kind='final_editing' AND NOT EXISTS(
          SELECT 1 FROM final_editing_submissions s JOIN manuscripts m ON m.manuscript_id=s.manuscript_id
          JOIN final_editing_submission_invitations b ON b.submission_id=s.submission_id
          JOIN final_editor_invitations i ON i.invitation_id=b.invitation_id
          JOIN author_agreements a ON a.manuscript_id=m.manuscript_id AND a.author_id=m.author_id
          JOIN eic_decisions d ON d.decision_id=a.decision_id AND d.manuscript_id=m.manuscript_id
          WHERE s.submission_id=NEW.submission_id AND s.manuscript_id=NEW.manuscript_id
          AND s.editor_id=NEW.actor_id AND s.file_path=NEW.storage_identity AND s.status='pending_eic'
          AND i.manuscript_id=NEW.manuscript_id AND i.editor_id=NEW.actor_id AND i.status='accepted'
          AND m.status='final_editing' AND a.status='accepted' AND d.decision='accept' AND d.review_round=m.review_round))
        OR (NEW.kind='formatting' AND NOT EXISTS(
          SELECT 1 FROM formatting_submissions s JOIN manuscripts m ON m.manuscript_id=s.manuscript_id
          JOIN formatter_invitations i ON i.invitation_id=s.invitation_id
          WHERE s.submission_id=NEW.submission_id AND s.manuscript_id=NEW.manuscript_id
          AND s.file_path=NEW.storage_identity AND s.sha256=NEW.sha256 AND s.status='pending_author'
          AND i.manuscript_id=NEW.manuscript_id AND i.formatter_id=NEW.actor_id AND i.status='accepted'
          AND m.status='formatting'))
      BEGIN SELECT RAISE(ABORT,'invalid sample stage artifact binding'); END''',
    'sample_stage_no_update': '''CREATE TRIGGER sample_stage_no_update BEFORE UPDATE ON sample_stage_artifacts
      BEGIN SELECT RAISE(ABORT,'immutable sample stage artifact'); END''',
    'sample_stage_no_delete': '''CREATE TRIGGER sample_stage_no_delete BEFORE DELETE ON sample_stage_artifacts
      BEGIN SELECT RAISE(ABORT,'immutable sample stage artifact'); END''',
}


def normalize(sql):
    return ' '.join(sql.strip().rstrip(';').lower().split())


def migrate(database, *, authorize_main=False):
    path = checked_database_target(database)
    if path == (Path(__file__).resolve().parents[1] / 'manuscript.db').resolve() and not authorize_main:
        raise ValueError('Persistent Main database is not permitted')
    with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
        for prerequisite in ('035_sample_document_storage', '006_formatter_publication'):
            if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (prerequisite,)).fetchone():
                raise RuntimeError('Sample and formatting migrations required')
        installed = db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)).fetchone()
        if not installed:
            if any(db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (name,)).fetchone() for name in DDL):
                raise RuntimeError('Partial sample stage artifact schema')
            for sql in DDL.values(): db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))", (MIGRATION_ID,))
        for name, expected in DDL.items():
            row = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if not row or not row[0] or normalize(row[0]) != normalize(expected):
                raise RuntimeError('Incompatible sample stage artifact schema')
        if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key violation')
        db.commit()


def downgrade_empty(database):
    path = checked_database_target(database)
    if path == (Path(__file__).resolve().parents[1] / 'manuscript.db').resolve():
        raise ValueError('Persistent Main database is not permitted')
    with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM sample_stage_artifacts LIMIT 1').fetchone():
            raise RuntimeError('Sample stage artifact history must be retained')
        for name in ('sample_stage_artifact_binding','sample_stage_no_update','sample_stage_no_delete'):
            db.execute('DROP TRIGGER ' + name)
        db.execute('DROP TABLE sample_stage_artifacts')
        db.execute('DELETE FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)); db.commit()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('database'); parser.add_argument('--downgrade-empty', action='store_true')
    parser.add_argument('--authorize-main', action='store_true', help='Explicitly authorize migration of Main (never permits downgrade)')
    args = parser.parse_args()
    if args.downgrade_empty:
        if args.authorize_main: parser.error('--authorize-main cannot be used for downgrade')
        downgrade_empty(args.database)
    else:
        migrate(args.database, authorize_main=args.authorize_main)

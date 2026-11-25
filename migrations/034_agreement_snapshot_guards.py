"""Protect existing agreement snapshots and finalized responses additively."""
try:
    from migrations._target_safety import checked_database_target
except ModuleNotFoundError as exc:
    if exc.name != 'migrations':
        raise
    from _target_safety import checked_database_target
from pathlib import Path
import sqlite3

MIGRATION_ID = '034_agreement_snapshot_guards'
DDL = {
 'author_agreement_binding_check': '''CREATE TRIGGER author_agreement_binding_check BEFORE INSERT ON author_agreements
 WHEN NEW.status!='pending' OR NEW.responded_at IS NOT NULL OR NOT EXISTS(SELECT 1 FROM manuscripts m JOIN eic_decisions d ON d.manuscript_id=m.manuscript_id
 WHERE m.manuscript_id=NEW.manuscript_id AND m.author_id=NEW.author_id AND d.decision_id=NEW.decision_id AND d.decision='accept' AND d.review_round=m.review_round)
 BEGIN SELECT RAISE(ABORT,'agreement binding unavailable'); END''',
 'author_agreement_snapshot_immutable': '''CREATE TRIGGER author_agreement_snapshot_immutable BEFORE UPDATE ON author_agreements
 WHEN NEW.agreement_id IS NOT OLD.agreement_id OR NEW.manuscript_id IS NOT OLD.manuscript_id OR NEW.decision_id IS NOT OLD.decision_id OR NEW.author_id IS NOT OLD.author_id OR NEW.agreement_version IS NOT OLD.agreement_version OR NEW.agreement_text IS NOT OLD.agreement_text OR NEW.created_at IS NOT OLD.created_at
 BEGIN SELECT RAISE(ABORT,'immutable agreement snapshot'); END''',
 'author_agreement_response_immutable': '''CREATE TRIGGER author_agreement_response_immutable BEFORE UPDATE ON author_agreements
 WHEN OLD.status IN ('accepted','declined') AND (NEW.status IS NOT OLD.status OR NEW.responded_at IS NOT OLD.responded_at)
 BEGIN SELECT RAISE(ABORT,'immutable agreement response'); END''',
 'author_agreement_no_delete': "CREATE TRIGGER author_agreement_no_delete BEFORE DELETE ON author_agreements BEGIN SELECT RAISE(ABORT,'immutable agreement history'); END",
}


def normalize(sql):return ' '.join(sql.strip().rstrip(';').lower().split())


def migrate(database):
    path=checked_database_target(database)
    if path == (Path(__file__).resolve().parents[1]/'manuscript.db').resolve():raise ValueError('Persistent Main database is not permitted')
    with sqlite3.connect(path.as_uri()+'?mode=rw',uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='004_author_agreements'").fetchone():raise RuntimeError('Migration 004 required')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone():
            if any(db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone() for name in DDL):raise RuntimeError('Partial agreement guard schema')
            for sql in DDL.values():db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",(MIGRATION_ID,))
        for name,sql in DDL.items():
            row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
            if not row or not row[0] or normalize(row[0])!=normalize(sql):raise RuntimeError('Incompatible agreement guard schema')
        if db.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('Foreign key violation')
        db.commit()


def downgrade_empty(database):
    path=checked_database_target(database)
    if path == (Path(__file__).resolve().parents[1]/'manuscript.db').resolve():raise ValueError('Persistent Main database is not permitted')
    with sqlite3.connect(path.as_uri()+'?mode=rw',uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM author_agreements LIMIT 1').fetchone():raise RuntimeError('Agreement history must be retained')
        for name in DDL:db.execute('DROP TRIGGER '+name)
        db.execute('DELETE FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,));db.commit()


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('database');p.add_argument('--downgrade-empty',action='store_true');a=p.parse_args()
    (downgrade_empty if a.downgrade_empty else migrate)(a.database)

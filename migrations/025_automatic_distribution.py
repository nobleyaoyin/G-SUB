"""Add inert evidence tables for prospective editor distribution.

This migration does not enable automatic distribution or alter 021 grants.
It may only be applied explicitly to a named SQLite database.
"""
import argparse
from pathlib import Path
import sqlite3

MIGRATION_ID = '025_automatic_distribution'

DDL = {
    'automatic_distribution_configurations': '''CREATE TABLE automatic_distribution_configurations (
        configuration_id TEXT PRIMARY KEY,
        manuscript_id INTEGER NOT NULL REFERENCES manuscripts(manuscript_id) ON DELETE RESTRICT,
        invitation_kind TEXT NOT NULL CHECK(invitation_kind IN ('initial','final')),
        source_kind TEXT NOT NULL CHECK(source_kind='current_author_manuscript'),
        source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
        version INTEGER NOT NULL CHECK(version>0),
        actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        created_at TEXT NOT NULL,
        UNIQUE(manuscript_id,invitation_kind,version)
    )''',
    'automatic_distribution_configurations_eic': '''CREATE TRIGGER automatic_distribution_configurations_eic
        BEFORE INSERT ON automatic_distribution_configurations BEGIN
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.actor_id AND role='eic')
            THEN RAISE(ABORT,'EIC required') END;
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM manuscripts WHERE manuscript_id=NEW.manuscript_id AND status!='draft')
            THEN RAISE(ABORT,'Manuscript unavailable') END;
    END''',
    'automatic_distribution_configuration_revocations': '''CREATE TABLE automatic_distribution_configuration_revocations (
        configuration_id TEXT PRIMARY KEY REFERENCES automatic_distribution_configurations(configuration_id) ON DELETE RESTRICT,
        actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000),
        created_at TEXT NOT NULL
    )''',
    'automatic_distribution_revocations_eic': '''CREATE TRIGGER automatic_distribution_revocations_eic
        BEFORE INSERT ON automatic_distribution_configuration_revocations BEGIN
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.actor_id AND role='eic')
            THEN RAISE(ABORT,'EIC required') END;
    END''',
    'automatic_distribution_intents': '''CREATE TABLE automatic_distribution_intents (
        intent_id TEXT PRIMARY KEY,
        configuration_id TEXT NOT NULL REFERENCES automatic_distribution_configurations(configuration_id) ON DELETE RESTRICT,
        invitation_kind TEXT NOT NULL CHECK(invitation_kind IN ('initial','final')),
        invitation_id INTEGER NOT NULL CHECK(invitation_id>0),
        recipient_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
        idempotency_key TEXT NOT NULL UNIQUE CHECK(length(idempotency_key) BETWEEN 16 AND 128),
        fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64 AND fingerprint NOT GLOB '*[^0-9a-f]*'),
        created_at TEXT NOT NULL,
        UNIQUE(invitation_kind,invitation_id)
    )''',
    'automatic_distribution_intents_validate': '''CREATE TRIGGER automatic_distribution_intents_validate
        BEFORE INSERT ON automatic_distribution_intents BEGIN
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM automatic_distribution_configurations c
            WHERE c.configuration_id=NEW.configuration_id AND c.invitation_kind=NEW.invitation_kind
            AND NOT EXISTS(SELECT 1 FROM automatic_distribution_configuration_revocations r WHERE r.configuration_id=c.configuration_id)
            AND ((NEW.invitation_kind='initial' AND EXISTS(SELECT 1 FROM initial_editor_invitations i
                WHERE i.invitation_id=NEW.invitation_id AND i.manuscript_id=c.manuscript_id AND i.editor_id=NEW.recipient_id AND i.status='accepted'))
              OR (NEW.invitation_kind='final' AND EXISTS(SELECT 1 FROM final_editor_invitations i
                WHERE i.invitation_id=NEW.invitation_id AND i.manuscript_id=c.manuscript_id AND i.editor_id=NEW.recipient_id AND i.status='accepted')))
            AND EXISTS(SELECT 1 FROM users u WHERE u.user_id=NEW.recipient_id AND u.role='editor'))
            THEN RAISE(ABORT,'Eligible editor invitation required') END;
    END''',
    'automatic_distribution_results': '''CREATE TABLE automatic_distribution_results (
        result_id TEXT PRIMARY KEY,
        intent_id TEXT NOT NULL REFERENCES automatic_distribution_intents(intent_id) ON DELETE RESTRICT,
        state TEXT NOT NULL CHECK(state IN ('pending','granted','failed')),
        grant_id TEXT REFERENCES distribution_grants(grant_id) ON DELETE RESTRICT,
        reason_code TEXT,
        created_at TEXT NOT NULL,
        CHECK((state='granted' AND grant_id IS NOT NULL AND reason_code IS NULL) OR
              (state='pending' AND grant_id IS NULL AND reason_code IS NULL) OR
              (state='failed' AND grant_id IS NULL AND reason_code IS NOT NULL))
    )''',
    'automatic_distribution_results_grant': '''CREATE TRIGGER automatic_distribution_results_grant
        BEFORE INSERT ON automatic_distribution_results WHEN NEW.state='granted' BEGIN
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM automatic_distribution_intents i
            JOIN automatic_distribution_configurations c ON c.configuration_id=i.configuration_id
            JOIN distribution_grants g ON g.grant_id=NEW.grant_id
            JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id
            WHERE i.intent_id=NEW.intent_id AND g.manuscript_id=c.manuscript_id
              AND g.recipient_id=i.recipient_id AND a.sha256=c.source_sha256
              AND ((i.invitation_kind='initial' AND g.initial_invitation_id=i.invitation_id)
                OR (i.invitation_kind='final' AND g.final_invitation_id=i.invitation_id)))
            THEN RAISE(ABORT,'Grant evidence mismatch') END;
    END''',
}
for _table in ('automatic_distribution_configurations', 'automatic_distribution_configuration_revocations',
               'automatic_distribution_intents', 'automatic_distribution_results'):
    for _operation in ('UPDATE', 'DELETE'):
        _name = f'{_table}_no_{_operation.lower()}'
        DDL[_name] = f"CREATE TRIGGER {_name} BEFORE {_operation} ON {_table} BEGIN SELECT RAISE(ABORT,'immutable automatic distribution evidence'); END"


def _normalize(sql):
    return ' '.join(sql.strip().rstrip(';').lower().split())


def migrate(database_path):
    path = Path(database_path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Existing SQLite database required')
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='021_document_distribution'").fetchone():
            raise RuntimeError('Migration 021 required')
        applied = db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)).fetchone()
        if not applied:
            existing = {row[0] for row in db.execute('SELECT name FROM sqlite_master')}.intersection(DDL)
            if existing:
                raise RuntimeError('Conflicting or partial automatic distribution schema')
            for sql in DDL.values():
                db.execute(sql)
            db.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))", (MIGRATION_ID,))
        for name, sql in DDL.items():
            found = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if not found or _normalize(found[0]) != _normalize(sql):
                raise RuntimeError('Incompatible automatic distribution schema: ' + name)
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key violation')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def downgrade_empty(database_path):
    path = Path(database_path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)).fetchone():
            raise RuntimeError('Migration not installed')
        tables = ('automatic_distribution_results', 'automatic_distribution_intents',
                  'automatic_distribution_configuration_revocations', 'automatic_distribution_configurations')
        if any(db.execute('SELECT 1 FROM ' + table + ' LIMIT 1').fetchone() for table in tables):
            raise RuntimeError('Automatic distribution evidence must be retained')
        for table in tables:
            db.execute('DROP TABLE ' + table)
        db.execute('DELETE FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('database')
    parser.add_argument('--downgrade-empty', action='store_true')
    args = parser.parse_args()
    (downgrade_empty if args.downgrade_empty else migrate)(args.database)

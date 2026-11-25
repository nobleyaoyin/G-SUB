"""Supported forward-aware 028–030 upgrade for an explicitly named database.

The historical 028 standalone entrypoint validates its original trigger and is
not forward-aware. This command validates the legitimate 029 replacement.
It refuses the persistent Main database and never runs implicitly at startup.
"""
import argparse
from importlib import import_module
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.validate_028_forward import validate


def _has(path,migration):
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try: return bool(db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(migration,)).fetchone())
    finally: db.close()


def upgrade(database, through_rounds=False):
    path=Path(database).resolve(strict=True)
    if not path.is_file(): raise ValueError('Existing SQLite database required')
    if path==(ROOT/'manuscript.db').resolve(): raise ValueError('Persistent Main database is not permitted')
    old=import_module('migrations.028_automatic_distribution_intents')
    newer=import_module('migrations.029_intent_precision_failures')
    processor=import_module('migrations.030_automatic_processing')
    if not _has(path,'027_source_grant_provenance'): raise RuntimeError('Migration 027 required')
    if not _has(path,old.MIGRATION_ID): old.migrate(path)
    else: validate(path)
    newer.migrate(path)
    validate(path)
    processor.migrate(path)
    validate(path)
    if through_rounds:
        import_module('migrations.031_editor_invitation_revocation').migrate(path)
        import_module('migrations.032_editor_distribution_rounds').migrate(path)
        validate(path)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('database');parser.add_argument('--through-rounds',action='store_true',help='Explicitly apply 031 and 032 after 028–030');args=parser.parse_args()
    upgrade(args.database,through_rounds=args.through_rounds)
    print('PASS: forward-aware 028–032 upgrade verified' if args.through_rounds else 'PASS: forward-aware 028–030 upgrade verified')

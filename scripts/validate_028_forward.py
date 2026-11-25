"""Read-only forward-aware 028/029 schema validation for an explicit SQLite file."""
import argparse
from importlib import import_module
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def validate(database):
    path=Path(database).resolve(strict=True)
    if not path.is_file(): raise ValueError('Existing SQLite database required')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        old=import_module('migrations.028_automatic_distribution_intents')
        newer=import_module('migrations.029_intent_precision_failures')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(old.MIGRATION_ID,)).fetchone():
            raise RuntimeError('Migration 028 required')
        installed=bool(db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(newer.MIGRATION_ID,)).fetchone())
        expected=dict(old.DDL)
        if installed: expected.update(newer.DDL)
        for name,sql in expected.items():
            row=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
            if not row or not row[0] or old.normalize(row[0])!=old.normalize(sql): raise RuntimeError('Incompatible intent schema: '+name)
        if db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Foreign key violation')
    finally: db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('database');args=parser.parse_args()
    validate(args.database)
    print('PASS: 028/029 intent schema verified')

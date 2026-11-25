#!/usr/bin/env python3
"""Main-only 046 preflight. Persistent execution remains deliberately disabled.

This is not a migration command. No manifest or CLI flag establishes exclusion
of nonparticipating writers, so successful checks always refuse execution.
"""
import argparse
from pathlib import Path
import sqlite3
import sys

# The collaboration copy has no authorized persistent Main target.  This
# sentinel keeps identity validation fail-closed and avoids publishing a
# developer's local account path.  Do not point it at a persistent database.
MAIN_ROOT = Path('/__gsub_unconfigured_main__')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import main_046_executor as preparation


def validate_identity(project, database, confirmation):
    """Reject alternate targets before reading their filesystem state."""
    if (Path(__file__).resolve().parents[1] != MAIN_ROOT
            or Path(project) != MAIN_ROOT
            or Path(database) != MAIN_ROOT / 'manuscript.db'
            or confirmation != preparation.CONFIRMATION):
        raise ValueError('Exact original Main project, database and identity required')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--confirm-main', required=True)
    parser.add_argument('--storage-root', action='append', default=[])
    parser.add_argument('--backup', required=True)
    parser.add_argument('--restore', required=True)
    parser.add_argument('--maintenance-manifest', required=True)
    args = parser.parse_args(argv)
    try:
        validate_identity(args.project, args.database, args.confirm_main)
        # This checks copies and their manifests only; it does not establish a
        # complete historical inventory or verify a maintenance window.
        preparation.validate(args.database, args.storage_root, args.backup, args.restore,
                             args.confirm_main, project=MAIN_ROOT)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 1
    # A self-declared file cannot prove exclusion of independent writers.
    # Its presence, contents and any CLI argument intentionally cannot enable
    # a Main transaction. A separately reviewed verifier is still required.
    print('REFUSED: independent writer exclusion and maintenance readiness are unverified; no Main transaction is available.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

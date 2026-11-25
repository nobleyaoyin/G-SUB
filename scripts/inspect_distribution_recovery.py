"""Local operator dry-run: python -m scripts.inspect_distribution_recovery --database ... --storage ..."""
import argparse
import json
import sqlite3
from pathlib import Path
from app.distribution_recovery import inspect_distribution
from app.reviewer_artifact_storage import ArtifactStorage


def main():
    parser=argparse.ArgumentParser(description='Read-only distribution storage diagnostic; never deletes files.')
    parser.add_argument('--database',required=True);parser.add_argument('--storage',required=True)
    args=parser.parse_args()
    path=Path(args.database).resolve(strict=True)
    if not path.is_file(): raise ValueError('Existing database required')
    connection=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        connection.execute('PRAGMA query_only=ON');connection.execute('BEGIN')
        with ArtifactStorage(args.storage) as storage:
            print(json.dumps(inspect_distribution(connection,storage),indent=2))
    finally: connection.close()

if __name__=='__main__': main()

"""Initialize a fresh disposable collaboration database under .test-data only.

A failed operation retains the partially initialized file for inspection; it
is never automatically removed or reused. Not a production upgrade tool.
"""
from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

PROJECT = Path(__file__).resolve().parents[2]
DATA = PROJECT / '.test-data'
BASE = PROJECT / 'database' / 'bootstrap' / 'collaboration_base_v1.sql'
MIGRATIONS = (
    '001_reviewer_file_bindings', '002_reviewer_invitations',
    '003_two_reviewer_policy', '004_author_agreements',
    '005_final_editor_workflow', '006_formatter_publication',
    '007_email_outbox', '008_email_verification',
    '009_account_invitation_lifecycle', '010_reviewer_profiles',
    '011_blind_review_policy', '012_reviewer_artifacts',
    '013_artifact_evidence', '014_online_document_versions',
    '015_google_oidc', '016_onlyoffice_sessions', '017_ai_prescreening',
    '018_general_comments', '019_personal_notes', '021_document_distribution',
    '022_eic_prospective_proof', '023_reviewer_candidate_intake',
    '024_reviewer_publication_audit', '025_automatic_distribution',
    '026_controlled_source_policy', '027_source_grant_provenance',
    '028_automatic_distribution_intents', '029_intent_precision_failures',
    '030_automatic_processing', '031_editor_invitation_revocation',
    '032_editor_distribution_rounds', '033_stage_dialogue',
    '034_agreement_snapshot_guards', '035_sample_document_storage',
    '036_sample_initial_editing', '037_sample_final_formatting',
    '038_candidate_preparation_provenance', '039_lifecycle_administration',
    '040_lifecycle_succession', '046_main_submission_schema',
)
SUBMISSION_PRIOR_IDS = (
    '041_author_submission_drafts', '042_author_submission_linkage',
    '043_author_submission_attachments', '044_manuscript_upload_names',
    '045_manuscript_upload_requests',
)
_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.sqlite$')


def initialize(name: str) -> Path:
    """Create a new named database. Never open or overwrite an existing file."""
    if not isinstance(name, str) or not _NAME.fullmatch(name) or '..' in name:
        raise ValueError('Database name must be a simple .sqlite filename')
    if DATA.is_symlink() or not DATA.is_dir():
        raise ValueError('Existing non-symlink .test-data directory required')
    root = DATA.resolve(strict=True)
    if root.parent != PROJECT or root != DATA:
        raise ValueError('Database directory escapes collaboration workspace')
    if not root.is_relative_to(Path(tempfile.gettempdir()).resolve(strict=True)):
        raise ValueError('Collaboration workspace must be inside the system temporary directory')
    info = root.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise ValueError('Database directory must be owner-controlled')
    path = root / name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if not hasattr(os, 'O_NOFOLLOW'):
        raise RuntimeError('No-follow filesystem protection required')
    flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    os.close(fd)
    try:
        if path.is_symlink() or path.resolve(strict=True).parent != root:
            raise RuntimeError('Created database path is unsafe')
        with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True) as db:
            db.executescript(BASE.read_text())
        for name in MIGRATIONS:
            if path.is_symlink() or path.resolve(strict=True).parent != root:
                raise RuntimeError('Database path changed during initialization')
            importlib.import_module('migrations.' + name).migrate(path)
        with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True) as db:
            db.execute('PRAGMA foreign_keys=ON')
            if db.execute('PRAGMA foreign_keys').fetchone() != (1,):
                raise RuntimeError('Foreign keys unavailable')
            if db.execute('SELECT version FROM collaboration_schema_version').fetchall() != [(1,)]:
                raise RuntimeError('Unexpected collaboration schema version')
            actual = {row[0] for row in db.execute('SELECT migration_id FROM schema_migrations')}
            if actual != set(MIGRATIONS + SUBMISSION_PRIOR_IDS) or db.execute('PRAGMA foreign_key_check').fetchone():
                raise RuntimeError('Migration ledger or foreign keys invalid')
        return path
    except Exception as exc:
        raise RuntimeError('Initialization failed; newly created file retained for inspection') from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True, help='New .sqlite filename inside .test-data')
    args = parser.parse_args()
    path = initialize(args.name)
    print(f'Initialized disposable collaboration database: {path.name}')


if __name__ == '__main__':
    main()

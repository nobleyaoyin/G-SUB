"""Fresh synthetic legacy schema through all available numbered migrations."""
from importlib import import_module
import sqlite3
from tests import test_reviewer_download as fixtures


def test_fresh_synthetic_schema_upgrades_through_032():
    fixture = fixtures.ReviewerDownloadsTest()
    fixture.setUp()
    try:
        # The fixture constructs a fresh base and explicitly installs 001–019.
        for name in ('021_document_distribution', '022_eic_prospective_proof',
                     '023_reviewer_candidate_intake', '024_reviewer_publication_audit',
                     '025_automatic_distribution', '026_controlled_source_policy',
                     '027_source_grant_provenance'):
            import_module('migrations.' + name).migrate(fixture.db_path)
        from scripts.upgrade_automatic_distribution import upgrade
        upgrade(fixture.db_path, through_rounds=True)
        upgrade(fixture.db_path, through_rounds=True)
        with sqlite3.connect(fixture.db_path) as db:
            assert db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='032_editor_distribution_rounds'").fetchone()
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        fixture.tearDown()

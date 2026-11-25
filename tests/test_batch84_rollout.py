"""Isolated checks for the 032 cutover and historical grant access."""
import sqlite3

import pytest
from tests.test_batch83_round_binding import setup
from tests.test_batch17b_distribution_migration import database


@pytest.mark.parametrize('mode', ['manual', 'automatic'])
def test_final_bound_download_survives_stage_change_and_revocation(mode):
    with setup('final', mode) as (fixture, chief, manuscript_id, invitation_id, grant_id, content):
        # Synthetic status mutation isolates access semantics; this is not a
        # substitute for exercising the application's workflow transition.
        with sqlite3.connect(fixture.db_path) as db:
            db.execute("UPDATE manuscripts SET status='formatting' WHERE manuscript_id=?", (manuscript_id,))
        fixture.current = fixture.editor
        assert fixture.client.get(f'/document-distribution/grants/{grant_id}/download').content == content
        fixture.current = chief
        assert fixture.client.post(f'/document-distribution/grants/{grant_id}/revoke', json={'reason': 'Synthetic'}).status_code == 200
        fixture.current = fixture.editor
        assert fixture.client.get(f'/document-distribution/grants/{grant_id}/download').status_code == 404


def test_unbound_legacy_intent_is_blocked_and_not_retryable():
    with setup('initial', 'automatic', defer=True) as (fixture, chief, manuscript_id, invitation_id, intent_id, content):
        # Recreate the pre-032 intent condition in the disposable database.
        with sqlite3.connect(fixture.db_path) as db:
            db.execute('DROP TRIGGER editor_distribution_intent_rounds_no_delete')
            db.execute('DELETE FROM editor_distribution_intent_rounds WHERE intent_id=?', (intent_id,))
            from importlib import import_module
            db.execute(import_module('migrations.032_editor_distribution_rounds').DDL['editor_distribution_intent_rounds_no_delete'])
        fixture.current = chief
        response = fixture.client.get(f'/document-distribution/manuscripts/{manuscript_id}/automatic-intents')
        assert response.status_code == 200
        item = next(row for row in response.json() if row['intent_id'] == intent_id)
        assert (item['state'], item['reason_code'], item['retryable']) == ('blocked', 'round_evidence_required', False)
        response = fixture.client.post(f'/document-distribution/manuscripts/{manuscript_id}/automatic-intents/{intent_id}/process')
        assert response.status_code == 409
        with sqlite3.connect(fixture.db_path) as db:
            assert db.execute('SELECT count(*) FROM distribution_grants').fetchone() == (0,)


@pytest.mark.parametrize('start_at_028', [False, True])
def test_supported_round_upgrade_from_027_or_028(database, start_at_028):
    from tests.test_batch73_acceptance_intents import manual, auto, policy_migration, provenance_migration, intent_migration
    from scripts.upgrade_automatic_distribution import upgrade
    manual.migrate(database)
    auto.migrate(database)
    policy_migration.migrate(database)
    provenance_migration.migrate(database)
    if start_at_028:
        intent_migration.migrate(database)
    upgrade(database, through_rounds=True)
    upgrade(database, through_rounds=True)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='032_editor_distribution_rounds'").fetchone()
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_final_current_and_version_routes_after_stage_transition():
    with setup('final', 'automatic') as (fixture, chief, manuscript_id, invitation_id, grant_id, content):
        fixture.current = fixture.editor
        with sqlite3.connect(fixture.db_path) as db:
            db.execute("UPDATE manuscripts SET status='formatting' WHERE manuscript_id=?", (manuscript_id,))
        assert fixture.client.get(f'/manuscripts/{manuscript_id}/download').content == content
        assert fixture.client.get(f'/manuscripts/{manuscript_id}/versions/source.txt').content == content

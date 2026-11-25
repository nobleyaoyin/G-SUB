"""Synthetic migration, UTC ordering and capture-failure checks."""
from tests.batch83_migration_support import bootstrap_prospective_distribution
from unittest.mock import patch
import importlib.util
import sqlite3
from pathlib import Path
import pytest
from datetime import datetime, timezone, timedelta

from tests import test_reviewer_download as fixtures
from tests.test_batch17b_distribution_migration import database
from tests.test_batch22_invitation_distribution import prepare
from tests.test_batch73_acceptance_intents import install, intent_migration

spec=importlib.util.spec_from_file_location('migration29',Path(__file__).resolve().parents[1]/'migrations/029_intent_precision_failures.py')
migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)


def test_timezone_normalization_and_naive_rejection():
    from app.strict_utc import canonical_utc
    assert canonical_utc(datetime(2026,1,1,2,0,0,2,tzinfo=timezone(timedelta(hours=2))))=='2026-01-01T00:00:00.000002Z'
    with pytest.raises(ValueError): canonical_utc(datetime(2026,1,1))


def test_upgrade_reapply_and_empty_rollback(database):
    install(database);migration.migrate(database);migration.migrate(database)
    # The old migration validates its original trigger exactly; running its
    # standalone entrypoint after a forward replacement is incompatible.
    with pytest.raises(RuntimeError,match='Incompatible automatic intent schema'):
        intent_migration.migrate(database)
    migration.downgrade_empty(database);migration.migrate(database)
    with sqlite3.connect(database) as db: assert db.execute('PRAGMA foreign_key_check').fetchall()==[]


@pytest.mark.parametrize('authorized,accepted,stored,allowed',[
    ('2026-01-01T00:00:00.000001Z','2026-01-01T00:00:00.000002Z','2026-01-01 00:00:00.000002',True),
    ('2026-01-01T00:00:00.000002Z','2026-01-01T00:00:00.000002Z','2026-01-01 00:00:00.000002',False),
    ('2026-01-01T00:00:00.000003Z','2026-01-01T00:00:00.000002Z','2026-01-01 00:00:00.000002',False),
    ('2026-01-01T00:00:00.000001Z','2026-01-01T00:00:00.000002Z','2026-01-01 00:00:00.000003',False),
    ('2026-01-01T00:00:00.000001+00:00','2026-01-01T00:00:00.000002Z','2026-01-01 00:00:00.000002',False),
])
def test_microsecond_ordering_and_exact_invitation_time(authorized,accepted,stored,allowed):
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);migration.migrate(f.db_path)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute("UPDATE initial_editor_invitations SET status='accepted',responded_at=? WHERE invitation_id=?",(stored,iid))
            ref=f'uploads/manuscripts/{mid}/paper.txt';digest='a'*64
            db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('policy',mid,'initial','automatic','current_author_manuscript',ref,digest,1,chief.user_id,authorized))
            args=('intent','policy',mid,'initial',iid,f.editor.user_id,1,ref,digest,'idempotency-key', 'b'*64,accepted,accepted)
            if allowed:
                db.execute('INSERT INTO controlled_automatic_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',args)
                assert db.execute('SELECT COUNT(*) FROM controlled_automatic_intents').fetchone()==(1,)
            else:
                with pytest.raises(sqlite3.IntegrityError): db.execute('INSERT INTO controlled_automatic_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',args)
    finally:f.tearDown()


def test_capture_failure_recorded_and_visible_even_if_intent_schema_damaged():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);migration.migrate(f.db_path)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('c'*32,mid,'initial','automatic','current_author_manuscript',f'uploads/manuscripts/{mid}/paper.txt','a'*64,1,chief.user_id,'2020-01-01T00:00:00.000000Z'))
            db.execute('DROP TRIGGER controlled_automatic_intents_no_update')
        f.current=f.editor
        assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
        assert f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-capture-failures').status_code==403
        f.current=chief
        response=f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-capture-failures')
        assert response.status_code==200,response.text
        assert len(response.json())==1 and response.json()[0]['reason_code']=='capture_unavailable'
        assert 'source_ref' not in response.json()[0]
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_intents').fetchone()==(0,)
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
            with pytest.raises(sqlite3.IntegrityError): db.execute('DELETE FROM controlled_automatic_capture_failures')
    finally:f.tearDown()


def test_acceptance_with_029_records_pending_and_eic_can_read_history():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);migration.migrate(f.db_path);bootstrap_prospective_distribution(f.db_path)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('d'*32,mid,'initial','automatic','current_author_manuscript',f'uploads/manuscripts/{mid}/paper.txt','a'*64,1,chief.user_id,'2020-01-01T00:00:00.000000Z'))
        f.current=f.editor
        with patch('app.automatic_distribution_intents.process_after_acceptance'):
            assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
        f.current=chief
        result=f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-intents')
        assert result.status_code==200,result.text
        assert len(result.json())==1 and result.json()[0]['state']=='pending'
        assert f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-capture-failures').json()==[]
    finally:f.tearDown()

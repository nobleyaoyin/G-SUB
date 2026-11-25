"""Synthetic direct processing of an acceptance-bound Initial Editor intent."""
from tests.batch83_migration_support import migrate_rounds
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from fastapi import HTTPException

from app.automatic_distribution_processor import process_intent
from app.routers import document_distribution as distribution
from tests import test_reviewer_download as fixtures, test_final_workflow as final_fixtures
from tests.test_batch22_invitation_distribution import prepare
from tests.test_batch73_acceptance_intents import install
from tests.test_batch74_precision_failures import migration as precision
from tests.test_batch17b_distribution_migration import database

spec=importlib.util.spec_from_file_location('migration30',Path(__file__).resolve().parents[1]/'migrations/030_automatic_processing.py')
processing_migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(processing_migration)


def test_forward_validator_and_processing_migration_reapplication(database):
    install(database);precision.migrate(database);processing_migration.migrate(database);processing_migration.migrate(database)
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,str(root/'scripts/validate_028_forward.py'),str(database)],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    processing_migration.downgrade_empty(database);processing_migration.migrate(database)
    with sqlite3.connect(database) as db: assert db.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_initial_intent_creates_real_grant_and_exact_download():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path)
        ref=f'uploads/manuscripts/{mid}/paper.txt';original=b'Synthetic batch 22 bytes\n';digest=hashlib.sha256(original).hexdigest()
        private=f.root/'batch75-private';private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch75-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch75-event'))
        with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=chief
            policy=f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':digest,'confirmed':True})
            assert policy.status_code==201,policy.text
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'reviewer','mode':'automatic','source_sha256':digest,'confirmed':True}).status_code==422
            f.current=f.reviewer
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':digest,'confirmed':True}).status_code==403
            f.current=f.editor
            response=f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'})
            assert response.status_code==200,response.text
            assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==409
            with sqlite3.connect(f.db_path) as db:
                intent=db.execute('SELECT intent_id FROM controlled_automatic_intents').fetchone()[0]
            with f.Session() as session: result=process_intent(session,intent)
            assert result['status']=='granted'
            assert f.client.get(f"/document-distribution/grants/{result['grant_id']}/download").content==original
            assert f.client.get(f'/manuscripts/{mid}/download').content==original
            with f.Session() as session: assert process_intent(session,intent)['grant_id']==result['grant_id']
            import pytest
            with pytest.raises(RuntimeError,match='retained'): processing_migration.downgrade_empty(f.db_path)
            f.current=chief
            assert f.client.post(f"/document-distribution/grants/{result['grant_id']}/revoke",json={'reason':'Synthetic'}).status_code==200
            retry=f.client.post(f'/document-distribution/manuscripts/{mid}/automatic-intents/{intent}/process')
            assert retry.status_code==409
            f.current=f.editor
            assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
            with sqlite3.connect(f.db_path) as db:
                assert db.execute('SELECT COUNT(*) FROM controlled_automatic_intents').fetchone()==(1,)
                assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(1,)
    finally:f.tearDown()


def test_final_acceptance_processes_real_grant_with_agreement():
    from app.routers import eic
    f=final_fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();f.current=f.author
            assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond",json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
            invitation=f.invite(f.editor);assert invitation.status_code==201
            iid=invitation.json()['invitation_id'];original=b'Synthetic batch 75 final\n';digest=hashlib.sha256(original).hexdigest()
            ref=f.write(f'uploads/manuscripts/{f.mid}/paper.txt',original);f.manuscript.file_path=ref;f.db.commit()
            install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path)
            private=f.root/'batch75-final-private';private.mkdir(mode=0o700)
            with sqlite3.connect(f.db_path) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch75-final-event',f.editor.user_id,1,None,'active',1,f.chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
                db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch75-final-event'))
            with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
                f.current=f.chief
                policy=f.client.post(f'/document-distribution/manuscripts/{f.mid}/policies',json={'invitation_kind':'final','mode':'automatic','source_sha256':digest,'confirmed':True})
                assert policy.status_code==201,policy.text
                response=f.respond(f.editor,iid,'accept');assert response.status_code==200,response.text
                with sqlite3.connect(f.db_path) as db:
                    row=db.execute('SELECT intent_id,grant_id FROM controlled_automatic_grant_provenance').fetchone()
                    assert row
                    assert db.execute('SELECT state FROM controlled_automatic_processing_events ORDER BY sequence DESC LIMIT 1').fetchone()==('granted',)
                f.current=f.editor
                assert f.client.get(f'/document-distribution/grants/{row[1]}/download').content==original
                assert f.client.get(f'/manuscripts/{f.mid}/download').content==original
    finally:f.tearDown()


def test_failure_retry_and_concurrent_processing_reconcile():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path)
        original=b'Synthetic batch 22 bytes\n';digest=hashlib.sha256(original).hexdigest()
        private=f.root/'batch75-retry-private';private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch75-retry-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch75-retry-event'))
        with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=chief
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':digest,'confirmed':True}).status_code==201
            f.current=f.editor
            with patch.object(distribution,'_storage',side_effect=HTTPException(503,'Synthetic failure')):
                assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            with sqlite3.connect(f.db_path) as db:
                intent=db.execute('SELECT intent_id FROM controlled_automatic_intents').fetchone()[0]
                assert db.execute('SELECT state FROM controlled_automatic_processing_events ORDER BY sequence DESC LIMIT 1').fetchone()==('failed',)
                assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
            f.current=chief
            assert f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-intents').json()[0]['state']=='failed'
            barrier=Barrier(2)
            def run():
                with f.Session() as session:
                    barrier.wait()
                    try: return process_intent(session,intent)
                    except HTTPException as exc: return exc.status_code
            with ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(lambda _:run(),range(2)))
            assert any(isinstance(value,dict) and value['status']=='granted' for value in outcomes)
            with sqlite3.connect(f.db_path) as db:
                assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(1,)
                assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(1,)
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/automatic-intents/{intent}/process').json()['status']=='granted'
    finally:f.tearDown()


def test_policy_revoked_during_snapshot_prevents_grant():
    from app.reviewer_artifact_storage import ArtifactStorage
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path)
        original=b'Synthetic batch 22 bytes\n';digest=hashlib.sha256(original).hexdigest()
        private=f.root/'batch75-revoke-private';private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch75-revoke-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch75-revoke-event'))
        with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=chief
            policy=f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':digest,'confirmed':True})
            assert policy.status_code==201
            policy_id=policy.json()['policy_id'];publish=ArtifactStorage.publish_reserved
            def revoke_after_snapshot(store,*args,**kwargs):
                result=publish(store,*args,**kwargs)
                with sqlite3.connect(f.db_path) as db:
                    db.execute('PRAGMA foreign_keys=ON')
                    db.execute('INSERT INTO controlled_source_policy_revocations VALUES(?,?,?,?)',(policy_id,chief.user_id,'Synthetic','2026-01-01T00:00:00.000000Z'))
                return result
            f.current=f.editor
            with patch.object(ArtifactStorage,'publish_reserved',revoke_after_snapshot):
                assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            with sqlite3.connect(f.db_path) as db:
                assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
                assert db.execute('SELECT state,reason_code FROM controlled_automatic_processing_events ORDER BY sequence DESC LIMIT 1').fetchone()==('failed','authorization_unavailable')
            f.current=chief
            assert f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-intents').json()[0]['state']=='revoked'
    finally:f.tearDown()


def test_crash_after_snapshot_recovers_after_lease_expiry():
    from app.reviewer_artifact_storage import ArtifactStorage
    import pytest
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path)
        original=b'Synthetic batch 22 bytes\n';digest=hashlib.sha256(original).hexdigest()
        private=f.root/'batch75-crash-private';private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch75-crash-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch75-crash-event'))
        with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=chief
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':digest,'confirmed':True}).status_code==201
            f.current=f.editor
            with patch('app.automatic_distribution_intents.process_after_acceptance'):
                assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            with sqlite3.connect(f.db_path) as db: intent=db.execute('SELECT intent_id FROM controlled_automatic_intents').fetchone()[0]
            publish=ArtifactStorage.publish_reserved
            def crash_after_publish(store,*args,**kwargs):
                publish(store,*args,**kwargs)
                raise KeyboardInterrupt('Synthetic crash')
            with patch.object(ArtifactStorage,'publish_reserved',crash_after_publish):
                with f.Session() as session:
                    with pytest.raises(KeyboardInterrupt): process_intent(session,intent)
            with sqlite3.connect(f.db_path) as db:
                assert db.execute('SELECT state FROM controlled_automatic_processing_events ORDER BY sequence DESC LIMIT 1').fetchone()==('processing',)
                assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
            future=time.time_ns()+120_000_000_000
            with patch('app.automatic_distribution_processor.time.time_ns',return_value=future):
                with f.Session() as session: result=process_intent(session,intent)
            assert result['status']=='granted'
            with sqlite3.connect(f.db_path) as db:
                assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(1,)
                assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(1,)
            assert f.client.get(f'/manuscripts/{mid}/download').content==original
    finally:f.tearDown()


def test_source_changed_during_snapshot_is_not_granted():
    from app.reviewer_artifact_storage import ArtifactStorage
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path)
        original=b'Synthetic batch 22 bytes\n';digest=hashlib.sha256(original).hexdigest()
        private=f.root/'batch75-change-private';private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch75-change-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch75-change-event'))
        with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=chief
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':digest,'confirmed':True}).status_code==201
            publish=ArtifactStorage.publish_reserved
            def change_after_snapshot(store,*args,**kwargs):
                result=publish(store,*args,**kwargs)
                (f.root/f'uploads/manuscripts/{mid}/paper.txt').write_bytes(b'Changed synthetic source\n')
                return result
            f.current=f.editor
            with patch.object(ArtifactStorage,'publish_reserved',change_after_snapshot):
                assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            with sqlite3.connect(f.db_path) as db:
                assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
                assert db.execute('SELECT state,reason_code FROM controlled_automatic_processing_events ORDER BY sequence DESC LIMIT 1').fetchone()==('failed','source_changed')
            f.current=chief
            history=f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-intents').json()[0]
            assert history['state']=='failed' and history['retryable'] is False
    finally:f.tearDown()

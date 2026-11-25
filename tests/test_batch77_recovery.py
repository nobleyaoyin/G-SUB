"""Synthetic race and crash checks for accepted Initial Editor intents."""
from tests.batch83_migration_support import migrate_rounds
import hashlib
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.automatic_distribution_processor import process_intent
from app.reviewer_artifact_storage import ArtifactStorage
from app.routers import document_distribution as distribution
from tests import test_reviewer_download as fixtures
from tests.test_batch22_invitation_distribution import prepare
from tests.test_batch73_acceptance_intents import install
from tests.test_batch74_precision_failures import migration as precision
from tests.test_batch75_automatic_processor import processing_migration


@contextmanager
def pending():
    f = fixtures.ReviewerDownloadsTest(); f.setUp()
    try:
        chief, mid, iid = prepare(f)
        install(f.db_path); precision.migrate(f.db_path); processing_migration.migrate(f.db_path);migrate_rounds(f.db_path)
        private = f.root / 'batch77-private'; private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch77-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch77-event'))
        with patch.object(distribution,'DATA_ROOT',f.root), patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=chief
            digest=hashlib.sha256(b'Synthetic batch 22 bytes\n').hexdigest()
            response=f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':digest,'confirmed':True})
            assert response.status_code==201,response.text
            policy=response.json()['policy_id'];f.current=f.editor
            with patch('app.automatic_distribution_intents.process_after_acceptance'):
                assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            with sqlite3.connect(f.db_path) as db:
                intent=db.execute('SELECT intent_id FROM controlled_automatic_intents').fetchone()[0]
            yield f,chief,mid,iid,policy,intent
    finally:
        f.tearDown()


@pytest.mark.parametrize('revocation',['policy','invitation'])
def test_revocation_concurrent_with_snapshot_prevents_grant(revocation):
    with pending() as (f,chief,mid,iid,policy,intent):
        entered=Event();proceed=Event();publish=ArtifactStorage.publish_reserved
        def paused(store,*args,**kwargs):
            result=publish(store,*args,**kwargs);entered.set()
            assert proceed.wait(10)
            return result
        def process():
            with f.Session() as session:
                try: return process_intent(session,intent)
                except HTTPException as exc: return exc.status_code
        def revoke():
            assert entered.wait(10)
            try:
                if revocation=='policy':
                    f.current=chief
                    return f.client.post(f'/document-distribution/manuscripts/{mid}/policies/{policy}/revoke',json={'reason':'Synthetic race'}).status_code
                with sqlite3.connect(f.db_path, timeout=10) as db:
                    db.execute("UPDATE initial_editor_invitations SET status='declined' WHERE invitation_id=?",(iid,))
                return 200
            finally: proceed.set()
        with patch.object(ArtifactStorage,'publish_reserved',paused), ThreadPoolExecutor(max_workers=2) as pool:
            work=pool.submit(process);change=pool.submit(revoke)
            assert change.result(timeout=15)==200
            assert work.result(timeout=15)==409
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(0,)
        f.current=f.editor
        assert f.client.get(f'/manuscripts/{mid}/download').status_code in (403,404)
        with f.Session() as session:
            with pytest.raises(HTTPException): process_intent(session,intent)


def test_lost_response_after_commit_reconciles_without_duplicate_grant():
    with pending() as (f,chief,mid,iid,policy,intent):
        with f.Session() as session:
            commit=session.commit;count=0
            def lost():
                nonlocal count
                count+=1;commit()
                if count==3: raise RuntimeError('synthetic response loss after commit')
            with patch.object(session,'commit',side_effect=lost):
                with pytest.raises(HTTPException): process_intent(session,intent)
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(1,)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(1,)
            assert db.execute('SELECT state FROM controlled_automatic_processing_events ORDER BY sequence DESC LIMIT 1').fetchone()==('granted',)
        with f.Session() as session: result=process_intent(session,intent)
        assert result['status']=='granted'
        f.current=f.editor
        assert f.client.get(f"/document-distribution/grants/{result['grant_id']}/download").content==b'Synthetic batch 22 bytes\n'


@pytest.mark.parametrize('boundary',['claim','reservation'])
def test_crash_before_publication_recovers_after_lease_expiry(boundary):
    with pending() as (f,chief,mid,iid,policy,intent):
        with f.Session() as session:
            commit=session.commit;count=0
            def crash():
                nonlocal count
                count+=1;commit()
                if count==(1 if boundary=='claim' else 2): raise KeyboardInterrupt('synthetic crash')
            with patch.object(session,'commit',side_effect=crash):
                with pytest.raises(KeyboardInterrupt): process_intent(session,intent)
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
        with patch('app.automatic_distribution_processor.time.time_ns',return_value=time.time_ns()+120_000_000_000):
            with f.Session() as session: result=process_intent(session,intent)
        assert result['status']=='granted'
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(1,)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(1,)


def test_grant_revocation_races_idempotent_processing_and_blocks_download():
    from threading import Barrier
    from app.models import User
    with pending() as (f,chief,mid,iid,policy,intent):
        with f.Session() as session: grant=process_intent(session,intent)['grant_id']
        barrier=Barrier(2)
        def retry():
            with f.Session() as session:
                barrier.wait()
                try: return process_intent(session,intent)
                except HTTPException as exc: return exc.status_code
        def revoke():
            with f.Session() as session:
                actor=session.get(User,chief.user_id);barrier.wait()
                return distribution.revoke(grant,distribution.RevokeRequest(reason='Synthetic race'),actor,session)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(retry);b=pool.submit(revoke)
            outcome=a.result(timeout=15);assert b.result(timeout=15)
        assert outcome==409 or (isinstance(outcome,dict) and outcome['grant_id']==grant)
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(1,)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(1,)
            assert db.execute('SELECT COUNT(*) FROM distribution_revocations WHERE grant_id=?',(grant,)).fetchone()==(1,)
        f.current=f.editor
        assert f.client.get(f'/document-distribution/grants/{grant}/download').status_code==404
        assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
        with f.Session() as session:
            with pytest.raises(HTTPException): process_intent(session,intent)


def test_two_distinct_intents_process_concurrently_without_duplicate_grants():
    from threading import Barrier
    from app.models import Manuscript
    with pending() as (f,chief,mid,iid,policy,intent):
        manuscript=Manuscript(title='Synthetic second Batch 77',abstract='Synthetic',author_id=f.author.user_id,status='initial_scan_passed',review_round=1)
        f.db.add(manuscript);f.db.flush();other=manuscript.manuscript_id
        manuscript.file_path=f.write(f'uploads/manuscripts/{other}/paper.txt',b'Synthetic batch 22 bytes\n');f.db.commit()
        f.current=chief
        invitation=f.client.post('/eic/initial-editor/invite',json={'manuscript_id':other,'editor_id':f.editor.user_id})
        assert invitation.status_code==201,invitation.text
        digest=hashlib.sha256(b'Synthetic batch 22 bytes\n').hexdigest()
        assert f.client.post(f'/document-distribution/manuscripts/{other}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':digest,'confirmed':True}).status_code==201
        f.current=f.editor
        with patch('app.automatic_distribution_intents.process_after_acceptance'):
            assert f.client.post(f"/eic/initial-editor/invitations/{invitation.json()['invitation_id']}/respond",json={'decision':'accept'}).status_code==200
        with sqlite3.connect(f.db_path) as db:
            other_intent=db.execute('SELECT intent_id FROM controlled_automatic_intents WHERE manuscript_id=?',(other,)).fetchone()[0]
        barrier=Barrier(2)
        def run(item):
            with f.Session() as session:
                barrier.wait();return process_intent(session,item)
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,[intent,other_intent]))
        assert all(item['status']=='granted' for item in results)
        assert len({item['grant_id'] for item in results})==2
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(2,)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(2,)


def test_database_failure_before_grant_commit_recovers_without_visible_orphan():
    import app.automatic_distribution_processor as processor
    event=processor._event
    with pending() as (f,chief,mid,iid,policy,intent):
        def fail_before_commit(raw,item,state,stamp,reason=None,grant=None):
            if state=='granted': raise sqlite3.OperationalError('Synthetic commit-boundary failure')
            return event(raw,item,state,stamp,reason,grant)
        with patch.object(processor,'_event',side_effect=fail_before_commit):
            with f.Session() as session:
                with pytest.raises(HTTPException) as error: process_intent(session,intent)
                assert error.value.status_code==503
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(0,)
            assert db.execute('SELECT state FROM controlled_automatic_processing_events ORDER BY sequence DESC LIMIT 1').fetchone()==('failed',)
        f.current=f.editor
        assert f.client.get('/document-distribution/my').json()==[]
        assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
        with f.Session() as session: result=process_intent(session,intent)
        assert result['status']=='granted'
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(1,)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(1,)

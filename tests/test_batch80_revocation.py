"""Isolated HTTP checks for durable editor invitation revocation."""
from tests.batch83_migration_support import migrate_rounds
import importlib
import sqlite3
import pytest
from tests.test_batch79_http_matrix import workspace
from tests.test_batch17b_distribution_migration import database

migration=importlib.import_module('migrations.031_editor_invitation_revocation')

@pytest.mark.parametrize('kind',['initial','final'])
def test_revocation_blocks_existing_grant_and_records_immutable_history(kind):
    with workspace(kind) as (f,chief,mid,iid,policy,grant,other,content):
        migration.migrate(f.db_path);migration.migrate(f.db_path)
        endpoint=f'/document-distribution/manuscripts/{mid}/editor-invitations/{kind}/{iid}/revoke'
        f.current=f.editor;assert f.client.post(endpoint,json={'reason':'Synthetic'}).status_code==403
        f.current=chief
        assert f.client.post(f'/document-distribution/manuscripts/999999/{"editor-invitations"}/{kind}/{iid}/revoke',json={'reason':'Synthetic'}).status_code==404
        history=f.client.get(f'/document-distribution/manuscripts/{mid}/editor-invitations');assert history.status_code==200,history.text
        assert next(x for x in history.json() if x['invitation_kind']==kind and x['invitation_id']==iid)['status']=='accepted'
        revoked=f.client.post(endpoint,json={'reason':'Synthetic'});assert revoked.status_code==200,revoked.text
        assert f.client.post(endpoint,json={'reason':'Again'}).status_code==409
        row=next(x for x in f.client.get(f'/document-distribution/manuscripts/{mid}/editor-invitations').json() if x['invitation_kind']==kind and x['invitation_id']==iid)
        assert row['status']=='revoked' and row['original_status']=='accepted' and row['revoked_at'] and row['reason']=='Synthetic'
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM editor_invitation_revocations').fetchone()==(1,)
            with pytest.raises(sqlite3.IntegrityError):db.execute("UPDATE editor_invitation_revocations SET reason='changed'")
        f.current=f.editor
        assert f.client.get(f'/document-distribution/grants/{grant}/download').status_code==409
        assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
        assert f.client.get('/document-distribution/my').json()==[]
        f.current=chief
        with sqlite3.connect(f.db_path) as db:intent=db.execute('SELECT intent_id FROM controlled_automatic_intents WHERE manuscript_id=?',(mid,)).fetchone()[0]
        intent_history=f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-intents').json()
        assert next(item for item in intent_history if item['intent_id']==intent)['state']=='revoked'
        assert not next(item for item in intent_history if item['intent_id']==intent)['retryable']
        assert f.client.post(f'/document-distribution/manuscripts/{mid}/automatic-intents/{intent}/process').status_code==409
        with pytest.raises(RuntimeError,match='retained'):migration.downgrade_empty(f.db_path)


def test_revoked_pending_invitation_cannot_be_accepted():
    from tests import test_reviewer_download as fixtures
    from tests.test_batch22_invitation_distribution import prepare
    from tests.test_batch73_acceptance_intents import install
    from tests.test_batch74_precision_failures import migration as precision
    from tests.test_batch75_automatic_processor import processing_migration
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path);migration.migrate(f.db_path)
        f.current=chief
        assert f.client.post(f'/document-distribution/manuscripts/{mid}/editor-invitations/initial/{iid}/revoke',json={'reason':'Synthetic pending'}).status_code==200
        f.current=f.editor
        assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==409
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT status FROM initial_editor_invitations WHERE invitation_id=?',(iid,)).fetchone()==('pending',)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_intents').fetchone()==(0,)
    finally:f.tearDown()


def test_initial_revocation_during_processing_prevents_grant():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from unittest.mock import patch
    from fastapi import HTTPException
    from app.automatic_distribution_processor import process_intent
    from app.reviewer_artifact_storage import ArtifactStorage
    from tests.test_batch77_recovery import pending
    with pending() as (f,chief,mid,iid,policy,intent):
        migration.migrate(f.db_path);entered=Event();proceed=Event();publish=ArtifactStorage.publish_reserved
        def paused(store,*args,**kwargs):
            result=publish(store,*args,**kwargs);entered.set();assert proceed.wait(10);return result
        def process():
            with f.Session() as db:
                try:return process_intent(db,intent)
                except HTTPException as exc:return exc.status_code
        def revoke():
            assert entered.wait(10)
            try:
                f.current=chief
                return f.client.post(f'/document-distribution/manuscripts/{mid}/editor-invitations/initial/{iid}/revoke',json={'reason':'Synthetic race'}).status_code
            finally:proceed.set()
        with patch.object(ArtifactStorage,'publish_reserved',paused),ThreadPoolExecutor(max_workers=2) as pool:
            work=pool.submit(process);change=pool.submit(revoke)
            assert change.result(timeout=15)==200 and work.result(timeout=15)==409
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(0,)


def test_final_revocation_during_processing_prevents_grant():
    import hashlib,os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from unittest.mock import patch
    from fastapi import HTTPException
    from app.automatic_distribution_processor import process_intent
    from app.reviewer_artifact_storage import ArtifactStorage
    from app.routers import document_distribution as distribution,eic
    from tests import test_final_workflow as fixtures
    from tests.test_batch73_acceptance_intents import install
    from tests.test_batch74_precision_failures import migration as precision
    from tests.test_batch75_automatic_processor import processing_migration
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();f.current=f.author
            assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond",json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
            invitation=f.invite(f.editor);assert invitation.status_code==201
        mid=f.mid;iid=invitation.json()['invitation_id'];content=b'Synthetic final batch80\n'
        f.manuscript.file_path=f.write(f'uploads/manuscripts/{mid}/source.txt',content);f.db.commit()
        install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path);migration.migrate(f.db_path)
        private=f.root/'batch80-private';private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch80-event',f.editor.user_id,1,None,'active',1,f.chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch80-event'))
        with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=f.chief
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'final','mode':'automatic','source_sha256':hashlib.sha256(content).hexdigest(),'confirmed':True}).status_code==201
            f.current=f.editor
            with patch('app.automatic_distribution_intents.process_after_acceptance'):
                assert f.client.post(f'/final-workflow/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            with sqlite3.connect(f.db_path) as db:intent=db.execute('SELECT intent_id FROM controlled_automatic_intents').fetchone()[0]
            entered=Event();proceed=Event();publish=ArtifactStorage.publish_reserved
            def paused(store,*args,**kwargs):
                result=publish(store,*args,**kwargs);entered.set();assert proceed.wait(10);return result
            def process():
                with f.Session() as db:
                    try:return process_intent(db,intent)
                    except HTTPException as exc:return exc.status_code
            def revoke():
                assert entered.wait(10)
                try:
                    f.current=f.chief
                    return f.client.post(f'/document-distribution/manuscripts/{mid}/editor-invitations/final/{iid}/revoke',json={'reason':'Synthetic race'}).status_code
                finally:proceed.set()
            with patch.object(ArtifactStorage,'publish_reserved',paused),ThreadPoolExecutor(max_workers=2) as pool:
                work=pool.submit(process);change=pool.submit(revoke)
                assert change.result(timeout=15)==200 and work.result(timeout=15)==409
            with sqlite3.connect(f.db_path) as db:
                assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
                assert db.execute('SELECT COUNT(*) FROM controlled_automatic_grant_provenance').fetchone()==(0,)
    finally:f.tearDown()


def test_legacy_initial_current_source_denied_after_invitation_revocation():
    from tests import test_reviewer_download as fixtures
    from tests.test_batch22_invitation_distribution import prepare
    from tests.test_batch73_acceptance_intents import install
    from tests.test_batch74_precision_failures import migration as precision
    from tests.test_batch75_automatic_processor import processing_migration
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path);migration.migrate(f.db_path)
        f.current=f.editor
        assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
        assert f.client.get(f'/manuscripts/{mid}/download').content==b'Synthetic batch 22 bytes\n'
        f.current=chief
        assert f.client.post(f'/document-distribution/manuscripts/{mid}/editor-invitations/initial/{iid}/revoke',json={'reason':'Synthetic legacy'}).status_code==200
        f.current=f.editor
        assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
        assert f.client.get(f'/manuscripts/{mid}/versions/paper.txt').status_code==403
    finally:f.tearDown()


def test_concurrent_initial_acceptance_and_revocation_are_serialized():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from app.models import User
    from app.schemas import InitialEditorInvitationDecision
    from app.routers import document_distribution as distribution,eic
    from tests import test_reviewer_download as fixtures
    from tests.test_batch22_invitation_distribution import prepare
    from tests.test_batch73_acceptance_intents import install
    from tests.test_batch74_precision_failures import migration as precision
    from tests.test_batch75_automatic_processor import processing_migration
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path);migration.migrate(f.db_path)
        editor_id=f.editor.user_id;chief_id=chief.user_id;barrier=Barrier(2)
        def accept():
            with f.Session() as db:
                actor=db.get(User,editor_id);barrier.wait()
                try:return eic.respond_initial_editor_invitation(iid,InitialEditorInvitationDecision(decision='accept'),actor,db).status
                except HTTPException as exc:db.rollback();return exc.status_code
        def revoke():
            with f.Session() as db:
                actor=db.get(User,chief_id);barrier.wait()
                return distribution.revoke_editor_invitation(mid,'initial',iid,distribution.RevokeRequest(reason='Synthetic race'),actor,db)['status']
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(accept);b=pool.submit(revoke)
            assert b.result(timeout=15)=='revoked'
            assert a.result(timeout=15) in ('accepted',409)
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM editor_invitation_revocations').fetchone()==(1,)
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
        f.current=f.editor
        assert f.client.get(f'/manuscripts/{mid}/download').status_code in (403,404)
    finally:f.tearDown()


@pytest.mark.parametrize('kind',['initial','final'])
def test_concurrent_duplicate_revocation_has_one_immutable_event(kind):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from app.models import User
    from app.routers import document_distribution as distribution
    with workspace(kind) as (f,chief,mid,iid,policy,grant,other,content):
        migration.migrate(f.db_path);chief_id=chief.user_id;barrier=Barrier(2)
        def revoke():
            with f.Session() as db:
                actor=db.get(User,chief_id);barrier.wait()
                try:return distribution.revoke_editor_invitation(mid,kind,iid,distribution.RevokeRequest(reason='Synthetic duplicate'),actor,db)['status']
                except HTTPException as exc:db.rollback();return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(lambda _:revoke(),range(2)))
        assert sorted(str(x) for x in outcomes)==['409','revoked']
        with sqlite3.connect(f.db_path) as db:assert db.execute('SELECT COUNT(*) FROM editor_invitation_revocations').fetchone()==(1,)


def test_revoked_pending_final_invitation_cannot_be_accepted():
    from unittest.mock import patch
    from app.routers import eic
    from tests import test_final_workflow as fixtures
    from tests.test_batch73_acceptance_intents import install
    from tests.test_batch74_precision_failures import migration as precision
    from tests.test_batch75_automatic_processor import processing_migration
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();f.current=f.author
            assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond",json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
            invitation=f.invite(f.editor);assert invitation.status_code==201
        iid=invitation.json()['invitation_id'];install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path);migration.migrate(f.db_path)
        f.current=f.chief
        assert f.client.post(f'/document-distribution/manuscripts/{f.mid}/editor-invitations/final/{iid}/revoke',json={'reason':'Synthetic pending'}).status_code==200
        f.current=f.editor
        assert f.client.post(f'/final-workflow/invitations/{iid}/respond',json={'decision':'accept'}).status_code==409
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT status FROM final_editor_invitations WHERE invitation_id=?',(iid,)).fetchone()==('pending',)
            assert db.execute('SELECT COUNT(*) FROM controlled_automatic_intents').fetchone()==(0,)
    finally:f.tearDown()


def test_revocation_migration_reapplication_and_empty_downgrade(database):
    from tests.test_batch73_acceptance_intents import install
    from tests.test_batch74_precision_failures import migration as precision
    from tests.test_batch75_automatic_processor import processing_migration
    install(database);precision.migrate(database);processing_migration.migrate(database)
    migration.migrate(database);migration.migrate(database);migration.downgrade_empty(database);migration.migrate(database)
    with sqlite3.connect(database) as db:assert db.execute('PRAGMA foreign_key_check').fetchall()==[]

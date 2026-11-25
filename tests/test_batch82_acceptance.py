"""Disposable acceptance and concurrency checks for invitation revocation."""
from tests.batch83_migration_support import migrate_rounds
import hashlib
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from app.automatic_distribution_processor import process_intent
from app.routers import document_distribution as distribution,eic,onlyoffice
from app import onlyoffice_docx
from app.models import User
from tests import test_final_workflow as final_fixtures
from tests.test_batch77_recovery import pending
from tests.test_batch79_http_matrix import workspace
from tests.test_batch80_revocation import migration
from tests.test_batch73_acceptance_intents import install
from tests.test_batch74_precision_failures import migration as precision
from tests.test_batch75_automatic_processor import processing_migration
from tests.academic_docx_fixture import academic_docx
from tests.test_onlyoffice_gsub_integration import CONFIG


@contextmanager
def pending_role(kind):
    if kind=='initial':
        with pending() as (f,chief,mid,iid,policy,intent):
            migration.migrate(f.db_path)
            yield f,chief,mid,iid,intent
        return
    f=final_fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();f.current=f.author
            assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond",json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
            invite=f.invite(f.editor);assert invite.status_code==201
        mid=f.mid;iid=invite.json()['invitation_id'];source=b'Synthetic batch82 final\n'
        f.manuscript.file_path=f.write(f'uploads/manuscripts/{mid}/source.txt',source);f.db.commit()
        install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path);migration.migrate(f.db_path)
        private=f.root/'batch82-private';private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch82-event',f.editor.user_id,1,None,'active',1,f.chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch82-event'))
        with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=f.chief
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'final','mode':'automatic','source_sha256':hashlib.sha256(source).hexdigest(),'confirmed':True}).status_code==201
            f.current=f.editor
            with patch('app.automatic_distribution_intents.process_after_acceptance'):
                assert f.client.post(f'/final-workflow/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            with sqlite3.connect(f.db_path) as db:intent=db.execute('SELECT intent_id FROM controlled_automatic_intents').fetchone()[0]
            yield f,f.chief,mid,iid,intent
    finally:f.tearDown()


@pytest.mark.parametrize('kind',['initial','final'])
@pytest.mark.parametrize('initial_state',['pending','failed'])
def test_revoked_intent_cannot_be_processed(kind,initial_state):
    with pending_role(kind) as (f,chief,mid,iid,intent):
        if initial_state=='failed':
            with patch.object(distribution,'_storage',side_effect=HTTPException(503,'Synthetic failure')):
                with f.Session() as db:
                    with pytest.raises(HTTPException):process_intent(db,intent)
        f.current=chief
        before=f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-intents').json()
        assert next(x for x in before if x['intent_id']==intent)['state']==initial_state
        assert f.client.post(f'/document-distribution/manuscripts/{mid}/editor-invitations/{kind}/{iid}/revoke',json={'reason':'Synthetic'}).status_code==200
        after=f.client.get(f'/document-distribution/manuscripts/{mid}/automatic-intents').json()
        item=next(x for x in after if x['intent_id']==intent)
        assert item['state']=='revoked' and item['retryable'] is False
        assert f.client.post(f'/document-distribution/manuscripts/{mid}/automatic-intents/{intent}/process').status_code==409
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT count(*) FROM distribution_grants').fetchone()==(0,)
            assert db.execute('SELECT count(*) FROM controlled_automatic_intents WHERE intent_id=?',(intent,)).fetchone()==(1,)


@pytest.mark.parametrize('kind',['initial','final'])
def test_concurrent_grant_download_and_revocation(kind):
    with workspace(kind) as (f,chief,mid,iid,policy,grant,other,content):
        migration.migrate(f.db_path);editor_id=f.editor.user_id;chief_id=chief.user_id;barrier=Barrier(2)
        def read():
            with f.Session() as db:
                actor=db.get(User,editor_id);barrier.wait()
                try:return distribution.download(grant,actor,db).body
                except HTTPException as exc:return exc.status_code
        def revoke():
            with f.Session() as db:
                actor=db.get(User,chief_id);barrier.wait()
                return distribution.revoke_editor_invitation(mid,kind,iid,distribution.RevokeRequest(reason='Synthetic race'),actor,db)['status']
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(read);b=pool.submit(revoke)
            outcome=a.result(timeout=15);assert b.result(timeout=15)=='revoked'
        assert outcome in (content,409)
        f.current=f.editor
        assert f.client.get(f'/document-distribution/grants/{grant}/download').status_code==409


@pytest.mark.parametrize('operation',['session','document'])
def test_concurrent_docx_operation_and_invitation_revocation(operation):
    import json
    from urllib.parse import urlsplit,parse_qs
    from tests import test_reviewer_download as fixtures
    from tests.test_batch22_invitation_distribution import prepare
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);source=academic_docx()
        manuscript=f.db.get(__import__('app.models',fromlist=['Manuscript']).Manuscript,mid)
        manuscript.file_path=f.write(f'uploads/manuscripts/{mid}/source.docx',source);f.db.commit()
        install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path);migration.migrate(f.db_path)
        private=f.root/'batch82-docx';private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch82-docx',f.editor.user_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch82-docx'))
        env={**CONFIG,'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}
        with patch.object(distribution,'DATA_ROOT',f.root),patch.object(onlyoffice_docx,'BASE_DIR',f.root),patch.dict(os.environ,env):
            f.current=chief
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':hashlib.sha256(source).hexdigest(),'confirmed':True}).status_code==201
            f.current=f.editor;assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            initial=f.client.post(f'/onlyoffice/manuscripts/{mid}/initial/sessions');assert initial.status_code==200,initial.text
            sid=initial.json()['session'];url=urlsplit(initial.json()['config']['document']['url']);token=parse_qs(url.query)['token'][0]
            editor_id=f.editor.user_id;chief_id=chief.user_id;barrier=Barrier(2)
            def run():
                with f.Session() as db:
                    actor=db.get(User,editor_id);barrier.wait()
                    try:
                        response=onlyoffice.create_session(mid,'initial',actor,db) if operation=='session' else onlyoffice.document(sid,token,db)
                        return response.status_code
                    except HTTPException as exc:return exc.status_code
            def revoke():
                with f.Session() as db:
                    actor=db.get(User,chief_id);barrier.wait()
                    return distribution.revoke_editor_invitation(mid,'initial',iid,distribution.RevokeRequest(reason='Synthetic race'),actor,db)['status']
            with ThreadPoolExecutor(max_workers=2) as pool:
                a=pool.submit(run);b=pool.submit(revoke)
                outcome=a.result(timeout=15);assert b.result(timeout=15)=='revoked'
            assert outcome in (200,403)
            f.current=f.editor
            assert f.client.get(url.path+'?'+url.query).status_code==403
            assert f.client.post(f'/onlyoffice/manuscripts/{mid}/initial/sessions').status_code==403
    finally:f.tearDown()


def test_final_source_grant_evidence_does_not_record_review_round():
    # Capture the existing schema contract; do not infer that a missing round is zero.
    with workspace('final') as (f,chief,mid,iid,policy,grant,other,content):
        migration.migrate(f.db_path)
        with sqlite3.connect(f.db_path) as db:
            row=db.execute('SELECT review_round FROM distribution_grants WHERE grant_id=?',(grant,)).fetchone()
            columns={item[1] for item in db.execute('PRAGMA table_info(controlled_automatic_grant_provenance)')}
            assert row==(None,) and 'review_round' not in columns

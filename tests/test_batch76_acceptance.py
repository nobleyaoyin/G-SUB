"""Disposable migration-chain and grant-identity regressions."""
from tests.batch83_migration_support import migrate_rounds
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import urlsplit
from unittest.mock import patch
import jwt
import pytest

from app.routers import document_distribution as distribution
from app.reviewer_artifact_storage import ArtifactStorage
from tests import test_reviewer_download as fixtures, test_final_workflow as final_fixtures
from tests.test_batch17b_distribution_migration import database, migration as manual
from tests.test_batch22_invitation_distribution import prepare
from tests.test_batch67_auto_migration import auto
from tests.test_batch70_controlled_source import policy_migration, provenance_migration
from tests.test_batch73_acceptance_intents import install, intent_migration
from tests.test_batch74_precision_failures import migration as precision
from tests.test_batch75_automatic_processor import processing_migration
from tests.academic_docx_fixture import academic_docx
from tests.test_onlyoffice_gsub_integration import CONFIG, SECRET
from app import onlyoffice_docx


def test_supported_upgrade_from_027_and_existing_028_is_reentrant(database):
    manual.migrate(database);auto.migrate(database);policy_migration.migrate(database);provenance_migration.migrate(database)
    root=Path(__file__).resolve().parents[1]
    cmd=[sys.executable,str(root/'scripts/upgrade_automatic_distribution.py'),str(database)]
    for _ in range(2):
        result=subprocess.run(cmd,cwd=root,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    processing_migration.downgrade_empty(database);precision.downgrade_empty(database)
    intent_migration.migrate(database)
    result=subprocess.run(cmd,cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute("SELECT count(*) FROM schema_migrations WHERE migration_id IN ('028_automatic_distribution_intents','029_intent_precision_failures','030_automatic_processing')").fetchone()==(3,)


def test_unprovenanced_grant_cannot_borrow_another_grants_provenance():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path)
        content=b'Synthetic batch 22 bytes\n';digest=hashlib.sha256(content).hexdigest()
        private=f.root/'batch76-private';private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch76-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch76-event'))
        with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=chief
            policy=f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':digest,'confirmed':True})
            assert policy.status_code==201,policy.text
            f.current=f.editor
            assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            listing=f.client.get('/document-distribution/my').json()
            assert len(listing)==1 and listing[0]['mode']=='automatic'
            real=listing[0]['grant_id'];assert f.client.get(f'/document-distribution/grants/{real}/download').content==content
            sid='a'*32;artifact='b'*32;unproven='c'*32;stamp='2026-01-01T00:00:00.000000Z'
            with ArtifactStorage(str(private)) as store: store.publish_reserved(sid,content,'txt')
            with sqlite3.connect(f.db_path) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('INSERT INTO distribution_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(sid,mid,chief.user_id,'editor_source',None,None,digest,len(content),'txt','batch76-reserve-key-01','d'*64,stamp))
                db.execute('INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(artifact,mid,'editor_source',2,sid,digest,len(content),'txt',None,None,chief.user_id,stamp))
                db.execute('INSERT INTO distribution_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(unproven,mid,artifact,f.editor.user_id,'editor',iid,None,None,None,chief.user_id,'manual','not_requested','not_requested','batch76-unproven-key-01','e'*64,stamp))
            assert f.client.get(f'/document-distribution/grants/{unproven}/download').status_code==403
            assert [item['grant_id'] for item in f.client.get('/document-distribution/my').json()]==[real]
            with sqlite3.connect(f.db_path) as db: db.execute('DROP TRIGGER controlled_automatic_grant_provenance_no_update')
            assert f.client.get(f'/document-distribution/grants/{real}/download').status_code==503
            with sqlite3.connect(f.db_path) as db: db.execute(processing_migration.DDL['controlled_automatic_grant_provenance_no_update'])
            f.current=chief
            history=f.client.get(f'/document-distribution/manuscripts/{mid}/history').json()
            assert next(item for item in history if item['grant_id']==real)['mode']=='automatic'
            assert next(item for item in history if item['grant_id']==unproven)['mode']=='manual'
            assert f.client.post(f"/document-distribution/manuscripts/{mid}/policies/{policy.json()['policy_id']}/revoke",json={'reason':'Synthetic'}).status_code==200
            history=f.client.get(f'/document-distribution/manuscripts/{mid}/history').json()
            assert next(item for item in history if item['grant_id']==real)['policy_status']=='revoked'
            f.current=f.editor
            assert f.client.get('/document-distribution/my').json()==[]
            assert f.client.get(f'/document-distribution/grants/{real}/download').status_code==403
    finally:f.tearDown()


@pytest.mark.parametrize('revocation',['grant','policy'])
def test_controlled_automatic_docx_session_and_preview_recheck(revocation):
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f)
        source=academic_docx();digest=hashlib.sha256(source).hexdigest()
        from app.models import Manuscript
        manuscript=f.db.get(Manuscript,mid);manuscript.file_path=f.write(f'uploads/manuscripts/{mid}/paper.docx',source);f.db.commit()
        install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path)
        private=f.root/'batch76-docx-private';private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch76-docx-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch76-docx-event'))
        env={**CONFIG,'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}
        with patch.object(distribution,'DATA_ROOT',f.root),patch.object(onlyoffice_docx,'BASE_DIR',f.root),patch.dict(os.environ,env):
            f.current=chief
            policy=f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':digest,'confirmed':True})
            assert policy.status_code==201,policy.text
            f.current=f.editor
            assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
            base=f'/onlyoffice/manuscripts/{mid}/initial'
            session=f.client.post(base+'/sessions');assert session.status_code==200,session.text
            data=session.json();sid=data['session'];uri=urlsplit(data['config']['document']['url'])
            assert f.client.get(uri.path+'?'+uri.query).content==source
            body={'key':sid,'status':6,'url':'http://127.0.0.1:8088/cache/files/synthetic','forcesavetype':1}
            token=jwt.encode({'payload':body,'operation':'callback'},SECRET,algorithm='HS256')
            with patch.object(onlyoffice_docx,'fetch',return_value=source):
                assert f.client.post('/onlyoffice/callbacks/'+sid,json=body,headers={'Authorization':'Bearer '+token}).status_code==200
            versions=f.client.get(base+'/versions');assert versions.status_code==200 and len(versions.json())==1
            vid=versions.json()[0]['id'];assert f.client.get(base+'/versions/'+vid).content==source
            preview=f.client.post(base+'/versions/'+vid+'/preview');assert preview.status_code==200
            p=urlsplit(preview.json()['config']['document']['url']);assert f.client.get(p.path+'?'+p.query).content==source
            grant=f.client.get('/document-distribution/my').json()[0]['grant_id']
            f.current=f.reviewer;assert f.client.post(base+'/sessions').status_code!=200
            f.current=chief
            endpoint=(f'/document-distribution/grants/{grant}/revoke' if revocation=='grant' else f"/document-distribution/manuscripts/{mid}/policies/{policy.json()['policy_id']}/revoke")
            assert f.client.post(endpoint,json={'reason':'Synthetic'}).status_code==200
            f.current=f.editor
            assert f.client.get(uri.path+'?'+uri.query).status_code==403
            assert f.client.post(base+'/sessions').status_code==403
            assert f.client.get(base+'/versions').status_code==403
            assert f.client.post(base+'/versions/'+vid+'/preview').status_code==403
            assert f.client.get(p.path+'?'+p.query).status_code==403
    finally:f.tearDown()


def test_concurrent_final_acceptance_produces_one_automatic_grant():
    from fastapi import HTTPException
    from app.models import User
    from app.routers import eic, final_workflow
    f=final_fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();f.current=f.author
            assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond",json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
            invitation=f.invite(f.editor);assert invitation.status_code==201
            iid=invitation.json()['invitation_id'];content=b'Synthetic batch76 final concurrent\n';digest=hashlib.sha256(content).hexdigest()
            f.manuscript.file_path=f.write(f'uploads/manuscripts/{f.mid}/paper.txt',content);f.db.commit()
            install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path)
            private=f.root/'batch76-final-concurrent';private.mkdir(mode=0o700)
            with sqlite3.connect(f.db_path) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch76-final-event',f.editor.user_id,1,None,'active',1,f.chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
                db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch76-final-event'))
            with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
                f.current=f.chief
                assert f.client.post(f'/document-distribution/manuscripts/{f.mid}/policies',json={'invitation_kind':'final','mode':'automatic','source_sha256':digest,'confirmed':True}).status_code==201
                barrier=Barrier(2)
                def respond():
                    with f.Session() as session:
                        actor=session.get(User,f.editor.user_id);barrier.wait()
                        try: return final_workflow.respond(iid,final_workflow.Respond(decision='accept'),actor,session)['status']
                        except HTTPException as exc: session.rollback();return exc.status_code
                with ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(lambda _:respond(),range(2)))
                assert sorted(str(x) for x in outcomes)==['409','accepted']
                with sqlite3.connect(f.db_path) as db:
                    assert db.execute('SELECT count(*) FROM controlled_automatic_intents').fetchone()==(1,)
                    assert db.execute('SELECT count(*) FROM controlled_automatic_grant_provenance').fetchone()==(1,)
                    assert db.execute('SELECT count(*) FROM distribution_grants').fetchone()==(1,)
    finally:f.tearDown()

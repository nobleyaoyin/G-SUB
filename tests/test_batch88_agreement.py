"""Disposable agreement snapshot, response and authorization checks."""
import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import pytest
from app import agreement_content, main, models
from app.database import get_db
from app.routers import eic
from tests import test_final_workflow as fixtures

migration=importlib.import_module('migrations.034_agreement_snapshot_guards')


def test_template_registry_never_claims_approval():
    item=agreement_content.issuance_template('development')
    assert item.version=='placeholder-v1' and item.approval_status=='prototype' and item.approval_reference is None
    assert item.approved_by is None and item.approved_at is None
    assert len(item.content_sha256)==64
    with pytest.raises(RuntimeError,match='Approved'):agreement_content.issuance_template('production')
    with pytest.raises(TypeError):agreement_content.TEMPLATES['new']=item
    assert agreement_content.snapshot_status(item.version,item.text)=='prototype'
    assert agreement_content.snapshot_status(item.version,item.text+' changed')=='unverified'
    assert agreement_content.snapshot_status('unknown','synthetic')=='unverified'


def test_generation_snapshot_migration_response_and_final_workflow():
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        migration.migrate(f.db_path);migration.migrate(f.db_path)
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();aid=agreement['agreement_id'];version=agreement['agreement_version'];mid=f.mid
            assert agreement['template_status']=='prototype' and 'not a legal' in agreement['agreement_text']
            with sqlite3.connect(f.db_path) as db:
                record=db.execute('SELECT manuscript_id,author_id,decision_id,agreement_version,agreement_text,status FROM author_agreements WHERE agreement_id=?',(aid,)).fetchone()
                assert record[:2]==(mid,f.author.user_id) and record[3:]==(version,agreement['agreement_text'],'pending')
                assert db.execute('SELECT decision,manuscript_id FROM eic_decisions WHERE decision_id=?',(record[2],)).fetchone()==('accept',mid)
                with pytest.raises(sqlite3.IntegrityError,match='agreement binding unavailable'):
                    db.execute("INSERT INTO author_agreements(manuscript_id,decision_id,author_id,agreement_version,agreement_text,status,created_at,responded_at) VALUES(?,?,?,?,?,'accepted','synthetic','synthetic')",(mid,record[2],f.author.user_id,version,agreement['agreement_text']))
                with pytest.raises(sqlite3.IntegrityError):db.execute("UPDATE author_agreements SET agreement_text='altered' WHERE agreement_id=?",(aid,))
                with pytest.raises(sqlite3.IntegrityError):db.execute("UPDATE author_agreements SET agreement_version='changed' WHERE agreement_id=?",(aid,))
                with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE author_agreements SET author_id=? WHERE agreement_id=?',(f.other_author.user_id,aid))
                with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM author_agreements WHERE agreement_id=?',(aid,))
                assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
            f.current=f.chief
            assert f.client.post(f'/eic/manuscripts/{mid}/decision',json={'decision':'accept','comments':'Duplicate'}).status_code==409
            assert f.client.post('/final-workflow/invite',json={'manuscript_id':mid,'editor_id':f.editor.user_id}).status_code==409
            assert f.client.post(f'/agreements/{aid}/respond',json={'decision':'accept','agreement_version':version}).status_code==403
            f.current=f.other_author
            assert f.client.get(f'/agreements/manuscripts/{mid}').status_code==404
            assert f.client.post(f'/agreements/{aid}/respond',json={'decision':'accept','agreement_version':version}).status_code==403
            f.current=f.author
            with patch.object(agreement_content,'TEMPLATES',{}):
                historical=f.client.get('/agreements/my').json()[0]
                assert historical['agreement_text']==agreement['agreement_text'] and historical['template_status']=='unverified'
            assert f.client.post(f'/agreements/{aid}/respond',json={'decision':'accept','agreement_version':version,'agreement_text':'fake'}).status_code==422
            assert f.client.post(f'/agreements/{aid}/respond',json={'decision':'accept','agreement_version':'bad-version'}).status_code==409
            first=f.client.post(f'/agreements/{aid}/respond',json={'decision':'accept','agreement_version':version})
            repeat=f.client.post(f'/agreements/{aid}/respond',json={'decision':'accept','agreement_version':version})
            assert first.status_code==repeat.status_code==200 and first.json()['responded_at']==repeat.json()['responded_at']
            assert f.client.post(f'/agreements/{aid}/respond',json={'decision':'decline','agreement_version':version}).status_code==409
            with sqlite3.connect(f.db_path) as db:
                with pytest.raises(sqlite3.IntegrityError):db.execute("UPDATE author_agreements SET status='declined' WHERE agreement_id=?",(aid,))
                assert db.execute('SELECT count(*) FROM author_agreements WHERE decision_id=?',(record[2],)).fetchone()==(1,)
            f.current=f.chief
            assert f.client.post('/final-workflow/invite',json={'manuscript_id':mid,'editor_id':f.editor.user_id}).status_code==201
            with pytest.raises(RuntimeError,match='retained'):migration.downgrade_empty(f.db_path)
    finally:f.tearDown()


@pytest.mark.parametrize('decisions',[('accept','accept'),('accept','decline')])
def test_concurrent_responses_are_consistent(decisions):
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        migration.migrate(f.db_path)
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();aid=agreement['agreement_id'];version=agreement['agreement_version'];f.current=f.author
            def independent():
                with f.Session() as db:yield db
            main.app.dependency_overrides[get_db]=independent
            barrier=Barrier(2)
            def send(decision):
                barrier.wait()
                return f.client.post(f'/agreements/{aid}/respond',json={'decision':decision,'agreement_version':version})
            with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(send,decisions))
            assert sorted(x.status_code for x in results)==([200,200] if decisions[0]==decisions[1] else [200,409]),[x.text for x in results]
            with sqlite3.connect(f.db_path) as db:
                status,stamp=db.execute('SELECT status,responded_at FROM author_agreements WHERE agreement_id=?',(aid,)).fetchone()
                assert status in ('accepted','declined') and stamp
                count=db.execute("SELECT count(*) FROM notifications WHERE manuscript_id=? AND notification_type='author_agreement_response'",(f.mid,)).fetchone()[0]
                assert count==2
    finally:f.tearDown()


def test_migration_empty_downgrade_and_reapply():
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        migration.migrate(f.db_path);migration.downgrade_empty(f.db_path);migration.migrate(f.db_path)
        with sqlite3.connect(f.db_path) as db:assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    finally:f.tearDown()


def test_wrong_author_on_legacy_agreement_cannot_authorize_final_invitation():
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();aid=agreement['agreement_id'];f.current=f.author
            assert f.client.post(f'/agreements/{aid}/respond',json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
            # Corrupt only an isolated pre-034 legacy fixture to test the guard.
            with sqlite3.connect(f.db_path) as db:db.execute('UPDATE author_agreements SET author_id=? WHERE agreement_id=?',(f.other_author.user_id,aid))
            f.current=f.chief
            assert f.client.post('/final-workflow/invite',json={'manuscript_id':f.mid,'editor_id':f.editor.user_id}).status_code==409
    finally:f.tearDown()


def test_synthetic_approved_template_requires_installed_snapshot_guards():
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            f.select_single_blind_policy()
            assignment=f.assign(f.reviewer,1);assert assignment.status_code==201,assignment.text
            f.current=f.reviewer
            assert f.client.post('/reviews/',json={'assignment_id':assignment.json()['assignment_id'],'comments':'Synthetic review','recommendation':'accept'}).status_code==201
            f.current=f.chief
            test_only=agreement_content.AgreementTemplate('synthetic-test-only','Synthetic test text','approved','synthetic-test-only')
            with patch.object(eic,'issuance_template',return_value=test_only):
                decision=f.client.post(f'/eic/manuscripts/{f.mid}/decision',json={'decision':'accept','comments':'Synthetic'})
            assert decision.status_code==503 and 'protection' in decision.json()['detail']
            with sqlite3.connect(f.db_path) as db:
                assert db.execute('SELECT count(*) FROM author_agreements WHERE manuscript_id=?',(f.mid,)).fetchone()==(0,)
                assert db.execute('SELECT count(*) FROM eic_decisions WHERE manuscript_id=?',(f.mid,)).fetchone()==(0,)
    finally:f.tearDown()


def test_decline_is_idempotent_and_final_invitation_remains_blocked():
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        migration.migrate(f.db_path)
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();aid=agreement['agreement_id'];version=agreement['agreement_version'];f.current=f.author
            payload={'decision':'decline','agreement_version':version}
            first=f.client.post(f'/agreements/{aid}/respond',json=payload)
            repeat=f.client.post(f'/agreements/{aid}/respond',json=payload)
            assert first.status_code==repeat.status_code==200 and first.json()['responded_at']==repeat.json()['responded_at']
            assert f.client.post(f'/agreements/{aid}/respond',json={**payload,'decision':'accept'}).status_code==409
            f.current=f.chief
            assert f.client.post('/final-workflow/invite',json={'manuscript_id':f.mid,'editor_id':f.editor.user_id}).status_code==409
            with sqlite3.connect(f.db_path) as db:
                with pytest.raises(sqlite3.IntegrityError):db.execute("UPDATE author_agreements SET status='accepted' WHERE agreement_id=?",(aid,))
    finally:f.tearDown()


def test_invalid_legacy_agreement_blocks_existing_final_editor_paths():
    from fastapi import HTTPException
    from app import onlyoffice_docx
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();aid=agreement['agreement_id'];f.current=f.author
            assert f.client.post(f'/agreements/{aid}/respond',json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
            invitation=f.invite(f.editor);assert invitation.status_code==201
            assert f.respond(f.editor,invitation.json()['invitation_id'],'accept').status_code==200
            # Simulate an invalid pre-034 record only in the disposable fixture.
            with sqlite3.connect(f.db_path) as db:db.execute('UPDATE author_agreements SET author_id=? WHERE agreement_id=?',(f.other_author.user_id,aid))
            f.db.expire_all();f.current=f.editor
            assert f.client.get(f'/eic/manuscripts/{f.mid}/online-text/final').status_code==404
            assert f.client.post(f'/eic/final-editing/{f.mid}/submit',data={'comments':'Synthetic'},files={'file':('final.pdf',b'%PDF-synthetic','application/pdf')}).status_code==409
            with pytest.raises(HTTPException) as exc:onlyoffice_docx.source(f.db,f.mid,f.editor.user_id,'final')
            assert exc.value.status_code==404
    finally:f.tearDown()


def test_retry_reconciles_if_other_response_commits_between_reads():
    from threading import Event, Lock
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        migration.migrate(f.db_path)
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();aid=agreement['agreement_id'];version=agreement['agreement_version'];f.current=f.author
            first_read=Event();release=Event();gate=Lock();claimed=[False]
            def independent():
                with f.Session() as db:
                    original=db.get
                    def controlled(entity,*args,**kwargs):
                        if entity is models.Manuscript:
                            with gate:
                                should_wait=not claimed[0]
                                if should_wait:claimed[0]=True
                            if should_wait:
                                first_read.set()
                                if not release.wait(10):raise RuntimeError('synthetic race timed out')
                        return original(entity,*args,**kwargs)
                    db.get=controlled
                    yield db
            main.app.dependency_overrides[get_db]=independent
            payload={'decision':'accept','agreement_version':version}
            with ThreadPoolExecutor(max_workers=1) as pool:
                earlier=pool.submit(f.client.post,f'/agreements/{aid}/respond',json=payload)
                assert first_read.wait(10)
                try:later=f.client.post(f'/agreements/{aid}/respond',json=payload)
                finally:release.set()
                earlier=earlier.result(timeout=15)
            assert earlier.status_code==later.status_code==200,(earlier.text,later.text)
            assert earlier.json()['responded_at']==later.json()['responded_at']
            with sqlite3.connect(f.db_path) as db:
                assert db.execute("SELECT count(*) FROM notifications WHERE manuscript_id=? AND notification_type='author_agreement_response'",(f.mid,)).fetchone()==(2,)
    finally:f.tearDown()


def test_damaged_installed_guards_block_new_agreement_issuance():
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        migration.migrate(f.db_path)
        with patch.object(eic,'BASE_DIR',f.root):
            f.select_single_blind_policy()
            assignment=f.assign(f.reviewer,1);assert assignment.status_code==201
            f.current=f.reviewer
            assert f.client.post('/reviews/',json={'assignment_id':assignment.json()['assignment_id'],'comments':'Synthetic review','recommendation':'accept'}).status_code==201
            with sqlite3.connect(f.db_path) as db:db.execute('DROP TRIGGER author_agreement_snapshot_immutable')
            f.current=f.chief
            response=f.client.post(f'/eic/manuscripts/{f.mid}/decision',json={'decision':'accept','comments':'Synthetic'})
            assert response.status_code==503 and 'protection' in response.json()['detail']
            with sqlite3.connect(f.db_path) as db:
                assert db.execute('SELECT count(*) FROM author_agreements').fetchone()==(0,)
                assert db.execute('SELECT count(*) FROM eic_decisions').fetchone()==(0,)
    finally:f.tearDown()


def test_missing_legacy_agreement_cannot_reuse_final_invitation():
    f=fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();aid=agreement['agreement_id'];f.current=f.author
            assert f.client.post(f'/agreements/{aid}/respond',json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
            invitation=f.invite(f.editor);assert invitation.status_code==201
            assert f.respond(f.editor,invitation.json()['invitation_id'],'accept').status_code==200
            # Simulate a missing pre-034 agreement in the disposable database.
            with sqlite3.connect(f.db_path) as db:db.execute('DELETE FROM author_agreements WHERE agreement_id=?',(aid,))
            f.db.expire_all();f.current=f.editor
            response=f.client.post(f'/eic/final-editing/{f.mid}/submit',data={'comments':'Synthetic'},files={'file':('final.pdf',b'%PDF-synthetic','application/pdf')})
            assert response.status_code==409,response.text
    finally:f.tearDown()

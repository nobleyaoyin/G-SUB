"""Effective editor invitation status using disposable HTTP fixtures."""
import importlib
import sqlite3
import pytest
from tests.test_batch79_http_matrix import workspace

migration=importlib.import_module('migrations.031_editor_invitation_revocation')

@pytest.mark.parametrize('kind',['initial','final'])
def test_revoked_invitation_is_inactive_in_role_lists_and_eic_overview(kind):
    with workspace(kind) as (f,chief,mid,iid,policy,grant,other,content):
        migration.migrate(f.db_path)
        f.current=chief
        assert f.client.post(f'/document-distribution/manuscripts/{mid}/editor-invitations/{kind}/{iid}/revoke',json={'reason':'Synthetic'}).status_code==200
        overview=f.client.get(f'/eic/manuscripts/{mid}/overview');assert overview.status_code==200,overview.text
        group='invitations' if kind=='initial' else 'final_invitations'
        entry=next(x for x in overview.json()[group] if x['invitation_id']==iid)
        assert entry['status']=='revoked' and entry['original_status']=='accepted'
        replacement_url='/eic/initial-editor/invite' if kind=='initial' else '/final-workflow/invite'
        replacement=f.client.post(replacement_url,json={'manuscript_id':mid,'editor_id':other.user_id})
        assert replacement.status_code==409
        f.current=f.editor
        if kind=='initial':
            result=f.client.get('/eic/initial-editing/my');assert result.status_code==200
            item=next(x for x in result.json() if x['manuscript_id']==mid)
            assert item['invitation']['status']=='revoked' and item['invitation_abstract'] is None and not item['submissions']
            upload=f.client.post(f'/eic/initial-editing/{mid}/submit',data={'comments':'Synthetic'},files={'file':('x.pdf',b'%PDF-synthetic','application/pdf')})
        else:
            result=f.client.get('/final-workflow/my');assert result.status_code==200
            item=next(x for x in result.json() if x['invitation_id']==iid)
            assert item['status']=='revoked' and item['original_status']=='accepted' and item['invitation_abstract'] is None and not item['submissions']
            upload=f.client.post(f'/eic/final-editing/{mid}/submit',data={'comments':'Synthetic'},files={'file':('x.pdf',b'%PDF-synthetic','application/pdf')})
        assert upload.status_code==403,upload.text
        with sqlite3.connect(f.db_path) as db:
            table='initial_editor_invitations' if kind=='initial' else 'final_editor_invitations'
            assert db.execute(f'SELECT status FROM {table} WHERE invitation_id=?',(iid,)).fetchone()==('accepted',)


def test_final_acceptance_races_revocation():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from unittest.mock import patch
    from fastapi import HTTPException
    from app.models import User
    from app.routers import eic,final_workflow,document_distribution
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
        iid=invitation.json()['invitation_id'];mid=f.mid;editor_id=f.editor.user_id;chief_id=f.chief.user_id
        install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migration.migrate(f.db_path)
        barrier=Barrier(2)
        def accept():
            with f.Session() as db:
                actor=db.get(User,editor_id);barrier.wait()
                try:return final_workflow.respond(iid,final_workflow.Respond(decision='accept'),actor,db)['status']
                except HTTPException as exc:db.rollback();return exc.status_code
        def revoke():
            with f.Session() as db:
                actor=db.get(User,chief_id);barrier.wait()
                return document_distribution.revoke_editor_invitation(mid,'final',iid,document_distribution.RevokeRequest(reason='Synthetic race'),actor,db)['status']
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(accept);b=pool.submit(revoke)
            assert b.result(timeout=15)=='revoked'
            assert a.result(timeout=15) in ('accepted',409)
        with sqlite3.connect(f.db_path) as db:
            assert db.execute('SELECT COUNT(*) FROM editor_invitation_revocations').fetchone()==(1,)
            assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
    finally:f.tearDown()

"""Synthetic initial invitation, notification and immutable manual grant integration."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import pytest
from sqlalchemy import event, select
from fastapi import HTTPException
from app import models
from app.schemas import InitialEditorInvitationDecision
from app.routers import eic, document_distribution as distribution
from tests import test_reviewer_download as fixtures
from tests.test_batch17c_editor_distribution import migrate_current_distribution


def prepare(f):
    chief=models.User(name='Synthetic EIC',email='eic22@example.invalid',password_hash='x',role='eic')
    manuscript=models.Manuscript(title='Synthetic 22',abstract='Synthetic abstract',author_id=f.author.user_id,status='initial_scan_passed',review_round=1)
    f.db.add_all([chief,manuscript]);f.db.flush();mid=manuscript.manuscript_id
    manuscript.file_path=f.write(f'uploads/manuscripts/{mid}/paper.txt',b'Synthetic batch 22 bytes\n')
    f.db.commit();f.current=chief
    response=f.client.post('/eic/initial-editor/invite',json={'manuscript_id':mid,'editor_id':f.editor.user_id})
    assert response.status_code==201,response.text
    return chief,mid,response.json()['invitation_id']


def test_invitation_accept_notification_grant_download_and_revoke():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);migrate_current_distribution(f.db_path)
        private=f.root/'private-22';private.mkdir(mode=0o700)
        with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            before=f.client.get(f'/document-distribution/manuscripts/{mid}/candidates').json()
            assert not any(x['invitation_id']==iid for x in before['recipients'])
            f.current=f.other
            assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==403
            f.current=f.editor
            pending=next(x for x in f.client.get('/eic/initial-editing/my').json() if x['manuscript_id']==mid)
            assert pending['invitation']['invited_at'] and pending['invitation']['responded_at'] is None
            accepted=f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'})
            assert accepted.status_code==200,accepted.text
            assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==409
            item=next(x for x in f.client.get('/eic/initial-editing/my').json() if x['manuscript_id']==mid)
            assert item['invitation']['status']=='accepted' and item['invitation']['responded_at']
            f.current=chief
            notices=[n for n in f.client.get('/notifications/my').json() if n['manuscript_id']==mid and n['notification_type']=='initial_editor_response']
            assert len(notices)==1
            overview=f.client.get(f'/eic/manuscripts/{mid}/overview').json()
            assert overview['invitations'][0]['responded_at']
            candidates=f.client.get(f'/document-distribution/manuscripts/{mid}/candidates').json()
            request={'invitation_kind':'initial','invitation_id':iid,'source_sha256':candidates['document']['sha256'],'idempotency_key':'synthetic-batch22-key-001'}
            assert any(x['invitation_id']==iid for x in candidates['recipients'])
            granted=f.client.post(f'/document-distribution/manuscripts/{mid}/grants',json=request)
            assert granted.status_code==200,granted.text
            gid=granted.json()['grant_id']
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/grants',json=request).json()['grant_id']==gid
            f.current=f.editor
            assert f.client.get(f'/document-distribution/grants/{gid}/download').content==b'Synthetic batch 22 bytes\n'
            f.current=chief
            assert f.client.post(f'/document-distribution/grants/{gid}/revoke',json={'reason':'Synthetic'}).status_code==200
            assert f.client.post(f'/document-distribution/manuscripts/{mid}/grants',json=request).status_code==409
            f.current=f.editor
            assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==404
    finally:f.tearDown()


def test_concurrent_initial_acceptance_has_one_notification():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f);uid=f.editor.user_id
        barrier=Barrier(2)
        def respond():
            with f.Session() as session:
                actor=session.get(models.User,uid);connection_id=id(session.connection().connection.driver_connection);barrier.wait()
                try:
                    result=eic.respond_initial_editor_invitation(iid,InitialEditorInvitationDecision(decision='accept'),actor,session)
                    return result.status,connection_id
                except HTTPException as exc:
                    session.rollback();return exc.status_code,connection_id
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(lambda _:respond(),range(2)))
        assert len({identity for _,identity in outcomes})==2
        assert sorted(str(status) for status,_ in outcomes)==['409','accepted']
        f.db.expire_all()
        rows=f.db.scalars(select(models.Notification).where(models.Notification.user_id==chief.user_id,models.Notification.manuscript_id==mid,models.Notification.notification_type=='initial_editor_response')).all()
        assert len(rows)==1
        assert f.db.get(models.Manuscript,mid).status=='initial_editing'
    finally:f.tearDown()


def test_initial_response_notification_failure_rolls_back():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,iid=prepare(f)
        def fail(mapper,connection,target):
            if target.notification_type=='initial_editor_response': raise RuntimeError('Synthetic insert failure')
        event.listen(models.Notification,'before_insert',fail)
        try:
            with f.Session() as session:
                actor=session.get(models.User,f.editor.user_id)
                with pytest.raises(RuntimeError): eic.respond_initial_editor_invitation(iid,InitialEditorInvitationDecision(decision='accept'),actor,session)
                session.rollback()
        finally:event.remove(models.Notification,'before_insert',fail)
        f.db.expire_all()
        assert f.db.get(models.InitialEditorInvitation,iid).status=='pending'
        assert f.db.get(models.Manuscript,mid).status=='initial_editor_invited'
        f.current=f.editor
        assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
    finally:f.tearDown()

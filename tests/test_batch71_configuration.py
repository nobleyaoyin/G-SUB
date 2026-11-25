"""Disposable HTTP tests for prospective EIC policy administration."""
from unittest.mock import patch
import sqlite3

from app.routers import document_distribution as distribution
from tests import test_reviewer_download as fixtures
from tests.test_batch17c_editor_distribution import migration as manual
from tests.test_batch22_invitation_distribution import prepare
from tests.test_batch67_auto_migration import auto
from tests.test_batch70_controlled_source import policy_migration


def test_eic_manual_policy_authorization_history_revocation_and_restrictions():
    f=fixtures.ReviewerDownloadsTest();f.setUp()
    try:
        chief,mid,_=prepare(f)
        manual.migrate(f.db_path);auto.migrate(f.db_path);policy_migration.migrate(f.db_path)
        with patch.object(distribution,'DATA_ROOT',f.root):
            f.current=chief
            import hashlib
            digest=hashlib.sha256(b'Synthetic batch 22 bytes\n').hexdigest()
            path=f'/document-distribution/manuscripts/{mid}/policies'
            assert f.client.get(path).json()=={'default_mode':'manual','policies':[]}
            payload={'invitation_kind':'initial','mode':'manual','source_sha256':digest,'confirmed':True}
            f.current=f.editor
            assert f.client.post(path,json=payload).status_code==403
            f.current=chief
            assert f.client.post(path,json={**payload,'invitation_kind':'reviewer'}).status_code==422
            assert f.client.post(path,json={**payload,'confirmed':False}).status_code==422
            assert f.client.post(path,json={**payload,'source_sha256':'0'*64}).status_code==409
            assert f.client.post(path,json={**payload,'mode':'automatic'}).status_code==503
            assert f.client.post(path,json=payload).status_code==503
            with sqlite3.connect(f.db_path) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',('a'*32,mid,'initial','manual','current_author_manuscript',f'uploads/manuscripts/{mid}/paper.txt',digest,1,chief.user_id,'2026-01-01T00:00:00.000000Z'))
            history=f.client.get(path).json()['policies']
            assert len(history)==1 and history[0]['status']=='active' and 'source_ref' not in history[0]
            policy_id=history[0]['policy_id']
            assert f.client.post(f'/document-distribution/manuscripts/999999/policies/{policy_id}/revoke',json={'reason':'Synthetic'}).status_code==404
            revoke=f.client.post(f'{path}/{policy_id}/revoke',json={'reason':'Synthetic'})
            assert revoke.status_code==200
            assert f.client.post(f'{path}/{policy_id}/revoke',json={'reason':'Synthetic'}).status_code==200
            assert f.client.get(path).json()['policies'][0]['status']=='revoked'
            assert f.client.post(path,json={**payload,'invitation_kind':'final'}).status_code==503
    finally:f.tearDown()

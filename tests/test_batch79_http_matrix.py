"""Controlled source HTTP denials against independent synthetic Editor contexts."""
from tests.batch83_migration_support import migrate_rounds
import hashlib
import os
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from app.automatic_distribution_processor import process_intent
from app.routers import document_distribution as distribution, eic
from app import models, onlyoffice_docx
from tests import test_final_workflow as final_fixtures
from tests.test_batch77_recovery import pending
from tests.test_batch73_acceptance_intents import install
from tests.test_batch74_precision_failures import migration as precision
from tests.test_batch75_automatic_processor import processing_migration
from tests.test_onlyoffice_gsub_integration import CONFIG


@contextmanager
def workspace(kind):
    if kind=='initial':
        with pending() as (f,chief,mid,iid,policy,intent):
            with f.Session() as session: grant=process_intent(session,intent)['grant_id']
            other=models.User(name='Other editor',email='batch79-other@example.invalid',password_hash='x',role='editor')
            f.db.add(other);f.db.commit()
            yield f,chief,mid,iid,policy,grant,other,b'Synthetic batch 22 bytes\n'
        return
    f=final_fixtures.FinalWorkflowTest();f.setUp()
    try:
        with patch.object(eic,'BASE_DIR',f.root):
            agreement=f.reach_agreement();f.current=f.author
            assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond",json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
            inv=f.invite(f.editor);assert inv.status_code==201
        iid=inv.json()['invitation_id'];mid=f.mid;chief=f.chief
        content=b'Synthetic Batch 79 final source\n'
        f.manuscript.file_path=f.write(f'uploads/manuscripts/{mid}/batch79.txt',content);f.db.commit()
        install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);migrate_rounds(f.db_path)
        private=f.root/'batch79-private';private.mkdir(mode=0o700)
        with sqlite3.connect(f.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch79-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
            db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch79-event'))
        with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
            f.current=chief
            policy=f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'final','mode':'automatic','source_sha256':hashlib.sha256(content).hexdigest(),'confirmed':True});assert policy.status_code==201,policy.text
            f.current=f.editor
            accept=f.client.post(f'/final-workflow/invitations/{iid}/respond',json={'decision':'accept'});assert accept.status_code==200,accept.text
            listing=f.client.get('/document-distribution/my').json();assert len(listing)==1
            yield f,chief,mid,iid,policy.json()['policy_id'],listing[0]['grant_id'],f.alternate,content
    finally:f.tearDown()


@pytest.mark.parametrize('kind',['initial','final'])
@pytest.mark.parametrize('case',['wrong_recipient','wrong_role','wrong_grant','wrong_manuscript','unaccepted','declined','wrong_assignment','stale_source','changed_digest','revoked_policy','revoked_grant','unauthorized_preview','invalid_capability','missing_schema','missing_provenance'])
def test_controlled_source_denials(kind,case):
    with workspace(kind) as (f,chief,mid,iid,policy,grant,other,content):
        f.current=f.editor;url=f'/document-distribution/grants/{grant}/download'
        table='initial_editor_invitations' if kind=='initial' else 'final_editor_invitations'
        if case=='wrong_recipient':
            f.current=other;assert f.client.get(url).status_code==404
        elif case=='wrong_role':
            f.current=f.reviewer;assert f.client.get(url).status_code==403
        elif case=='wrong_grant':
            assert f.client.get('/document-distribution/grants/'+'0'*32+'/download').status_code==404
        elif case=='wrong_manuscript':
            assert f.client.get('/manuscripts/99999999/download').status_code==404
        elif case in ('unaccepted','declined'):
            with sqlite3.connect(f.db_path) as db:db.execute(f'UPDATE {table} SET status=? WHERE invitation_id=?',('pending' if case=='unaccepted' else 'declined',iid))
            assert f.client.get(url).status_code==409
        elif case=='wrong_assignment':
            with sqlite3.connect(f.db_path) as db:db.execute(f'UPDATE {table} SET editor_id=? WHERE invitation_id=?',(other.user_id,iid))
            assert f.client.get(url).status_code==404
        elif case=='stale_source':
            with sqlite3.connect(f.db_path) as db:db.execute('UPDATE manuscripts SET file_path=? WHERE manuscript_id=?',('uploads/manuscripts/stale.txt',mid))
            assert f.client.get(url).status_code==403
        elif case=='changed_digest':
            with sqlite3.connect(f.db_path) as db:ref=db.execute('SELECT file_path FROM manuscripts WHERE manuscript_id=?',(mid,)).fetchone()[0]
            (f.root/ref).write_bytes(b'Changed synthetic bytes\n')
            assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
        elif case=='revoked_policy':
            f.current=chief;assert f.client.post(f'/document-distribution/manuscripts/{mid}/policies/{policy}/revoke',json={'reason':'Synthetic'}).status_code==200
            f.current=f.editor;assert f.client.get(url).status_code==403
        elif case=='revoked_grant':
            f.current=chief;assert f.client.post(f'/document-distribution/grants/{grant}/revoke',json={'reason':'Synthetic'}).status_code==200
            f.current=f.editor;assert f.client.get(url).status_code==404
        elif case=='unauthorized_preview':
            with patch.object(onlyoffice_docx,'BASE_DIR',f.root),patch.dict(os.environ,CONFIG):
                f.current=f.reviewer
                assert f.client.post(f'/onlyoffice/manuscripts/{mid}/{kind}/versions/'+('0'*32)+'/preview').status_code==404
        elif case=='invalid_capability':
            with patch.dict(os.environ,CONFIG):assert f.client.get('/onlyoffice/documents/'+('0'*32)+'?token=invalid').status_code==403
        elif case=='missing_provenance':
            from app.reviewer_artifact_storage import ArtifactStorage
            storage='a'*32;artifact='b'*32;fake='c'*32;digest=hashlib.sha256(content).hexdigest();stamp='2026-01-01T00:00:00.000000Z'
            with ArtifactStorage(os.environ['GSUB_DISTRIBUTION_PRIVATE_ROOT']) as store:store.publish_reserved(storage,content,'txt')
            with sqlite3.connect(f.db_path) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('INSERT INTO distribution_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(storage,mid,chief.user_id,'editor_source',None,None,digest,len(content),'txt','batch79-reserve-key-01','d'*64,stamp))
                version=db.execute("SELECT COALESCE(MAX(version),0)+1 FROM distribution_artifacts WHERE manuscript_id=? AND kind='editor_source'",(mid,)).fetchone()[0]
                db.execute('INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(artifact,mid,'editor_source',version,storage,digest,len(content),'txt',None,None,chief.user_id,stamp))
                db.execute('INSERT INTO distribution_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(fake,mid,artifact,f.editor.user_id,'editor',iid if kind=='initial' else None,iid if kind=='final' else None,None,None,chief.user_id,'manual','not_requested','not_requested','batch79-unproven-key-01','e'*64,stamp))
            assert f.client.get(f'/document-distribution/grants/{fake}/download').status_code==403
        else:
            with sqlite3.connect(f.db_path) as db:db.execute('DROP TRIGGER controlled_automatic_grant_provenance_no_update')
            assert f.client.get(url).status_code==503

"""Synthetic prospective Initial/Final distribution round binding."""
import hashlib
import importlib
import os
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch
import pytest
from app.routers import document_distribution as distribution,eic
from tests import test_reviewer_download as initial_fixtures,test_final_workflow as final_fixtures
from tests.test_batch22_invitation_distribution import prepare
from tests.test_batch73_acceptance_intents import install
from tests.test_batch74_precision_failures import migration as precision
from tests.test_batch75_automatic_processor import processing_migration
from tests.test_batch80_revocation import migration as revocation
from tests.test_batch17b_distribution_migration import database

migration=importlib.import_module('migrations.032_editor_distribution_rounds')

@contextmanager
def setup(kind,mode,defer=False,with_policy=True,final_round=None):
 f=initial_fixtures.ReviewerDownloadsTest() if kind=='initial' else final_fixtures.FinalWorkflowTest();f.setUp()
 try:
  if kind=='initial':chief,mid,iid=prepare(f)
  else:
   with patch.object(eic,'BASE_DIR',f.root):
    agreement=f.reach_agreement();f.current=f.author
    if final_round is not None:
     from app.models import AuthorAgreement,EICDecision
     recorded=f.db.get(AuthorAgreement,agreement['agreement_id'])
     decision=f.db.get(EICDecision,recorded.decision_id);decision.review_round=final_round
     f.manuscript.review_round=final_round;f.db.commit()
    assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond",json={'decision':'accept','agreement_version':agreement['agreement_version']}).status_code==200
    invite=f.invite(f.editor);assert invite.status_code==201
   chief=f.chief;mid=f.mid;iid=invite.json()['invitation_id']
  content=b'Synthetic batch83 source\n';digest=hashlib.sha256(content).hexdigest()
  from app.models import Manuscript
  manuscript=f.db.get(Manuscript,mid);manuscript.file_path=f.write(f'uploads/manuscripts/{mid}/source.txt',content);f.db.commit()
  install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);revocation.migrate(f.db_path);migration.migrate(f.db_path)
  private=f.root/'batch83-private';private.mkdir(mode=0o700)
  with sqlite3.connect(f.db_path) as db:
   db.execute('PRAGMA foreign_keys=ON')
   db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch83-event',f.editor.user_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
   db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(f.editor.user_id,'active',1,1,'batch83-event'))
  with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
   f.current=chief
   if with_policy:
    p=f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':kind,'mode':mode,'source_sha256':digest,'confirmed':True});assert p.status_code==201,p.text
   f.current=f.editor
   endpoint=f'/eic/initial-editor/invitations/{iid}/respond' if kind=='initial' else f'/final-workflow/invitations/{iid}/respond'
   if defer:
    with patch('app.automatic_distribution_intents.process_after_acceptance'):
     response=f.client.post(endpoint,json={'decision':'accept'})
   else:response=f.client.post(endpoint,json={'decision':'accept'})
   assert response.status_code==200,response.text
   if mode=='automatic':
    if defer:
     with sqlite3.connect(f.db_path) as db:gid=db.execute('SELECT intent_id FROM controlled_automatic_intents').fetchone()[0]
    else:
     listing=f.client.get('/document-distribution/my');assert listing.status_code==200,listing.text
     assert len(listing.json())==1,listing.text;gid=listing.json()[0]['grant_id']
   else:
    f.current=chief
    response=f.client.post(f'/document-distribution/manuscripts/{mid}/grants',json={'invitation_kind':kind,'invitation_id':iid,'source_sha256':digest,'idempotency_key':'batch83-manual-request-01'})
    assert response.status_code==200,response.text;gid=response.json()['grant_id']
   yield f,chief,mid,iid,gid,content
 finally:f.tearDown()

@pytest.mark.parametrize('kind',['initial','final'])
@pytest.mark.parametrize('mode',['manual','automatic'])
def test_prospective_grant_round(kind,mode):
 with setup(kind,mode) as (f,chief,mid,iid,gid,content):
  with sqlite3.connect(f.db_path) as db:
   row=db.execute('SELECT round_kind,review_round,agreement_id,decision_id,mode FROM editor_distribution_grant_rounds WHERE grant_id=?',(gid,)).fetchone()
   assert row[0]==('pre_review' if kind=='initial' else 'review_round')
   assert (row[1] is None and row[2] is None and row[3] is None) if kind=='initial' else (row[1]==1 and row[2] and row[3])
   assert row[4]==mode
   with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE editor_distribution_grant_rounds SET source_ref=? WHERE grant_id=?',('fake',gid))
  f.current=f.editor
  assert f.client.get(f'/document-distribution/grants/{gid}/download').content==content
  listing=f.client.get('/document-distribution/my').json();assert listing[0]['round_kind']==row[0] and listing[0]['review_round']==row[1]
  f.current=chief;history=f.client.get(f'/document-distribution/manuscripts/{mid}/history').json()
  item=next(item for item in history if item['grant_id']==gid);assert item['round_kind']==row[0] and item['review_round']==row[1]
  with pytest.raises(RuntimeError,match='retained'):migration.downgrade_empty(f.db_path)


def test_migration_upgrade_and_empty_downgrade(database):
 install(database);precision.migrate(database);processing_migration.migrate(database);revocation.migrate(database)
 migration.migrate(database);migration.migrate(database);migration.downgrade_empty(database);migration.migrate(database)
 with sqlite3.connect(database) as db:assert db.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_changed_round_invalidates_final_grant():
 with setup('final','automatic') as (f,chief,mid,iid,gid,content):
  with sqlite3.connect(f.db_path) as db:db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=?',(mid,))
  f.current=f.editor
  assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==403


def test_final_uses_the_recorded_second_round():
 # The source records are synthetically set before agreement acceptance;
 # the test does not claim this is a full second-round workflow.
 with setup('final','automatic',final_round=2) as (f,chief,mid,iid,gid,content):
  with sqlite3.connect(f.db_path) as db:
   assert db.execute('SELECT round_kind,review_round FROM editor_distribution_grant_rounds WHERE grant_id=?',(gid,)).fetchone()==('review_round',2)
  f.current=f.editor
  assert f.client.get(f'/document-distribution/grants/{gid}/download').content==content


def test_round_change_during_automatic_publication_prevents_grant():
 from app.reviewer_artifact_storage import ArtifactStorage
 from app.automatic_distribution_processor import process_intent
 from fastapi import HTTPException
 with setup('final','automatic',defer=True) as (f,chief,mid,iid,intent,content):
  publish=ArtifactStorage.publish_reserved
  def change(store,*args,**kwargs):
   result=publish(store,*args,**kwargs)
   with sqlite3.connect(f.db_path) as db:db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=?',(mid,))
   return result
  with patch.object(ArtifactStorage,'publish_reserved',change):
   with f.Session() as db:
    with pytest.raises(HTTPException) as exc:process_intent(db,intent)
    assert exc.value.status_code==409
  with sqlite3.connect(f.db_path) as db:
   assert db.execute('SELECT COUNT(*) FROM distribution_grants').fetchone()==(0,)
   assert db.execute('SELECT COUNT(*) FROM editor_distribution_grant_rounds').fetchone()==(0,)


def test_manual_duplicate_and_revocation():
 with setup('initial','manual') as (f,chief,mid,iid,gid,content):
  digest=hashlib.sha256(content).hexdigest();f.current=chief
  request={'invitation_kind':'initial','invitation_id':iid,'source_sha256':digest,'idempotency_key':'batch83-manual-request-01'}
  result=f.client.post(f'/document-distribution/manuscripts/{mid}/grants',json=request)
  assert result.status_code==200 and result.json()['grant_id']==gid
  with sqlite3.connect(f.db_path) as db:assert db.execute('SELECT count(*) FROM editor_distribution_grant_rounds').fetchone()==(1,)
  assert f.client.post(f'/document-distribution/manuscripts/{mid}/editor-invitations/initial/{iid}/revoke',json={'reason':'Synthetic'}).status_code==200
  f.current=f.editor;assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==409


def test_legacy_grant_is_preserved_without_fabricating_round():
 from tests.test_batch17b_distribution_migration import migration as manual
 from app.reviewer_artifact_storage import ArtifactStorage
 f=initial_fixtures.ReviewerDownloadsTest();f.setUp()
 try:
  chief,mid,iid=prepare(f);manual.migrate(f.db_path)
  f.current=f.editor;assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
  private=f.root/'batch83-legacy';private.mkdir(mode=0o700)
  content=b'Synthetic batch 22 bytes\n';digest=hashlib.sha256(content).hexdigest();storage='a'*32;artifact='b'*32;gid='c'*32;stamp='2020-01-01T00:00:00.000000Z'
  with ArtifactStorage(str(private)) as store:store.publish_reserved(storage,content,'txt')
  with sqlite3.connect(f.db_path) as db:
   db.execute('PRAGMA foreign_keys=ON')
   db.execute('INSERT INTO distribution_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(storage,mid,chief.user_id,'editor_source',None,None,digest,len(content),'txt','batch83-legacy-reserve','d'*64,stamp))
   db.execute('INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(artifact,mid,'editor_source',1,storage,digest,len(content),'txt',None,None,chief.user_id,stamp))
   db.execute('INSERT INTO distribution_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(gid,mid,artifact,f.editor.user_id,'editor',iid,None,None,None,chief.user_id,'manual','not_requested','not_requested','batch83-legacy-grant','e'*64,stamp))
  install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);revocation.migrate(f.db_path);migration.migrate(f.db_path)
  with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
   f.current=f.editor;assert f.client.get(f'/document-distribution/grants/{gid}/download').content==content
   assert f.client.get('/document-distribution/my').json()[0]['round_kind']=='historical_unknown'
  with sqlite3.connect(f.db_path) as db:
   assert db.execute('SELECT count(*) FROM editor_distribution_grant_rounds').fetchone()==(0,)
   assert db.execute('SELECT grant_id FROM editor_distribution_legacy_grants').fetchone()==(gid,)
   with pytest.raises(sqlite3.IntegrityError):db.execute('INSERT INTO editor_distribution_legacy_grants VALUES(?)',('f'*32,))
 finally:f.tearDown()


def test_unbound_new_grant_cannot_borrow_round_evidence():
 from app.reviewer_artifact_storage import ArtifactStorage
 with setup('initial','automatic') as (f,chief,mid,iid,gid,content):
  storage='a'*32;artifact='b'*32;fake='c'*32;digest=hashlib.sha256(content).hexdigest();stamp='2026-01-01T00:00:00.000000Z'
  with ArtifactStorage(os.environ['GSUB_DISTRIBUTION_PRIVATE_ROOT']) as store:store.publish_reserved(storage,content,'txt')
  with sqlite3.connect(f.db_path) as db:
   db.execute('PRAGMA foreign_keys=ON')
   db.execute('INSERT INTO distribution_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(storage,mid,chief.user_id,'editor_source',None,None,digest,len(content),'txt','batch83-fake-reserve','d'*64,stamp))
   version=db.execute("SELECT MAX(version)+1 FROM distribution_artifacts WHERE manuscript_id=? AND kind='editor_source'",(mid,)).fetchone()[0]
   db.execute('INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(artifact,mid,'editor_source',version,storage,digest,len(content),'txt',None,None,chief.user_id,stamp))
   db.execute('INSERT INTO distribution_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(fake,mid,artifact,f.editor.user_id,'editor',iid,None,None,None,chief.user_id,'manual','not_requested','not_requested','batch83-fake-grant','e'*64,stamp))
   valid=[fake,None,mid,'pre_review',None,None,None,f'uploads/manuscripts/{mid}/source.txt',digest,version,f.editor.user_id,'initial',iid,'manual',chief.user_id,'batch83-fake-grant',stamp]
   for index,value in ((7,'wrong/source.txt'),(10,chief.user_id),(12,iid+10000),(3,'review_round')):
    forged=valid.copy();forged[index]=value
    with pytest.raises(sqlite3.IntegrityError):db.execute('INSERT INTO editor_distribution_grant_rounds VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',forged)
  f.current=f.editor
  assert f.client.get(f'/document-distribution/grants/{fake}/download').status_code==403
  assert [x['grant_id'] for x in f.client.get('/document-distribution/my').json()]==[gid]
  f.current=chief
  history=f.client.get(f'/document-distribution/manuscripts/{mid}/history').json()
  assert next(x for x in history if x['grant_id']==fake)['round_status']=='unavailable'


@pytest.mark.parametrize('kind',['initial','final'])
def test_concurrent_automatic_processing_creates_one_round_binding(kind):
 from concurrent.futures import ThreadPoolExecutor
 from threading import Barrier
 from fastapi import HTTPException
 from app.automatic_distribution_processor import process_intent
 with setup(kind,'automatic',defer=True) as (f,chief,mid,iid,intent,content):
  barrier=Barrier(2)
  def run():
   with f.Session() as db:
    barrier.wait()
    try:return process_intent(db,intent)
    except HTTPException as exc:return exc.status_code
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
  assert any(isinstance(x,dict) and x['status']=='granted' for x in results)
  with sqlite3.connect(f.db_path) as db:
   assert db.execute('SELECT count(*) FROM distribution_grants').fetchone()==(1,)
   assert db.execute('SELECT count(*) FROM editor_distribution_grant_rounds').fetchone()==(1,)
  with f.Session() as db:assert process_intent(db,intent)['status']=='granted'


def test_missing_round_migration_fails_closed_for_new_distribution():
 f=initial_fixtures.ReviewerDownloadsTest();f.setUp()
 try:
  chief,mid,iid=prepare(f);install(f.db_path);precision.migrate(f.db_path);processing_migration.migrate(f.db_path);revocation.migrate(f.db_path)
  digest=hashlib.sha256(b'Synthetic batch 22 bytes\n').hexdigest()
  private=f.root/'batch83-no-round';private.mkdir(mode=0o700)
  with patch.object(distribution,'DATA_ROOT',f.root),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private)}):
   f.current=chief
   policy=f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'initial','mode':'automatic','source_sha256':digest,'confirmed':True})
   assert policy.status_code==503
   f.current=f.editor;assert f.client.post(f'/eic/initial-editor/invitations/{iid}/respond',json={'decision':'accept'}).status_code==200
   f.current=chief
   grant=f.client.post(f'/document-distribution/manuscripts/{mid}/grants',json={'invitation_kind':'initial','invitation_id':iid,'source_sha256':digest,'idempotency_key':'batch83-missing-round-01'})
   assert grant.status_code==503
   with sqlite3.connect(f.db_path) as db:assert db.execute('SELECT count(*) FROM distribution_grants').fetchone()==(0,)
 finally:f.tearDown()


@pytest.mark.parametrize('kind',['initial','final'])
@pytest.mark.parametrize('mode',['manual','automatic'])
@pytest.mark.parametrize('revocation_kind',['invitation','grant'])
def test_round_bound_grant_revocation(kind,mode,revocation_kind):
 with setup(kind,mode) as (f,chief,mid,iid,gid,content):
  f.current=chief
  endpoint=(f'/document-distribution/grants/{gid}/revoke' if revocation_kind=='grant' else f'/document-distribution/manuscripts/{mid}/editor-invitations/{kind}/{iid}/revoke')
  assert f.client.post(endpoint,json={'reason':'Synthetic'}).status_code==200
  if revocation_kind=='grant':
   history=f.client.get(f'/document-distribution/manuscripts/{mid}/history').json()
   assert next(item for item in history if item['grant_id']==gid)['round_status']=='recorded'
  f.current=f.editor
  assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==(404 if revocation_kind=='grant' else 409)
  with sqlite3.connect(f.db_path) as db:assert db.execute('SELECT count(*) FROM editor_distribution_grant_rounds WHERE grant_id=?',(gid,)).fetchone()==(1,)


def test_unconfigured_manual_grant_revocation_blocks_alternate_current_source():
 with setup('initial','manual',with_policy=False) as (f,chief,mid,iid,gid,content):
  f.current=f.editor
  assert f.client.get(f'/manuscripts/{mid}/download').content==content
  assert f.client.get(f'/manuscripts/{mid}/versions/source.txt').content==content
  f.current=chief
  assert f.client.post(f'/document-distribution/grants/{gid}/revoke',json={'reason':'Synthetic'}).status_code==200
  f.current=f.editor
  assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==404
  assert f.client.get(f'/manuscripts/{mid}/download').status_code==403
  assert f.client.get(f'/manuscripts/{mid}/versions/source.txt').status_code==403


def test_concurrent_initial_final_same_source_respects_current_round():
 from concurrent.futures import ThreadPoolExecutor
 from threading import Barrier
 from datetime import datetime,timezone
 from fastapi import HTTPException
 from app import models
 from app.automatic_distribution_processor import process_intent
 with setup('initial','automatic',defer=True) as (f,chief,mid,iid,initial_intent,content):
  # Construct a later Final stage in a disposable database while the older
  # Initial intent remains unprocessed; no application transition is implied.
  other=models.User(name='Synthetic final editor',email='batch83-final-other@example.invalid',password_hash='x',role='editor')
  manuscript=f.db.get(models.Manuscript,mid);manuscript.status='final_editing'
  decision=models.EICDecision(manuscript_id=mid,eic_id=chief.user_id,review_round=manuscript.review_round,decision='accept',comments='Synthetic');f.db.add_all([other,decision]);f.db.flush()
  agreement=models.AuthorAgreement(manuscript_id=mid,decision_id=decision.decision_id,author_id=manuscript.author_id,agreement_version='synthetic',agreement_text='Synthetic',status='accepted',responded_at=datetime.now(timezone.utc));f.db.add(agreement);f.db.commit();other_id=other.user_id
  with sqlite3.connect(f.db_path) as db:
   db.execute('PRAGMA foreign_keys=ON')
   db.execute('INSERT INTO account_lifecycle_events VALUES(?,?,?,?,?,?,?,?,?)',('batch83-other',other_id,1,None,'active',1,chief.user_id,'2020-01-01T00:00:00.000000Z','initial_enrollment'))
   db.execute('INSERT INTO account_lifecycle VALUES(?,?,?,?,?)',(other_id,'active',1,1,'batch83-other'))
  f.current=chief
  invitation=f.client.post('/final-workflow/invite',json={'manuscript_id':mid,'editor_id':other_id});assert invitation.status_code==201,invitation.text
  digest=hashlib.sha256(content).hexdigest()
  assert f.client.post(f'/document-distribution/manuscripts/{mid}/policies',json={'invitation_kind':'final','mode':'automatic','source_sha256':digest,'confirmed':True}).status_code==201
  f.current=other
  with patch('app.automatic_distribution_intents.process_after_acceptance'):
   response=f.client.post(f"/final-workflow/invitations/{invitation.json()['invitation_id']}/respond",json={'decision':'accept'});assert response.status_code==200,response.text
  with sqlite3.connect(f.db_path) as db:final_intent=db.execute("SELECT intent_id FROM controlled_automatic_intents WHERE invitation_kind='final'").fetchone()[0]
  barrier=Barrier(2)
  def run(intent):
   with f.Session() as db:
    barrier.wait()
    try:return process_intent(db,intent)
    except HTTPException as exc:return exc.status_code
  with ThreadPoolExecutor(max_workers=2) as pool:initial,final=list(pool.map(run,[initial_intent,final_intent]))
  assert initial==409 and final['status']=='granted'
  with sqlite3.connect(f.db_path) as db:
   assert db.execute('SELECT count(*) FROM distribution_grants').fetchone()==(1,)
   assert db.execute('SELECT recipient_id,invitation_kind,review_round FROM editor_distribution_grant_rounds').fetchone()==(other_id,'final',1)


def test_round_binding_failure_rolls_back_grant_and_retry_recovers():
 from fastapi import HTTPException
 from app.automatic_distribution_processor import process_intent
 with setup('initial','automatic',defer=True) as (f,chief,mid,iid,intent,content):
  with sqlite3.connect(f.db_path) as db:
   db.execute("CREATE TRIGGER batch83_synthetic_failure BEFORE INSERT ON editor_distribution_grant_rounds BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
  with f.Session() as db:
   with pytest.raises(HTTPException) as exc:process_intent(db,intent)
   assert exc.value.status_code==503
  with sqlite3.connect(f.db_path) as db:
   assert db.execute('SELECT count(*) FROM distribution_grants').fetchone()==(0,)
   assert db.execute('SELECT count(*) FROM controlled_automatic_grant_provenance').fetchone()==(0,)
   assert db.execute('SELECT count(*) FROM editor_distribution_grant_rounds').fetchone()==(0,)
   db.execute('DROP TRIGGER batch83_synthetic_failure')
  with f.Session() as db:assert process_intent(db,intent)['status']=='granted'
  with sqlite3.connect(f.db_path) as db:
   assert db.execute('SELECT count(*) FROM distribution_grants').fetchone()==(1,)
   assert db.execute('SELECT count(*) FROM editor_distribution_grant_rounds').fetchone()==(1,)


def test_partial_round_schema_cannot_fall_back_to_legacy_access():
 with setup('initial','manual',with_policy=False) as (f,chief,mid,iid,gid,content):
  with sqlite3.connect(f.db_path) as db:db.execute("DELETE FROM schema_migrations WHERE migration_id='032_editor_distribution_rounds'")
  f.current=f.editor
  assert f.client.get(f'/manuscripts/{mid}/download').status_code==503
  assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==503
  assert f.client.get('/document-distribution/my').status_code==503
  f.current=chief
  assert f.client.get(f'/document-distribution/manuscripts/{mid}/history').status_code==503


def test_final_grant_rejects_inconsistent_agreement_evidence():
 with setup('final','manual') as (f,chief,mid,iid,gid,content):
  with sqlite3.connect(f.db_path) as db:
   db.execute("UPDATE author_agreements SET status='declined' WHERE manuscript_id=?",(mid,))
  f.current=f.editor
  assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code==403


def test_inconsistent_initial_round_does_not_authorize_pre_review_grant():
 from app.automatic_distribution_processor import process_intent
 from fastapi import HTTPException
 with setup('initial','automatic',defer=True) as (f,chief,mid,iid,intent,content):
  with sqlite3.connect(f.db_path) as db:db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=?',(mid,))
  with f.Session() as db:
   with pytest.raises(HTTPException) as exc:process_intent(db,intent)
   assert exc.value.status_code==409
  with sqlite3.connect(f.db_path) as db:assert db.execute('SELECT count(*) FROM distribution_grants').fetchone()==(0,)

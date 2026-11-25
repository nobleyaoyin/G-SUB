"""Prospective immutable candidate provenance in disposable fixtures only."""
import hashlib, importlib, sqlite3
import pytest
from test_batch38_eic_proof import fixture
from test_batch40_reviewer_candidates import ready, CHECKS
from test_sprint6_docx_preparation import word_document

migration=importlib.import_module('migrations.038_candidate_preparation_provenance')

def submit(f,chief,headers,sid,content=None):
    return f.client.post(f'/eic/manuscripts/{f.mid}/reviewer-candidates',headers=headers(chief),
        data={'review_round':1,'source_id':sid,'artifact_version':1,'fmt':'docx','metadata_preparation':'docx-v1'},
        files={'file':('candidate.docx',content or word_document(),'application/octet-stream')})

def test_missing_migration_fails_closed_without_reservation(fixture):
    f,chief,headers,_,sid,_,_=ready(fixture)
    assert submit(f,chief,headers,sid).status_code==503
    with sqlite3.connect(f.db_path) as db: assert db.execute('select count(*) from reviewer_candidate_reservations').fetchone()[0]==0

def test_provenance_binds_exact_source_input_output_and_human_status(fixture):
    f,chief,headers,aid,sid,_,_=ready(fixture)
    migration.migrate(f.db_path);migration.migrate(f.db_path)
    content=word_document();response=submit(f,chief,headers,sid,content);assert response.status_code==201,response.text
    body=response.json();candidate=body['candidate_id'];base=f'/eic/manuscripts/{f.mid}/reviewer-candidates/{candidate}'
    assert f.client.get(base+'/processing',headers=headers(f.reviewer)).status_code==403
    result=f.client.get(base+'/processing',headers=headers(chief));assert result.status_code==200,result.text
    info=result.json();assert info['method']=='docx-v1' and info['review_round']==1 and info['source_id']==sid
    assert info['source_sha256']==hashlib.sha256(b'%PDF-first').hexdigest()
    assert info['input_sha256']==hashlib.sha256(content).hexdigest()
    assert info['prepared_sha256']==body['sha256'] and info['human_review']['status']=='pending'
    assert f.client.post(base+'/publish',headers=headers(chief)).status_code==409
    info=f.client.get(base+'/processing',headers=headers(chief)).json()
    context={'expected_sha256':info['prepared_sha256'],'expected_artifact_version':info['artifact_version'],'expected_review_round':info['review_round']}
    assert f.client.post(base+'/verify',headers=headers(chief),json={**CHECKS,'filename_verified':True,**context}).status_code==200
    assert f.client.post(base+'/approve',headers=headers(chief),json={**context,'confirmed':True}).status_code==200
    after=f.client.get(base+'/processing',headers=headers(chief)).json()
    assert after['human_review']['status']=='verified' and after['approval']['status']=='approved'
    with sqlite3.connect(f.db_path) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute("update candidate_preparation_events set result='prepared'")
        with pytest.raises(sqlite3.IntegrityError):db.execute('delete from candidate_preparation_events')
        assert db.execute('select count(*) from candidate_preparation_events').fetchone()[0]==1


def test_two_reviewers_double_blind_prepared_artifact_and_own_reviews(fixture):
    from app import models
    f,chief,headers,aid1,sid,_,_=ready(fixture)
    f.author.name='SyntheticAuthorSecret';f.reviewer.name='SyntheticReviewerOne';f.other.name='SyntheticReviewerTwo';f.db.commit()
    migration.migrate(f.db_path)
    second=f.client.post('/assignments/',headers=headers(chief),json={'manuscript_id':f.mid,'reviewer_id':f.other.user_id,'review_round':1})
    assert second.status_code==201,second.text
    aid2=second.json()['assignment_id']
    assert f.client.post(f'/assignments/{aid2}/invitation-response',headers=headers(f.other),json={'decision':'accept'}).status_code==200
    prepared=submit(f,chief,headers,sid);assert prepared.status_code==201,prepared.text
    base=f"/eic/manuscripts/{f.mid}/reviewer-candidates/{prepared.json()['candidate_id']}"
    assert f.client.get(f'/assignments/{aid1}/download',headers=headers(f.reviewer)).status_code==409
    info=f.client.get(base+'/processing',headers=headers(chief)).json()
    context={'expected_sha256':info['prepared_sha256'],'expected_artifact_version':info['artifact_version'],'expected_review_round':info['review_round']}
    assert f.client.post(base+'/verify',headers=headers(chief),json={**CHECKS,'filename_verified':True,**context}).status_code==200
    assert f.client.post(base+'/approve',headers=headers(chief),json={**context,'confirmed':True}).status_code==200
    assert f.client.post(base+'/publish',headers=headers(chief)).status_code==200
    for aid in (aid1,aid2):assert f.client.post(base+f'/bind/{aid}',headers=headers(chief)).status_code==200
    for actor,aid,private in ((f.reviewer,aid1,'Private first review'),(f.other,aid2,'Private second review')):
        document=f.client.get(f'/assignments/{aid}/download',headers=headers(actor));assert document.status_code==200
        assert hashlib.sha256(document.content).hexdigest()==prepared.json()['sha256']
        detail=f.client.get(f'/manuscripts/{f.mid}',headers=headers(actor));assert detail.status_code==200
        assert 'SyntheticAuthorSecret' not in detail.text and 'SyntheticReviewerOne' not in detail.text and 'SyntheticReviewerTwo' not in detail.text
        assignments=f.client.get('/assignments/my',headers=headers(actor));assert assignments.status_code==200
        for secret in ('SyntheticAuthorSecret','SyntheticReviewerOne','SyntheticReviewerTwo'):assert secret not in assignments.text
        review=f.client.post('/reviews/',headers=headers(actor),json={'assignment_id':aid,'recommendation':'revision','comments':private});assert review.status_code==201,review.text
    first=f'/reviews/my/manuscripts/{f.mid}/rounds/1/assignments/{aid1}';second_path=f'/reviews/my/manuscripts/{f.mid}/rounds/1/assignments/{aid2}'
    assert f.client.get(first,headers=headers(f.reviewer)).json()['comments']=='Private first review'
    assert f.client.get(second_path,headers=headers(f.other)).json()['comments']=='Private second review'
    assert f.client.get(first,headers=headers(f.other)).status_code==404
    assert f.client.get(second_path,headers=headers(f.reviewer)).status_code==404
    assert f.client.get(first,headers=headers(f.author)).status_code==403
    progress=f.client.get(f'/manuscripts/{f.mid}/progress',headers=headers(f.author));assert progress.status_code==200
    assert 'SyntheticReviewerOne' not in progress.text and 'SyntheticReviewerTwo' not in progress.text
    eic=f.client.get(f'/eic/manuscripts/{f.mid}/overview',headers=headers(chief));assert eic.status_code==200
    assert 'SyntheticAuthorSecret' in eic.text and 'SyntheticReviewerOne' in eic.text and 'SyntheticReviewerTwo' in eic.text
    for actor,forbidden in ((f.author,('SyntheticReviewerOne','SyntheticReviewerTwo')),(f.reviewer,('SyntheticAuthorSecret','SyntheticReviewerTwo')),(f.other,('SyntheticAuthorSecret','SyntheticReviewerOne'))):
        notices=f.client.get('/notifications/my',headers=headers(actor));assert notices.status_code==200
        assert all(secret not in notices.text for secret in forbidden)
    f.db.add(models.ReviewerInvitationInvalidation(invalidation_id='sprint7-fixture-cancel',assignment_id=aid1,kind='cancelled',actor_user_id=chief.user_id,occurred_at='2026-01-01T00:00:00.000000Z',reason_code='editorial_cancellation'));f.db.commit()
    assert f.client.get(f'/assignments/{aid1}/download',headers=headers(f.reviewer)).status_code==409


def test_human_rejection_is_immutable_and_blocks_approval_and_release(fixture):
    f,chief,headers,aid,sid,_,_=ready(fixture);migration.migrate(f.db_path)
    response=submit(f,chief,headers,sid);assert response.status_code==201
    base=f"/eic/manuscripts/{f.mid}/reviewer-candidates/{response.json()['candidate_id']}"
    assert f.client.post(base+'/reject',headers=headers(f.reviewer),json={'reason':'synthetic'}).status_code==403
    assert f.client.post(base+'/reject',headers=headers(chief),json={'reason':'  '}).status_code==422
    assert f.client.post(base+'/reject',headers=headers(chief),json={'reason':'Identifying content remains'}).status_code==200
    info=f.client.get(base+'/processing',headers=headers(chief));assert info.status_code==200
    assert info.json()['human_review']['status']=='rejected' and info.json()['human_review']['reason']=='Identifying content remains'
    assert f.client.get(base+'/content',headers=headers(chief)).status_code==200
    assert f.client.get(base+'/content',headers=headers(f.reviewer)).status_code==403
    assert f.client.post(base+'/verify',headers=headers(chief),json=CHECKS).status_code==409
    assert f.client.post(base+'/approve',headers=headers(chief)).status_code==409
    assert f.client.post(base+'/publish',headers=headers(chief)).status_code==409
    assert f.client.get(f'/assignments/{aid}/download',headers=headers(f.reviewer)).status_code==409
    with sqlite3.connect(f.db_path) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute("update candidate_review_rejections set reason='changed'")
        with pytest.raises(sqlite3.IntegrityError):db.execute('delete from candidate_review_rejections')

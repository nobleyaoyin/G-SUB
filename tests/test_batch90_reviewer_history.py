"""Assignment-scoped reviewed-document history on a disposable database."""
import os
import sqlite3
from unittest.mock import patch
from app.models import ReviewAssignment, ReviewerInvitation, ReviewerInvitationInvalidation
import app.routers.document_distribution as distribution
from tests import test_reviewer_download as fixtures
from tests.test_batch17c_editor_distribution import migration


def test_reviewer_own_history_isolated_and_revocable():
    f=fixtures.ReviewerDownloadsTest(); f.setUp()
    try:
        f.activate_reviewer(f.reviewer); f.activate_reviewer(f.other)
        assignments=[]
        for reviewer in (f.reviewer,f.other):
            a=ReviewAssignment(manuscript_id=f.mid,reviewer_id=reviewer.user_id,assigned_by=f.editor.user_id,review_round=1,status='assigned')
            f.db.add(a); f.db.flush(); f.db.add(ReviewerInvitation(assignment_id=a.assignment_id,status='accepted')); assignments.append(a.assignment_id)
        f.db.commit(); migration.migrate(f.db_path)
        private=f.root/'batch90-private'; private.mkdir(mode=0o700)
        with patch.object(distribution,'DATA_ROOT',f.root.resolve()),patch.dict(os.environ,{'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private.resolve())}):
            uploaded=[]
            for index,reviewer in enumerate((f.reviewer,f.other)):
                f.current=reviewer
                response=f.client.post(f'/document-distribution/review-assignments/{assignments[index]}/documents',headers={'Idempotency-Key':f'batch90-synthetic-key-{index:04}'},files={'file':('review.txt',f'review {index}'.encode(),'text/plain')})
                assert response.status_code==200,response.text
                uploaded.append(response.json()['artifact_id'])
            f.current=f.reviewer
            path=f'/document-distribution/review-assignments/{assignments[0]}/documents'
            listing=f.client.get(path); assert listing.status_code==200,listing.text
            assert [x['artifact_id'] for x in listing.json()]==[uploaded[0]]
            response=f.client.get(f'{path}/{uploaded[0]}/download'); assert response.status_code==200 and response.content==b'review 0'
            with sqlite3.connect(f.db_path) as connection:
                storage_id=connection.execute('SELECT storage_id FROM distribution_artifacts WHERE artifact_id=?',(uploaded[0],)).fetchone()[0]
            stored=private/storage_id;stored.chmod(0o600);stored.write_bytes(b'altered!')
            assert f.client.get(f'{path}/{uploaded[0]}/download').status_code==409
            stored.write_bytes(b'review 0')
            assert f.client.get(f'{path}/{uploaded[1]}/download').status_code==404
            assert f.client.get(f'/document-distribution/review-assignments/{assignments[1]}/documents').status_code==404
            assert f.client.get(f'/document-distribution/review-assignments/999999/documents').status_code==404
            f.current=f.author; assert f.client.get(path).status_code==403
            f.current=f.reviewer
            assignment=f.db.get(ReviewAssignment,assignments[0]);assignment.status='completed';f.manuscript.review_round=2;f.db.commit()
            assert f.client.get(path).status_code==200
            assert f.client.get(f'{path}/{uploaded[0]}/download').status_code==404
            invitation=f.db.get(ReviewerInvitation,assignments[0]);invitation.status='declined';f.db.commit()
            assert f.client.get(path).status_code==404
            assert f.client.get(f'{path}/{uploaded[0]}/download').status_code==404
            invitation.status='accepted';f.db.add(ReviewerInvitationInvalidation(invalidation_id='batch90-cancel',assignment_id=assignments[0],kind='cancelled',actor_user_id=f.editor.user_id,occurred_at='2026-01-01T00:00:00.000000Z',reason_code='editorial_cancellation'));f.db.commit()
            assert f.client.get(path).status_code==404
            assert f.client.get(f'{path}/{uploaded[0]}/download').status_code==404
    finally:
        f.tearDown()


def test_old_round_submission_remains_closed():
    f=fixtures.ReviewerDownloadsTest(); f.setUp()
    try:
        a=ReviewAssignment(manuscript_id=f.mid,reviewer_id=f.reviewer.user_id,assigned_by=f.editor.user_id,review_round=1,status='assigned')
        f.db.add(a);f.db.flush();f.db.add(ReviewerInvitation(assignment_id=a.assignment_id,status='accepted'));f.manuscript.review_round=2;f.db.commit()
        f.current=f.reviewer
        response=f.client.post('/reviews/',json={'assignment_id':a.assignment_id,'comments':'Late synthetic review','recommendation':'accept'})
        assert response.status_code==409 and response.json()['detail']=='This assignment is not in the current review round'
    finally:
        f.tearDown()

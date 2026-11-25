"""Each reviewed-document version remains assignment-scoped and immutable."""
import os
from unittest.mock import patch
from app import models
from app.routers import document_distribution as distribution
from tests import test_reviewer_download as fixtures
from tests.test_batch17c_editor_distribution import migration


def test_reviewer_two_versions_are_distinct_and_private():
    f = fixtures.ReviewerDownloadsTest(); f.setUp()
    try:
        f.activate_reviewer(f.reviewer)
        f.activate_reviewer(f.other)
        assignments = []
        for reviewer in (f.reviewer, f.other):
            assignment = models.ReviewAssignment(manuscript_id=f.mid, reviewer_id=reviewer.user_id,
                assigned_by=f.editor.user_id, review_round=1, status='assigned')
            f.db.add(assignment); f.db.flush()
            f.db.add(models.ReviewerInvitation(assignment_id=assignment.assignment_id, status='accepted'))
            assignments.append(assignment.assignment_id)
        f.db.commit(); migration.migrate(f.db_path)
        private = f.root/'sprint413-private'; private.mkdir(mode=0o700)
        with patch.object(distribution, 'DATA_ROOT', f.root.resolve()), patch.dict(os.environ, {'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private.resolve())}):
            f.current = f.reviewer; base = f'/document-distribution/review-assignments/{assignments[0]}/documents'
            results = []
            for i, content in enumerate((b'Synthetic reviewed version one', b'Synthetic reviewed version two')):
                response = f.client.post(base, headers={'Idempotency-Key':f'sprint413-reviewed-version-{i:04}'}, files={'file':('review.txt',content,'text/plain')})
                assert response.status_code == 200, response.text; results.append(response.json())
            assert [item['version'] for item in results] == [1, 2]
            assert results[0]['artifact_id'] != results[1]['artifact_id']
            for item, content in zip(results, (b'Synthetic reviewed version one', b'Synthetic reviewed version two')):
                response = f.client.get(base+'/'+item['artifact_id']+'/download')
                assert response.status_code == 200 and response.content == content
            assignment = f.db.get(models.ReviewAssignment, assignments[0])
            assignment.status = 'completed'; f.db.commit()
            assert f.client.get(base+'/'+results[0]['artifact_id']+'/download').status_code == 404
            assignment.status = 'assigned'; f.db.commit()
            manuscript = f.db.get(models.Manuscript, f.mid)
            manuscript.review_round = 2; f.db.commit()
            assert f.client.get(base+'/'+results[0]['artifact_id']+'/download').status_code == 404
            manuscript.review_round = 1; f.db.commit()
            assert f.client.get(f'/document-distribution/review-assignments/{assignments[1]}/documents/{results[0]["artifact_id"]}/download').status_code == 404
            f.current = f.other
            assert f.client.get(base+'/'+results[0]['artifact_id']+'/download').status_code == 404
            f.current = f.author
            assert f.client.get(base+'/'+results[0]['artifact_id']+'/download').status_code == 403
            f.current = f.reviewer
            event_id = 'synthetic-disabled-reviewer'
            f.db.add(models.AccountLifecycleEvent(
                event_id=event_id, user_id=f.reviewer.user_id, sequence=2,
                from_state='active', to_state='disabled', auth_generation=2,
                actor_user_id=f.editor.user_id, occurred_at='2026-01-01T00:00:00.000000Z',
                reason_code='administrative_disable'))
            f.db.flush()
            lifecycle = f.db.get(models.AccountLifecycle, f.reviewer.user_id)
            lifecycle.state = 'disabled'; lifecycle.sequence = 2
            lifecycle.auth_generation = 2; lifecycle.last_event_id = event_id
            f.db.commit()
            assert f.client.get(base+'/'+results[0]['artifact_id']+'/download').status_code == 404
    finally:
        f.tearDown()

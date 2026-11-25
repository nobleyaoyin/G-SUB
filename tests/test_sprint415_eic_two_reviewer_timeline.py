"""Two independently uploaded Reviewer artifacts retain EIC-only evidence."""
import os
from unittest.mock import patch
from app import models
from app.routers import document_distribution as distribution
from tests import test_reviewer_download as fixtures
from tests.test_batch17c_editor_distribution import migration


def test_eic_timeline_distinguishes_two_reviewers_and_never_claims_delivery():
    f = fixtures.ReviewerDownloadsTest(); f.setUp()
    try:
        chief = models.User(name='Synthetic EIC', email='sprint415@example.com', password_hash='x', role='eic')
        f.db.add(chief); f.db.commit(); f.select_single_blind_policy()
        assignments = []
        for reviewer in (f.reviewer, f.other):
            result = f.assign(reviewer, 1); assert result.status_code == 201, result.text
            assignments.append(result.json()['assignment_id'])
        migration.migrate(f.db_path)
        private = f.root/'sprint415-private'; private.mkdir(mode=0o700)
        with patch.object(distribution, 'DATA_ROOT', f.root.resolve()), patch.dict(os.environ, {'GSUB_DISTRIBUTION_PRIVATE_ROOT':str(private.resolve())}):
            artifacts = []
            for i, reviewer in enumerate((f.reviewer, f.other)):
                f.current = reviewer; content = f'Synthetic reviewer artifact {i}'.encode()
                result = f.client.post(f'/document-distribution/review-assignments/{assignments[i]}/documents',
                    headers={'Idempotency-Key':f'sprint415-eic-reviewer-key-{i:04}'}, files={'file':('review.txt',content,'text/plain')})
                assert result.status_code == 200, result.text; artifacts.append((result.json(), content))
            f.current = chief; url = f'/eic/manuscripts/{f.mid}/document-timeline'
            response = f.client.get(url); assert response.status_code == 200, response.text
            events = response.json()['events']
            for assignment, (artifact, content) in zip(assignments, artifacts):
                bindings = [row for row in events if row['id'] == f'reviewer-binding:{assignment}']
                assert len(bindings) == 1 and bindings[0]['direction'] == 'outbound'
                assert bindings[0]['status'] == 'bound; delivery unknown'
                reviewed = [row for row in events if row['id'] == f'reviewed:{artifact["artifact_id"]}']
                assert len(reviewed) == 1 and reviewed[0]['direction'] == 'inbound'
                assert reviewed[0]['review_round'] == 1 and reviewed[0]['version'] == artifact['version']
                result = f.client.get(f'{url}/reviewed/{artifact["artifact_id"]}/download')
                assert result.status_code == 200 and result.content == content
            assert str(f.root) not in response.text and f.reviewer.email not in response.text and f.other.email not in response.text
            assert all(content.decode() not in response.text for _, content in artifacts)
            f.current = f.author; assert f.client.get(url).status_code == 403
    finally:
        f.tearDown()

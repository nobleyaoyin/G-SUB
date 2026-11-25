"""Verify that revoked prospective grants cannot be bypassed by Editor access paths."""
from tests.batch83_migration_support import bootstrap_prospective_distribution
import os
from unittest.mock import patch

from app.routers import document_distribution as distribution, eic
from tests import test_reviewer_download as fixtures
from tests.test_batch17c_editor_distribution import migration
from tests.test_batch22_invitation_distribution import prepare
from tests.test_final_workflow import FinalWorkflowTest


def test_initial_editor_legacy_paths_are_independent_of_grant_and_revocation():
    f = fixtures.ReviewerDownloadsTest()
    f.setUp()
    try:
        chief, mid, invitation_id = prepare(f)
        bootstrap_prospective_distribution(f.db_path)
        private = f.root / 'batch68-private'
        private.mkdir(mode=0o700)
        with patch.object(distribution, 'DATA_ROOT', f.root), patch.object(eic, 'BASE_DIR', f.root), \
                patch.dict(os.environ, {'GSUB_DISTRIBUTION_PRIVATE_ROOT': str(private)}):
            f.current = f.editor
            accepted = f.client.post(f'/eic/initial-editor/invitations/{invitation_id}/respond', json={'decision': 'accept'})
            assert accepted.status_code == 200, accepted.text
            original = b'Synthetic batch 22 bytes\n'
            # Existing accepted-invitation access precedes any distribution grant.
            assert f.client.get(f'/manuscripts/{mid}/download').content == original
            assert f.client.get(f'/manuscripts/{mid}/versions/paper.txt').content == original
            online = f.client.get(f'/eic/manuscripts/{mid}/online-text/initial')
            assert online.status_code == 200 and online.json()['content'].encode() == original

            f.current = chief
            candidates = f.client.get(f'/document-distribution/manuscripts/{mid}/candidates').json()
            grant = f.client.post(f'/document-distribution/manuscripts/{mid}/grants', json={
                'invitation_kind': 'initial', 'invitation_id': invitation_id,
                'source_sha256': candidates['document']['sha256'], 'idempotency_key': 'batch68-access-test-0001',
            })
            assert grant.status_code == 200, grant.text
            gid = grant.json()['grant_id']
            assert f.client.post(f'/document-distribution/grants/{gid}/revoke', json={'reason': 'Synthetic test'}).status_code == 200

            f.current = f.editor
            assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code == 404
            assert f.client.get(f'/manuscripts/{mid}/download').status_code == 403
            assert f.client.get(f'/manuscripts/{mid}/versions/paper.txt').status_code == 403
            assert f.client.get(f'/eic/manuscripts/{mid}/online-text/initial').status_code == 403
    finally:
        f.tearDown()


def test_final_editor_legacy_paths_are_independent_of_revocation():
    f = FinalWorkflowTest()
    f.setUp()
    try:
        with patch.object(eic, 'BASE_DIR', f.root):
            agreement = f.reach_agreement()
            f.current = f.author
            assert f.client.post(f"/agreements/{agreement['agreement_id']}/respond", json={
                'decision': 'accept', 'agreement_version': agreement['agreement_version'],
            }).status_code == 200
            invitation = f.invite(f.editor)
            assert invitation.status_code == 201
            invitation_id = invitation.json()['invitation_id']
            assert f.respond(f.editor, invitation_id, 'accept').status_code == 200
            content = b'Synthetic final editor manuscript\n'
            f.manuscript.file_path = f.write(f'uploads/manuscripts/{f.mid}/paper.txt', content)
            f.db.commit()
            bootstrap_prospective_distribution(f.db_path)
            private = f.root / 'batch68-final-private'
            private.mkdir(mode=0o700)
            with patch.object(distribution, 'DATA_ROOT', f.root), patch.dict(os.environ, {'GSUB_DISTRIBUTION_PRIVATE_ROOT': str(private)}):
                f.current = f.chief
                data = f.client.get(f'/document-distribution/manuscripts/{f.mid}/candidates').json()
                grant = f.client.post(f'/document-distribution/manuscripts/{f.mid}/grants', json={
                    'invitation_kind': 'final', 'invitation_id': invitation_id,
                    'source_sha256': data['document']['sha256'], 'idempotency_key': 'batch68-final-test-0001',
                })
                assert grant.status_code == 200, grant.text
                gid = grant.json()['grant_id']
                assert f.client.post(f'/document-distribution/grants/{gid}/revoke', json={'reason': 'Synthetic test'}).status_code == 200
                f.current = f.editor
                assert f.client.get(f'/document-distribution/grants/{gid}/download').status_code == 404
                assert f.client.get(f'/manuscripts/{f.mid}/download').status_code == 403
                assert f.client.get(f'/manuscripts/{f.mid}/versions/paper.txt').status_code == 403
    finally:
        f.tearDown()

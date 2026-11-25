"""One continuous single-blind sample workflow via existing HTTP operations."""
import hashlib
import importlib
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('SECRET_KEY', 'synthetic-peer-workflow-key-00000000000000000')
import pytest
from sqlalchemy import text
import app.main as main
from app.models import User
from app.sample_storage import SampleStorage
from tests import test_reviewer_download as fixtures
from tests.test_secure_word_uploads import docx_bytes


def test_two_reviewers_and_round_two_sample_revision():
    f = fixtures.ReviewerDownloadsTest()
    f.setUp()
    try:
        f.activate_reviewer(f.reviewer); f.activate_reviewer(f.other); f.db.commit()
        assert f.root.is_relative_to(Path(os.environ['TMPDIR']).resolve())
        assert not f.root.is_relative_to(Path(__file__).resolve().parents[1])
        eic = User(name='Synthetic EIC', email='peer-eic@example.com', role='eic', password_hash='x')
        other_editor = User(name='Other editor', email='peer-other-editor@example.com', role='editor', password_hash='x')
        other_author = User(name='Other author', email='peer-other-author@example.com', role='author', password_hash='x')
        f.db.add_all([eic, other_editor, other_author]); f.db.commit()
        importlib.import_module('migrations.035_sample_document_storage').migrate(f.db_path)
        importlib.import_module('migrations.036_sample_initial_editing').migrate(f.db_path)
        f.current = f.author
        created = f.client.post('/manuscripts/', json={'title':'Synthetic peer study', 'abstract':'Synthetic research abstract.'})
        assert created.status_code == 201
        mid = created.json()['manuscript_id']
        f.db.execute(text("INSERT INTO sample_manuscripts VALUES (:mid,datetime('now'))"), {'mid':mid})
        f.db.commit()  # Initial operator provisioning, not a workflow transition.
        storage = SampleStorage(f.root / 'sample_documents', f.root / 'uploads')
        with patch.object(SampleStorage, 'for_development', return_value=storage):
            original = b'%PDF-synthetic-author-original'
            upload = f.client.post(f'/manuscripts/{mid}/upload', files={'file':('original.pdf', original, 'application/pdf')})
            assert upload.status_code == 200, upload.text
            f.db.rollback(); submitted = f.client.post(f'/manuscripts/{mid}/submit')
            assert submitted.status_code == 200, submitted.text
            f.db.rollback(); f.current = eic
            scan = f.client.post(f'/eic/manuscripts/{mid}/initial-scan', json={'decision':'pass','comments':'Proceed to editing.'})
            assert scan.status_code == 201, scan.text
            f.db.rollback(); invite = f.client.post('/eic/initial-editor/invite', json={'manuscript_id':mid,'editor_id':f.editor.user_id})
            assert invite.status_code == 201, invite.text
            invitation_id = invite.json()['invitation_id']
            f.db.rollback(); f.current = f.editor
            response = f.client.post(f'/eic/initial-editor/invitations/{invitation_id}/respond', json={'decision':'accept'})
            assert response.status_code == 200, response.text
            f.db.rollback(); source = f.client.get(f'/manuscripts/{mid}/download')
            assert source.status_code == 200 and source.content == original
            f.db.rollback(); f.current = other_editor
            assert f.client.get(f'/manuscripts/{mid}/download').status_code == 403
            f.db.rollback(); f.current = f.editor
            edited_bytes = b'%PDF-synthetic-initial-editor'
            edited = f.client.post(f'/eic/initial-editing/{mid}/submit', data={'comments':'Edited the synthetic document.'}, files={'file':('edited.pdf',edited_bytes,'application/pdf')})
            assert edited.status_code == 201, edited.text
            sid = edited.json()['submission_id']
            assert 'file_path' not in edited.json() and len(edited.json()['version_id']) == 32
            f.db.rollback()
            artifact = f.db.execute(text('SELECT version_id,sha256,editor_id FROM sample_initial_artifacts WHERE submission_id=:sid'), {'sid':sid}).mappings().one()
            assert artifact['version_id'] == edited.json()['version_id'] and artifact['editor_id'] == f.editor.user_id
            assert artifact['sha256'] == hashlib.sha256(edited_bytes).hexdigest()
            f.db.rollback(); assert f.client.get(f'/eic/initial-editing/submissions/{sid}/download').content == edited_bytes
            f.db.rollback(); f.current = f.author
            assert f.client.get(f'/eic/initial-editing/submissions/{sid}/download').content == edited_bytes
            assert f.client.post(f'/eic/initial-editing/submissions/{sid}/author-review', json={'decision':'approve','comments':'Approved.'}).status_code == 200
            f.db.rollback(); f.current = f.editor
            approval = f.client.post(f'/eic/initial-editing/submissions/{sid}/editor-approval', json={'decision':'approve','comments':'Approved.'})
            assert approval.status_code == 200, approval.text
            f.db.rollback(); f.current = eic
            approval = f.client.post(f'/eic/initial-editing/submissions/{sid}/eic-approval', json={'decision':'approve','comments':'Approved.'})
            assert approval.status_code == 200, approval.text
            f.db.rollback(); f.current = f.author
            confirmation = f.client.post(f'/eic/initial-editing/submissions/{sid}/pre-review-confirmation', json={'decision':'confirm','comments':'Confirmed.'})
            assert confirmation.status_code == 200, confirmation.text
            f.db.rollback(); f.current = eic
            policy = f.client.put(f'/eic/manuscripts/{mid}/review-policy', json={'mode':'single_blind'})
            assert policy.status_code == 200, policy.text
            assignment_ids = []
            for reviewer in (f.reviewer, f.other):
                f.db.rollback(); f.current = eic
                assigned = f.client.post('/assignments/', json={'manuscript_id':mid,'reviewer_id':reviewer.user_id,'review_round':1})
                assert assigned.status_code == 201, assigned.text
                aid = assigned.json()['assignment_id']; assignment_ids.append(aid)
                f.db.rollback(); f.current = reviewer
                accepted = f.client.post(f'/assignments/{aid}/invitation-response', json={'decision':'accept'})
                assert accepted.status_code == 200, accepted.text
                f.db.rollback(); download = f.client.get(f'/assignments/{aid}/download')
                assert download.status_code == 200 and download.content == edited_bytes, download.text
                f.db.rollback(); review = f.client.post('/reviews/', json={'assignment_id':aid,'recommendation':'revision','comments':f'Independent review {aid}.'})
                assert review.status_code == 201, review.text
            f.db.rollback(); f.current = f.reviewer
            assert f.client.get(f'/assignments/{assignment_ids[1]}/download').status_code != 200
            assert f.client.get(f'/reviews/manuscript/{mid}').status_code == 403
            f.db.rollback(); f.current = f.author
            assert f.client.get(f'/reviews/manuscript/{mid}').status_code == 403
            assert f.client.get(f'/eic/manuscripts/{mid}/overview').status_code == 403
            f.db.rollback(); f.current = eic
            overview = f.client.get(f'/eic/manuscripts/{mid}/overview')
            assert overview.status_code == 200
            assert len([item for item in overview.json()['assignments'] if item['review'] and item['review']['recommendation'] == 'revision']) == 2
            f.db.rollback()
            decision = f.client.post(f'/eic/manuscripts/{mid}/decision', json={'decision':'revision_required','expected_review_round':1,'comments':'Please revise.'})
            assert decision.status_code == 201, decision.text
            f.db.rollback(); f.current = f.author
            assert f.db.execute(text("SELECT count(*) FROM notifications WHERE manuscript_id=:mid AND user_id=:uid AND notification_type='eic_decision'"), {'mid':mid,'uid':f.author.user_id}).scalar_one() == 1
            f.db.rollback()
            stale = f.client.post(f'/manuscripts/{mid}/resubmit', json={'abstract':'Updated research abstract.'})
            assert stale.status_code == 409
            f.db.rollback()
            revision_bytes = docx_bytes()
            revised = f.client.post(f'/manuscripts/{mid}/upload', files={'file':('revision.docx', revision_bytes, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
            assert revised.status_code == 200, revised.text
            f.db.rollback(); forged = f.client.post(f'/manuscripts/{mid}/resubmit', params={'expected_online_version':'0' * 64}, json={'abstract':'Updated research abstract.'})
            assert forged.status_code == 409
            f.db.rollback(); result = f.client.post(f'/manuscripts/{mid}/resubmit', json={'abstract':'Updated research abstract.'})
            assert result.status_code == 200, result.text
            assert result.json()['status'] == 'revised'
            f.db.rollback(); duplicate = f.client.post(f'/manuscripts/{mid}/resubmit', json={'abstract':'Updated research abstract.'})
            assert duplicate.status_code == 409
            f.db.rollback()
            rows = f.db.execute(text('SELECT snapshot_id,submission_kind,review_round,file_sha256 FROM manuscript_submission_snapshots WHERE manuscript_id=:mid ORDER BY submission_sequence'), {'mid':mid}).mappings().all()
            assert [r['submission_kind'] for r in rows] == ['initial','peer_revision']
            assert [r['review_round'] for r in rows] == [1,2]
            assert [r['file_sha256'] for r in rows] == [hashlib.sha256(original).hexdigest(),hashlib.sha256(revision_bytes).hexdigest()]
            snapshot_ids = [r['snapshot_id'] for r in rows]; f.db.rollback()
            for snapshot, expected in zip(snapshot_ids, [original, revision_bytes]):
                result = f.client.get(f'/manuscripts/{mid}/generation-history/submissions/{snapshot}/download')
                assert result.status_code == 200 and result.content == expected
            f.db.rollback(); f.current = other_author
            assert f.client.get(f'/manuscripts/{mid}/generation-history/submissions/{snapshot_ids[1]}/download').status_code in (403,404)
            f.db.rollback(); f.current = eic
            third = f.client.post('/assignments/', json={'manuscript_id':mid,'reviewer_id':f.reviewer.user_id,'review_round':2})
            assert third.status_code == 201, third.text
            round_two_id = third.json()['assignment_id']; f.db.rollback(); f.current = f.reviewer
            assert f.client.post(f'/assignments/{round_two_id}/invitation-response', json={'decision':'accept'}).status_code == 200
            f.db.rollback(); round_two = f.client.get(f'/assignments/{round_two_id}/download')
            assert round_two.status_code == 200 and round_two.content == revision_bytes, round_two.text
            f.db.rollback(); historical_round = f.client.get(f'/assignments/{assignment_ids[0]}/download')
            assert historical_round.status_code == 409 and edited_bytes not in historical_round.content
            f.db.rollback()
            with pytest.raises(RuntimeError, match='history must be retained'):
                importlib.import_module('migrations.036_sample_initial_editing').downgrade_empty(f.db_path)
            assert not (f.root / 'uploads' / 'manuscripts' / str(mid)).exists()
            assert not (f.root / 'uploads' / 'initial_editing' / str(mid)).exists()
    finally:
        f.client.__exit__(None, None, None)
        main.app.dependency_overrides.clear()
        for item in reversed(f.patches): item.stop()
        f.db.close(); f.engine.dispose(); f.temp._finalizer.detach()

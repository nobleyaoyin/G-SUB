"""Isolated author upload/version regressions; review decisions are seeded states."""
import hashlib
import pytest
from app import models
from tests import test_reviewer_download as fixtures
from tests.test_secure_word_uploads import doc_bytes, docx_bytes


@pytest.mark.parametrize('extension,payload,mime', [
    ('pdf', b'%PDF-synthetic-original', 'application/pdf'),
    ('docx', docx_bytes(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ('doc', doc_bytes(), 'application/msword'),
    ('txt', b'Synthetic original manuscript\n', 'text/plain'),
])
def test_author_upload_submit_two_revisions_and_history(extension, payload, mime):
    f = fixtures.ReviewerDownloadsTest(); f.setUp()
    try:
        f.current = f.author
        response = f.client.post('/manuscripts/', json={'title': 'Synthetic draft', 'abstract': 'Synthetic abstract'})
        assert response.status_code == 201, response.text
        mid = response.json()['manuscript_id']
        def upload(data):
            return f.client.post(f'/manuscripts/{mid}/upload', files={'file': ('source.'+extension, data, mime)})
        malformed = upload(b'\x00invalid')
        assert malformed.status_code in (400, 415, 422), malformed.text
        unsupported = f.client.post(f'/manuscripts/{mid}/upload', files={'file': ('bad.exe', b'hello', 'application/octet-stream')})
        assert unsupported.status_code == 400
        f.current = f.other
        assert upload(payload).status_code == 403
        f.current = f.author
        original = upload(payload)
        assert original.status_code == 200, original.text
        filenames = [original.json()['filename']]
        contents = [payload]
        assert f.client.get(f'/manuscripts/{mid}/download').content == payload
        assert f.client.post(f'/manuscripts/{mid}/submit').status_code == 200
        assert f.client.post(f'/manuscripts/{mid}/submit').status_code == 409
        # The fixture explicitly represents decisions already made by the EIC.
        for round_number in (2, 3):
            manuscript = f.db.get(models.Manuscript, mid)
            manuscript.status = 'revision_required'; f.db.commit()
            denied_before = f.client.get(f'/manuscripts/{mid}/versions').json()
            assert len(denied_before) == round_number-1
            revised_payload = (docx_bytes(str(round_number).encode()) if extension == 'docx' else payload + str(round_number).encode())
            result = upload(revised_payload)
            assert result.status_code == 200, result.text
            filenames.append(result.json()['filename'])
            contents.append(revised_payload)
            resubmitted = f.client.post(f'/manuscripts/{mid}/resubmit', json={'abstract': f'Revision {round_number}'})
            assert resubmitted.status_code == 200, resubmitted.text
            f.db.expire_all()
            assert f.db.get(models.Manuscript, mid).review_round == round_number
            assert resubmitted.json()['status'] == 'revised'
            assert f.client.post(f'/manuscripts/{mid}/resubmit', json={'abstract': 'duplicate'}).status_code == 409
        assert len(set(filenames)) == 3
        versions = f.client.get(f'/manuscripts/{mid}/versions').json()
        assert {v['filename'] for v in versions} == set(filenames)
        assert [v['filename'] for v in versions if v['is_current']] == [filenames[-1]]
        for name, expected in zip(filenames, contents):
            downloaded = f.client.get(f'/manuscripts/{mid}/versions/{name}')
            assert downloaded.status_code == 200
            assert hashlib.sha256(downloaded.content).digest() == hashlib.sha256(expected).digest()
        assert f.client.get(f'/manuscripts/{mid}/download').content == contents[-1]
        assert upload(b'invalid').status_code == 409
        chief = models.User(name='EIC', email='chief-181@example.test', password_hash='x', role='eic')
        f.db.add(chief)
        f.db.add(models.InitialEditorInvitation(manuscript_id=mid, editor_id=f.editor.user_id, invited_by=f.editor.user_id, status='accepted'))
        f.db.commit()
        for user in (chief, f.editor):
            f.current = user
            latest = f.client.get(f'/manuscripts/{mid}/download')
            assert latest.status_code == 200 and latest.content == contents[-1]
            assert f.client.get(f'/manuscripts/{mid}/versions/{filenames[0]}').content == contents[0]
        other_author = models.User(name='Other', email='other-author-181@example.test', password_hash='x', role='author')
        other_editor = models.User(name='Other editor', email='other-editor-181@example.test', password_hash='x', role='editor')
        f.db.add_all([other_author, other_editor]); f.db.commit()
        for user in (other_author, other_editor, f.reviewer):
            f.current = user
            assert f.client.get(f'/manuscripts/{mid}/versions').status_code == 403
            assert f.client.get(f'/manuscripts/{mid}/versions/{filenames[0]}').status_code == 403
            assert f.client.get(f'/manuscripts/{mid}/download').status_code == 403
        f.current = f.author
        assert f.client.get('/manuscripts/999999/versions').status_code == 404
        assert f.client.post(f'/manuscripts/{mid}/upload', files={'file': ('bad.exe', b'x', 'application/octet-stream')}).status_code == 409
    finally:
        f.tearDown()


def test_reviewer_invitation_requires_eic_policy_positive_control():
    f = fixtures.ReviewerDownloadsTest(); f.setUp()
    try:
        missing = f.assign(f.reviewer, 1)
        assert missing.status_code == 409
        assert 'policy' in missing.json()['detail'].lower()
        f.select_single_blind_policy()
        accepted = f.assign(f.reviewer, 1)
        assert accepted.status_code == 201, accepted.text
    finally:
        f.tearDown()

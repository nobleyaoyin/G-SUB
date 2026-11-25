"""Stage correction histories through supported routes and isolated files."""
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from app.routers import eic
from tests import test_reviewer_download as fixtures
from tests.test_batch22_invitation_distribution import prepare
from tests import test_final_workflow as final_fixture
from tests.test_secure_word_uploads import doc_bytes, docx_bytes

FORMATS = [
    ('pdf', b'%PDF-original-stage', b'%PDF-replacement-stage', 'application/pdf'),
    ('docx', docx_bytes(b'original'), docx_bytes(b'replacement'), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ('doc', doc_bytes(), doc_bytes() + b'replacement', 'application/msword'),
    ('txt', b'Original stage document\n', b'Replacement stage document\n', 'text/plain'),
]


def safe_root(root):
    root = root.resolve()
    assert root.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert not root.is_relative_to((Path(__file__).resolve().parents[1] / 'uploads').resolve())
    return root


@pytest.mark.parametrize('ext,first,second,mime', FORMATS)
def test_initial_editor_format_correction_keeps_both_versions(ext, first, second, mime):
    f = fixtures.ReviewerDownloadsTest()
    f.setUp()
    try:
        root = safe_root(f.root)
        with patch.object(eic, 'BASE_DIR', root):
            chief, mid, invitation = prepare(f)
            f.current = f.editor
            assert f.client.post(f'/eic/initial-editor/invitations/{invitation}/respond', json={'decision': 'accept'}).status_code == 200
            def submit(data):
                return f.client.post(f'/eic/initial-editing/{mid}/submit', data={'comments': 'Synthetic edit'}, files={'file': (f'edited.{ext}', data, mime)})
            one = submit(first)
            assert one.status_code == 201, one.text
            sid1 = one.json()['submission_id']
            assert submit(second).status_code == 409
            f.current = f.author
            change = f.client.post(f'/eic/initial-editing/submissions/{sid1}/author-review', json={'decision': 'request_revision', 'comments': 'Synthetic correction'})
            assert change.status_code == 200, change.text
            f.current = f.editor
            two = submit(second)
            assert two.status_code == 201, two.text
            sid2 = two.json()['submission_id']
            assert sid1 != sid2
            for user in (f.editor, f.author, chief):
                f.current = user
                for sid, data in ((sid1, first), (sid2, second)):
                    result = f.client.get(f'/eic/initial-editing/submissions/{sid}/download')
                    assert result.status_code == 200 and result.content == data
            f.current = f.reviewer
            for sid in (sid1, sid2):
                assert f.client.get(f'/eic/initial-editing/submissions/{sid}/download').status_code == 403
    finally:
        f.tearDown()


@pytest.mark.parametrize('ext,first,second,mime', FORMATS)
def test_final_editor_format_correction_keeps_both_versions(ext, first, second, mime):
    f = final_fixture.FinalWorkflowTest()
    f.setUp()
    try:
        root = safe_root(f.root)
        with patch.object(eic, 'BASE_DIR', root):
            agreement = f.reach_agreement()
            f.current = f.author
            response = f.client.post(f"/agreements/{agreement['agreement_id']}/respond", json={'decision': 'accept', 'agreement_version': agreement['agreement_version']})
            assert response.status_code == 200, response.text
            invited = f.invite(f.editor)
            assert invited.status_code == 201, invited.text
            assert f.respond(f.editor, invited.json()['invitation_id'], 'accept').status_code == 200
            def submit(user, data):
                f.current = user
                return f.client.post(f'/eic/final-editing/{f.mid}/submit', data={'comments': 'Synthetic edit'}, files={'file': (f'edited.{ext}', data, mime)})
            assert submit(f.alternate, first).status_code == 403
            one = submit(f.editor, first)
            assert one.status_code == 201, one.text
            sid1 = one.json()['submission_id']
            assert submit(f.editor, second).status_code == 409
            assert f.review(f.chief, sid1, 'eic', 'request_revision').status_code == 200
            two = submit(f.editor, second)
            assert two.status_code == 201, two.text
            sid2 = two.json()['submission_id']
            assert sid1 != sid2
            for user in (f.editor, f.author, f.chief):
                f.current = user
                for sid, data in ((sid1, first), (sid2, second)):
                    result = f.client.get(f'/eic/final-editing/submissions/{sid}/download')
                    assert result.status_code == 200 and result.content == data
            for user in (f.reviewer, f.other_author):
                f.current = user
                for sid in (sid1, sid2):
                    assert f.client.get(f'/eic/final-editing/submissions/{sid}/download').status_code == 403
    finally:
        f.tearDown()

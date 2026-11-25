"""Double-Blind HTTP denial without a trusted artifact, using synthetic storage."""
import pytest
from app import models
import test_reviewer_download as reviewer_fixture


@pytest.fixture
def fixture():
    case = reviewer_fixture.ReviewerDownloadsTest(methodName='test_first_round_binding_and_access')
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()


def test_selected_double_blind_never_falls_back_to_original(fixture):
    f = fixture
    chief = models.User(name='Synthetic EIC', email='batch35-eic@example.com', password_hash='x', role='eic')
    f.db.add(chief); f.db.commit()
    f.current = f.author
    denied = f.client.put(f'/eic/manuscripts/{f.mid}/review-policy', json={'mode':'double_blind'})
    assert denied.status_code == 403
    f.current = chief
    selected = f.client.put(f'/eic/manuscripts/{f.mid}/review-policy', json={'mode':'double_blind'})
    assert selected.status_code == 200 and selected.json()['mode'] == 'double_blind'
    assignment = f.assign(f.reviewer, 1)
    assert assignment.status_code == 201, assignment.text
    assignment_id = assignment.json()['assignment_id']
    f.current = f.reviewer
    response = f.client.get(f'/assignments/{assignment_id}/download')
    assert response.status_code == 409
    assert b'%PDF-first' not in response.content
    assert 'review-document.pdf' not in response.headers.get('content-disposition', '')
    f.current = f.other
    assert f.client.get(f'/assignments/{assignment_id}/download').status_code == 409
    f.current = f.author
    assert f.client.get(f'/assignments/{assignment_id}/download').status_code == 403

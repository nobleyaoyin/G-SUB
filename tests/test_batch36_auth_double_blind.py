"""Real bearer-authenticated Double Blind no-proof denial on disposable data."""
import pytest
from app import models
from app.routers.users import get_current_user
from app.security import create_access_token
import app.main as main
import test_reviewer_download as reviewer_fixture


@pytest.fixture
def fixture():
    case = reviewer_fixture.ReviewerDownloadsTest(methodName='test_first_round_binding_and_access')
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()


def test_real_bearer_double_blind_missing_proof_denied(fixture):
    f = fixture
    chief = models.User(name='Synthetic EIC', email='batch36-eic@example.com', password_hash='x', role='eic')
    f.db.add(chief); f.db.commit()
    main.app.dependency_overrides.pop(get_current_user, None)
    def headers(user):
        return {'Authorization': f'Bearer {create_access_token(user.user_id)}'}
    wrong = f.client.put(f'/eic/manuscripts/{f.mid}/review-policy', headers=headers(f.author), json={'mode':'double_blind'})
    assert wrong.status_code == 403
    selected = f.client.put(f'/eic/manuscripts/{f.mid}/review-policy', headers=headers(chief), json={'mode':'double_blind'})
    assert selected.status_code == 200 and selected.json()['mode'] == 'double_blind'
    assignment = f.client.post('/assignments/', headers=headers(f.editor), json={'manuscript_id':f.mid,'reviewer_id':f.reviewer.user_id,'review_round':1})
    assert assignment.status_code == 201, assignment.text
    aid = assignment.json()['assignment_id']
    response = f.client.post(f'/assignments/{aid}/invitation-response', headers=headers(f.reviewer), json={'decision':'accept'})
    assert response.status_code == 200, response.text
    download = f.client.get(f'/assignments/{aid}/download', headers=headers(f.reviewer))
    assert download.status_code == 409 and b'%PDF-first' not in download.content
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.other)).status_code == 409
    assert f.client.get(f'/assignments/{aid}/download', headers=headers(f.author)).status_code == 403
    assert f.client.get(f'/assignments/{aid}/download').status_code == 401

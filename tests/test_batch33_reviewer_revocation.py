"""Real assignment-download authorization with isolated synthetic records."""
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


def test_invalidated_assignment_cannot_download_but_other_reviewer_can(fixture):
    case = fixture
    case.select_single_blind_policy()
    first = case.assign(case.reviewer, 1)
    assert first.status_code == 201, first.text
    second = case.assign(case.other, 1)
    assert second.status_code == 201, second.text
    first_id, second_id = first.json()['assignment_id'], second.json()['assignment_id']
    case.current = case.reviewer
    before = case.client.get(f'/assignments/{first_id}/download')
    assert before.status_code == 200 and before.content == b'%PDF-first'
    case.db.add(models.ReviewerInvitationInvalidation(
        invalidation_id='batch33-synthetic-cancel', assignment_id=first_id,
        kind='cancelled', actor_user_id=case.editor.user_id,
        occurred_at='2026-01-01T00:00:00.000000Z', reason_code='editorial_cancellation'))
    case.db.commit()
    after = case.client.get(f'/assignments/{first_id}/download')
    assert after.status_code == 409 and b'%PDF-first' not in after.content
    assert case.client.get(f'/manuscripts/{case.mid}/timeline').status_code == 404
    case.current = case.other
    other = case.client.get(f'/assignments/{second_id}/download')
    assert other.status_code == 200 and other.content == b'%PDF-first'
    assert case.client.get(f'/assignments/{first_id}/download').status_code == 409

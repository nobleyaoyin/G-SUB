"""Isolated HTTP checks for policy-aware reviewer document delivery."""
import io
import zipfile

import pytest
from sqlalchemy.orm import Session

from app import models, review_files
from app.reviewer_demo_download import DemoArtifactContext, reviewer_demo_artifact_context
from tests.test_phase_2f_reviewer_projections import api_factory


def source_bytes(extension):
    if extension == 'pdf':
        return b'%PDF-synthetic author metadata and body'
    if extension == 'docx':
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            z.writestr('[Content_Types].xml', 'synthetic')
            z.writestr('word/document.xml', 'synthetic author body')
            z.writestr('docProps/core.xml', 'synthetic creator')
        return out.getvalue()
    return b'synthetic text'


def setup_file(api_factory, monkeypatch, tmp_path, policy, extension='pdf'):
    client, actor, engine = api_factory(policy)
    monkeypatch.setattr(review_files, 'BASE_DIR', tmp_path)
    directory = tmp_path / 'uploads' / 'manuscripts' / '1'
    directory.mkdir(parents=True)
    path = directory / f'source.{extension}'
    original = source_bytes(extension)
    path.write_bytes(original)
    with Session(engine) as db:
        manuscript = db.get(models.Manuscript, 1)
        assignment = db.get(models.ReviewAssignment, 1)
        manuscript.review_round = assignment.review_round = 2
        db.add(models.ReviewRoundFile(round_file_id=1, manuscript_id=1, review_round=2,
            source_kind='author_revision', file_path=str(path.relative_to(tmp_path))))
        db.flush()
        db.add(models.ReviewAssignmentFile(assignment_id=1, round_file_id=1))
        db.commit()
    return client, actor, engine, path, original


@pytest.mark.parametrize('extension', ['pdf', 'docx', 'txt'])
def test_locked_single_releases_bound_original_without_claiming_sanitization(api_factory, monkeypatch, tmp_path, extension):
    client, _, _, path, original = setup_file(api_factory, monkeypatch, tmp_path, 'single', extension)
    response = client.get('/assignments/1/download')
    assert response.status_code == 200 and response.content == original
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-disposition'].endswith(f'review-document.{extension}"')
    assert path.read_bytes() == original


@pytest.mark.parametrize('policy', ['missing', 'unlocked', 'invalid', 'unavailable', 'double'])
def test_unresolved_policy_and_missing_double_artifact_fail_closed(api_factory, monkeypatch, tmp_path, policy):
    client, _, _, path, original = setup_file(api_factory, monkeypatch, tmp_path, policy)
    response = client.get('/assignments/1/download')
    assert response.status_code == 409 and original not in response.content
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert path.read_bytes() == original


def test_artifact_context_without_evidence_never_falls_back(api_factory, monkeypatch, tmp_path):
    client, _, _, _, original = setup_file(api_factory, monkeypatch, tmp_path, 'double')
    client.app.dependency_overrides[reviewer_demo_artifact_context] = lambda: DemoArtifactContext(object(), object(), object())
    response = client.get('/assignments/1/download')
    assert response.status_code == 409 and original not in response.content


@pytest.mark.parametrize('state', ['completed', 'legacy'])
def test_single_blind_completed_and_legacy_assignment_are_denied(api_factory, monkeypatch, tmp_path, state):
    client, _, engine, _, original = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    with Session(engine) as db:
        if state == 'completed':
            db.get(models.ReviewAssignment, 1).status = 'completed'
        else:
            # Do not delete the invitation referenced by the lock event; use a
            # second historical assignment to the same round instead.
            db.add(models.ReviewAssignment(assignment_id=2, manuscript_id=1, reviewer_id=2, assigned_by=3, review_round=2, status='assigned'))
            db.flush()
            db.add(models.ReviewAssignmentFile(assignment_id=2, round_file_id=1))
        db.commit()
    response = client.get(f'/assignments/{2 if state == "legacy" else 1}/download')
    assert response.status_code == 409 and original not in response.content


def test_wrong_reviewer_and_wrong_round_denied(api_factory, monkeypatch, tmp_path):
    client, actor, engine, _, original = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    actor['id'] = 5
    assert client.get('/assignments/1/download').status_code == 409
    actor['id'] = 2
    with Session(engine) as db:
        db.get(models.ReviewAssignment, 1).review_round = 3
        db.commit()
    response = client.get('/assignments/1/download')
    assert response.status_code == 409 and original not in response.content


def test_invalidated_invitation_is_denied(api_factory, monkeypatch, tmp_path):
    client, _, engine, _, original = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    with Session(engine) as db:
        db.add(models.ReviewerInvitationInvalidation(invalidation_id='synthetic', assignment_id=1,
            kind='cancelled', actor_user_id=4, occurred_at='2026-01-02T03:04:05.000000Z',
            reason_code='editorial_cancellation'))
        db.commit()
    response = client.get('/assignments/1/download')
    assert response.status_code == 409 and original not in response.content


def test_wrong_manuscript_binding_is_denied(api_factory, monkeypatch, tmp_path):
    client, _, engine, _, original = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    with Session(engine) as db:
        db.add(models.Manuscript(manuscript_id=2, author_id=1, title='Other', abstract='Other', status='revised', review_round=2))
        db.flush()
        db.get(models.ReviewRoundFile, 1).manuscript_id = 2
        db.commit()
    assert original not in client.get('/assignments/1/download').content


@pytest.mark.parametrize('extension,marker', [('pdf', b'author metadata'), ('docx', b'synthetic creator')])
def test_single_blind_metadata_is_not_automatically_removed(api_factory, monkeypatch, tmp_path, extension, marker):
    client, _, _, _, original = setup_file(api_factory, monkeypatch, tmp_path, 'single', extension)
    response = client.get('/assignments/1/download')
    assert response.content == original
    if extension == 'pdf':
        assert marker in response.content
    else:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert marker in archive.read('docProps/core.xml')

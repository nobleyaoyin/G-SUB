"""Synthetic in-memory API and temporary-file snapshot regressions."""
import hashlib
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app import models, review_files, reviewer_document_release
from app.reviewer_artifact_read import ArtifactReadUnavailable
from app.reviewer_demo_download import DemoArtifactContext, reviewer_demo_artifact_context
from tests.test_phase_2f_reviewer_projections import api_factory
from tests.test_phase_2f_reviewer_document_release import setup_file


@pytest.mark.parametrize('extension', ['pdf', 'docx', 'doc', 'txt'])
def test_exact_snapshot_and_neutral_availability(api_factory, monkeypatch, tmp_path, extension):
    client, _, engine, path, original = setup_file(api_factory, monkeypatch, tmp_path, 'single', extension)
    if extension == 'doc':
        original = bytes.fromhex('d0cf11e0a1b11ae1') + b'synthetic historical word'
        path.write_bytes(original)
    listing = client.get('/assignments/my').json()[0]
    assert listing['review_file_available'] is True and listing['review_file_status'] == 'available'
    assert not {'author_id', 'file_path', 'mode', 'storage_id'} & listing.keys()
    with Session(engine) as db:
        assignment = db.get(models.ReviewAssignment, 1)
        snapshot = review_files.snapshot_assignment_file(db, assignment, db.get(models.Manuscript, 1))
        assert snapshot.content == original and snapshot.sha256 == hashlib.sha256(original).hexdigest()
    response = client.get('/assignments/1/download')
    assert response.status_code == 200 and response.content == snapshot.content
    assert response.headers['cache-control'] == 'no-store' and response.headers['x-content-type-options'] == 'nosniff'


@pytest.mark.parametrize('policy', ['missing', 'unlocked', 'invalid', 'unavailable', 'double'])
def test_unresolved_policy_never_reported_available(api_factory, monkeypatch, tmp_path, policy):
    client, _, _, _, original = setup_file(api_factory, monkeypatch, tmp_path, policy)
    item = client.get('/assignments/my').json()[0]
    assert item['review_file_available'] is False and item['review_file_status'] == 'unavailable'
    assert original not in client.get('/assignments/1/download').content


@pytest.mark.parametrize('kind', ['missing', 'oversized', 'symlink', 'fifo', 'traversal'])
def test_unsafe_files_are_denied(api_factory, monkeypatch, tmp_path, kind):
    client, _, engine, path, _ = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    if kind == 'missing':
        path.unlink()
    elif kind == 'oversized':
        path.write_bytes(b'%PDF-' + b'x' * (10 * 1024 * 1024))
    elif kind == 'symlink':
        target = path.with_name('other.pdf'); target.write_bytes(b'%PDF-synthetic')
        path.unlink(); path.symlink_to(target)
    elif kind == 'fifo':
        path.unlink(); os.mkfifo(path)
    else:
        with Session(engine) as db:
            db.get(models.ReviewRoundFile, 1).file_path = 'uploads/manuscripts/1/../1/source.pdf'
            db.commit()
    assert client.get('/assignments/my').json()[0]['review_file_available'] is False
    assert client.get('/assignments/1/download').status_code == 409


def test_same_path_replaced_after_validation_delivers_snapshot(api_factory, monkeypatch, tmp_path):
    client, _, _, path, original = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    validate = review_files.validate_manuscript_file
    def replace_after_validation(name, content, **kwargs):
        result = validate(name, content, **kwargs)
        replacement = path.with_name('replacement.pdf')
        replacement.write_bytes(b'%PDF-replacement')
        os.replace(replacement, path)
        return result
    monkeypatch.setattr(review_files, 'validate_manuscript_file', replace_after_validation)
    response = client.get('/assignments/1/download')
    assert response.status_code == 200 and response.content == original
    assert path.read_bytes() == b'%PDF-replacement'


def test_same_inode_mutation_during_read_is_denied(api_factory, monkeypatch, tmp_path):
    client, _, _, path, original = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    read = os.read
    changed = False
    def mutate(fd, count):
        nonlocal changed
        data = read(fd, count)
        if data and not changed:
            changed = True
            path.write_bytes(b'%PDF-mutated-synthetic-data')
        return data
    with patch.object(review_files.os, 'read', mutate):
        response = client.get('/assignments/1/download')
    assert changed and response.status_code == 409 and original not in response.content


def test_historical_round_is_unavailable_and_invalidation_remains_denied(api_factory, monkeypatch, tmp_path):
    client, _, engine, _, original = setup_file(api_factory, monkeypatch, tmp_path, 'single')
    with Session(engine) as db:
        db.get(models.Manuscript, 1).review_round = 3
        db.commit()
    response = client.get('/assignments/1/download')
    assert response.status_code == 409 and original not in response.content
    assert client.get('/assignments/my').json()[0]['review_file_available'] is False
    with Session(engine) as db:
        db.add(models.ReviewerInvitationInvalidation(invalidation_id='synthetic', assignment_id=1, kind='cancelled', actor_user_id=4,
            occurred_at='2026-01-02T03:04:05.000000Z', reason_code='editorial_cancellation'))
        db.commit()
    assert client.get('/assignments/my').json()[0]['review_file_available'] is False
    assert client.get('/assignments/1/download').status_code == 409
    assert client.get('/assignments/999/download').status_code == 409


@pytest.mark.parametrize('approved', [True, False])
def test_artifact_reader_result_controls_double_blind_availability(api_factory, monkeypatch, tmp_path, approved):
    """Mocked reader tests evaluator wiring, not real evidence/approval."""
    client, _, _, _, original = setup_file(api_factory, monkeypatch, tmp_path, 'double')
    client.app.dependency_overrides[reviewer_demo_artifact_context] = lambda: DemoArtifactContext(object(), object(), object())
    def reader(*args):
        if not approved:
            raise ArtifactReadUnavailable('synthetic revoked approval')
        return SimpleNamespace(content=b'synthetic reviewer copy', media_type='text/plain', filename='review-document.txt')
    monkeypatch.setattr(reviewer_document_release, 'read_reviewer_artifact', reader)
    item = client.get('/assignments/my').json()[0]
    response = client.get('/assignments/1/download')
    assert item['review_file_available'] is approved
    assert response.status_code == (200 if approved else 409)
    assert original not in response.content

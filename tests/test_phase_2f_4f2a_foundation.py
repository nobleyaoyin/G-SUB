"""Isolated checks of the non-routed source/policy observation service."""
import hashlib
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app import models, review_files, source_policy_foundation
from app.source_policy_foundation import FoundationUnavailable, capture, revalidate
from tests.test_phase_2f_policy_management import policy_api
from tests.test_phase_2f_reviewer_projections import api_factory


@pytest.fixture
def context(policy_api, monkeypatch, tmp_path):
    client, actor, engine = policy_api
    actor['id'] = 4
    assert client.put('/eic/manuscripts/2/review-policy', json={'mode': 'double_blind'}).status_code == 200
    monkeypatch.setattr(review_files, 'BASE_DIR', tmp_path)
    directory = tmp_path / 'uploads' / 'manuscripts' / '2'
    directory.mkdir(parents=True)
    path = directory / 'round_2_synthetic.txt'
    content = b'synthetic revision text'
    path.write_bytes(content)
    with Session(engine) as db:
        db.get(models.Manuscript, 2).file_path = str(path.relative_to(tmp_path))
        db.get(models.ReviewRoundFile, 2).file_path = str(path.relative_to(tmp_path))
        db.commit()

    class Proof:
        revision = 'trusted-proof-1'
        def verify_prospective(self, manuscript_id, rnd, source_id, confirmation):
            assert (manuscript_id, rnd, source_id, confirmation) == (2, 2, 2, None)
            return self.revision, hashlib.sha256(content).hexdigest(), len(content), 'txt'
    proof = Proof()
    monkeypatch.setattr(source_policy_foundation, '_server_proof_adapter', lambda: proof)
    return client, engine, path, content, proof


def capture_current(db, proof, revision=1, user_id=4, manuscript=2, source=2):
    return capture(db, db.get(models.User, user_id), manuscript, source, revision, proof_adapter=proof)


def test_later_round_capture_and_unchanged_original(context):
    _, engine, path, content, proof = context
    with Session(engine) as db:
        result = capture_current(db, proof)
        assert result.actor_id == 4 and result.source_id == 2 and result.review_round == 2
        assert result.source_sha256 == hashlib.sha256(content).hexdigest()
        assert result.byte_length == len(content) and result.policy_revision == 1
        assert result.source_revision == proof.revision and result.policy_event_id
        db.rollback()
        assert revalidate(db, db.get(models.User, 4), result, proof_adapter=proof).source_sha256 == result.source_sha256
    assert path.read_bytes() == content


@pytest.mark.parametrize('user_id', [1, 2, 3, 5])
def test_non_eic_rejected_with_valid_positive_control(context, user_id):
    _, engine, _, _, proof = context
    with Session(engine) as db:
        assert capture_current(db, proof).actor_id == 4
        db.rollback()
        with pytest.raises(FoundationUnavailable, match='EIC'):
            capture_current(db, proof, user_id=user_id)


def test_missing_proof_and_wrong_source_fail_closed(context):
    _, engine, _, _, proof = context
    with Session(engine) as db:
        assert capture_current(db, proof).source_id == 2
        db.rollback()
        with pytest.raises(FoundationUnavailable, match='proof'):
            capture_current(db, None)
        with pytest.raises(FoundationUnavailable):
            capture_current(db, proof, source=999)
        db.rollback()
        with pytest.raises(FoundationUnavailable):
            capture_current(db, proof, manuscript=1)
        db.rollback()
        with pytest.raises(FoundationUnavailable):
            capture_current(db, proof, revision=99)
        db.rollback()
        with pytest.raises(FoundationUnavailable, match='EIC'):
            capture(db, None, 2, 2, 1, proof_adapter=proof)
        formatter = models.User(user_id=9, name='Formatter', email='formatter@example.test', password_hash='x', role='formatter')
        db.add(formatter)
        db.commit()
        with pytest.raises(FoundationUnavailable, match='EIC'):
            capture(db, formatter, 2, 2, 1, proof_adapter=proof)


def test_same_size_change_and_proof_revision_rejected(context):
    _, engine, path, content, proof = context
    with Session(engine) as db:
        initial = capture_current(db, proof)
        db.rollback()
        proof.revision = 'trusted-proof-2'
        with pytest.raises(FoundationUnavailable, match='stale'):
            revalidate(db, db.get(models.User, 4), initial, proof_adapter=proof)
        db.rollback()
        proof.revision = initial.source_revision
        path.write_bytes(content.upper())
        with pytest.raises(FoundationUnavailable, match='proof mismatch'):
            revalidate(db, db.get(models.User, 4), initial, proof_adapter=proof)


def test_policy_aba_rejected(context):
    client, engine, _, _, proof = context
    with Session(engine) as db:
        initial = capture_current(db, proof)
    path = '/eic/manuscripts/2/review-policy'
    assert client.put(path, json={'mode':'single_blind', 'expected_revision':1}).status_code == 200
    assert client.put(path, json={'mode':'double_blind', 'expected_revision':2}).status_code == 200
    with Session(engine) as db:
        assert capture_current(db, proof, revision=3).policy_revision == 3
        db.rollback()
        with pytest.raises(FoundationUnavailable, match='stale'):
            revalidate(db, db.get(models.User, 4), initial, proof_adapter=proof)


def test_traversal_and_symlink_denied(context):
    _, engine, path, _, proof = context
    with Session(engine) as db:
        assert capture_current(db, proof).source_id == 2
        db.rollback()
        record = db.get(models.ReviewRoundFile, 2)
        manuscript = db.get(models.Manuscript, 2)
        record.file_path = manuscript.file_path = 'uploads/manuscripts/2/../2/round_2_synthetic.txt'
        db.commit()
        with pytest.raises(FoundationUnavailable):
            capture_current(db, proof)
        record.file_path = manuscript.file_path = 'uploads/manuscripts/2/link.txt'
        db.commit()
        path.with_name('link.txt').symlink_to(path)
        with pytest.raises(FoundationUnavailable):
            capture_current(db, proof)


def test_first_round_real_source_and_eic_author_confirmation(context, tmp_path, monkeypatch):
    _, engine, _, _, _ = context
    directory = tmp_path / 'uploads' / 'initial_editing' / '2'
    directory.mkdir(parents=True)
    path = directory / 'initial.txt'
    content = b'synthetic initial manuscript'
    path.write_bytes(content)
    relative = str(path.relative_to(tmp_path))
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        manuscript = db.get(models.Manuscript, 2)
        manuscript.review_round = 1
        manuscript.status = 'ready_for_peer_review'
        db.add(models.InitialEditingSubmission(submission_id=10, manuscript_id=2, editor_id=3,
            file_path=relative, comments='', status='eic_approved', eic_approved_by=4, eic_reviewed_at=now))
        db.flush()
        db.add(models.PreReviewConfirmation(confirmation_id=10, manuscript_id=2, submission_id=10,
            author_id=1, file_path=relative, decision='confirm', comments='', confirmed_at=now))
        db.flush()
        record = db.get(models.ReviewRoundFile, 2)
        record.review_round, record.source_kind, record.confirmation_id, record.file_path = 1, 'initial_editing', 10, relative
        db.commit()
    class Proof:
        def verify_prospective(self, mid, rnd, source, confirmation):
            assert (mid, rnd, source, confirmation) == (2, 1, 2, 10)
            return 'first-proof', hashlib.sha256(content).hexdigest(), len(content), 'txt'
    proof = Proof()
    monkeypatch.setattr(source_policy_foundation, '_server_proof_adapter', lambda: proof)
    with Session(engine) as db:
        result = capture_current(db, proof)
        assert result.workflow_event == 'confirmation:10' and result.review_round == 1
        db.rollback()
        submission = db.get(models.InitialEditingSubmission, 10)
        submission.eic_approved_by = None
        db.commit()
        with pytest.raises(FoundationUnavailable, match='approval evidence'):
            capture_current(db, proof)
    assert path.read_bytes() == content


def test_locked_policy_and_superseded_source_rejected(context):
    client, engine, _, _, proof = context
    with Session(engine) as db:
        assert capture_current(db, proof).policy_revision == 1
        db.rollback()
        manuscript = db.get(models.Manuscript, 2)
        manuscript.file_path = 'uploads/manuscripts/2/other.txt'
        db.commit()
        with pytest.raises(FoundationUnavailable, match='stale'):
            capture_current(db, proof)
        manuscript.file_path = db.get(models.ReviewRoundFile, 2).file_path
        db.commit()
    assert client.post('/assignments/', json={'manuscript_id':2, 'reviewer_id':5, 'review_round':2}).status_code == 201
    with Session(engine) as db:
        with pytest.raises(FoundationUnavailable, match='policy'):
            capture_current(db, proof, revision=2)


def test_dirty_session_does_not_flush_unrelated_changes(context):
    _, engine, _, _, proof = context
    with Session(engine) as db:
        assert capture_current(db, proof).actor_id == 4
        db.rollback()
        principal = db.get(models.User, 4)
        manuscript = db.get(models.Manuscript, 2)
        manuscript.title = 'pending synthetic change'
        with pytest.raises(FoundationUnavailable, match='clean read session'):
            capture(db, principal, 2, 2, 1, proof_adapter=proof)
        assert manuscript in db.dirty
        db.rollback()
        assert db.get(models.Manuscript, 2).title != 'pending synthetic change'


def test_unconfigured_or_request_supplied_adapter_is_denied(context, monkeypatch):
    _, engine, _, _, proof = context
    with Session(engine) as db:
        assert capture_current(db, proof).actor_id == 4
        db.rollback()
        with pytest.raises(FoundationUnavailable, match='proof'):
            capture_current(db, object())
        monkeypatch.setattr(source_policy_foundation, '_server_proof_adapter', lambda: None)
        with pytest.raises(FoundationUnavailable, match='proof'):
            capture_current(db, proof)

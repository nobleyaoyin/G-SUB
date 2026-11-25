"""Isolated HTTP checks for current-round reviewer document authorization."""
import sqlite3
import pytest

from app.main import app
from app.reviewer_metadata_gate import MetadataMode, reviewer_metadata_mode
from tests.test_phase26_backend_integration import environment, auth


@pytest.mark.parametrize("mode", [MetadataMode.DISABLED, MetadataMode.EXPERIMENTAL])
@pytest.mark.parametrize("state", [
    "accepted", "completed", "pending", "declined", "legacy",
    "expired", "revoked", "stale_round", "wrong_stage", "other_reviewer",
    "disabled_account",
])
def test_review_document_requires_exact_current_authorized_assignment(environment, mode, state):
    client, dbpath, source = environment
    app.dependency_overrides[reviewer_metadata_mode] = lambda: mode
    try:
        uid = 2
        assignment_id = 1
        with sqlite3.connect(dbpath) as db:
            db.execute("PRAGMA foreign_keys=ON")
            if state == "completed":
                db.execute("UPDATE review_assignments SET status='completed' WHERE assignment_id=1")
            elif state in ("pending", "declined"):
                db.execute("UPDATE reviewer_invitations SET status=? WHERE assignment_id=1", (state,))
            elif state == "legacy":
                db.execute("""INSERT INTO review_assignments
                    (assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at)
                    VALUES (3,1,5,3,2,'assigned','2026-01-01')""")
                db.execute("INSERT INTO review_assignment_files(assignment_id,round_file_id,bound_at) VALUES (3,1,'2026-01-01')")
                uid, assignment_id = 5, 3
            elif state == "expired":
                # Expiration has no first-class schema field; unknown assignment
                # states must fail closed if historical records contain one.
                db.execute("UPDATE review_assignments SET status='expired' WHERE assignment_id=1")
            elif state == "revoked":
                db.execute("INSERT INTO reviewer_invitation_invalidations VALUES (?,?,?,?,?,?,?)",
                           ("phase4-revocation", 1, "cancelled", None, 3,
                            "2026-01-01T00:00:00.000000Z", "editorial_cancellation"))
            elif state == "stale_round":
                db.execute("UPDATE manuscripts SET review_round=3 WHERE manuscript_id=1")
            elif state == "wrong_stage":
                db.execute("UPDATE manuscripts SET status='eic_decision' WHERE manuscript_id=1")
            elif state == "other_reviewer":
                uid = 5
            elif state == "disabled_account":
                db.execute("INSERT INTO account_lifecycle_events VALUES (?,?,?,?,?,?,?,?,?)",
                           ("phase4-disabled", 2, 2, "active", "disabled", 2, 3,
                            "2026-01-01T00:00:00.000000Z", "administrative_disable"))
                db.execute("""UPDATE account_lifecycle
                    SET state='disabled', sequence=2, auth_generation=2, last_event_id='phase4-disabled'
                    WHERE user_id=2""")
        response = client.get(f"/assignments/{assignment_id}/download", headers=auth(uid))
        if state == "accepted":
            assert response.status_code == 200 and response.content == source.read_bytes()
        else:
            assert response.status_code == 409
            assert source.read_bytes() not in response.content
    finally:
        app.dependency_overrides.pop(reviewer_metadata_mode, None)


def test_other_active_assignment_does_not_authorize_completed_one(environment):
    client, dbpath, source = environment
    with sqlite3.connect(dbpath) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("UPDATE review_assignments SET status='completed' WHERE assignment_id=1")
        db.execute("""INSERT INTO review_assignments
            (assignment_id,manuscript_id,reviewer_id,assigned_by,review_round,status,assigned_at)
            VALUES (3,1,2,3,2,'assigned','2026-01-01')""")
        db.execute("INSERT INTO reviewer_invitations(assignment_id,status,invited_at) VALUES (3,'accepted','2026-01-01')")
    response = client.get("/assignments/1/download", headers=auth(2))
    assert response.status_code == 409
    assert source.read_bytes() not in response.content


def test_reviewers_cannot_bypass_assignment_with_general_downloads(environment):
    client, _, source = environment
    for path in ("/manuscripts/1/download", "/manuscripts/1/versions/revision.txt"):
        response = client.get(path, headers=auth(2))
        assert response.status_code == 403
        assert source.read_bytes() not in response.content


@pytest.mark.parametrize("mode", [MetadataMode.DISABLED, MetadataMode.EXPERIMENTAL])
def test_double_blind_without_approved_artifact_never_returns_original(environment, mode):
    client, _, source = environment
    app.dependency_overrides[reviewer_metadata_mode] = lambda: mode
    try:
        response = client.get("/assignments/2/download", headers=auth(2))
        assert response.status_code == 409
        assert source.read_bytes() not in response.content
    finally:
        app.dependency_overrides.pop(reviewer_metadata_mode, None)

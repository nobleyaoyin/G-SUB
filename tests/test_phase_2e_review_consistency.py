"""Review-count regressions using only a synthetic in-memory SQLite database."""
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app import models
from app.database import Base
from app.review_progress import review_progress
from app.split_review import split_review_status


def test_legacy_completed_review_is_not_automatically_split_eligible():
    engine = create_engine("sqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    tables = [models.User, models.Manuscript, models.ReviewAssignment,
              models.ManuscriptReviewPolicy, models.ReviewerInvitation,
              models.InitialEditingSubmission, models.PreReviewConfirmation,
              models.ReviewRoundFile, models.ReviewAssignmentFile, models.Review]
    Base.metadata.create_all(engine, tables=[item.__table__ for item in tables])
    try:
        with Session(engine) as db:
            assert db.scalar(text("PRAGMA foreign_keys")) == 1
            db.add_all([
                models.User(user_id=1, name="Author", email="a@example.test", password_hash="x", role="author"),
                models.User(user_id=2, name="Reviewer", email="r@example.test", password_hash="x", role="reviewer"),
                models.User(user_id=3, name="Editor", email="e@example.test", password_hash="x", role="editor"),
                models.User(user_id=4, name="Second reviewer", email="r2@example.test", password_hash="x", role="reviewer"),
            ])
            db.commit()
            manuscript = models.Manuscript(manuscript_id=1, title="Synthetic", abstract="Synthetic",
                                           author_id=1, status="ready_for_peer_review", review_round=1)
            db.add(manuscript)
            db.commit()
            db.add(models.InitialEditingSubmission(submission_id=1, manuscript_id=1, editor_id=3,
                                                   file_path="synthetic.pdf", comments="Synthetic", status="eic_approved"))
            db.commit()
            db.add(models.PreReviewConfirmation(confirmation_id=1, manuscript_id=1, submission_id=1,
                                                author_id=1, file_path="synthetic.pdf", decision="confirm", comments="Synthetic"))
            db.commit()
            db.add(models.ReviewAssignment(assignment_id=1, manuscript_id=1, reviewer_id=2,
                                           assigned_by=3, review_round=1, status="completed"))
            db.commit()
            db.add(models.Review(assignment_id=1, comments="Synthetic", recommendation="accept"))
            db.commit()
            assert review_progress(db, manuscript)["completed_distinct"] == 1
            assert split_review_status(db, manuscript)["eligible_completed"] == 0
            assert db.execute(text("PRAGMA foreign_key_check")).all() == []
            db.add(models.ReviewAssignment(assignment_id=2, manuscript_id=1, reviewer_id=4,
                                           assigned_by=3, review_round=1, status="assigned"))
            db.commit()
            db.add(models.ReviewerInvitation(assignment_id=2, status="pending"))
            db.commit()
            blocked = review_progress(db, manuscript)
            assert blocked["completed_distinct"] == blocked["required"] == 1
            assert not blocked["can_decide"]
            assert "All other non-declined" in blocked["blocked_reason"]
            db.add(models.ReviewerInvitation(assignment_id=1, status="accepted", responded_at=datetime.now(timezone.utc)))
            db.add(models.ReviewRoundFile(round_file_id=1, manuscript_id=1, review_round=1,
                                          source_kind="initial_editing", confirmation_id=1, file_path="synthetic.pdf"))
            db.commit()
            db.add(models.ReviewAssignmentFile(assignment_id=1, round_file_id=1))
            db.commit()
            assert split_review_status(db, manuscript)["eligible_completed"] == 1
            db.add(models.ManuscriptReviewPolicy(manuscript_id=1, minimum_completed_reviewers=2))
            db.commit()
            assert review_progress(db, manuscript)["completed_distinct"] == 1
            assert not review_progress(db, manuscript)["can_decide"]
            manuscript.review_round = 2
            db.commit()
            assert review_progress(db, manuscript)["completed_distinct"] == 0
            assert split_review_status(db, manuscript)["eligible_completed"] == 0
            assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        engine.dispose()

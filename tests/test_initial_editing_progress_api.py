"""Integration tests for Initial Editing progress using disposable SQLite."""

import unittest

from app import models
from tests.test_reviewer_download import ReviewerDownloadsTest


class ProgressFixture(ReviewerDownloadsTest):
    """Reuse isolated setup without inheriting unrelated test cases."""

    __test__ = False


class InitialEditingProgressAPITests(unittest.TestCase):
    def setUp(self):
        self.fixture = ProgressFixture(methodName="runTest")
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def progress(self, user):
        f = self.fixture
        f.current = user
        response = f.client.get(f"/manuscripts/{f.mid}/progress")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def steps(self, user):
        data = self.progress(user)
        stage = next(
            item for item in data["stages"]
            if item["name"] == "Initial Editing"
        )
        return {
            step["name"]: step["state"]
            for step in stage.get("steps", [])
        }

    def add_submission(self, status, editor=None):
        f = self.fixture
        submission = models.InitialEditingSubmission(
            manuscript_id=f.mid,
            editor_id=(editor or f.editor).user_id,
            file_path=f.pdf,
            comments="synthetic",
            status=status,
        )
        f.db.add(submission)
        f.db.commit()
        return submission

    def test_existing_confirmed_version(self):
        steps = self.steps(self.fixture.author)
        self.assertEqual(steps["Editor Invitation"], "completed")
        self.assertEqual(steps["Editor Submission"], "completed")
        self.assertEqual(steps["EIC Approval"], "completed")
        self.assertEqual(
            steps["Pre-review Author Confirmation"],
            "completed",
        )

    def test_new_submission_does_not_inherit_old_confirmation(self):
        self.add_submission("eic_approved")
        steps = self.steps(self.fixture.author)
        self.assertEqual(
            steps["Pre-review Author Confirmation"],
            "current",
        )

    def test_new_submission_pending_author(self):
        self.add_submission("pending_author")
        steps = self.steps(self.fixture.author)
        self.assertEqual(steps["Editor Submission"], "completed")
        self.assertEqual(steps["Author Approval"], "current")
        self.assertEqual(steps["EIC Approval"], "unknown")

    def test_new_submission_revision_requested(self):
        self.add_submission("author_revision_requested")
        steps = self.steps(self.fixture.author)
        self.assertEqual(steps["Editor Submission"], "completed")
        self.assertEqual(steps["Author Approval"], "unknown")
        self.assertEqual(steps["EIC Approval"], "unknown")

    def test_editor_invitation_bound_to_submission_editor(self):
        f = self.fixture
        other_editor = models.User(
            name="Second Editor",
            email="second-editor@example.com",
            password_hash="x",
            role="editor",
        )
        f.db.add(other_editor)
        f.db.flush()

        # A newer invitation must not replace the editor of the submission.
        f.db.add(models.InitialEditorInvitation(
            manuscript_id=f.mid,
            editor_id=other_editor.user_id,
            invited_by=f.editor.user_id,
            status="declined",
        ))
        f.db.commit()

        steps = self.steps(f.author)
        self.assertEqual(steps["Editor Invitation"], "completed")

    def test_assigned_reviewer_cannot_see_steps(self):
        f = self.fixture
        f.select_single_blind_policy()
        assigned = f.assign(f.reviewer, 1)
        self.assertEqual(assigned.status_code, 201, assigned.text)

        data = self.progress(f.reviewer)
        initial = next(
            item for item in data["stages"]
            if item["name"] == "Initial Editing"
        )
        self.assertNotIn("steps", initial)

    def test_unassigned_reviewer_denied(self):
        f = self.fixture
        f.current = f.reviewer
        response = f.client.get(f"/manuscripts/{f.mid}/progress")
        self.assertEqual(response.status_code, 404)

    def test_author_response_contains_no_private_details(self):
        data = self.progress(self.fixture.author)
        forbidden = {
            "file_path", "editor_id", "reviewer_id",
            "comments", "author_comments", "eic_comments",
            "submission_id", "invitation_id",
        }

        initial = next(
            item for item in data["stages"]
            if item["name"] == "Initial Editing"
        )
        for step in initial["steps"]:
            self.assertEqual(set(step), {"name", "state"})
            self.assertTrue(forbidden.isdisjoint(step))


if __name__ == "__main__":
    unittest.main()

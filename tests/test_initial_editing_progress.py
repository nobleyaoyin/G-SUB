"""Unit tests for version-aware Initial Editing progress milestones."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.routers.manuscripts import (
    INITIAL_EDITING_STEPS,
    initial_editing_progress,
)


class InitialEditingProgressTests(unittest.TestCase):
    def get_steps(
        self,
        *,
        status=None,
        editor_id=10,
        invitation_status="accepted",
        confirmation=None,
    ):
        db = MagicMock()
        db.get.return_value = SimpleNamespace(author_id=5)

        submission = (
            SimpleNamespace(
                submission_id=100,
                manuscript_id=1,
                editor_id=editor_id,
                file_path="uploads/initial_editing/1/synthetic.pdf",
                status=status,
            )
            if status is not None
            else None
        )

        invitation = (
            SimpleNamespace(status=invitation_status)
            if invitation_status is not None
            else None
        )

        # The helper performs three scalar queries:
        # latest submission, editor invitation, pre-review confirmation.
        results = [submission, invitation]
        if status == "eic_approved":
            results.append(
                SimpleNamespace(decision=confirmation, author_id=5,
                                file_path="uploads/initial_editing/1/synthetic.pdf")
                if confirmation is not None
                else None
            )

        db.scalar.side_effect = results

        steps = initial_editing_progress(db, 1)

        self.assertEqual(
            [step["name"] for step in steps],
            list(INITIAL_EDITING_STEPS),
        )

        return {step["name"]: step["state"] for step in steps}

    def test_pending_invitation(self):
        steps = self.get_steps(
            status=None,
            invitation_status="pending",
        )
        self.assertEqual(steps["Editor Invitation"], "current")
        self.assertEqual(steps["Editor Submission"], "unknown")

    def test_pending_author(self):
        steps = self.get_steps(status="pending_author")
        self.assertEqual(steps["Editor Invitation"], "completed")
        self.assertEqual(steps["Editor Submission"], "completed")
        self.assertEqual(steps["Author Approval"], "current")

    def test_author_approved(self):
        steps = self.get_steps(status="author_approved")
        self.assertEqual(steps["Author Approval"], "completed")
        self.assertEqual(steps["Editor Approval"], "current")

    def test_editor_approved(self):
        steps = self.get_steps(status="editor_approved")
        self.assertEqual(steps["Editor Approval"], "completed")
        self.assertEqual(steps["EIC Approval"], "current")

    def test_eic_approved(self):
        steps = self.get_steps(status="eic_approved")
        self.assertEqual(steps["EIC Approval"], "completed")
        self.assertEqual(
            steps["Pre-review Author Confirmation"],
            "current",
        )

    def test_author_confirmed(self):
        steps = self.get_steps(
            status="eic_approved",
            confirmation="confirm",
        )
        self.assertEqual(
            steps["Pre-review Author Confirmation"],
            "completed",
        )

    def test_author_rejected_pre_review(self):
        steps = self.get_steps(
            status="eic_approved",
            confirmation="reject",
        )
        self.assertEqual(
            steps["Pre-review Author Confirmation"],
            "unknown",
        )

    def test_author_revision_requested(self):
        steps = self.get_steps(status="author_revision_requested")
        self.assertEqual(steps["Editor Submission"], "completed")
        self.assertEqual(steps["Author Approval"], "unknown")
        self.assertEqual(steps["EIC Approval"], "unknown")

    def test_editor_revision_requested(self):
        steps = self.get_steps(status="editor_revision_requested")
        self.assertEqual(steps["Editor Submission"], "completed")
        self.assertEqual(steps["Editor Approval"], "unknown")
        self.assertEqual(steps["EIC Approval"], "unknown")

    def test_eic_revision_requested(self):
        steps = self.get_steps(status="eic_revision_requested")
        self.assertEqual(steps["Editor Submission"], "completed")
        self.assertEqual(steps["EIC Approval"], "unknown")
        self.assertEqual(
            steps["Pre-review Author Confirmation"],
            "unknown",
        )

    def test_no_submission_or_invitation(self):
        steps = self.get_steps(
            status=None,
            invitation_status=None,
        )
        self.assertTrue(
            all(state == "unknown" for state in steps.values())
        )


if __name__ == "__main__":
    unittest.main()

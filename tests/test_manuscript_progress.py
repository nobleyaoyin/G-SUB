"""Read-only manuscript progress API tests with isolated SQLite fixtures."""

import unittest

from tests.test_reviewer_download import ReviewerDownloadsTest


class ManuscriptProgressTests(ReviewerDownloadsTest):
    def test_author_progress_and_safe_fields(self):
        self.current = self.author
        response = self.client.get(f"/manuscripts/{self.mid}/progress")

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()

        self.assertEqual(data["manuscript_id"], self.mid)
        self.assertEqual(data["title"], "Title")
        self.assertEqual(data["status"], "ready_for_peer_review")
        self.assertEqual(data["review_round"], 1)
        self.assertEqual(data["current_stage"], "Peer Review")
        self.assertEqual(len(data["stages"]), 10)

        self.assertEqual(
            [stage["name"] for stage in data["stages"]],
            [
                "Submission",
                "Initial Screening",
                "Initial Editing",
                "Peer Review",
                "EIC Decision",
                "Author Agreement",
                "Final Editing",
                "Formatting",
                "Proofing",
                "Publication",
            ],
        )

        self.assertEqual(
            next(s["state"] for s in data["stages"]
                 if s["name"] == "Peer Review"),
            "current",
        )

        # The endpoint must not expose private workflow details.
        forbidden = {
            "file_path",
            "reviewer",
            "reviewer_id",
            "comments",
            "abstract",
            "author_id",
            "password_hash",
        }
        self.assertTrue(forbidden.isdisjoint(data.keys()))

    def test_authorized_editor(self):
        self.current = self.editor
        response = self.client.get(f"/manuscripts/{self.mid}/progress")
        self.assertEqual(response.status_code, 200, response.text)

    def test_unassigned_reviewer_denied(self):
        self.current = self.reviewer
        response = self.client.get(f"/manuscripts/{self.mid}/progress")
        self.assertEqual(response.status_code, 404, response.text)

    def test_assigned_reviewer_allowed(self):
        self.select_single_blind_policy()
        assigned = self.assign(self.reviewer, 1)
        self.assertEqual(assigned.status_code, 201, assigned.text)

        self.current = self.reviewer
        response = self.client.get(f"/manuscripts/{self.mid}/progress")
        self.assertEqual(response.status_code, 200, response.text)

        data = response.json()
        self.assertEqual(data["review_round"], 1)
        self.assertNotIn("assignments", data)
        self.assertNotIn("reviews", data)

    def test_missing_manuscript_returns_404(self):
        self.current = self.author
        response = self.client.get("/manuscripts/999999/progress")
        self.assertEqual(response.status_code, 404, response.text)

    def test_legacy_accepted_status_maps_without_fabricating_completion(self):
        self.manuscript.status = "accepted"
        self.db.commit()

        self.current = self.author
        response = self.client.get(f"/manuscripts/{self.mid}/progress")

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["current_stage"], "EIC Decision")

        states = {item["name"]: item["state"] for item in data["stages"]}
        self.assertEqual(states["EIC Decision"], "current")
        self.assertNotEqual(states["Peer Review"], "completed")
        self.assertNotEqual(states["Author Agreement"], "completed")
        self.assertNotEqual(states["Publication"], "completed")


if __name__ == "__main__":
    unittest.main()

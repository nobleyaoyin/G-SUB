"""Tests for staff-only manuscript General Comments."""

import unittest

from tests.test_reviewer_download import ReviewerDownloadsTest
from app import models


class GeneralCommentsTests(unittest.TestCase):

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return relative

    def setUp(self):
        # Reuse the existing isolated database and migration fixture.
        ReviewerDownloadsTest.setUp(self)

        self.eic = models.User(
            name="EIC",
            email="comments-eic@example.com",
            password_hash="x",
            role="eic",
        )

        self.final_editor = models.User(
            name="Final Editor",
            email="comments-final@example.com",
            password_hash="x",
            role="editor",
        )

        self.db.add_all([self.eic, self.final_editor])
        self.db.flush()

        self.second_manuscript = models.Manuscript(
            title="Second Manuscript",
            abstract="Second Abstract",
            author_id=self.author.user_id,
            status="submitted",
        )
        self.db.add(self.second_manuscript)
        self.db.flush()

        self.db.add(
            models.FinalEditorInvitation(
                manuscript_id=self.mid,
                editor_id=self.final_editor.user_id,
                invited_by=self.eic.user_id,
                status="accepted",
            )
        )

        self.db.commit()

    def tearDown(self):
        ReviewerDownloadsTest.tearDown(self)

    def create_comment(self, manuscript_id, content):
        return self.client.post(
            f"/manuscripts/{manuscript_id}/general-comments",
            json={"content": content},
        )

    def get_comments(self, manuscript_id):
        return self.client.get(
            f"/manuscripts/{manuscript_id}/general-comments"
        )

    def test_accepted_initial_editor_can_create_and_read_comments(self):
        self.current = self.editor

        response = self.create_comment(self.mid, "Initial screening note.")

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["content"], "Initial screening note.")
        self.assertEqual(response.json()["visibility"], "staff")
        self.assertEqual(response.json()["author_name"], "Editor")

        listing = self.get_comments(self.mid)

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 1)
        self.assertEqual(
            listing.json()[0]["content"],
            "Initial screening note.",
        )

    def test_eic_can_access_staff_comments(self):
        self.current = self.eic

        response = self.create_comment(self.mid, "EIC internal note.")

        self.assertEqual(response.status_code, 201, response.text)

        listing = self.get_comments(self.mid)

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 1)

    def test_accepted_final_editor_can_access_comments(self):
        self.current = self.final_editor

        response = self.create_comment(self.mid, "Final editing note.")

        self.assertEqual(response.status_code, 201, response.text)

    def test_author_cannot_read_or_create_staff_comments(self):
        self.current = self.author

        self.assertEqual(self.get_comments(self.mid).status_code, 403)
        self.assertEqual(
            self.create_comment(self.mid, "Unauthorized note.").status_code,
            403,
        )

    def test_reviewer_cannot_read_or_create_staff_comments(self):
        self.current = self.reviewer

        self.assertEqual(self.get_comments(self.mid).status_code, 403)
        self.assertEqual(
            self.create_comment(self.mid, "Unauthorized reviewer note.").status_code,
            403,
        )

    def test_editor_cannot_access_uninvited_manuscript(self):
        self.current = self.editor

        self.assertEqual(
            self.get_comments(self.second_manuscript.manuscript_id).status_code,
            403,
        )

        self.assertEqual(
            self.create_comment(
                self.second_manuscript.manuscript_id,
                "Unauthorized cross-manuscript note.",
            ).status_code,
            403,
        )

    def test_comments_are_isolated_between_manuscripts(self):
        self.current = self.editor

        response = self.create_comment(self.mid, "First manuscript only.")
        self.assertEqual(response.status_code, 201)

        listing = self.get_comments(self.mid)
        self.assertEqual(len(listing.json()), 1)

        # The second manuscript has no comments.
        self.current = self.eic
        second_listing = self.get_comments(
            self.second_manuscript.manuscript_id
        )

        self.assertEqual(second_listing.status_code, 200)
        self.assertEqual(second_listing.json(), [])

    def test_blank_comment_is_rejected(self):
        self.current = self.editor

        response = self.create_comment(self.mid, "   ")

        self.assertEqual(response.status_code, 422)

    def test_missing_manuscript_returns_404(self):
        self.current = self.eic

        response = self.get_comments(999999)

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

"""Tests for private manuscript-scoped personal notes."""

import unittest
import importlib

from app import models
from tests.test_reviewer_download import ReviewerDownloadsTest


class PersonalNotesTests(unittest.TestCase):

    def setUp(self):
        self.fixture = ReviewerDownloadsTest(methodName="runTest")
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setUp()

        self.db = self.fixture.db
        self.client = self.fixture.client
        self.author = self.fixture.author
        self.editor = self.fixture.editor
        self.reviewer = self.fixture.reviewer
        self.mid = self.fixture.mid

        self.second_manuscript = models.Manuscript(
            title="Second Manuscript",
            abstract="Second Abstract",
            author_id=self.author.user_id,
            status="submitted",
        )
        self.db.add(self.second_manuscript)
        self.db.commit()

        self.second_mid = self.second_manuscript.manuscript_id

    def create_note(self, manuscript_id, content):
        return self.client.post(
            f"/manuscripts/{manuscript_id}/notes",
            json={"content": content},
        )

    def get_notes(self, manuscript_id):
        return self.client.get(
            f"/manuscripts/{manuscript_id}/notes"
        )

    def test_author_can_create_and_read_note(self):
        self.fixture.current = self.author

        response = self.create_note(self.mid, "My private note.")

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["content"], "My private note.")
        self.assertEqual(response.json()["user_id"], self.author.user_id)

        listing = self.get_notes(self.mid)

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 1)

    def test_author_can_update_note(self):
        self.fixture.current = self.author

        created = self.create_note(self.mid, "Original note.")
        note_id = created.json()["note_id"]

        response = self.client.put(
            f"/manuscripts/{self.mid}/notes/{note_id}",
            json={"content": "Updated note."},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["content"], "Updated note.")

    def test_author_can_delete_note(self):
        self.fixture.current = self.author

        created = self.create_note(self.mid, "Delete me.")
        note_id = created.json()["note_id"]

        response = self.client.delete(
            f"/manuscripts/{self.mid}/notes/{note_id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted"], True)
        self.assertEqual(self.get_notes(self.mid).json(), [])

    def test_notes_are_private_between_users(self):
        self.fixture.current = self.author
        response = self.create_note(self.mid, "Author only.")

        self.assertEqual(response.status_code, 201)

        self.fixture.current = self.editor
        listing = self.get_notes(self.mid)

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json(), [])

    def test_other_user_cannot_update_or_delete_note(self):
        self.fixture.current = self.author
        created = self.create_note(self.mid, "Private note.")
        note_id = created.json()["note_id"]

        self.fixture.current = self.editor

        update = self.client.put(
            f"/manuscripts/{self.mid}/notes/{note_id}",
            json={"content": "Unauthorized update."},
        )

        delete = self.client.delete(
            f"/manuscripts/{self.mid}/notes/{note_id}"
        )

        self.assertEqual(update.status_code, 404)
        self.assertEqual(delete.status_code, 404)

    def test_notes_are_isolated_between_manuscripts(self):
        self.fixture.current = self.author

        self.create_note(self.mid, "First manuscript.")
        self.create_note(self.second_mid, "Second manuscript.")

        first = self.get_notes(self.mid)
        second = self.get_notes(self.second_mid)

        self.assertEqual(len(first.json()), 1)
        self.assertEqual(len(second.json()), 1)
        self.assertEqual(
            first.json()[0]["content"],
            "First manuscript.",
        )
        self.assertEqual(
            second.json()[0]["content"],
            "Second manuscript.",
        )

    def test_reviewer_cannot_access_uninvited_manuscript(self):
        self.fixture.current = self.reviewer

        response = self.get_notes(self.mid)

        self.assertEqual(response.status_code, 403)

    def test_blank_note_is_rejected(self):
        self.fixture.current = self.author

        response = self.create_note(self.mid, "   ")

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

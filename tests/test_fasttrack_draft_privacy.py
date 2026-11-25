"""Independent draft ownership regressions using only a temporary database."""
import unittest

from app import models
from tests.test_reviewer_download import ReviewerDownloadsTest


class DraftPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ReviewerDownloadsTest(methodName="runTest")
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setUp()
        self.db = self.fixture.db
        self.client = self.fixture.client
        self.owner = self.fixture.author
        self.eic = models.User(name="Synthetic EIC", email="eic@example.invalid", password_hash="x", role="eic")
        self.other_author = models.User(name="Synthetic Other", email="other@example.invalid", password_hash="x", role="author")
        self.db.add_all([self.eic, self.other_author])
        self.db.flush()
        self.draft = models.Manuscript(title="Private synthetic draft", abstract="Synthetic", author_id=self.owner.user_id, status="draft", review_round=1)
        self.db.add(self.draft)
        self.db.flush()
        # A historical/stale assignment must not override draft ownership.
        self.db.add(models.InitialEditorInvitation(manuscript_id=self.draft.manuscript_id, editor_id=self.fixture.editor.user_id, invited_by=self.eic.user_id, status="accepted"))
        self.db.commit()
        self.mid = self.draft.manuscript_id

    def test_draft_denies_eic_and_other_users_without_leaking_title_or_existence(self):
        for actor in (self.eic, self.other_author, self.fixture.editor, self.fixture.reviewer):
            with self.subTest(role=actor.role):
                self.fixture.current = actor
                for method, path, payload in (
                    ("get", f"/manuscripts/{self.mid}/general-comments", None),
                    ("post", f"/manuscripts/{self.mid}/general-comments", {"content": "synthetic"}),
                    ("get", f"/manuscripts/{self.mid}/notes", None),
                    ("post", f"/manuscripts/{self.mid}/notes", {"content": "synthetic"}),
                    ("get", f"/formatting/manuscripts/{self.mid}", None),
                ):
                    response = getattr(self.client, method)(path, **({"json": payload} if payload else {}))
                    # Formatting rejects the Reviewer role before it looks up any manuscript.
                    expected = 403 if actor.role == "reviewer" and path.startswith("/formatting/") else 404
                    self.assertEqual(response.status_code, expected, response.text)
                    self.assertNotIn("Private synthetic draft", response.text)
        self.assertEqual(self.db.query(models.GeneralComment).filter_by(manuscript_id=self.mid).count(), 0)
        self.assertEqual(self.db.query(models.PersonalNote).filter_by(manuscript_id=self.mid).count(), 0)

    def test_owner_draft_notes_and_submitted_staff_workflows_remain_available(self):
        self.fixture.current = self.owner
        created = self.client.post(f"/manuscripts/{self.mid}/notes", json={"content": "Owner note"})
        self.assertEqual(created.status_code, 201, created.text)
        note_id = created.json()["note_id"]
        self.fixture.current = self.eic
        self.assertEqual(self.client.put(f"/manuscripts/{self.mid}/notes/{note_id}", json={"content": "Unauthorized"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/manuscripts/{self.mid}/notes/{note_id}").status_code, 404)
        self.fixture.current = self.owner
        self.assertEqual(self.client.get(f"/manuscripts/{self.mid}/notes").status_code, 200)
        self.assertEqual(self.client.get(f"/manuscripts/{self.mid}/notes").json()[0]["content"], "Owner note")
        self.assertEqual(self.client.put(f"/manuscripts/{self.mid}/notes/{note_id}", json={"content": "Updated"}).status_code, 200)
        self.assertEqual(self.client.delete(f"/manuscripts/{self.mid}/notes/{note_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/formatting/manuscripts/{self.mid}").status_code, 200)
        # General comments are staff-only even when the caller owns a draft.
        self.assertEqual(self.client.get(f"/manuscripts/{self.mid}/general-comments").status_code, 404)
        self.fixture.current = self.eic
        submitted = self.fixture.mid
        self.assertEqual(self.client.get(f"/formatting/manuscripts/{submitted}").status_code, 200)
        self.assertEqual(self.client.post(f"/manuscripts/{submitted}/general-comments", json={"content": "Staff note"}).status_code, 201)
        self.assertEqual(self.client.get(f"/manuscripts/{submitted}/notes").status_code, 200)
        self.fixture.current = self.fixture.editor
        self.assertEqual(self.client.get(f"/manuscripts/{submitted}/general-comments").status_code, 200)


if __name__ == "__main__":
    unittest.main()

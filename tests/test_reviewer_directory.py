"""Reviewer discovery against disposable SQLite and synthetic users."""
import unittest
from app import models
from tests import test_reviewer_download


class ReviewerDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.fx = test_reviewer_download.ReviewerDownloadsTest('test_first_round_binding_and_access')
        self.fx.setUp(); self.addCleanup(self.fx.tearDown)
        self.f = self.fx
        self.chief = models.User(name='Chief', email='chief@example.test', password_hash='x', role='eic')
        self.unassigned = models.User(name='Other editor', email='editor@example.test', password_hash='x', role='editor')
        self.f.db.add_all([self.chief, self.unassigned]); self.f.db.commit()

    def search(self, actor, term='reviewer'):
        self.f.current = actor
        return self.f.client.get(f'/assignments/manuscript/{self.f.mid}/reviewer-directory', params={'q': term})

    def test_authorized_search_name_email_and_minimal_fields(self):
        for actor in (self.chief, self.f.editor):
            for term in ('reviewer', 'REVIEWER@example'):
                with self.subTest(role=actor.role, term=term):
                    result = self.search(actor, term)
                    self.assertEqual(result.status_code, 200, result.text)
                    self.assertEqual(result.headers['cache-control'], 'no-store')
                    entry = next(x for x in result.json() if x['reviewer_id'] == self.f.reviewer.user_id)
                    self.assertEqual(set(entry), {'reviewer_id', 'name', 'email', 'invitation_status', 'assignment_status', 'selectable', 'profile'})
                    self.assertIsNone(entry['profile'])
                    self.assertTrue(entry['selectable'])
        self.assertEqual(self.search(self.chief, 'no-such-reviewer').json(), [])
        self.assertEqual(self.search(self.chief, '%%').json(), [])
        self.assertEqual(self.search(self.chief, ' ').status_code, 422)

    def test_unauthorized_or_wrong_context(self):
        for actor in (self.f.author, self.f.reviewer, self.unassigned):
            self.assertEqual(self.search(actor).status_code, 403)
        self.f.manuscript.status = 'draft'; self.f.db.commit()
        self.assertEqual(self.search(self.chief).status_code, 409)

    def test_search_results_are_bounded(self):
        for number in range(25):
            self.f.db.add(models.User(name=f'Synthetic Candidate {number}', email=f'candidate{number}@example.test', password_hash='x', role='reviewer'))
        self.f.db.commit()
        self.assertEqual(len(self.search(self.chief, 'candidate').json()), 20)

    def test_invitation_duplicate_and_round_status(self):
        f = self.f; f.current = self.chief
        payload = {'manuscript_id': f.mid, 'reviewer_id': f.reviewer.user_id, 'review_round': 1}
        first = f.client.post('/assignments/', json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        entry = next(x for x in self.search(self.chief).json() if x['reviewer_id'] == f.reviewer.user_id)
        self.assertFalse(entry['selectable']); self.assertEqual(entry['invitation_status'], 'pending')
        f.current = self.chief
        self.assertEqual(f.client.post('/assignments/', json=payload).status_code, 409)
        f.current = f.reviewer
        self.assertEqual(f.client.post(f"/assignments/{first.json()['assignment_id']}/invitation-response", json={'decision':'decline'}).status_code, 200)
        entry = next(x for x in self.search(self.chief).json() if x['reviewer_id'] == f.reviewer.user_id)
        self.assertFalse(entry['selectable']); self.assertEqual(entry['invitation_status'], 'declined')


if __name__ == '__main__': unittest.main()

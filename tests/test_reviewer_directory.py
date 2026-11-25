"""Reviewer discovery against disposable SQLite and synthetic users."""
import unittest
import sqlite3
import importlib
from sqlalchemy import select
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

    def install_revocations(self):
        from tests.test_batch73_acceptance_intents import install
        self.f.db.commit()
        install(self.f.db_path)
        importlib.import_module('migrations.029_intent_precision_failures').migrate(self.f.db_path)
        importlib.import_module('migrations.030_automatic_processing').migrate(self.f.db_path)
        importlib.import_module('migrations.031_editor_invitation_revocation').migrate(self.f.db_path)
        return self.f.db.scalar(select(models.InitialEditorInvitation.invitation_id).where(
            models.InitialEditorInvitation.manuscript_id == self.f.mid,
            models.InitialEditorInvitation.editor_id == self.f.editor.user_id,
            models.InitialEditorInvitation.status == 'accepted'))

    def revoke(self, invitation_id):
        self.f.db.commit()
        with sqlite3.connect(self.f.db_path) as raw:
            raw.execute('PRAGMA foreign_keys=ON')
            raw.execute('INSERT INTO editor_invitation_revocations VALUES (?,?,?,?,?,?,?)',
                        ('initial', invitation_id, self.f.mid, self.f.editor.user_id,
                         self.chief.user_id, 'Synthetic revocation', '2026-01-01T00:00:00.000000Z'))

    def test_revoked_editor_cannot_search_or_invite_but_eic_can(self):
        f = self.f
        f.select_single_blind_policy()
        invitation_id = self.install_revocations()
        self.assertEqual(self.search(f.editor).status_code, 200)
        payload = {'manuscript_id': f.mid, 'reviewer_id': f.other.user_id, 'review_round': 1}
        f.current = f.editor
        first = f.client.post('/assignments/', json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.revoke(invitation_id)
        self.assertEqual(self.search(f.editor).status_code, 403)
        payload['reviewer_id'] = f.reviewer.user_id
        f.current = f.editor
        self.assertEqual(f.client.post('/assignments/', json=payload).status_code, 403)
        self.assertEqual(self.search(self.chief).status_code, 200)
        f.current = self.chief
        result = f.client.post('/assignments/', json=payload)
        self.assertEqual(result.status_code, 201, result.text)

    def test_other_unrevoked_accepted_invitation_preserves_editor_access(self):
        f = self.f
        f.select_single_blind_policy()
        old = self.install_revocations()
        new = models.InitialEditorInvitation(manuscript_id=f.mid, editor_id=f.editor.user_id,
                                             invited_by=self.chief.user_id, status='accepted')
        f.db.add(new); f.db.commit()
        self.revoke(old)
        self.assertEqual(self.search(f.editor).status_code, 200)
        f.current = f.editor
        result = f.client.post('/assignments/', json={'manuscript_id': f.mid,
                                                      'reviewer_id': f.reviewer.user_id,
                                                      'review_round': 1})
        self.assertEqual(result.status_code, 201, result.text)
        self.revoke(new.invitation_id)
        self.assertEqual(self.search(f.editor).status_code, 403)

    def test_incomplete_revocation_schema_fails_closed_for_editor(self):
        f = self.f
        f.select_single_blind_policy()
        self.install_revocations()
        f.db.commit()
        with sqlite3.connect(f.db_path) as raw:
            raw.execute('DROP TRIGGER editor_invitation_revocations_no_update')
        self.assertEqual(self.search(f.editor).status_code, 503)
        f.current = f.editor
        payload = {'manuscript_id': f.mid, 'reviewer_id': f.reviewer.user_id, 'review_round': 1}
        self.assertEqual(f.client.post('/assignments/', json=payload).status_code, 503)
        self.assertEqual(self.search(self.chief).status_code, 200)

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
        f = self.f; f.select_single_blind_policy(); f.current = self.chief
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

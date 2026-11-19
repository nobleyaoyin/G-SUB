"""Evidence projection tests: all records live in disposable synthetic SQLite."""
import unittest
from app import models
from tests.test_reviewer_download import ReviewerDownloadsTest


class ProgressEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f=ReviewerDownloadsTest('runTest');self.f.setUp();self.addCleanup(self.f.tearDown)
        self.f.current=self.f.author

    def states(self):
        f=self.f;response=f.client.get(f'/manuscripts/{f.mid}/progress')
        self.assertEqual(response.status_code,200,response.text)
        return {item['name']:item['state'] for item in response.json()['stages']}

    def test_draft_and_submitted_distinguish_current_and_upcoming(self):
        f=self.f;f.manuscript.status='draft';f.db.commit();s=self.states()
        self.assertEqual(s['Submission'],'current');self.assertEqual(s['Initial Screening'],'pending')
        f.manuscript.status='submitted';f.db.commit();s=self.states()
        self.assertEqual(s['Submission'],'completed');self.assertEqual(s['Initial Screening'],'current')

    def test_missing_history_is_not_inferred_from_publication(self):
        f=self.f;f.manuscript.status='published';f.db.commit();s=self.states()
        self.assertEqual(s['Publication'],'current')
        for name in ('Submission','Initial Screening','Peer Review','EIC Decision','Author Agreement','Final Editing','Formatting'):
            self.assertEqual(s[name],'unknown',name)
        # This fixture contains a real matching synthetic approval and confirmation.
        self.assertEqual(s['Initial Editing'],'completed')

    def test_initial_screen_and_confirmation_require_matching_evidence(self):
        f=self.f;f.manuscript.status='initial_editing';f.db.commit();s=self.states()
        self.assertEqual(s['Initial Editing'],'current');self.assertEqual(s['Initial Screening'],'unknown')
        chief=models.User(name='Synthetic chief',email='evidence-chief@example.com',password_hash='x',role='eic');f.db.add(chief);f.db.flush()
        f.db.add(models.EICInitialScan(manuscript_id=f.mid,eic_id=chief.user_id,decision='pass',comments='Synthetic'));f.db.commit()
        self.assertEqual(self.states()['Initial Screening'],'completed')
        f.manuscript.status='ready_for_peer_review';f.db.commit();self.assertEqual(self.states()['Initial Editing'],'completed')
        confirmation=f.db.query(models.PreReviewConfirmation).filter_by(manuscript_id=f.mid).one()
        confirmation.decision='request_revision';f.db.commit();self.assertEqual(self.states()['Initial Editing'],'unknown')

    def test_prior_round_decision_does_not_complete_new_round(self):
        f=self.f;chief=models.User(name='Synthetic chief',email='round-chief@example.com',password_hash='x',role='eic');f.db.add(chief);f.db.flush()
        f.db.add(models.EICDecision(manuscript_id=f.mid,eic_id=chief.user_id,review_round=1,decision='revision_required',comments='Synthetic'))
        f.manuscript.status='revised';f.manuscript.review_round=2;f.db.commit();s=self.states()
        self.assertEqual(s['Peer Review'],'current');self.assertEqual(s['EIC Decision'],'pending')

    def test_revision_and_terminal_screening(self):
        f=self.f;f.manuscript.status='revision_required';f.db.commit();s=self.states()
        self.assertEqual(s['Peer Review'],'current');self.assertEqual(s['EIC Decision'],'pending')
        f.manuscript.status='initial_rejected';f.db.commit();s=self.states()
        self.assertEqual(s['Initial Screening'],'current');self.assertEqual(s['Peer Review'],'unknown')

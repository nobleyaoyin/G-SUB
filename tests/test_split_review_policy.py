"""HTTP checks using only the existing disposable two-reviewer fixture."""
from test_two_reviewer_policy import TwoReviewerPolicyTest
from app import models


class SplitReviewTest(TwoReviewerPolicyTest):
    def review_as(self, reviewer, assignment, recommendation):
        self.current = reviewer
        response = self.client.post('/reviews/', json={'assignment_id': assignment,
            'comments': 'Synthetic review', 'recommendation': recommendation})
        self.assertEqual(response.status_code, 201, response.text)

    def summary(self):
        self.current = self.chief
        response = self.client.get(f'/eic/manuscripts/{self.mid}/overview')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['split_review']

    def two_reviews(self, second):
        self.enable_new_submission()
        for reviewer, recommendation in [(self.reviewer, 'accept'), (self.other, second)]:
            aid = self.invite(reviewer)
            self.respond(reviewer, aid, 'accept')
            self.review_as(reviewer, aid, recommendation)

    def test_aligned_and_ambiguous_are_not_split(self):
        self.two_reviews('revision')
        self.assertEqual(self.summary()['classification'], 'ambiguous')
        self.current = self.chief
        self.assertEqual(self.client.post('/assignments/additional-reviewer', json={
            'manuscript_id': self.mid, 'reviewer_id': self.third.user_id, 'review_round': 1}).status_code, 409)

    def test_aligned(self):
        self.two_reviews('accept')
        self.assertEqual(self.summary()['classification'], 'aligned')

    def test_split_decline_replacement_and_review(self):
        self.two_reviews('reject')
        state = self.summary()
        self.assertEqual(state['classification'], 'split')
        self.assertTrue(state['can_invite_additional'])
        fourth = models.User(name='Fourth', email='fourth-split@example.test', password_hash='x', role='reviewer')
        self.db.add(fourth); self.db.commit()
        payload = {'manuscript_id': self.mid, 'reviewer_id': self.third.user_id, 'review_round': 1}
        self.current = self.author
        self.assertEqual(self.client.post('/assignments/additional-reviewer', json=payload).status_code, 403)
        self.current = self.chief
        result = self.client.post('/assignments/additional-reviewer', json=payload)
        self.assertEqual(result.status_code, 201, result.text)
        aid = result.json()['assignment_id']
        self.assertEqual(self.client.post('/assignments/additional-reviewer', json={**payload, 'reviewer_id': fourth.user_id}).status_code, 409)
        self.respond(self.third, aid, 'decline')
        self.assertTrue(self.summary()['can_invite_additional'])
        self.current = self.chief
        result = self.client.post('/assignments/additional-reviewer', json={**payload, 'reviewer_id': fourth.user_id})
        self.assertEqual(result.status_code, 201, result.text)
        aid = result.json()['assignment_id']
        self.respond(fourth, aid, 'accept')
        self.current = fourth
        self.assertEqual(self.client.get(f'/assignments/{aid}/download').content, b'%PDF-first')
        self.review_as(fourth, aid, 'revision')
        state = self.summary()
        self.assertEqual(state['eligible_completed'], 3)
        self.assertEqual(state['recommendations'], ['accept', 'reject', 'revision'])
        self.assertFalse(state['can_invite_additional'])
        self.assertEqual(self.decision('accept').status_code, 201)
        notifications = self.db.query(models.Notification).filter_by(user_id=self.chief.user_id).all()
        self.assertTrue(any(n.notification_type == 'review_submitted' for n in notifications))

    def test_pending_and_rounds_do_not_count(self):
        self.enable_new_submission()
        aid = self.invite(self.reviewer); self.respond(self.reviewer, aid, 'accept'); self.review_as(self.reviewer, aid, 'accept')
        self.invite(self.other)
        self.assertEqual(self.summary()['eligible_completed'], 1)
        self.manuscript.review_round = 2; self.db.commit()
        self.assertEqual(self.summary()['eligible_completed'], 0)

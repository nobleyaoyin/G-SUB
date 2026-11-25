"""Exercise the actual guarded additional-invitation route in a synthetic blind demo."""
import unittest
from tests import test_double_blind_demo_http as fixture
from tests.test_reviewer_artifact_binding import T
from tests import test_blind_demo_eic_http as single_fixture


class SplitBlindHTTPTest(unittest.TestCase):
    def test_single_blind_additional_reviewer(self):
        f = single_fixture.EICDemoHTTPTests('test_single_invitation_locks_and_notifies_atomically')
        f.setUp(); self.addCleanup(f.doCleanups); f.f.enable()
        for uid in (7, 8):
            f.db.execute("INSERT INTO users(user_id,name,email,password_hash,role,created_at) VALUES (?,?,?,'x','reviewer',?)", (uid, f'Synthetic {uid}', f'reviewer{uid}@example.test', T))
            f.db.execute("INSERT INTO account_lifecycle_events VALUES (?,?,1,NULL,'active',1,5,?,'initial_enrollment')", (f'active-{uid}', uid, T))
            f.db.execute("INSERT INTO account_lifecycle VALUES (?,'active',1,1,?)", (uid, f'active-{uid}'))
        f.db.commit()
        self.assertEqual(f.req('PUT', '/assignments/demo-policy/3', json={'mode':'single_blind'}).status_code, 200)
        for uid, recommendation in ((2, 'accept'), (7, 'reject')):
            result = f.req('POST', '/assignments/demo-invitations', json={'manuscript_id':3, 'reviewer_id':uid, 'review_round':1})
            self.assertEqual(result.status_code, 201, result.text); aid = result.json()['assignment_id']
            self.assertEqual(f.req('POST', f'/assignments/{aid}/invitation-response', user=uid, json={'decision':'accept'}).status_code, 200)
            self.assertEqual(f.req('POST', '/reviews/', user=uid, json={'assignment_id':aid, 'comments':'Synthetic', 'recommendation':recommendation}).status_code, 201)
        result = f.req('POST', '/assignments/additional-reviewer', json={'manuscript_id':3, 'reviewer_id':8, 'review_round':1})
        self.assertEqual(result.status_code, 201, result.text); aid = result.json()['assignment_id']
        self.assertEqual(f.req('POST', f'/assignments/{aid}/invitation-response', user=8, json={'decision':'accept'}).status_code, 200)
        self.assertEqual(f.req('GET', f'/assignments/{aid}/download', user=8).content, b'%PDF-synthetic')
        self.assertEqual(f.req('POST', '/reviews/', user=8, json={'assignment_id':aid, 'comments':'Synthetic', 'recommendation':'revision'}).status_code, 201)

    def test_double_blind_split_invitation_and_download(self):
        f = fixture.DoubleBlindDemoTests('test_full_http_flow')
        f.setUp()
        self.addCleanup(f.doCleanups)
        for uid in (7, 8):
            f.db.execute("INSERT INTO users(user_id,name,email,password_hash,role,created_at) VALUES (?,?,?,'x','reviewer',?)", (uid, f'Synthetic {uid}', f'reviewer{uid}@example.test', T))
            f.db.execute("INSERT INTO account_lifecycle_events VALUES (?,?,1,NULL,'active',1,5,?,'initial_enrollment')", (f'active-{uid}', uid, T))
            f.db.execute("INSERT INTO account_lifecycle VALUES (?,'active',1,1,?)", (uid, f'active-{uid}'))
        f.db.commit()
        for uid, recommendation in ((2, 'accept'), (7, 'reject')):
            result = f.f.req('POST', '/assignments/demo-invitations', json={'manuscript_id': 3, 'reviewer_id': uid, 'review_round': 1})
            self.assertEqual(result.status_code, 201, result.text)
            aid = result.json()['assignment_id']
            self.assertEqual(f.f.req('POST', f'/assignments/{aid}/invitation-response', user=uid, json={'decision':'accept'}).status_code, 200)
            self.assertEqual(f.f.req('POST', f'/assignments/demo-invitations/{aid}/bind-artifact').status_code, 200)
            result = f.f.req('POST', '/reviews/', user=uid, json={'assignment_id': aid, 'comments':'Synthetic', 'recommendation': recommendation})
            self.assertEqual(result.status_code, 201, result.text)
        result = f.f.req('POST', '/assignments/additional-reviewer', json={'manuscript_id':3, 'reviewer_id':8, 'review_round':1})
        self.assertEqual(result.status_code, 201, result.text)
        aid = result.json()['assignment_id']
        self.assertEqual(f.f.req('POST', f'/assignments/{aid}/invitation-response', user=8, json={'decision':'accept'}).status_code, 200)
        self.assertEqual(f.f.req('GET', f'/assignments/{aid}/download', user=8).status_code, 409)
        self.assertEqual(f.f.req('POST', f'/assignments/demo-invitations/{aid}/bind-artifact').status_code, 200)
        result = f.f.req('GET', f'/assignments/{aid}/download', user=8)
        self.assertEqual(result.content, b'Anonymous synthetic text')
        self.assertEqual(f.f.req('GET', '/manuscripts/3/download', user=8).status_code, 403)
        self.assertEqual(f.f.req('POST', '/reviews/', user=8, json={'assignment_id':aid, 'comments':'Synthetic', 'recommendation':'revision'}).status_code, 201)

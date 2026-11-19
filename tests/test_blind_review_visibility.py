"""Direct visibility and JSON tests using disposable SQLite and synthetic users."""
from contextlib import contextmanager
import json
import sqlite3
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app import models
from app import blind_policy_store as store
from app import blind_review_visibility as visibility
from tests import test_blind_policy_store


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        self.fx = test_blind_policy_store.BlindPolicyTests('test_select_change_stale_and_invalid')
        self.fx.setUp(); self.addCleanup(self.fx.doCleanups)
        self.db = self.fx.migrated()
        self.mid = self.fx.mid; self.eic = self.fx.actor
        self.author = self.fx.f.author.user_id; self.editor = self.fx.f.editor.user_id
        self.reviewer = self.fx.f.reviewer.user_id; self.other = self.fx.f.other.user_id
        self.formatter = models.User(name='Synthetic Formatter', email='formatter@example.test', password_hash='x', role='formatter')
        self.unassigned_editor = models.User(name='Other Editor', email='editor2@example.test', password_hash='x', role='editor')
        self.fx.f.db.add_all([self.formatter, self.unassigned_editor]); self.fx.f.db.commit()
        self.formatter_id = self.formatter.user_id; self.unassigned_editor_id = self.unassigned_editor.user_id

    def activate(self, mode='double_blind'):
        self.fx.write(self.db, store.select_mode, self.mid, mode, self.eic)
        aid = self.fx.invitation(self.db)
        self.db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=?", (aid,)); self.db.commit()
        self.fx.write(self.db, store.lock_mode, self.mid, aid, self.eic, 1)
        return aid

    @contextmanager
    def snapshot(self):
        self.db.execute('BEGIN')
        try: yield self.db
        finally: self.db.rollback()

    def test_double_blind_is_explicit_minimal_json(self):
        self.activate()
        with self.snapshot() as db:
            dto = visibility.reviewer_manuscript_dto(db, self.mid, self.reviewer)
            parsed = json.loads(dto.model_dump_json())
            self.assertEqual(parsed, {'manuscript_id': self.mid, 'review_round': 1})
            self.assertFalse(visibility.resolve_visibility(db, self.mid, self.reviewer).can_view_author_identity)
            for forbidden in ('author_id', 'author', 'email', 'reviewer_id', 'assignment_id', 'assigned_by', 'abstract', 'title'):
                self.assertNotIn(forbidden, parsed)

    def test_single_blind_allows_author_identity(self):
        self.activate('single_blind')
        with self.snapshot() as db:
            parsed = json.loads(visibility.reviewer_manuscript_dto(db, self.mid, self.reviewer).model_dump_json())
            self.assertEqual(parsed, {'manuscript_id': self.mid, 'review_round': 1, 'author_id': self.author, 'author_name': self.fx.f.author.name})
            resolved = visibility.resolve_visibility(db, self.mid, self.reviewer)
            self.assertTrue(resolved.can_view_author_identity); self.assertFalse(resolved.can_view_reviewer_identities)

    def test_unclassified_and_unlocked_fail_closed(self):
        with self.snapshot() as db:
            self.assertEqual(visibility.resolve_visibility(db, self.mid, self.author).mode, 'legacy')
            with self.assertRaises(visibility.VisibilityError): visibility.reviewer_manuscript_dto(db, self.mid, self.author)
        self.fx.write(self.db, store.select_mode, self.mid, 'double_blind', self.eic)
        aid = self.fx.invitation(self.db)
        self.db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=?", (aid,)); self.db.commit()
        with self.snapshot() as db:
            self.assertFalse(visibility.resolve_visibility(db, self.mid, self.reviewer).policy_locked)
            with self.assertRaises(visibility.VisibilityError): visibility.reviewer_manuscript_dto(db, self.mid, self.reviewer)

    def test_missing_incompatible_and_invalid_policy(self):
        with self.snapshot() as db, patch.object(visibility, 'read_policy', return_value={'mode':'invented','locked_at':'x'}):
            with self.assertRaises(visibility.VisibilityError): visibility.resolve_visibility(db, self.mid, self.author)
        self.db.execute('DROP TRIGGER blind_events_no_delete'); self.db.commit()
        with self.snapshot() as db:
            with self.assertRaises(visibility.VisibilityError): visibility.resolve_visibility(db, self.mid, self.author)

    def test_legacy_accepted_reviewer_is_never_given_blind_dto(self):
        aid = self.fx.invitation(self.db)
        self.db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=?", (aid,)); self.db.commit()
        with self.snapshot() as db:
            self.assertEqual(visibility.resolve_visibility(db, self.mid, self.reviewer).mode, 'legacy')
            with self.assertRaises(visibility.VisibilityError): visibility.reviewer_manuscript_dto(db, self.mid, self.reviewer)

    def test_nonexistent_schema_fails_closed(self):
        self.db.execute('DROP TRIGGER blind_events_no_delete'); self.db.execute('DROP TRIGGER blind_events_no_update')
        self.db.execute('DROP TRIGGER blind_events_invitation_match'); self.db.execute('DROP TABLE blind_policies'); self.db.execute('DROP TABLE blind_policy_events')
        self.db.execute("DELETE FROM schema_migrations WHERE migration_id='011_blind_review_policy'"); self.db.commit()
        with self.snapshot() as db:
            with self.assertRaises(visibility.VisibilityError): visibility.resolve_visibility(db, self.mid, self.author)

    def test_other_reviewer_and_other_manuscript_denied(self):
        self.activate()
        self.db.execute("INSERT INTO manuscripts(title,abstract,author_id,status,review_round,created_at) VALUES ('Other','Abstract',?,'ready_for_peer_review',1,'2026-01-01')", (self.author,))
        other_mid = self.db.execute('SELECT last_insert_rowid()').fetchone()[0]; self.db.commit()
        with self.snapshot() as db:
            for mid, actor in ((self.mid, self.other), (other_mid, self.reviewer)):
                with self.assertRaises(visibility.VisibilityError): visibility.reviewer_manuscript_dto(db, mid, actor)

    def test_other_round_pending_declined_and_old_assignment_denied(self):
        aid = self.activate()
        for status in ('pending', 'declined'):
            self.db.execute('UPDATE reviewer_invitations SET status=? WHERE assignment_id=?', (status, aid)); self.db.commit()
            with self.snapshot() as db:
                with self.assertRaises(visibility.VisibilityError): visibility.reviewer_manuscript_dto(db, self.mid, self.reviewer)
        self.db.execute("UPDATE reviewer_invitations SET status='accepted' WHERE assignment_id=?", (aid,))
        self.db.execute('UPDATE manuscripts SET review_round=2 WHERE manuscript_id=?', (self.mid,)); self.db.commit()
        with self.snapshot() as db:
            with self.assertRaises(visibility.VisibilityError): visibility.reviewer_manuscript_dto(db, self.mid, self.reviewer)

    def test_author_editor_eic_and_unauthorized_editor(self):
        self.activate()
        with self.snapshot() as db:
            author = visibility.resolve_visibility(db, self.mid, self.author)
            self.assertEqual(author.audience, 'author'); self.assertFalse(author.can_view_reviewer_identities)
            with self.assertRaises(visibility.VisibilityError): visibility.reviewer_manuscript_dto(db, self.mid, self.author)
            for actor, audience in ((self.editor, 'editor'), (self.eic, 'eic')):
                view = visibility.resolve_visibility(db, self.mid, actor)
                self.assertEqual(view.audience, audience); self.assertTrue(view.can_view_author_identity); self.assertTrue(view.can_view_reviewer_identities)
            with self.assertRaises(visibility.VisibilityError): visibility.resolve_visibility(db, self.mid, self.unassigned_editor_id)

    def test_formatter_requires_accepted_assignment_and_has_no_identity_flags(self):
        self.activate()
        with self.snapshot() as db:
            with self.assertRaises(visibility.VisibilityError): visibility.resolve_visibility(db, self.mid, self.formatter_id)
        final = models.FinalEditingSubmission(manuscript_id=self.mid, editor_id=self.editor, file_path='synthetic.pdf', comments='Synthetic', status='author_approved')
        self.fx.f.db.add(final); self.fx.f.db.commit()
        self.db.execute("INSERT INTO formatter_invitations(manuscript_id,formatter_id,invited_by,final_submission_id,status,invited_at) VALUES (?,?,?,?,'accepted','2026-01-01')", (self.mid, self.formatter_id, self.eic, final.submission_id)); self.db.commit()
        with self.snapshot() as db:
            result = visibility.resolve_visibility(db, self.mid, self.formatter_id)
            self.assertEqual(result.audience, 'formatter'); self.assertFalse(result.can_view_author_identity); self.assertFalse(result.can_view_reviewer_identities)
            with self.assertRaises(visibility.VisibilityError): visibility.reviewer_manuscript_dto(db, self.mid, self.formatter_id)

    def test_editor_with_formatting_only_has_formatter_visibility(self):
        self.activate()

        final = models.FinalEditingSubmission(
            manuscript_id=self.mid,
            editor_id=self.editor,
            file_path='synthetic.pdf',
            comments='Synthetic',
            status='author_approved',
        )
        self.fx.f.db.add(final)
        self.fx.f.db.commit()

        self.db.execute(
            "INSERT INTO formatter_invitations(manuscript_id,formatter_id,invited_by,final_submission_id,status,invited_at) VALUES (?,?,?,?,'pending','2026-01-01')",
            (self.mid, self.unassigned_editor_id, self.eic, final.submission_id),
        )
        self.db.commit()

        with self.snapshot() as db:
            with self.assertRaises(visibility.VisibilityError):
                visibility.resolve_visibility(db, self.mid, self.unassigned_editor_id)

        self.db.execute(
            "UPDATE formatter_invitations SET status='accepted' WHERE manuscript_id=? AND formatter_id=?",
            (self.mid, self.unassigned_editor_id),
        )
        self.db.commit()

        with self.snapshot() as db:
            result = visibility.resolve_visibility(
                db, self.mid, self.unassigned_editor_id
            )
            self.assertEqual(result.audience, 'formatter')
            self.assertFalse(result.can_view_author_identity)
            self.assertFalse(result.can_view_reviewer_identities)

            with self.assertRaises(visibility.VisibilityError):
                visibility.reviewer_manuscript_dto(
                    db, self.mid, self.unassigned_editor_id
                )

            existing_editor = visibility.resolve_visibility(
                db, self.mid, self.editor
            )
            self.assertEqual(existing_editor.audience, 'editor')
            self.assertTrue(existing_editor.can_view_author_identity)
            self.assertTrue(existing_editor.can_view_reviewer_identities)

    def test_dto_rejects_unexpected_nested_fields(self):
        with self.assertRaises(ValidationError):
            visibility.ReviewerDoubleBlindDTO(manuscript_id=self.mid, review_round=1, author={'name':'Synthetic'})

    def test_explicit_transaction_required_and_bad_ids(self):
        with self.assertRaises(visibility.VisibilityError): visibility.resolve_visibility(self.db, self.mid, self.author)
        with self.snapshot() as db:
            for actor in (True, 0, -1, 999999):
                with self.assertRaises(visibility.VisibilityError): visibility.resolve_visibility(db, self.mid, actor)


if __name__ == '__main__': unittest.main()

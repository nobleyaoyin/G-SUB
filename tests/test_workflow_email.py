"""Workflow email tests use fake SMTP clients and isolated SQLite data only."""
import os
import unittest
from unittest.mock import patch

from app.config import load_smtp_settings
from app.email.service import notify_workflow_email
from app.email.templates import render_template


class FakeSMTP:
    instances = []

    def __init__(self, host, port, **kwargs):
        self.host = host
        self.port = port
        self.kwargs = kwargs
        self.message = None
        self.tls = False
        self.credentials = None
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def ehlo(self):
        return 250, b"ok"

    def starttls(self, **_):
        self.tls = True
        return 220, b"ready"

    def login(self, username, password):
        self.credentials = (username, password)
        return 235, b"ok"

    def send_message(self, message):
        self.message = message
        return {}


class WorkflowEmailServiceTests(unittest.TestCase):
    def setUp(self):
        FakeSMTP.instances.clear()

    def test_templates_validate_context_and_avoid_blind_metadata(self):
        invitation = render_template(
            "reviewer_invitation",
            "v1",
            "reviewer@example.com",
            {"manuscript_id": 12},
        )
        self.assertIn("12", invitation.subject)
        self.assertNotIn("Title", invitation.text_body)
        self.assertIn("revision has been requested", render_template(
            "revision_requested", "v1", "author@example.com", {"manuscript_id": 12}
        ).text_body)
        with self.assertRaisesRegex(ValueError, "Invalid review round"):
            render_template(
                "review_submitted",
                "v1",
                "editor@example.com",
                {"manuscript_id": 12, "review_round": 0},
            )
        with self.assertRaisesRegex(ValueError, "Invalid manuscript decision"):
            render_template(
                "manuscript_decision",
                "v1",
                "author@example.com",
                {"manuscript_id": 12, "decision": "pending"},
            )

    def test_smtp_starttls_auth_and_sender_configuration(self):
        environment = {
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "synthetic-user",
            "SMTP_PASSWORD": "synthetic-password",
            "SMTP_FROM_EMAIL": "notifications@example.com",
            "SMTP_FROM_NAME": "G-Sub Test",
            "SMTP_USE_TLS": "true",
            "SMTP_USE_SSL": "false",
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "app.email.service.smtplib.SMTP", FakeSMTP
        ), patch("app.email.service.load_smtp_settings", load_smtp_settings):
            sent = notify_workflow_email(
                "manuscript_submitted",
                "author@example.com",
                {"manuscript_id": 17},
            )

        self.assertTrue(sent)
        client = FakeSMTP.instances[0]
        self.assertEqual((client.host, client.port), ("smtp.example.test", 587))
        self.assertTrue(client.tls)
        self.assertEqual(client.credentials, ("synthetic-user", "synthetic-password"))
        self.assertEqual(client.message["To"], "author@example.com")
        self.assertEqual(client.message["From"], "G-Sub Test <notifications@example.com>")
        self.assertIn("17", client.message["Subject"])

    def test_implicit_ssl(self):
        environment = {
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "465",
            "SMTP_FROM_EMAIL": "notifications@example.com",
            "SMTP_USE_TLS": "false",
            "SMTP_USE_SSL": "true",
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "app.email.service.smtplib.SMTP_SSL", FakeSMTP
        ), patch("app.email.service.load_smtp_settings", load_smtp_settings):
            sent = notify_workflow_email(
                "reviewer_invitation",
                "reviewer@example.com",
                {"manuscript_id": 17},
            )

        self.assertTrue(sent)
        self.assertEqual(FakeSMTP.instances[0].port, 465)
        self.assertFalse(FakeSMTP.instances[0].tls)
        self.assertIn("17", FakeSMTP.instances[0].message["Subject"])

    def test_unconfigured_and_failed_delivery_are_nonfatal(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "app.email.service.smtplib.SMTP"
        ) as smtp:
            self.assertFalse(notify_workflow_email(
                "manuscript_submitted",
                "author@example.com",
                {"manuscript_id": 17},
            ))
        smtp.assert_not_called()

        environment = {
            "SMTP_HOST": "smtp.example.test",
            "SMTP_FROM_EMAIL": "notifications@example.com",
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "app.email.service.smtplib.SMTP", side_effect=RuntimeError("synthetic")
        ), patch(
            "app.email.service.load_smtp_settings", load_smtp_settings
        ), self.assertLogs("app.email.service", level="WARNING") as logs:
            self.assertFalse(notify_workflow_email(
                "manuscript_submitted",
                "author@example.com",
                {"manuscript_id": 17},
            ))
        self.assertIn("workflow_email_failed", logs.output[0])
        self.assertNotIn("synthetic", logs.output[0])

    def test_invalid_smtp_configuration_is_nonfatal_and_does_not_connect(self):
        for invalid in (
            {"SMTP_PORT": "invalid"},
            {"SMTP_USE_TLS": "invalid"},
            {"SMTP_USE_TLS": "true", "SMTP_USE_SSL": "true"},
            {"SMTP_USERNAME": "synthetic-user"},
            {"SMTP_FROM_EMAIL": ""},
        ):
            env = {"SMTP_HOST": "smtp.example.test", "SMTP_FROM_EMAIL": "notifications@example.com", **invalid}
            with self.subTest(invalid=list(invalid)), patch.dict(os.environ, env, clear=True), \
                 patch("app.email.service.load_smtp_settings", load_smtp_settings), \
                 patch("app.email.service.smtplib.SMTP") as smtp, \
                 patch("app.email.service.smtplib.SMTP_SSL") as smtp_ssl:
                self.assertFalse(notify_workflow_email("manuscript_submitted", "author@example.com", {"manuscript_id": 17}))
                smtp.assert_not_called()
                smtp_ssl.assert_not_called()


class WorkflowEmailIntegrationTests(unittest.TestCase):
    def setUp(self):
        from tests.test_reviewer_download import ReviewerDownloadsTest

        self.fixture = ReviewerDownloadsTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        for name in (
            "author", "client", "db", "editor", "manuscript",
            "mid", "other", "reviewer", "write", "select_single_blind_policy",
            "assign",
        ):
            setattr(self, name, getattr(self.fixture, name))

    @property
    def current(self):
        return self.fixture.current

    @current.setter
    def current(self, user):
        self.fixture.current = user

    def test_submission_email_is_after_commit_and_failure_is_nonfatal(self):
        from app.routers import manuscripts

        self.manuscript.status = "draft"
        self.manuscript.file_path = self.write(
            f"uploads/manuscripts/{self.mid}/draft.txt",
            b"Synthetic manuscript content.\n",
        )
        self.db.commit()
        self.current = self.author

        def fake_smtp(*_, **__):
            raise RuntimeError("synthetic SMTP failure")

        with patch.dict(os.environ, {
            "SMTP_HOST": "smtp.example.test",
            "SMTP_FROM_EMAIL": "notifications@example.com",
        }, clear=True), patch(
            "app.email.service.smtplib.SMTP", side_effect=fake_smtp
        ), patch(
            "app.email.service.load_smtp_settings", load_smtp_settings
        ):
            response = self.client.post(f"/manuscripts/{self.mid}/submit")

        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.get(manuscripts.Manuscript, self.mid).status, "submitted")

    def test_submission_notifies_owner_once_after_visible_commit(self):
        from app.routers import manuscripts

        self.manuscript.status = "draft"
        self.manuscript.file_path = self.write(
            f"uploads/manuscripts/{self.mid}/draft.txt", b"Synthetic manuscript content.\n"
        )
        self.db.commit()
        self.current = self.author

        def check_committed(event, recipient, context):
            with self.fixture.Session() as independent:
                self.assertEqual(independent.get(manuscripts.Manuscript, self.mid).status, "submitted")
            self.assertEqual((event, recipient), ("manuscript_submitted", self.author.email))
            self.assertEqual(context, {"manuscript_id": self.mid})

        with patch.object(manuscripts, "notify_workflow_email", side_effect=check_committed) as send:
            response = self.client.post(f"/manuscripts/{self.mid}/submit")
        self.assertEqual(response.status_code, 200, response.text)
        send.assert_called_once()

    def test_assignment_review_and_decision_emails_use_committed_recipients(self):
        from app.routers import assignments, eic, reviews

        self.select_single_blind_policy()
        with (
            patch.object(assignments, "notify_workflow_email") as assignment_email,
            patch.object(reviews, "notify_workflow_email") as review_email,
            patch.object(eic, "notify_workflow_email") as decision_email,
        ):
            assignment_id = self.assign(self.reviewer, 1).json()["assignment_id"]
            self.assertEqual(assignment_email.call_args.args[:2], (
                "reviewer_invitation", self.reviewer.email
            ))
            self.current = self.reviewer
            review_response = self.client.post(
                "/reviews/",
                json={
                    "assignment_id": assignment_id,
                    "comments": "Synthetic review",
                    "recommendation": "accept",
                },
            )
            self.assertEqual(review_response.status_code, 201, review_response.text)
            self.assertEqual(review_email.call_args.args[:2], (
                "review_submitted", self.editor.email
            ))

            second_assignment = self.assign(self.other, 1).json()["assignment_id"]
            self.current = self.other
            second_review = self.client.post(
                "/reviews/",
                json={
                    "assignment_id": second_assignment,
                    "comments": "Synthetic review",
                    "recommendation": "accept",
                },
            )
            self.assertEqual(second_review.status_code, 201, second_review.text)

            chief = self.db.query(assignments.User).filter_by(role="eic").first()
            self.current = chief
            decision = self.client.post(
                f"/eic/manuscripts/{self.mid}/decision",
                json={"decision": "accept", "comments": "Synthetic decision"},
            )
            self.assertEqual(decision.status_code, 201, decision.text)
            self.assertEqual(decision_email.call_args.args[:2], (
                "manuscript_decision", self.author.email
            ))
            self.assertEqual(
                decision_email.call_args.args[2]["decision"], "accepted"
            )

    def test_initial_scan_revision_request_notifies_author_after_commit(self):
        from app import models
        from app.routers import eic, manuscripts

        self.manuscript.status = "submitted"
        self.manuscript.file_path = self.write(
            f"uploads/manuscripts/{self.mid}/initial.pdf",
            b"%PDF-synthetic",
        )
        chief = models.User(
            name="Synthetic EIC",
            email="chief@example.com",
            password_hash="x",
            role="eic",
        )
        self.db.add(chief)
        self.db.commit()
        self.current = chief
        with patch.object(eic, "notify_workflow_email") as send_email:
            response = self.client.post(
                f"/eic/manuscripts/{self.mid}/initial-scan",
                json={
                    "decision": "revision_required",
                    "comments": "Synthetic revision request",
                },
            )

        self.assertEqual(response.status_code, 201, response.text)
        self.db.expire_all()
        self.assertEqual(
            self.db.get(manuscripts.Manuscript, self.mid).status,
            "initial_revision_required",
        )
        self.assertEqual(send_email.call_args.args[:2], (
            "revision_requested", self.author.email
        ))

    def test_initial_scan_rejection_notifies_author_only(self):
        from app import models
        from app.routers import eic

        self.manuscript.status = "submitted"
        self.manuscript.file_path = self.write(
            f"uploads/manuscripts/{self.mid}/initial.pdf", b"%PDF-synthetic"
        )
        chief = models.User(name="Synthetic EIC", email="chief@example.com", password_hash="x", role="eic")
        self.db.add(chief)
        self.db.commit()
        self.current = chief
        with patch.object(eic, "notify_workflow_email") as send:
            response = self.client.post(
                f"/eic/manuscripts/{self.mid}/initial-scan",
                json={"decision": "reject", "comments": "Synthetic decision"},
            )
        self.assertEqual(response.status_code, 201, response.text)
        send.assert_called_once_with(
            "manuscript_decision", self.author.email,
            {"manuscript_id": self.mid, "decision": "rejected"},
        )


if __name__ == "__main__":
    unittest.main()

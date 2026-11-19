"""Isolated HTTP tests for EIC advisory AI report access."""

import importlib
import unittest

from app import models
from tests.test_ai_submission_http import AISubmissionHTTPTests


class EICAIPrescreeningHTTPTests(unittest.TestCase):

    def setUp(self):
        self.base = AISubmissionHTTPTests(methodName="runTest")
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()

        self.fixture = self.base.fixture
        self.mid = self.fixture.mid
        self.url = f"/eic/manuscripts/{self.mid}/ai-prescreening"

        self.eic = models.User(
            name="Synthetic EIC",
            email="synthetic-eic@example.com",
            password_hash="x",
            role="eic",
        )

        self.fixture.db.add(self.eic)
        self.fixture.db.commit()

    def get_as(self, user, url=None):
        self.fixture.current = user
        return self.fixture.client.get(url or self.url)

    def test_eic_without_ai_tables(self):
        response = self.get_as(self.eic)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {
            "manuscript_id": self.mid,
            "advisory_only": True,
            "submissions": [],
        })

    def test_other_roles_denied(self):
        for user in [
            self.fixture.author,
            self.fixture.editor,
            self.fixture.reviewer,
        ]:
            with self.subTest(role=user.role):
                response = self.get_as(user)
                self.assertEqual(response.status_code, 403, response.text)

    def test_draft_hidden(self):
        self.fixture.manuscript.status = "draft"
        self.fixture.db.commit()

        response = self.get_as(self.eic)
        self.assertEqual(response.status_code, 404, response.text)

    def test_nonexistent_manuscript(self):
        response = self.get_as(
            self.eic,
            "/eic/manuscripts/999999999/ai-prescreening",
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_eic_with_ai_tables(self):
        self.base.install_ai_schema()

        response = self.get_as(self.eic)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["submissions"], [])


    def test_pending_and_completed_reports(self):
        import json
        from sqlalchemy import text

        self.base.install_ai_schema()

        db = self.fixture.db
        timestamp = "2026-11-14T00:00:00Z"

        for sequence, status in [(1, "completed"), (2, "pending")]:
            snapshot_id = f"synthetic-snapshot-{sequence}"
            job_id = f"synthetic-job-{sequence}"

            db.execute(text("""
                INSERT INTO manuscript_submission_snapshots (
                    snapshot_id, manuscript_id, submitted_by,
                    submission_kind, review_round,
                    submission_sequence, file_ref, file_sha256,
                    file_format, submitted_at
                ) VALUES (
                    :snapshot_id, :manuscript_id, :submitted_by,
                    :kind, :round, :sequence, :file_ref,
                    :sha256, 'txt', :timestamp
                )
            """), {
                "snapshot_id": snapshot_id,
                "manuscript_id": self.mid,
                "submitted_by": self.fixture.author.user_id,
                "kind": "initial" if sequence == 1 else "peer_revision",
                "round": sequence,
                "sequence": sequence,
                "file_ref": f"synthetic/{sequence}.txt",
                "sha256": "a" * 64,
                "timestamp": timestamp,
            })

            db.execute(text("""
                INSERT INTO ai_prescreening_jobs (
                    job_id, snapshot_id, status,
                    created_at, updated_at
                ) VALUES (
                    :job_id, :snapshot_id, :status,
                    :timestamp, :timestamp
                )
            """), {
                "job_id": job_id,
                "snapshot_id": snapshot_id,
                "status": status,
                "timestamp": timestamp,
            })

        report = {
            "status": "completed",
            "engine": "local_rules_v1",
            "advisory_only": True,
            "format": "txt",
            "word_count": 120,
            "sections_detected": ["abstract", "introduction"],
            "findings": [{
                "category": "structure",
                "code": "missing_methods",
                "severity": "warning",
                "message": "Methods section not detected.",
            }],
        }

        db.execute(text("""
            INSERT INTO ai_prescreening_reports (
                report_id, snapshot_id, job_id,
                engine, findings_json, created_at
            ) VALUES (
                'synthetic-report-1',
                'synthetic-snapshot-1',
                'synthetic-job-1',
                'local_rules_v1',
                :findings_json,
                :timestamp
            )
        """), {
            "findings_json": json.dumps(report),
            "timestamp": timestamp,
        })

        db.commit()

        response = self.get_as(self.eic)
        self.assertEqual(response.status_code, 200, response.text)

        payload = response.json()
        self.assertTrue(payload["advisory_only"])

        submissions = payload["submissions"]
        self.assertEqual(len(submissions), 2)
        self.assertEqual(
            [item["submission_sequence"] for item in submissions],
            [2, 1],
        )

        self.assertEqual(submissions[0]["status"], "pending")
        self.assertIsNone(submissions[0]["analysis"])

        self.assertEqual(submissions[1]["status"], "completed")
        analysis = submissions[1]["analysis"]

        self.assertEqual(analysis["engine"], "local_rules_v1")
        self.assertEqual(analysis["word_count"], 120)
        self.assertEqual(
            analysis["sections_detected"],
            ["abstract", "introduction"],
        )
        self.assertEqual(
            analysis["findings"][0]["code"],
            "missing_methods",
        )
        self.assertTrue(analysis["advisory_only"])

        self.assertEqual(
            self.get_as(self.fixture.author).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()

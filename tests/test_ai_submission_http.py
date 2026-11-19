"""Isolated HTTP regression tests for AI submission integration."""

import hashlib
import importlib
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import models
import app.routers.manuscripts as manuscripts
from tests.test_reviewer_download import ReviewerDownloadsTest


class AISubmissionHTTPTests(unittest.TestCase):
    """Exercise submission APIs using disposable SQLite fixtures."""

    def setUp(self):
        self.fixture = ReviewerDownloadsTest(methodName="runTest")
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setUp()

        self.root = Path(self.fixture.temp.name).resolve()
        self.db_path = Path(self.fixture.db_path).resolve()

        self.assertTrue(self.db_path.is_relative_to(self.root))
        self.assertEqual(self.db_path.name, "test.sqlite")

        self.fixture.db.close()
        self.fixture.engine.dispose()

        importlib.import_module(
            "migrations.014_online_document_versions"
        ).migrate(self.db_path)

        self.fixture.db = self.fixture.Session()
        self.fixture.manuscript = self.fixture.db.get(
            models.Manuscript, self.fixture.mid
        )
        self.fixture.current = self.fixture.author

    def install_ai_schema(self):
        self.fixture.db.close()
        self.fixture.engine.dispose()

        importlib.import_module(
            "migrations.017_ai_prescreening"
        ).migrate(self.db_path)

        self.fixture.db = self.fixture.Session()
        self.fixture.manuscript = self.fixture.db.get(
            models.Manuscript, self.fixture.mid
        )

    def prepare_manuscript(self, status, filename, content):
        relative_path = self.fixture.write(
            f"uploads/manuscripts/{self.fixture.mid}/{filename}",
            content,
        )

        manuscript = self.fixture.manuscript
        manuscript.status = status
        manuscript.review_round = 1
        manuscript.file_path = relative_path
        manuscript.title = "Synthetic AI Test"
        manuscript.abstract = "Synthetic abstract"
        self.fixture.db.commit()

        return relative_path

    def assert_snapshot(self, kind, round_number, path, content):
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT submission_kind, review_round,
                       submission_sequence, file_ref, file_sha256
                FROM manuscript_submission_snapshots
                WHERE manuscript_id=?
                """,
                (self.fixture.mid,),
            ).fetchall()

            self.assertEqual(len(rows), 1)
            self.assertEqual(
                rows[0],
                (
                    kind,
                    round_number,
                    1,
                    path,
                    hashlib.sha256(content).hexdigest(),
                ),
            )

            jobs = connection.execute(
                """
                SELECT j.status
                FROM ai_prescreening_jobs j
                JOIN manuscript_submission_snapshots s
                  ON j.snapshot_id=s.snapshot_id
                WHERE s.manuscript_id=?
                """,
                (self.fixture.mid,),
            ).fetchall()

            self.assertEqual(jobs, [("pending",)])

    def test_initial_submission(self):
        self.install_ai_schema()

        content = b"Synthetic initial manuscript.\n"
        path = self.prepare_manuscript(
            "draft", "initial.txt", content
        )

        with patch.object(
            manuscripts, "AI_PRESCREENING_ENABLED", True
        ):
            response = self.fixture.client.post(
                f"/manuscripts/{self.fixture.mid}/submit"
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.fixture.db.expire_all()

        manuscript = self.fixture.db.get(
            models.Manuscript, self.fixture.mid
        )
        self.assertEqual(manuscript.status, "submitted")
        self.assert_snapshot("initial", 1, path, content)

    def test_initial_revision(self):
        self.install_ai_schema()

        eic = models.User(
            name="Synthetic EIC",
            email="synthetic-eic@example.com",
            password_hash="x",
            role="eic",
        )
        self.fixture.db.add(eic)
        self.fixture.db.flush()

        scan_time = datetime.now(timezone.utc) - timedelta(minutes=5)

        self.fixture.db.add(
            models.EICInitialScan(
                manuscript_id=self.fixture.mid,
                eic_id=eic.user_id,
                decision="revision_required",
                comments="Synthetic revision request",
                created_at=scan_time,
            )
        )

        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        content = b"Synthetic initial revision.\n"

        path = self.prepare_manuscript(
            "initial_revision_required",
            f"revised_upload_{timestamp}_synthetic.txt",
            content,
        )

        with patch.object(
            manuscripts, "AI_PRESCREENING_ENABLED", True
        ):
            response = self.fixture.client.post(
                f"/manuscripts/{self.fixture.mid}/initial-resubmit",
                json={},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.fixture.db.expire_all()

        manuscript = self.fixture.db.get(
            models.Manuscript, self.fixture.mid
        )
        self.assertEqual(manuscript.status, "submitted")
        self.assertEqual(manuscript.review_round, 1)

        self.assert_snapshot("initial_revision", 1, path, content)

    def test_peer_revision(self):
        self.install_ai_schema()

        content = b"Synthetic peer revision.\n"
        path = self.prepare_manuscript(
            "revision_required",
            "round_2_synthetic_revision.txt",
            content,
        )

        with patch.object(
            manuscripts, "AI_PRESCREENING_ENABLED", True
        ):
            response = self.fixture.client.post(
                f"/manuscripts/{self.fixture.mid}/resubmit",
                json={"abstract": "Updated synthetic abstract"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.fixture.db.expire_all()

        manuscript = self.fixture.db.get(
            models.Manuscript, self.fixture.mid
        )

        self.assertEqual(manuscript.status, "revised")
        self.assertEqual(manuscript.review_round, 2)
        self.assertEqual(
            manuscript.abstract, "Updated synthetic abstract"
        )

        with sqlite3.connect(self.db_path) as connection:
            round_files = connection.execute(
                """
                SELECT review_round, source_kind, file_path
                FROM review_round_files
                WHERE manuscript_id=? AND review_round=2
                """,
                (self.fixture.mid,),
            ).fetchall()

        self.assertEqual(
            round_files, [(2, "author_revision", path)]
        )
        self.assert_snapshot("peer_revision", 2, path, content)

    def test_ai_disabled(self):
        self.prepare_manuscript(
            "draft",
            "disabled.txt",
            b"Synthetic disabled manuscript.\n",
        )

        with sqlite3.connect(self.db_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }

            self.assertIn("ai_prescreening_jobs", tables)

            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM manuscript_submission_snapshots"
                ).fetchone()[0],
                0,
            )

            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM ai_prescreening_jobs"
                ).fetchone()[0],
                0,
            )

        with patch.object(
            manuscripts, "AI_PRESCREENING_ENABLED", False
        ):
            response = self.fixture.client.post(
                f"/manuscripts/{self.fixture.mid}/submit"
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.fixture.db.expire_all()

        manuscript = self.fixture.db.get(
            models.Manuscript, self.fixture.mid
        )
        self.assertEqual(manuscript.status, "submitted")

    def test_ai_failure_rolls_back(self):
        self.prepare_manuscript(
            "draft",
            "rollback.txt",
            b"Synthetic rollback manuscript.\n",
        )

        # Simulate an AI queue failure at the router's imported service.
        with patch.object(
            manuscripts,
            "AI_PRESCREENING_ENABLED",
            True,
        ), patch.object(
            manuscripts,
            "try_create_submission_job",
            side_effect=RuntimeError("Simulated AI queue failure"),
        ) as mock_ai:
            with self.assertRaises(RuntimeError):
                self.fixture.client.post(
                    f"/manuscripts/{self.fixture.mid}/submit"
                )

        mock_ai.assert_called_once()

        # Roll back all pending submission changes.
        self.fixture.db.rollback()
        self.fixture.db.expire_all()

        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT status FROM manuscripts WHERE manuscript_id=?",
                (self.fixture.mid,),
            ).fetchone()

            snapshot_count = connection.execute(
                "SELECT COUNT(*) FROM manuscript_submission_snapshots"
            ).fetchone()[0]

            job_count = connection.execute(
                "SELECT COUNT(*) FROM ai_prescreening_jobs"
            ).fetchone()[0]

        self.assertEqual(row, ("draft",))
        self.assertEqual(snapshot_count, 0)
        self.assertEqual(job_count, 0)


if __name__ == "__main__":
    unittest.main()

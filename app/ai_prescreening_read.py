"""Read-only advisory AI prescreening results for authorized callers."""

import json

from sqlalchemy import text
from sqlalchemy.exc import OperationalError


def list_manuscript_ai_reports(db, manuscript_id):
    """Return newest-first submission snapshots with advisory AI status.

    Caller must enforce manuscript visibility and EIC authorization.
    This function never modifies the database.
    """
    if not isinstance(manuscript_id, int) or manuscript_id <= 0:
        raise ValueError("A positive manuscript ID is required")

    # A database without Migration 017 has no AI records.
    tables = {
        row[0]
        for row in db.execute(text(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name IN "
            "('manuscript_submission_snapshots', "
            "'ai_prescreening_jobs', 'ai_prescreening_reports')"
        )).all()
    }

    required = {
        "manuscript_submission_snapshots",
        "ai_prescreening_jobs",
        "ai_prescreening_reports",
    }

    if not required.issubset(tables):
        return []

    rows = db.execute(text("""
        SELECT
            s.snapshot_id,
            s.submission_kind,
            s.review_round,
            s.submission_sequence,
            s.file_format,
            s.file_sha256,
            s.submitted_at,
            j.status AS job_status,
            r.engine AS report_engine,
            r.findings_json AS report_json,
            r.created_at AS report_created_at
        FROM manuscript_submission_snapshots AS s
        LEFT JOIN ai_prescreening_jobs AS j
          ON j.snapshot_id = s.snapshot_id
        LEFT JOIN ai_prescreening_reports AS r
          ON r.snapshot_id = s.snapshot_id
         AND r.job_id = j.job_id
        WHERE s.manuscript_id = :manuscript_id
        ORDER BY s.submission_sequence DESC
    """), {"manuscript_id": manuscript_id}).mappings().all()

    results = []

    for row in rows:
        analysis = None

        if row["job_status"] == "completed" and row["report_json"]:
            try:
                parsed = json.loads(row["report_json"])
            except (TypeError, ValueError):
                parsed = None

            if isinstance(parsed, dict) and parsed.get("advisory_only") is True:
                analysis = {
                    "engine": row["report_engine"],
                    "format": parsed.get("format"),
                    "word_count": parsed.get("word_count"),
                    "sections_detected": parsed.get("sections_detected"),
                    "findings": parsed.get("findings"),
                    "advisory_only": True,
                }

        results.append({
            "snapshot_id": row["snapshot_id"],
            "submission_kind": row["submission_kind"],
            "review_round": row["review_round"],
            "submission_sequence": row["submission_sequence"],
            "file_format": row["file_format"],
            "file_sha256": row["file_sha256"],
            "submitted_at": row["submitted_at"],
            "status": row["job_status"] or "unavailable",
            "report_created_at": row["report_created_at"],
            "analysis": analysis,
        })

    return results

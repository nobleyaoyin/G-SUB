"""SQLite job-store primitives for advisory AI pre-screening.

These functions do not run AI analysis or commit transactions.
Callers must commit or roll back explicitly.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
import sqlite3


@dataclass(frozen=True)
class Lease:
    job_id: str
    token: str
    expires_at: str


def _utc(value=None):
    """Return a timezone-aware UTC datetime."""
    if value is None:
        value = datetime.now(timezone.utc)

    if not isinstance(value, datetime):
        raise TypeError("now must be a datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    return value.astimezone(timezone.utc)


def _stamp(value):
    """Use fixed-width UTC timestamps for SQLite comparisons."""
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _begin(db):
    """Acquire the SQLite write lock before selecting a job."""
    if not isinstance(db, sqlite3.Connection):
        raise TypeError("A sqlite3.Connection is required")

    if db.in_transaction:
        raise RuntimeError("Claim requires a fresh transaction")

    if db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("SQLite foreign keys must be enabled")

    db.execute("BEGIN IMMEDIATE")


def claim_next(db, *, lease_duration, now=None):
    """Claim one due AI job. Caller owns commit or rollback.

    Returns a Lease or None. A returned lease is not confirmed
    until the caller successfully commits the transaction.
    """
    if not isinstance(lease_duration, timedelta):
        raise TypeError("lease_duration must be a timedelta")

    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be positive")

    current = _utc(now)
    expires = current + lease_duration

    stamp = _stamp(current)
    until = _stamp(expires)

    token = secrets.token_urlsafe(32)

    _begin(db)

    row = db.execute("""
        SELECT job_id
        FROM ai_prescreening_jobs
        WHERE status IN ('pending', 'retry_wait')
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
          AND attempt_count < max_attempts
        ORDER BY created_at, job_id
        LIMIT 1
    """, (stamp,)).fetchone()

    if row is None:
        return None

    job_id = row[0]

    result = db.execute("""
        UPDATE ai_prescreening_jobs
        SET status='processing',
            lease_token=?,
            lease_until=?,
            next_attempt_at=NULL,
            attempt_count=attempt_count+1,
            updated_at=?
        WHERE job_id=?
          AND status IN ('pending', 'retry_wait')
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
          AND attempt_count < max_attempts
    """, (token, until, stamp, job_id, stamp))

    if result.rowcount != 1:
        raise RuntimeError("AI job claim changed unexpectedly")

    return Lease(job_id, token, until)


def renew_lease(db, lease, *, lease_duration, now=None):
    """Extend a valid, unexpired AI job lease.

    Returns a new Lease on success, or None if the lease is
    stale, expired, or no longer belongs to a processing job.

    Caller owns commit or rollback.
    """
    if not isinstance(lease, Lease):
        raise TypeError("Lease is required")

    if not isinstance(lease_duration, timedelta):
        raise TypeError("lease_duration must be a timedelta")

    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be positive")

    current = _utc(now)
    stamp = _stamp(current)
    until = _stamp(current + lease_duration)

    _begin(db)

    result = db.execute("""
        UPDATE ai_prescreening_jobs
        SET lease_until=?,
            updated_at=?
        WHERE job_id=?
          AND status='processing'
          AND lease_token=?
          AND lease_until > ?
          AND lease_until < ?
    """, (
        until,
        stamp,
        lease.job_id,
        lease.token,
        stamp,
        until,
    ))

    if result.rowcount != 1:
        return None

    return Lease(lease.job_id, lease.token, until)


def recover_expired(db, *, retry_delay=timedelta(minutes=1), now=None):
    """Recover one expired AI processing lease.

    Returns (job_id, new_status), or None if nothing is expired.
    Caller owns commit or rollback.
    """
    if not isinstance(retry_delay, timedelta):
        raise TypeError("retry_delay must be a timedelta")

    if retry_delay < timedelta(0):
        raise ValueError("retry_delay cannot be negative")

    current = _utc(now)
    stamp = _stamp(current)
    next_attempt = _stamp(current + retry_delay)

    _begin(db)

    row = db.execute("""
        SELECT job_id, lease_token, attempt_count, max_attempts
        FROM ai_prescreening_jobs
        WHERE status='processing'
          AND lease_until <= ?
        ORDER BY lease_until, job_id
        LIMIT 1
    """, (stamp,)).fetchone()

    if row is None:
        return None

    job_id, token, attempts, maximum = row

    if attempts >= maximum:
        new_status = "failed"
        due = None
    else:
        new_status = "retry_wait"
        due = next_attempt

    result = db.execute("""
        UPDATE ai_prescreening_jobs
        SET status=?,
            lease_token=NULL,
            lease_until=NULL,
            next_attempt_at=?,
            last_error='lease_expired',
            updated_at=?
        WHERE job_id=?
          AND status='processing'
          AND lease_token=?
          AND lease_until <= ?
    """, (
        new_status,
        due,
        stamp,
        job_id,
        token,
        stamp,
    ))

    if result.rowcount != 1:
        raise RuntimeError("AI job recovery changed unexpectedly")

    return job_id, new_status


def fail_attempt(
    db, lease, *, error_code,
    retry_delay=timedelta(minutes=1), now=None
):
    """Record a failed AI analysis attempt.

    Returns the new status, or None for a stale/expired lease.
    Caller owns commit or rollback.
    """
    if not isinstance(lease, Lease):
        raise TypeError("Lease is required")

    if not isinstance(error_code, str) or not error_code:
        raise ValueError("A nonempty error_code is required")

    if len(error_code) > 128:
        raise ValueError("error_code is too long")

    if not isinstance(retry_delay, timedelta):
        raise TypeError("retry_delay must be a timedelta")

    if retry_delay < timedelta(0):
        raise ValueError("retry_delay cannot be negative")

    current = _utc(now)
    stamp = _stamp(current)
    due = _stamp(current + retry_delay)

    _begin(db)

    row = db.execute("""
        SELECT attempt_count, max_attempts
        FROM ai_prescreening_jobs
        WHERE job_id=?
          AND status='processing'
          AND lease_token=?
          AND lease_until > ?
    """, (lease.job_id, lease.token, stamp)).fetchone()

    if row is None:
        return None

    attempts, maximum = row

    new_status = "failed" if attempts >= maximum else "retry_wait"
    next_attempt = None if new_status == "failed" else due

    result = db.execute("""
        UPDATE ai_prescreening_jobs
        SET status=?,
            lease_token=NULL,
            lease_until=NULL,
            next_attempt_at=?,
            last_error=?,
            updated_at=?
        WHERE job_id=?
          AND status='processing'
          AND lease_token=?
          AND lease_until > ?
    """, (
        new_status,
        next_attempt,
        error_code,
        stamp,
        lease.job_id,
        lease.token,
        stamp,
    ))

    if result.rowcount != 1:
        raise RuntimeError("AI failure update changed unexpectedly")

    return new_status


def complete_job(db, lease, *, report_id, engine, findings, now=None):
    """Persist an advisory AI report and complete its job atomically.

    Returns True on success, False for a stale or expired lease.
    Caller owns commit or rollback.

    findings must be JSON-compatible data. No external AI service
    is called by this function.
    """
    import json

    if not isinstance(lease, Lease):
        raise TypeError("Lease is required")

    if not isinstance(report_id, str) or not report_id.strip():
        raise ValueError("A nonempty report_id is required")

    if not isinstance(engine, str) or not engine.strip():
        raise ValueError("A nonempty engine is required")

    findings_json = json.dumps(
        findings,
        ensure_ascii=False,
        allow_nan=False,
    )

    current = _utc(now)
    stamp = _stamp(current)

    _begin(db)

    row = db.execute("""
        SELECT snapshot_id
        FROM ai_prescreening_jobs
        WHERE job_id=?
          AND status='processing'
          AND lease_token=?
          AND lease_until > ?
    """, (
        lease.job_id,
        lease.token,
        stamp,
    )).fetchone()

    if row is None:
        return False

    snapshot_id = row[0]

    db.execute("""
        INSERT INTO ai_prescreening_reports
        (report_id, snapshot_id, job_id, engine,
         findings_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        report_id,
        snapshot_id,
        lease.job_id,
        engine,
        findings_json,
        stamp,
    ))

    result = db.execute("""
        UPDATE ai_prescreening_jobs
        SET status='completed',
            lease_token=NULL,
            lease_until=NULL,
            next_attempt_at=NULL,
            last_error=NULL,
            updated_at=?
        WHERE job_id=?
          AND status='processing'
          AND lease_token=?
          AND lease_until > ?
    """, (
        stamp,
        lease.job_id,
        lease.token,
        stamp,
    ))

    if result.rowcount != 1:
        raise RuntimeError("AI completion changed unexpectedly")

    return True

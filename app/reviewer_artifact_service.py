"""Disconnected artifact transaction prototype; never import into live routes.

Adapters are privileged dependencies selected by the application, not request
data. Authentication, policy and historical source attestation have no real
adapter here. SQLite transaction ownership remains with the caller.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
import hmac
from uuid import uuid4

from app.reviewer_artifact_storage import StorageMetadata, StorageError, read_verified_fd

schema = import_module('migrations.012_reviewer_artifacts')


class ArtifactError(ValueError):
    pass


class PublishedArtifactUnrecorded(ArtifactError):
    """A published object must be reconciled, never automatically deleted."""
    def __init__(self, storage_id):
        self.storage_id = storage_id
        super().__init__('Published artifact was not recorded by this operation; reconcile before retrying')


@dataclass(frozen=True)
class PreparedArtifact:
    artifact_id: str
    storage_id: str
    state_revision: int


def _id(value):
    if type(value) is not int or value < 1: raise ArtifactError('Invalid context')
    return value


def _context(db):
    if not db.in_transaction or not db.execute('PRAGMA foreign_keys').fetchone()[0]:
        raise ArtifactError('Caller-owned SQLite transaction with foreign keys required')
    try:
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (schema.MIGRATION_ID,)).fetchone(): raise ArtifactError('Artifact schema unavailable')
        schema.validate_schema(db)
    except ArtifactError:
        raise
    except Exception as error:
        raise ArtifactError('Artifact schema unavailable or incompatible') from error


def _actor(db, authority, principal, action, manuscript_id, *, prepared_by=None):
    """Authority authenticates principal and enforces its policy in this transaction."""
    actor = authority.authorize(db, principal, action, manuscript_id, prepared_by=prepared_by)
    _id(actor)
    if not db.execute('SELECT 1 FROM users WHERE user_id=?', (actor,)).fetchone(): raise ArtifactError('Actor unavailable')
    return actor


def _source(db, manuscript_id, round_file_id):
    _id(manuscript_id); _id(round_file_id)
    row = db.execute('''SELECT m.review_round,m.status,r.review_round,r.source_kind,r.confirmation_id,r.file_path
        FROM manuscripts m JOIN review_round_files r ON r.manuscript_id=m.manuscript_id
        WHERE m.manuscript_id=? AND r.round_file_id=?''', (manuscript_id, round_file_id)).fetchone()
    if not row or row[0] != row[2] or row[1] not in ('ready_for_peer_review','revised'):
        raise ArtifactError('Source unavailable or review round is stale')
    if row[2] == 1:
        approved = db.execute('''SELECT 1 FROM pre_review_confirmations c
            JOIN initial_editing_submissions s ON s.submission_id=c.submission_id
            JOIN manuscripts m ON m.manuscript_id=c.manuscript_id
            WHERE c.confirmation_id=? AND c.manuscript_id=? AND c.author_id=m.author_id
            AND c.decision='confirm' AND s.manuscript_id=m.manuscript_id
            AND s.status='eic_approved' AND s.file_path=c.file_path AND c.file_path=?''', (row[4], manuscript_id, row[5])).fetchone()
        if row[3] != 'initial_editing' or not approved: raise ArtifactError('Approved source unavailable')
    elif row[2] > 1:
        if row[3] != 'author_revision' or row[4] is not None: raise ArtifactError('Approved source unavailable')
    else: raise ArtifactError('Approved source unavailable')
    return row


def _verified_source(db, provenance, manuscript_id, source_id, source, expected=None):
    """Provenance adapter must authenticate source approval and securely open it.

    Its context manager returns (fd, approved_sha256, approved_size, format).
    No current production adapter or historical source digests exist.
    """
    with provenance.open_attested_source(db, manuscript_id, source[2], source_id, source[5]) as (fd, digest, size, fmt):
        read_verified_fd(fd, digest, size, fmt)
    if expected is not None and (not isinstance(digest, str) or not hmac.compare_digest(digest, expected)):
        raise ArtifactError('Source provenance changed')
    return digest


def _now(): return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def prepare(db, principal, authority, provenance, storage, manuscript_id, source_id, content, fmt, artifact_revision):
    """Record prepared event without committing; published files are never removed."""
    _context(db); _id(artifact_revision)
    actor = _actor(db, authority, principal, 'prepare', manuscript_id)
    source = _source(db, manuscript_id, source_id)
    digest = _verified_source(db, provenance, manuscript_id, source_id, source)
    metadata = storage.publish(content, fmt)
    try:
        db.execute('SAVEPOINT artifact_prepare')
        aid, eid, at = uuid4().hex, uuid4().hex, _now()
        db.execute('INSERT INTO reviewer_artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (aid, manuscript_id, source[2], source_id, digest, metadata.sha256, metadata.format, metadata.byte_size, metadata.storage_id, actor, at, 'prepared', None, None, artifact_revision, 1, eid))
        db.execute('INSERT INTO reviewer_artifact_events VALUES (?,?,?,?,?,?,?)', (eid, aid, 1, 'prepared', actor, at, 'prepared'))
        db.execute('RELEASE SAVEPOINT artifact_prepare')
        return PreparedArtifact(aid, metadata.storage_id, 1)
    except Exception as error:
        try:
            db.execute('ROLLBACK TO SAVEPOINT artifact_prepare'); db.execute('RELEASE SAVEPOINT artifact_prepare')
        except Exception:
            pass
        raise PublishedArtifactUnrecorded(metadata.storage_id) from error


def transition(db, principal, authority, provenance, storage, artifact_id, action, expected_revision, *, human_review_attested=False):
    """Append approved/rejected/withdrawn event; caller commits or rolls back."""
    _context(db); _id(expected_revision)
    if action not in ('approved','rejected','withdrawn'): raise ArtifactError('Invalid action')
    row = db.execute('''SELECT manuscript_id,review_round,source_round_file_id,source_sha256,artifact_sha256,format,byte_size,storage_id,prepared_by,status,state_revision,current_event_id
        FROM reviewer_artifacts WHERE artifact_id=?''', (artifact_id,)).fetchone()
    if not row: raise ArtifactError('Artifact unavailable')
    mid, rnd, sid, source_digest, artifact_digest, fmt, size, storage_id, preparer, status, revision, eid = row
    actor = _actor(db, authority, principal, action, mid, prepared_by=preparer)
    source = _source(db, mid, sid)
    if source[2] != rnd or revision != expected_revision or not ((status == 'prepared' and action in ('approved','rejected','withdrawn')) or (status == 'approved' and action == 'withdrawn')):
        raise ArtifactError('Artifact state or review round is stale')
    last = db.execute('SELECT action,revision FROM reviewer_artifact_events WHERE event_id=? AND artifact_id=?', (eid, artifact_id)).fetchone()
    if last != (status, revision) or db.execute('SELECT count(*) FROM reviewer_artifact_events WHERE artifact_id=?', (artifact_id,)).fetchone()[0] != revision:
        raise ArtifactError('Inconsistent artifact history')
    if action == 'approved':
        if human_review_attested is not True: raise ArtifactError('Explicit human review attestation required')
        _verified_source(db, provenance, mid, sid, source, source_digest)
        storage.read_verified(StorageMetadata(storage_id, artifact_digest, size, fmt))
    event_id, at = uuid4().hex, _now()
    db.execute('INSERT INTO reviewer_artifact_events VALUES (?,?,?,?,?,?,?)', (event_id, artifact_id, revision+1, action, actor, at, action))
    return revision+1

"""Read-only operator diagnostics. No cleanup or authorization decisions."""
import re
from app.reviewer_artifact_storage import ArtifactStorage, StorageMetadata, StorageError

_ID=re.compile(r'^[0-9a-f]{32}$')


def inspect_distribution(connection, storage):
    """Classify a bounded inventory without changing database or filesystem.

    Caller owns the read-only connection and the open, trusted private store.
    Observations are not proof that an object can safely be deleted: a writer
    may be in flight, and database and filesystem do not share a snapshot.
    """
    if not isinstance(storage,ArtifactStorage): raise ValueError('Private store required')
    entries=storage.inspect_entries()
    rows=connection.execute('''SELECT r.storage_id,r.manuscript_id,r.kind,r.sha256,r.byte_size,r.format,
        a.artifact_id,
        (SELECT count(*) FROM distribution_grants g WHERE g.artifact_id=a.artifact_id),
        (SELECT count(*) FROM distribution_grants g JOIN distribution_revocations v ON v.grant_id=g.grant_id WHERE g.artifact_id=a.artifact_id)
        FROM distribution_reservations r LEFT JOIN distribution_artifacts a ON a.storage_id=r.storage_id ORDER BY r.storage_id LIMIT 10001''').fetchall()
    if len(rows)>10000: raise StorageError('Reservation inventory limit exceeded')
    known=set();results=[]
    for sid,mid,kind,digest,size,fmt,artifact,grants,revoked in rows:
        if not isinstance(sid,str) or not _ID.fullmatch(sid): raise StorageError('Invalid reservation')
        known.add(sid);state=entries.get(sid)
        if state=='unsafe': status='unsafe_object'
        elif state is None: status='missing_object' if artifact else 'pending_without_object'
        else:
            try:
                storage.read_verified(StorageMetadata(sid,digest,size,fmt))
                status='verified_artifact' if artifact else 'published_without_artifact'
            except StorageError: status='integrity_unavailable_or_mismatch'
        results.append({'storage_id':sid,'manuscript_id':mid,'kind':kind,'status':status,'staging_present':'.stage-'+sid in entries,'artifact_recorded':bool(artifact),'grant_count':grants,'revoked_grant_count':revoked})
    for name,kind in sorted(entries.items()):
        sid=name[7:] if name.startswith('.stage-') else name
        if _ID.fullmatch(sid) and sid not in known:
            results.append({'storage_id':sid,'status':'unregistered_stage' if name.startswith('.stage-') else 'unregistered_object','entry_type':kind})
    return {'dry_run':True,'note':'Observations can race with active writers; no object is safe to delete solely from this report.','records':results}

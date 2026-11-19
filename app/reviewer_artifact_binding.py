"""Disconnected evidence-gated binding prototype; no live route uses this.

Only trusted application code may select authority, proof and provenance
adapters. A caller-supplied actor ID or proof adapter is not authentication.
The caller owns an explicit SQLite write transaction, preferably IMMEDIATE.
"""
from importlib import import_module

from app import blind_policy_store, lifecycle_prototype, reviewer_artifact_evidence, reviewer_artifact_service
from app.reviewer_artifact_storage import StorageMetadata, read_verified_fd

lifecycle_schema = import_module('migrations.009_account_invitation_lifecycle')


def _verify(db, principal, authority, proof_adapter, provenance, storage, assignment_id, artifact_id, authorize, *, expected_policy_revision, expected_artifact_revision, expected_source_revision):
    """Shared snapshot checks; authorize is an internal, operation-specific callback."""
    error = reviewer_artifact_service.ArtifactError
    reviewer_artifact_evidence._context(db)
    for value in (assignment_id, expected_policy_revision, expected_artifact_revision, expected_source_revision): reviewer_artifact_service._id(value)
    try:
        if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(lifecycle_schema.MIGRATION_ID,)).fetchone(): raise error('Eligibility schema unavailable')
        lifecycle_schema._validate_own_schema(lifecycle_schema._objects(db))
    except error: raise
    except Exception as exc: raise error('Eligibility schema unavailable or incompatible') from exc
    row=db.execute('''SELECT a.manuscript_id,a.review_round,a.reviewer_id,a.status,i.status,m.review_round,m.status,f.round_file_id,u.role
        FROM review_assignments a JOIN reviewer_invitations i ON i.assignment_id=a.assignment_id
        JOIN manuscripts m ON m.manuscript_id=a.manuscript_id JOIN review_assignment_files f ON f.assignment_id=a.assignment_id
        JOIN users u ON u.user_id=a.reviewer_id WHERE a.assignment_id=?''',(assignment_id,)).fetchone()
    if not row: raise error('Assignment unavailable')
    mid,rnd,reviewer,assignment_status,invitation_status,current_round,manuscript_status,source_id,reviewer_role=row
    actor=authorize(db,principal,authority,mid,reviewer)
    if (reviewer_role!='reviewer' or assignment_status!='assigned' or invitation_status!='accepted' or rnd!=current_round or manuscript_status not in ('ready_for_peer_review','revised') or
        db.execute('SELECT 1 FROM reviewer_invitation_invalidations WHERE assignment_id=?',(assignment_id,)).fetchone()): raise error('Assignment is no longer eligible')
    try: lifecycle=lifecycle_prototype._state(db,reviewer)
    except (lifecycle_prototype.PolicyError, ValueError) as exc: raise error('Reviewer lifecycle unavailable') from exc
    if lifecycle is None or lifecycle.state!='active': raise error('Reviewer lifecycle unavailable')
    try: policy=blind_policy_store.read_policy(db,mid)
    except blind_policy_store.PolicyError as exc: raise error('Policy unavailable') from exc
    if not policy or policy['mode']!='double_blind' or not policy['locked_at'] or policy['revision']!=expected_policy_revision: raise error('Locked double-blind policy unavailable or stale')
    content, fmt = _verify_artifact(db, proof_adapter, provenance, storage, mid, rnd, source_id, artifact_id, expected_artifact_revision, expected_source_revision)
    return actor, content, fmt


def _verify_artifact(db, proof_adapter, provenance, storage, mid, rnd, source_id, artifact_id, expected_artifact_revision, expected_source_revision):
    error = reviewer_artifact_service.ArtifactError
    source=reviewer_artifact_service._source(db,mid,source_id)
    row=db.execute('''SELECT a.manuscript_id,a.review_round,a.source_round_file_id,a.source_sha256,a.artifact_sha256,a.format,a.byte_size,a.storage_id,a.status,a.state_revision,a.current_event_id,
        e.approver_id,e.attested_at,e.checklist_key,e.checklist_version,e.acknowledged,e.artifact_sha256,e.artifact_state_revision,
        s.source_sha256,s.byte_size,s.format,s.revision,s.proof_reference,s.confirmation_id,s.submission_id,s.eic_approver_id,
        s.manuscript_id,s.review_round,s.source_round_file_id,a.approved_by,a.approved_at
        FROM reviewer_artifacts a JOIN artifact_approval_evidence e ON e.artifact_id=a.artifact_id AND e.approval_event_id=a.current_event_id
        JOIN source_provenance_evidence s ON s.evidence_id=e.source_evidence_id WHERE a.artifact_id=?''',(artifact_id,)).fetchone()
    if not row: raise error('Approved artifact evidence unavailable')
    (art_mid,art_round,art_source,source_sha,artifact_sha,fmt,size,storage_id,status,revision,event_id,
     approver,attested_at,checklist,check_version,ack,evidence_sha,evidence_revision,
     evidence_source_sha,source_size,source_format,source_rev,proof_ref,confirmation,submission,eic,
     evidence_mid,evidence_round,evidence_source,artifact_approver,artifact_approved_at)=row
    if (art_mid,art_round,art_source)!=(mid,rnd,source_id) or (evidence_mid,evidence_round,evidence_source)!=(mid,rnd,source_id) or (artifact_approver,artifact_approved_at)!=(approver,attested_at) or status!='approved' or revision!=expected_artifact_revision or evidence_revision!=revision or artifact_sha!=evidence_sha or source_sha!=evidence_source_sha or checklist!='reviewer_document' or check_version!=1 or ack!=1 or source_rev!=expected_source_revision:
        raise error('Artifact evidence is inconsistent or stale')
    if db.execute('SELECT MAX(revision) FROM source_provenance_evidence WHERE source_round_file_id=?',(source_id,)).fetchone()[0]!=source_rev: raise error('Source evidence is stale')
    event=db.execute('SELECT action,revision,actor_id,occurred_at FROM reviewer_artifact_events WHERE event_id=? AND artifact_id=?',(event_id,artifact_id)).fetchone()
    if event!=('approved',revision,approver,attested_at): raise error('Approval event is inconsistent')
    history=db.execute('SELECT revision,action,actor_id,occurred_at FROM reviewer_artifact_events WHERE artifact_id=? ORDER BY revision',(artifact_id,)).fetchall()
    prepared=db.execute('SELECT prepared_by,prepared_at FROM reviewer_artifacts WHERE artifact_id=?',(artifact_id,)).fetchone()
    if not prepared or history!=[(1,'prepared',prepared[0],prepared[1]),(revision,'approved',approver,attested_at)] or revision!=2:
        raise error('Artifact audit history is inconsistent')
    if rnd==1:
        current=db.execute('SELECT c.confirmation_id,s.submission_id,s.eic_approved_by FROM pre_review_confirmations c JOIN initial_editing_submissions s ON s.submission_id=c.submission_id WHERE c.confirmation_id=? AND c.confirmed_at IS NOT NULL AND s.eic_reviewed_at IS NOT NULL',(source[4],)).fetchone()
        if current!=(confirmation,submission,eic) or eic is None: raise error('Source approval evidence is stale')
    elif (confirmation,submission,eic)!=(None,None,None): raise error('Source approval evidence is inconsistent')
    proof=proof_adapter.verify_prospective(db,mid,rnd,source_id,source[4])
    if proof!=(proof_ref,source_sha,source_size,source_format): raise error('Source provenance proof unavailable')
    with provenance.open_attested_source(db,mid,rnd,source_id,source[5]) as (fd,digest,actual_size,actual_format):
        if (digest,actual_size,actual_format)!=(source_sha,source_size,source_format): raise error('Source provenance mismatch')
        read_verified_fd(fd,source_sha,source_size,source_format)
    content=storage.read_verified(StorageMetadata(storage_id,artifact_sha,size,fmt))
    return content, fmt


def verify_preinvitation(db, proof_adapter, provenance, storage, manuscript_id, review_round, source_id):
    """Check exactly one approved artifact; this grants no reviewer access."""
    error = reviewer_artifact_service.ArtifactError
    reviewer_artifact_evidence._context(db)
    for value in (manuscript_id, review_round, source_id):
        reviewer_artifact_service._id(value)
    manuscript = db.execute('SELECT review_round,status FROM manuscripts WHERE manuscript_id=?', (manuscript_id,)).fetchone()
    policy = blind_policy_store.read_policy(db, manuscript_id)
    if manuscript != (review_round, 'ready_for_peer_review') and manuscript != (review_round, 'revised'):
        raise error('Review round unavailable')
    if not policy or policy['mode'] != 'double_blind':
        raise error('Double-blind policy unavailable')
    rows = db.execute('''SELECT a.artifact_id,a.state_revision,s.revision
      FROM reviewer_artifacts a
      JOIN artifact_approval_evidence e ON e.artifact_id=a.artifact_id AND e.approval_event_id=a.current_event_id
      JOIN source_provenance_evidence s ON s.evidence_id=e.source_evidence_id
      WHERE a.manuscript_id=? AND a.review_round=? AND a.source_round_file_id=? AND a.status='approved' ''',
      (manuscript_id, review_round, source_id)).fetchall()
    if len(rows) != 1:
        raise error('Approved artifact unavailable or ambiguous')
    artifact_id, artifact_revision, source_revision = rows[0]
    _verify_artifact(db, proof_adapter, provenance, storage, manuscript_id, review_round, source_id,
                     artifact_id, artifact_revision, source_revision)
    return artifact_id, artifact_revision, source_revision


def _editorial_actor(db,principal,authority,mid,_reviewer):
    error=reviewer_artifact_service.ArtifactError
    actor=reviewer_artifact_service._actor(db,authority,principal,'bind',mid)
    role=db.execute('SELECT role FROM users WHERE user_id=?',(actor,)).fetchone()
    if not role or (role[0]!='eic' and not (role[0]=='editor' and db.execute("SELECT 1 FROM initial_editor_invitations WHERE manuscript_id=? AND editor_id=? AND status='accepted'",(mid,actor)).fetchone())):
        raise error('Editorial authorization unavailable')
    return actor


def bind(db, principal, authority, proof_adapter, provenance, storage, assignment_id, artifact_id, *, expected_policy_revision, expected_artifact_revision, expected_source_revision):
    """Insert one immutable binding after verifying all current facts; never commit."""
    error=reviewer_artifact_service.ArtifactError
    actor,_,_=_verify(db,principal,authority,proof_adapter,provenance,storage,assignment_id,artifact_id,_editorial_actor,
        expected_policy_revision=expected_policy_revision,expected_artifact_revision=expected_artifact_revision,expected_source_revision=expected_source_revision)
    if db.execute('SELECT 1 FROM reviewer_artifact_assignments WHERE assignment_id=?',(assignment_id,)).fetchone(): raise error('Assignment already has an artifact binding')
    db.execute('INSERT INTO reviewer_artifact_assignments VALUES (?,?,?,?)',(assignment_id,artifact_id,actor,reviewer_artifact_service._now()))
    return artifact_id

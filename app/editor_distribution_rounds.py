"""Authoritative prospective editor distribution round evidence."""
from importlib import import_module
import sqlite3
from fastapi import HTTPException


def require_schema(raw):
    module=import_module('migrations.032_editor_distribution_rounds')
    try:
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(module.MIGRATION_ID,)).fetchone():raise HTTPException(503,'Distribution unavailable; migration 032 is required')
        for name,expected in module.DDL.items():
            row=raw.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
            if not row or not row[0] or module.normalize(row[0])!=module.normalize(expected):raise HTTPException(503,'Distribution round evidence unavailable')
    except sqlite3.Error:raise HTTPException(503,'Distribution round evidence unavailable') from None


def resolve(raw,mid,kind):
    row=raw.execute('SELECT status,review_round FROM manuscripts WHERE manuscript_id=?',(mid,)).fetchone()
    if not row:raise HTTPException(409,'Distribution round unavailable')
    if kind=='initial':
        if row[0]!='initial_editing' or row[1]!=1 or raw.execute('SELECT 1 FROM review_round_files WHERE manuscript_id=? UNION ALL SELECT 1 FROM review_assignments WHERE manuscript_id=? LIMIT 1',(mid,mid)).fetchone():raise HTTPException(409,'Distribution round unavailable')
        return ('pre_review',None,None,None)
    if kind!='final' or row[0]!='final_editing' or not isinstance(row[1],int) or row[1]<1:raise HTTPException(409,'Distribution round unavailable')
    agreement=raw.execute('''SELECT a.agreement_id,d.decision_id,d.review_round FROM author_agreements a JOIN eic_decisions d ON d.decision_id=a.decision_id JOIN manuscripts m ON m.manuscript_id=a.manuscript_id
        WHERE a.manuscript_id=? AND a.agreement_id=(SELECT MAX(last.agreement_id) FROM author_agreements last WHERE last.manuscript_id=m.manuscript_id) AND a.author_id=m.author_id AND a.status='accepted' AND d.manuscript_id=m.manuscript_id AND d.decision='accept' LIMIT 1''',(mid,)).fetchone()
    if not agreement or agreement[2]!=row[1]:raise HTTPException(409,'Distribution round unavailable')
    return ('review_round',agreement[2],agreement[0],agreement[1])


def validate_grant(raw,grant_id):
    require_schema(raw)
    if raw.execute('SELECT 1 FROM editor_distribution_legacy_grants WHERE grant_id=?',(grant_id,)).fetchone():return None
    row=raw.execute('''SELECT e.manuscript_id,e.round_kind,e.review_round,e.agreement_id,e.decision_id,e.source_ref,e.source_sha256,e.artifact_version,e.recipient_id,e.invitation_kind,e.invitation_id,e.mode,e.actor_id,e.idempotency_key,e.intent_id
      FROM editor_distribution_grant_rounds e JOIN distribution_grants g ON g.grant_id=e.grant_id JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id
      JOIN manuscripts m ON m.manuscript_id=g.manuscript_id
      WHERE e.grant_id=? AND g.manuscript_id=e.manuscript_id AND g.recipient_id=e.recipient_id AND g.actor_id=e.actor_id AND g.idempotency_key=e.idempotency_key AND a.version=e.artifact_version AND a.sha256=e.source_sha256 AND m.file_path=e.source_ref
      AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=g.grant_id)
      AND ((e.mode='manual' AND e.intent_id IS NULL) OR (e.mode='automatic' AND EXISTS(SELECT 1 FROM controlled_automatic_grant_provenance p WHERE p.grant_id=g.grant_id AND p.intent_id=e.intent_id AND p.source_ref=e.source_ref AND p.source_sha256=e.source_sha256)))
      AND ((e.invitation_kind='initial' AND g.initial_invitation_id=e.invitation_id) OR (e.invitation_kind='final' AND g.final_invitation_id=e.invitation_id))''',(grant_id,)).fetchone()
    if not row:raise HTTPException(403,'Distribution round unavailable')
    if row[9]=='final':
        # Stage transitions do not alter the evidence attached to a grant.  A
        # different round, source or agreement still requires a new grant.
        valid=raw.execute('''SELECT 1 FROM manuscripts m JOIN author_agreements a ON a.manuscript_id=m.manuscript_id
          JOIN eic_decisions d ON d.decision_id=a.decision_id AND d.manuscript_id=m.manuscript_id
          WHERE m.manuscript_id=? AND m.review_round=? AND a.agreement_id=? AND d.decision_id=?
          AND a.author_id=m.author_id AND a.status='accepted' AND d.decision='accept' AND d.review_round=?''',
          (row[0],row[2],row[3],row[4],row[2])).fetchone()
        if row[1]!='review_round' or not valid:raise HTTPException(403,'Distribution round unavailable')
    else:
        try:current=resolve(raw,row[0],row[9])
        except HTTPException:raise HTTPException(403,'Distribution round unavailable') from None
        if current!=tuple(row[1:5]):raise HTTPException(403,'Distribution round unavailable')
    return row


def validate_if_present(raw,grant_id):
    """Legacy reads remain available before the explicit 032 cutover."""
    marker=raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='032_editor_distribution_rounds'").fetchone()
    table=raw.execute("SELECT 1 FROM sqlite_master WHERE name='editor_distribution_grant_rounds'").fetchone()
    if not marker and not table:return None
    return validate_grant(raw,grant_id)


def authorize_unconfigured_source(raw,mid,user_id,digest,kind=None):
    """Enforce prospective grants while leaving pre-cutover access unchanged."""
    marker=raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='032_editor_distribution_rounds'").fetchone()
    table=raw.execute("SELECT 1 FROM sqlite_master WHERE name='editor_distribution_grant_rounds'").fetchone()
    if not marker and not table:return False
    require_schema(raw)
    grants=raw.execute('''SELECT g.grant_id,g.initial_invitation_id,g.final_invitation_id FROM distribution_grants g
      LEFT JOIN editor_distribution_legacy_grants l ON l.grant_id=g.grant_id
      WHERE g.manuscript_id=? AND g.recipient_id=? AND g.recipient_role='editor' AND l.grant_id IS NULL''',(mid,user_id)).fetchall()
    if kind=='initial':grants=[g for g in grants if g[1] is not None]
    elif kind=='final':grants=[g for g in grants if g[2] is not None]
    if not grants:return False
    from app.routers.document_distribution import _invite
    for gid,initial,final in grants:
        try:
            if _invite(raw,mid,'initial' if initial else 'final',initial or final)!=user_id:continue
            evidence=validate_grant(raw,gid)
            if evidence and evidence[6]==digest:return True
        except HTTPException as exc:
            if exc.status_code>=500:raise
    raise HTTPException(403,'Distribution round unavailable')

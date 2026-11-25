"""Synchronous, leased processing of one acceptance-bound editor intent."""
import time
import logging
import os
from importlib import import_module
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from app.reviewer_artifact_storage import StorageError, StorageMetadata

LEASE_US=60_000_000
logger=logging.getLogger(__name__)


def validate_processing_schema(db):
    from app.automatic_distribution_intents import validate_intent_schema
    from app.routers.document_distribution import _policy_schema, _provenance_schema
    conn=db.connection();_policy_schema(db);_provenance_schema(db)
    try: validate_intent_schema(conn)
    except (RuntimeError,SQLAlchemyError): raise HTTPException(503,'Automatic processing unavailable') from None
    module=import_module('migrations.030_automatic_processing')
    if not conn.exec_driver_sql('SELECT 1 FROM schema_migrations WHERE migration_id=?',(module.MIGRATION_ID,)).first():
        raise HTTPException(503,'Automatic processing unavailable')
    for name,expected in module.DDL.items():
        row=conn.exec_driver_sql('SELECT sql FROM sqlite_master WHERE name=?',(name,)).first()
        if not row or not row[0] or module.normalize(row[0])!=module.normalize(expected):
            raise HTTPException(503,'Automatic processing unavailable')


def _event(raw,intent,state,stamp,reason=None,grant=None):
    seq=raw.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM controlled_automatic_processing_events WHERE intent_id=?',(intent,)).fetchone()[0]
    raw.execute('INSERT INTO controlled_automatic_processing_events VALUES(?,?,?,?,?,?,?)',(uuid4().hex,intent,seq,state,reason,grant,stamp))


def _eligible(raw,intent_id):
    from app.routers.document_distribution import _actor, _invite, _manuscript, _source
    row=raw.execute('''SELECT i.manuscript_id,i.invitation_kind,i.invitation_id,i.recipient_id,i.policy_id,
       i.policy_version,i.source_ref,i.source_sha256,i.accepted_at,p.actor_id,p.authorized_at,p.mode,r.policy_id,
       i.idempotency_key,i.fingerprint,p.version,p.source_ref,p.source_sha256,p.invitation_kind,p.manuscript_id
       FROM controlled_automatic_intents i JOIN controlled_source_policies p ON p.policy_id=i.policy_id
       LEFT JOIN controlled_source_policy_revocations r ON r.policy_id=p.policy_id WHERE i.intent_id=?''',(intent_id,)).fetchone()
    if not row: raise HTTPException(404,'Intent unavailable')
    mid,kind,iid,recipient,policy,version,ref,digest,accepted,actor,authorized,mode,revoked,key,fingerprint,pversion,pref,pdigest,pkind,pmid=row
    import hashlib,json
    from app.strict_utc import canonical_utc
    try:
        if canonical_utc(authorized)!=authorized or canonical_utc(accepted)!=accepted: raise ValueError('Noncanonical timestamp')
    except ValueError: raise HTTPException(409,'Authorization evidence unavailable') from None
    expected_key=hashlib.sha256(f'editor-acceptance:{kind}:{iid}'.encode()).hexdigest()
    expected_fingerprint=hashlib.sha256(json.dumps([mid,kind,iid,recipient,policy,version,ref,digest,accepted],separators=(',',':')).encode()).hexdigest()
    if (key!=expected_key or fingerprint!=expected_fingerprint or (pversion,pref,pdigest,pkind,pmid)!=(version,ref,digest,kind,mid)):
        raise HTTPException(409,'Authorization evidence unavailable')
    _actor(raw,actor,'eic')
    if mode!='automatic' or revoked is not None or authorized>=accepted: raise HTTPException(409,'Policy unavailable')
    if _invite(raw,mid,kind,iid)!=recipient: raise HTTPException(409,'Assignment unavailable')
    if not raw.execute("SELECT 1 FROM account_lifecycle WHERE user_id=? AND state='active'",(recipient,)).fetchone(): raise HTTPException(409,'Editor unavailable')
    table='initial_editor_invitations' if kind=='initial' else 'final_editor_invitations'
    actual=raw.execute(f'SELECT responded_at FROM {table} WHERE invitation_id=?',(iid,)).fetchone()
    if not actual or not actual[0] or actual[0].replace(' ','T')+'Z'!=accepted: raise HTTPException(409,'Acceptance unavailable')
    manuscript=raw.execute('SELECT status FROM manuscripts WHERE manuscript_id=?',(mid,)).fetchone()
    if not manuscript or manuscript[0] != ('initial_editing' if kind=='initial' else 'final_editing'): raise HTTPException(409,'Workflow unavailable')
    if kind=='final':
        agreement=raw.execute('SELECT status FROM author_agreements WHERE manuscript_id=? ORDER BY agreement_id DESC LIMIT 1',(mid,)).fetchone()
        if not agreement or agreement[0]!='accepted': raise HTTPException(409,'Workflow unavailable')
    from app.editor_distribution_rounds import require_schema,resolve
    require_schema(raw)
    recorded=raw.execute('SELECT round_kind,review_round,agreement_id,decision_id FROM editor_distribution_intent_rounds WHERE intent_id=? AND manuscript_id=?',(intent_id,mid)).fetchone()
    if not recorded or recorded!=resolve(raw,mid,kind):raise HTTPException(409,'Distribution round unavailable')
    stored=_manuscript(raw,mid,for_source=True)
    if stored!=ref: raise HTTPException(409,'Source changed')
    data,fmt,actual_digest=_source(mid,stored)
    if actual_digest!=digest: raise HTTPException(409,'Source changed')
    return row,data,fmt


def process_intent(db, intent_id):
    """Participate for the entire multi-transaction processing operation."""
    directory = os.environ.get('GSUB_MAINTENANCE_ROOT')
    if not directory:
        return _process_intent(db, intent_id)
    from app.maintenance_barrier import MaintenanceActive, MaintenanceBarrier
    try:
        participant = MaintenanceBarrier(directory).operation()
        participant.__enter__()
    except (MaintenanceActive, OSError, ValueError, RuntimeError):
        raise HTTPException(503, 'Automatic processing temporarily unavailable') from None
    try:
        return _process_intent(db, intent_id)
    finally:
        participant.__exit__(None, None, None)


def _process_intent(db,intent_id):
    """Process or reconcile a single intent; failures never grant access."""
    from app.routers.document_distribution import _begin, _now, _storage
    token=uuid4().hex; claimed=False
    try:
        raw=_begin(db);validate_processing_schema(db)
        existing=raw.execute('''SELECT p.grant_id FROM controlled_automatic_grant_provenance p
            WHERE p.intent_id=? AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=p.grant_id)''',(intent_id,)).fetchone()
        if existing:
            _eligible(raw,intent_id)
            from app.editor_distribution_rounds import validate_grant
            validate_grant(raw,existing[0]);db.rollback();return {'status':'granted','grant_id':existing[0]}
        if raw.execute('SELECT 1 FROM controlled_automatic_grant_provenance WHERE intent_id=?',(intent_id,)).fetchone(): raise HTTPException(409,'Grant revoked')
        if not raw.execute('SELECT 1 FROM controlled_automatic_intents WHERE intent_id=?',(intent_id,)).fetchone(): raise HTTPException(404,'Intent unavailable')
        now_us=time.time_ns()//1000
        claim=raw.execute('SELECT expires_us FROM controlled_automatic_claims WHERE intent_id=?',(intent_id,)).fetchone()
        if claim and claim[0]>now_us: raise HTTPException(409,'Processing already in progress')
        raw.execute('INSERT INTO controlled_automatic_claims VALUES(?,?,?) ON CONFLICT(intent_id) DO UPDATE SET lease_token=excluded.lease_token,expires_us=excluded.expires_us',(intent_id,token,now_us+LEASE_US))
        _event(raw,intent_id,'processing',_now())
        db.commit();claimed=True
        raw=_begin(db);validate_processing_schema(db)
        row,data,fmt=_eligible(raw,intent_id)
        mid,kind,iid,recipient,policy,version,ref,digest,accepted,actor,authorized,*_=row
        key='auto_'+intent_id
        import hashlib,json
        fingerprint=hashlib.sha256(json.dumps([mid,kind,iid,digest],separators=(',',':')).encode()).hexdigest()
        reservation=raw.execute('SELECT storage_id,manuscript_id,sha256,byte_size,format,request_fingerprint FROM distribution_reservations WHERE actor_id=? AND idempotency_key=?',(actor,key)).fetchone()
        if reservation:
            if reservation[1:]!=(mid,digest,len(data),fmt,fingerprint): raise HTTPException(409,'Request conflict')
            storage_id=reservation[0]
        else:
            storage_id=uuid4().hex
            raw.execute('INSERT INTO distribution_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(storage_id,mid,actor,'editor_source',None,None,digest,len(data),fmt,key,fingerprint,_now()))
        db.commit()
        meta=StorageMetadata(storage_id,digest,len(data),fmt)
        with _storage() as store:
            try: store.reconcile_reserved(meta)
            except StorageError: store.publish_reserved(storage_id,data,fmt)
            store.reconcile_reserved(meta)
        raw=_begin(db);validate_processing_schema(db)
        current,_,_=_eligible(raw,intent_id)
        claim=raw.execute('SELECT lease_token,expires_us FROM controlled_automatic_claims WHERE intent_id=?',(intent_id,)).fetchone()
        if current!=row or not claim or claim[0]!=token or claim[1]<=time.time_ns()//1000: raise HTTPException(409,'Processing authorization changed')
        existing=raw.execute('SELECT grant_id FROM controlled_automatic_grant_provenance WHERE intent_id=?',(intent_id,)).fetchone()
        if existing: db.rollback();return {'status':'granted','grant_id':existing[0]}
        col='initial_invitation_id' if kind=='initial' else 'final_invitation_id'
        duplicate=raw.execute(f'''SELECT g.grant_id FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id
            WHERE g.manuscript_id=? AND g.recipient_id=? AND g.{col}=? AND a.sha256=?
            AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=g.grant_id)''',(mid,recipient,iid,digest)).fetchone()
        if duplicate: raise HTTPException(409,'Existing grant requires review')
        ver=raw.execute("SELECT COALESCE(MAX(version),0)+1 FROM distribution_artifacts WHERE manuscript_id=? AND kind='editor_source'",(mid,)).fetchone()[0]
        artifact_id=uuid4().hex;grant_id=uuid4().hex;stamp=_now()
        raw.execute('INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(artifact_id,mid,'editor_source',ver,storage_id,digest,len(data),fmt,None,None,actor,stamp))
        raw.execute('INSERT INTO distribution_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(grant_id,mid,artifact_id,recipient,'editor',iid if kind=='initial' else None,iid if kind=='final' else None,None,None,actor,'manual','created','not_requested',key,fingerprint,stamp))
        raw.execute('INSERT INTO controlled_automatic_grant_provenance VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (intent_id,grant_id,mid,policy,version,ref,digest,kind,iid,recipient,actor,authorized,accepted,stamp))
        round_evidence=raw.execute('SELECT round_kind,review_round,agreement_id,decision_id FROM editor_distribution_intent_rounds WHERE intent_id=?',(intent_id,)).fetchone()
        raw.execute('INSERT INTO editor_distribution_grant_rounds VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (grant_id,intent_id,mid,*round_evidence,ref,digest,ver,recipient,kind,iid,'automatic',actor,key,stamp))
        raw.execute("INSERT INTO notifications(user_id,manuscript_id,notification_type,message,is_read,created_at) VALUES(?,?,?,?,?,?)",(recipient,mid,'document_distributed','An editorial document is available.',0,stamp))
        _event(raw,intent_id,'granted',stamp,grant=grant_id)
        db.commit();return {'status':'granted','grant_id':grant_id}
    except Exception as exc:
        db.rollback()
        if claimed:
            try:
                raw=_begin(db);validate_processing_schema(db)
                claim=raw.execute('SELECT lease_token FROM controlled_automatic_claims WHERE intent_id=?',(intent_id,)).fetchone()
                if claim and claim[0]==token:
                    reason=('source_changed' if isinstance(exc,HTTPException) and exc.detail=='Source changed'
                            else 'authorization_unavailable' if isinstance(exc,HTTPException) and exc.status_code==409
                            else 'processing_unavailable')
                    _event(raw,intent_id,'failed',_now(),reason=reason)
                    raw.execute('UPDATE controlled_automatic_claims SET expires_us=1 WHERE intent_id=?',(intent_id,))
                    db.commit()
                else: db.rollback()
            except Exception:
                db.rollback()
                logger.warning('Automatic distribution failure evidence could not be recorded')
        if isinstance(exc,HTTPException): raise
        raise HTTPException(503,'Automatic processing unavailable') from None

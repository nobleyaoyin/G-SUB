"""Manual editor grants over immutable private snapshots; no automatic release."""
import hashlib
import json
import os
import re
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, SessionTransactionOrigin
from sqlalchemy.exc import SQLAlchemyError
from app.database import get_db
from app.models import User
from app.routers.users import require_role
from app.config import DATA_ROOT
from app.routers.manuscripts import ALLOWED_MANUSCRIPT_EXTENSIONS, MAX_MANUSCRIPT_FILE_SIZE, validate_manuscript_file
from app.reviewer_artifact_storage import ArtifactStorage, StorageError, StorageMetadata
from app.strict_utc import canonical_utc

router=APIRouter(prefix='/document-distribution', tags=['Document distribution'])

class GrantRequest(BaseModel):
    invitation_kind: str = Field(pattern='^(initial|final)$')
    invitation_id: int = Field(gt=0)
    source_sha256: str = Field(pattern='^[0-9a-f]{64}$')
    idempotency_key: str = Field(min_length=16,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')

class RevokeRequest(BaseModel):
    reason: str = Field(min_length=1,max_length=1000)

class PolicyRequest(BaseModel):
    invitation_kind: Literal['initial','final']
    mode: Literal['manual','automatic'] = 'manual'
    source_sha256: str = Field(pattern='^[0-9a-f]{64}$')
    confirmed: Literal[True]


def _storage():
    root=os.environ.get('GSUB_DISTRIBUTION_PRIVATE_ROOT','')
    if not root: raise HTTPException(503,'Private distribution storage is not configured')
    try: return ArtifactStorage(root)
    except (StorageError,OSError): raise HTTPException(503,'Private distribution storage unavailable') from None


def _begin(db):
    tx=db.get_transaction()
    if db.new or db.dirty or db.deleted or db.in_nested_transaction() or (tx is not None and tx.origin is not SessionTransactionOrigin.AUTOBEGIN):
        raise HTTPException(503,'A fresh distribution transaction is required')
    connection=db.connection()
    raw=connection.connection.driver_connection
    if connection.dialect.name!='sqlite' or raw.in_transaction: raise HTTPException(503,'A fresh distribution transaction is required')
    try:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        if not raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='021_document_distribution'").fetchone(): raise HTTPException(503,'Distribution schema unavailable')
        return raw
    except (sqlite3.Error,SQLAlchemyError): raise HTTPException(503,'Distribution database unavailable') from None


def _now(): return canonical_utc(datetime.now(timezone.utc))


def _actor(raw, user_id, role):
    if not raw.execute('SELECT 1 FROM users WHERE user_id=? AND role=?',(user_id,role)).fetchone(): raise HTTPException(403,'Not authorized')


def _manuscript(raw, mid, *, for_source=False):
    row=raw.execute("SELECT file_path,status FROM manuscripts WHERE manuscript_id=? AND status!='draft'",(mid,)).fetchone()
    if not row: raise HTTPException(404,'Manuscript unavailable')
    if for_source and row[1] in ('revision_required','initial_revision_required'): raise HTTPException(409,'Document unavailable during revision')
    return row[0]


def _invite(raw, mid, kind, iid):
    table={'initial':'initial_editor_invitations','final':'final_editor_invitations'}.get(kind)
    if table is None: raise HTTPException(400,'Invitation unavailable')
    row=raw.execute(f"SELECT i.editor_id FROM {table} i JOIN users u ON u.user_id=i.editor_id WHERE i.invitation_id=? AND i.manuscript_id=? AND i.status='accepted' AND u.role='editor'",(iid,mid)).fetchone()
    if not row: raise HTTPException(409,'Accepted editor invitation unavailable')
    from app.editor_invitation_revocation import is_revoked_raw
    if is_revoked_raw(raw,kind,iid): raise HTTPException(409,'Editor invitation unavailable')
    return row[0]


@router.get('/manuscripts/{mid}/editor-invitations')
def editor_invitations(mid:int,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');_manuscript(raw,mid)
        from app.editor_invitation_revocation import is_revoked_raw
        if not raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='031_editor_invitation_revocation'").fetchone():raise HTTPException(503,'Invitation revocation unavailable')
        is_revoked_raw(raw,'initial',0)
        result=[]
        for kind,table in (('initial','initial_editor_invitations'),('final','final_editor_invitations')):
            rows=raw.execute(f'''SELECT i.invitation_id,i.editor_id,i.status,i.invited_at,i.responded_at,r.actor_id,r.reason,r.revoked_at
                FROM {table} i LEFT JOIN editor_invitation_revocations r ON r.invitation_kind=? AND r.invitation_id=i.invitation_id
                WHERE i.manuscript_id=? ORDER BY i.invitation_id DESC''',(kind,mid)).fetchall()
            for iid,recipient,status,invited,responded,actor,reason,revoked in rows:
                result.append({'invitation_kind':kind,'invitation_id':iid,'recipient_id':recipient,'status':'revoked' if revoked else status,
                    'original_status':status,'invited_at':invited,'responded_at':responded,'revoked_at':revoked,'revoked_by':actor,'reason':reason})
        return result
    finally:db.rollback()


@router.post('/manuscripts/{mid}/editor-invitations/{kind}/{iid}/revoke')
def revoke_editor_invitation(mid:int,kind:Literal['initial','final'],iid:int,req:RevokeRequest,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');_manuscript(raw,mid)
        from app.editor_invitation_revocation import is_revoked_raw
        if not raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='031_editor_invitation_revocation'").fetchone():raise HTTPException(503,'Invitation revocation unavailable')
        if is_revoked_raw(raw,kind,iid):raise HTTPException(409,'Invitation already revoked')
        table='initial_editor_invitations' if kind=='initial' else 'final_editor_invitations'
        row=raw.execute(f'SELECT editor_id,status FROM {table} WHERE invitation_id=? AND manuscript_id=?',(iid,mid)).fetchone()
        if not row:raise HTTPException(404,'Invitation unavailable')
        if row[1] not in ('pending','accepted') or not req.reason.strip():raise HTTPException(409,'Invitation unavailable')
        stamp=_now()
        raw.execute('INSERT INTO editor_invitation_revocations VALUES(?,?,?,?,?,?,?)',(kind,iid,mid,row[0],user.user_id,req.reason.strip(),stamp))
        db.commit();return {'status':'revoked','invitation_kind':kind,'invitation_id':iid,'revoked_at':stamp}
    except HTTPException:db.rollback();raise
    except Exception:db.rollback();raise HTTPException(503,'Invitation revocation unavailable') from None


def _source(mid, stored):
    # Strictly select the current author's manuscript file, never an arbitrary path.
    if not isinstance(stored,str) or '..' in Path(stored).parts: raise HTTPException(409,'Document unavailable')
    base=Path(os.path.abspath(DATA_ROOT)); path=Path(os.path.abspath(base / stored)); root=base/'uploads'/'manuscripts'/str(mid)
    if path.parent!=root or path.suffix.lower() not in ALLOWED_MANUSCRIPT_EXTENSIONS: raise HTTPException(409,'Document unavailable')
    if not all(hasattr(os,x) for x in ('O_NOFOLLOW','O_DIRECTORY','O_NONBLOCK')) or os.open not in os.supports_dir_fd: raise HTTPException(503,'Secure file access unavailable')
    try:
        fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            for part in path.parts[1:-1]:
                new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd); os.close(fd); fd=new
            f=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
            try:
                before=os.fstat(f)
                if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=MAX_MANUSCRIPT_FILE_SIZE: raise OSError('Invalid file')
                chunks=[]; remaining=MAX_MANUSCRIPT_FILE_SIZE+1
                while remaining:
                    chunk=os.read(f,min(remaining,65536))
                    if not chunk: break
                    chunks.append(chunk);remaining-=len(chunk)
                data=b''.join(chunks);after=os.fstat(f)
                if len(data)!=before.st_size or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns): raise OSError('File changed')
            finally: os.close(f)
        finally: os.close(fd)
        validate_manuscript_file(path.name,data,historical=True)
        return data,path.suffix.lower()[1:],hashlib.sha256(data).hexdigest()
    except (OSError,ValueError,HTTPException): raise HTTPException(409,'Document unavailable') from None


def _fingerprint(mid, req):
    return hashlib.sha256(json.dumps([mid,req.invitation_kind,req.invitation_id,req.source_sha256],separators=(',',':')).encode()).hexdigest()


def _policy_schema(db):
    # Refuse partial or altered evidence schemas rather than treating them as
    # an empty configuration. Do not create or migrate tables at runtime.
    from app.controlled_source_authorization import _validate_policy_schema
    _validate_policy_schema(db.connection())


def _provenance_schema(db):
    from importlib import import_module
    module=import_module('migrations.027_source_grant_provenance')
    conn=db.connection()
    if not conn.exec_driver_sql("SELECT 1 FROM schema_migrations WHERE migration_id='027_source_grant_provenance'").first():
        raise HTTPException(503,'Source provenance unavailable')
    for name,expected in module.DDL.items():
        row=conn.exec_driver_sql('SELECT sql FROM sqlite_master WHERE name=?',(name,)).first()
        if not row or not row[0] or module.normalize(row[0])!=module.normalize(expected):
            raise HTTPException(503,'Source provenance unavailable')


def _manual_policy(db,raw,mid,kind,recipient,stored,digest):
    tables={r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'automatic_distribution_configurations' in tables and raw.execute('SELECT 1 FROM automatic_distribution_configurations WHERE manuscript_id=? LIMIT 1',(mid,)).fetchone():
        raise HTTPException(503,'Source policy unavailable')
    if 'controlled_source_policies' not in tables:
        if raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='026_controlled_source_policy'").fetchone(): raise HTTPException(503,'Source policy unavailable')
        return None
    row=raw.execute('''SELECT p.policy_id,p.version,p.mode,p.source_ref,p.source_sha256,r.policy_id
        FROM controlled_source_policies p LEFT JOIN controlled_source_policy_revocations r ON r.policy_id=p.policy_id
        WHERE p.manuscript_id=? AND p.invitation_kind=? ORDER BY p.version DESC LIMIT 1''',(mid,kind)).fetchone()
    if not row: return None
    _policy_schema(db);_provenance_schema(db)
    if row[5] is not None or row[2]!='manual' or row[3]!=stored or row[4]!=digest:
        raise HTTPException(409,'Current policy or document unavailable')
    if not raw.execute("SELECT 1 FROM account_lifecycle WHERE user_id=? AND state='active'",(recipient,)).fetchone():
        raise HTTPException(409,'Editor account unavailable')
    return row[0],row[1]


def _check_existing_provenance(raw,policy,grant_id):
    if policy and not raw.execute('SELECT 1 FROM controlled_source_grant_provenance WHERE grant_id=? AND policy_id=? AND policy_version=?',(grant_id,*policy)).fetchone():
        raise HTTPException(409,'Existing grant lacks current source provenance; revoke it before creating another')


@router.get('/manuscripts/{mid}/policies')
def policies(mid:int,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');_manuscript(raw,mid);_policy_schema(db)
        rows=raw.execute('''SELECT p.policy_id,p.invitation_kind,p.mode,p.source_sha256,p.version,
            p.actor_id,p.authorized_at,r.revoked_at
            FROM controlled_source_policies p LEFT JOIN controlled_source_policy_revocations r ON r.policy_id=p.policy_id
            WHERE p.manuscript_id=? ORDER BY p.invitation_kind,p.version DESC''',(mid,)).fetchall()
        return {'default_mode':'manual','policies':[{'policy_id':i,'invitation_kind':kind,'mode':mode,
            'source_sha256':digest,'version':version,'actor_id':actor,'authorized_at':created,
            'revoked_at':revoked,'status':'revoked' if revoked else 'active'}
            for i,kind,mode,digest,version,actor,created,revoked in rows]}
    finally: db.rollback()


@router.get('/manuscripts/{mid}/automatic-intents')
def automatic_intents(mid:int,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');_manuscript(raw,mid);_policy_schema(db);_provenance_schema(db)
        from importlib import import_module
        module=import_module('migrations.028_automatic_distribution_intents')
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(module.MIGRATION_ID,)).fetchone():
            raise HTTPException(503,'Automatic intent history unavailable')
        from app.automatic_distribution_intents import validate_intent_schema
        try: validate_intent_schema(db.connection())
        except (RuntimeError,SQLAlchemyError): raise HTTPException(503,'Automatic intent history unavailable') from None
        installed=raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='030_automatic_processing'").fetchone()
        if not installed:
            rows=raw.execute('''SELECT i.intent_id,i.policy_id,i.policy_version,i.invitation_kind,i.invitation_id,
                i.accepted_at,CASE WHEN r.policy_id IS NULL THEN e.state ELSE 'revoked' END,
                COALESCE(r.revoked_at,e.occurred_at) FROM controlled_automatic_intents i
                JOIN controlled_automatic_events e ON e.intent_id=i.intent_id
                LEFT JOIN controlled_source_policy_revocations r ON r.policy_id=i.policy_id
                WHERE i.manuscript_id=? AND e.sequence=(SELECT MAX(x.sequence) FROM controlled_automatic_events x WHERE x.intent_id=i.intent_id)
                ORDER BY i.created_at DESC,i.intent_id''',(mid,)).fetchall()
            return [{'intent_id':i,'policy_id':p,'policy_version':v,'invitation_kind':kind,'invitation_id':iid,
                     'accepted_at':accepted,'state':state,'updated_at':updated} for i,p,v,kind,iid,accepted,state,updated in rows]
        from app.automatic_distribution_processor import validate_processing_schema
        validate_processing_schema(db)
        rows=raw.execute('''SELECT i.intent_id,i.policy_id,i.policy_version,i.invitation_kind,i.invitation_id,
            i.accepted_at,CASE WHEN r.policy_id IS NOT NULL OR gr.grant_id IS NOT NULL THEN 'revoked' ELSE COALESCE(pe.state,e.state) END,
            COALESCE(gr.created_at,r.revoked_at,pe.occurred_at,e.occurred_at),pe.reason_code,pe.grant_id,c.expires_us FROM controlled_automatic_intents i
            JOIN controlled_automatic_events e ON e.intent_id=i.intent_id
            LEFT JOIN controlled_source_policy_revocations r ON r.policy_id=i.policy_id
            LEFT JOIN controlled_automatic_processing_events pe ON pe.intent_id=i.intent_id AND pe.sequence=(SELECT MAX(y.sequence) FROM controlled_automatic_processing_events y WHERE y.intent_id=i.intent_id)
            LEFT JOIN controlled_automatic_claims c ON c.intent_id=i.intent_id
            LEFT JOIN distribution_revocations gr ON gr.grant_id=pe.grant_id
            WHERE i.manuscript_id=? AND e.sequence=(SELECT MAX(x.sequence) FROM controlled_automatic_events x WHERE x.intent_id=i.intent_id)
            ORDER BY i.created_at DESC,i.intent_id''',(mid,)).fetchall()
        import time
        now_us=time.time_ns()//1000
        from app.editor_invitation_revocation import is_revoked_raw
        from app.editor_distribution_rounds import require_schema
        round_marker=raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='032_editor_distribution_rounds'").fetchone()
        round_table=raw.execute("SELECT 1 FROM sqlite_master WHERE name='editor_distribution_intent_rounds'").fetchone()
        if round_marker or round_table:require_schema(raw)
        result=[]
        for i,p,v,kind,iid,accepted,state,updated,reason,grant,expiry in rows:
            if is_revoked_raw(raw,kind,iid):state='revoked'
            if state not in ('granted','revoked') and (not round_table or not raw.execute('SELECT 1 FROM editor_distribution_intent_rounds WHERE intent_id=? AND manuscript_id=?',(i,mid)).fetchone()):
                state='blocked'
                reason='round_evidence_required'
            result.append({'intent_id':i,'policy_id':p,'policy_version':v,'invitation_kind':kind,'invitation_id':iid,
                 'accepted_at':accepted,'state':state,'updated_at':updated,'reason_code':reason,'grant_id':grant,
                 'retryable':state=='pending' or (state=='failed' and reason=='processing_unavailable') or (state=='processing' and expiry is not None and expiry<=now_us)})
        return result
    finally: db.rollback()


@router.post('/manuscripts/{mid}/automatic-intents/{intent_id}/process')
def process_automatic_intent(mid:int,intent_id:str,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    if not re.fullmatch('[0-9a-f]{32}',intent_id): raise HTTPException(404,'Intent unavailable')
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');_manuscript(raw,mid)
        if not raw.execute('SELECT 1 FROM controlled_automatic_intents WHERE intent_id=? AND manuscript_id=?',(intent_id,mid)).fetchone():
            raise HTTPException(404,'Intent unavailable')
    except sqlite3.Error:
        raise HTTPException(503,'Automatic processing unavailable') from None
    finally: db.rollback()
    from app.automatic_distribution_processor import process_intent
    return process_intent(db,intent_id)


@router.get('/manuscripts/{mid}/automatic-capture-failures')
def automatic_capture_failures(mid:int,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');_manuscript(raw,mid);_policy_schema(db);_provenance_schema(db)
        from importlib import import_module
        module=import_module('migrations.029_intent_precision_failures')
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(module.MIGRATION_ID,)).fetchone():
            raise HTTPException(503,'Capture failure history unavailable')
        for name,expected in module.DDL.items():
            if name=='controlled_automatic_intents_check': continue
            row=raw.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
            if not row or not row[0] or module.normalize(row[0])!=module.normalize(expected):
                raise HTTPException(503,'Capture failure history unavailable')
        rows=raw.execute('''SELECT failure_id,policy_id,invitation_kind,invitation_id,reason_code,occurred_at
            FROM controlled_automatic_capture_failures WHERE manuscript_id=? ORDER BY occurred_at DESC,failure_id''',(mid,)).fetchall()
        return [{'failure_id':i,'policy_id':p,'invitation_kind':kind,'invitation_id':iid,'reason_code':reason,'occurred_at':stamp}
                for i,p,kind,iid,reason,stamp in rows]
    finally: db.rollback()


@router.post('/manuscripts/{mid}/policies',status_code=201)
def create_policy(mid:int,req:PolicyRequest,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');stored=_manuscript(raw,mid,for_source=True);_policy_schema(db)
        _,_,digest=_source(mid,stored)
        if digest!=req.source_sha256: raise HTTPException(409,'Document changed; refresh before authorizing')
        _provenance_schema(db)
        from app.editor_distribution_rounds import require_schema
        require_schema(raw)
        if req.mode=='automatic':
            from app.automatic_distribution_processor import validate_processing_schema
            validate_processing_schema(db)
            with _storage(): pass
        if raw.execute('SELECT 1 FROM automatic_distribution_configurations WHERE manuscript_id=? LIMIT 1',(mid,)).fetchone():
            raise HTTPException(503,'Existing candidate policy requires reconciliation')
        version=raw.execute('SELECT COALESCE(MAX(version),0)+1 FROM controlled_source_policies WHERE manuscript_id=? AND invitation_kind=?',(mid,req.invitation_kind)).fetchone()[0]
        policy_id=uuid4().hex;now=_now()
        raw.execute('INSERT INTO controlled_source_policies VALUES(?,?,?,?,?,?,?,?,?,?)',
            (policy_id,mid,req.invitation_kind,req.mode,'current_author_manuscript',stored,digest,version,user.user_id,now))
        db.commit()
        return {'policy_id':policy_id,'invitation_kind':req.invitation_kind,'mode':req.mode,'source_sha256':digest,
            'version':version,'actor_id':user.user_id,'authorized_at':now,'status':'active'}
    except HTTPException:
        db.rollback();raise
    except sqlite3.IntegrityError:
        db.rollback();raise HTTPException(409,'A current policy already exists; revoke it first') from None
    except (sqlite3.Error,SQLAlchemyError):
        db.rollback();raise HTTPException(503,'Policy outcome unavailable; refresh history') from None


@router.post('/manuscripts/{mid}/policies/{policy_id}/revoke')
def revoke_policy(mid:int,policy_id:str,req:RevokeRequest,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    if not re.fullmatch('[0-9a-f]{32}',policy_id): raise HTTPException(404,'Policy unavailable')
    if not req.reason.strip(): raise HTTPException(422,'Reason required')
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');_manuscript(raw,mid);_policy_schema(db)
        if not raw.execute('SELECT 1 FROM controlled_source_policies WHERE policy_id=? AND manuscript_id=?',(policy_id,mid)).fetchone(): raise HTTPException(404,'Policy unavailable')
        raw.execute('INSERT OR IGNORE INTO controlled_source_policy_revocations VALUES(?,?,?,?)',(policy_id,user.user_id,req.reason.strip(),_now()))
        db.commit();return {'status':'revoked'}
    except HTTPException:
        db.rollback();raise
    except (sqlite3.Error,SQLAlchemyError):
        db.rollback();raise HTTPException(503,'Policy outcome unavailable; refresh history') from None


@router.get('/manuscripts/{mid}/candidates')
def candidates(mid:int, user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');stored=_manuscript(raw,mid,for_source=True);data,fmt,digest=_source(mid,stored)
        with _storage(): pass
        recipients=[]
        for kind,table in (('initial','initial_editor_invitations'),('final','final_editor_invitations')):
            rows=raw.execute(f"SELECT i.invitation_id,u.name FROM {table} i JOIN users u ON u.user_id=i.editor_id WHERE i.manuscript_id=? AND i.status='accepted' AND u.role='editor' ORDER BY i.invitation_id",(mid,)).fetchall()
            recipients.extend({'invitation_kind':kind,'invitation_id':i,'name':name} for i,name in rows)
        return {'document':{'source':'current manuscript','sha256':digest,'format':fmt,'byte_size':len(data)},'recipients':recipients}
    finally: db.rollback()


@router.post('/manuscripts/{mid}/grants')
def create_grant(mid:int, req:GrantRequest, user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    uid=user.user_id;fingerprint=_fingerprint(mid,req);raw=_begin(db)
    try:
        _actor(raw,uid,'eic');stored=_manuscript(raw,mid,for_source=True);recipient=_invite(raw,mid,req.invitation_kind,req.invitation_id)
        from app.editor_distribution_rounds import require_schema,resolve,validate_grant
        require_schema(raw);round_evidence=resolve(raw,mid,req.invitation_kind)
        data,fmt,digest=_source(mid,stored)
        if digest!=req.source_sha256: raise HTTPException(409,'Document changed; refresh before distributing')
        policy=_manual_policy(db,raw,mid,req.invitation_kind,recipient,stored,digest)
        existing=raw.execute('SELECT grant_id,fingerprint FROM distribution_grants WHERE actor_id=? AND idempotency_key=?',(uid,req.idempotency_key)).fetchone()
        if existing:
            if existing[1]!=fingerprint: raise HTTPException(409,'Idempotency key conflict')
            if raw.execute('SELECT 1 FROM distribution_revocations WHERE grant_id=?',(existing[0],)).fetchone(): raise HTTPException(409,'Grant revoked')
            _check_existing_provenance(raw,policy,existing[0])
            validate_grant(raw,existing[0])
            db.rollback()
            return {'grant_id':existing[0],'result':'access_granted','already_exists':True,'email':'not_requested'}
        reservation=raw.execute('SELECT storage_id,manuscript_id,sha256,byte_size,format,request_fingerprint FROM distribution_reservations WHERE actor_id=? AND idempotency_key=?',(uid,req.idempotency_key)).fetchone()
        if reservation:
            if reservation[1:]!=(mid,digest,len(data),fmt,fingerprint): raise HTTPException(409,'Idempotency key conflict')
            storage_id=reservation[0]
        else:
            storage_id=uuid4().hex
            raw.execute('INSERT INTO distribution_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(storage_id,mid,uid,'editor_source',None,None,digest,len(data),fmt,req.idempotency_key,fingerprint,_now()))
        db.commit()
    except HTTPException:
        db.rollback();raise
    except Exception:
        db.rollback();raise HTTPException(503,'Reservation outcome may be unknown; retry with the same key') from None
    meta=StorageMetadata(storage_id,digest,len(data),fmt)
    try:
        with _storage() as store:
            try: store.reconcile_reserved(meta)
            except StorageError: store.publish_reserved(storage_id,data,fmt)
            store.reconcile_reserved(meta)
    except (StorageError,OSError): raise HTTPException(503,'Publication outcome unavailable; retry with the same key') from None
    raw=_begin(db)
    try:
        _actor(raw,uid,'eic');stored2=_manuscript(raw,mid,for_source=True)
        if _invite(raw,mid,req.invitation_kind,req.invitation_id)!=recipient or stored2!=stored or _source(mid,stored2)[2]!=digest: raise HTTPException(409,'Document or invitation changed; refresh')
        require_schema(raw)
        if resolve(raw,mid,req.invitation_kind)!=round_evidence:raise HTTPException(409,'Distribution round changed; refresh')
        if _manual_policy(db,raw,mid,req.invitation_kind,recipient,stored2,digest)!=policy: raise HTTPException(409,'Policy changed; refresh')
        prior=raw.execute('SELECT grant_id FROM distribution_grants WHERE actor_id=? AND idempotency_key=?',(uid,req.idempotency_key)).fetchone()
        if prior:
            if raw.execute('SELECT 1 FROM distribution_revocations WHERE grant_id=?',(prior[0],)).fetchone():
                raise HTTPException(409,'Grant revoked')
            _check_existing_provenance(raw,policy,prior[0])
            validate_grant(raw,prior[0])
            db.rollback();return {'grant_id':prior[0],'result':'access_granted','already_exists':True,'email':'not_requested'}
        col='initial_invitation_id' if req.invitation_kind=='initial' else 'final_invitation_id'
        duplicate=raw.execute(f'SELECT g.grant_id FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id WHERE g.manuscript_id=? AND g.recipient_id=? AND g.{col}=? AND a.sha256=? AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=g.grant_id)',(mid,recipient,req.invitation_id,digest)).fetchone()
        if duplicate:
            _check_existing_provenance(raw,policy,duplicate[0])
            validate_grant(raw,duplicate[0])
            db.rollback();return {'grant_id':duplicate[0],'result':'access_granted','already_exists':True,'email':'not_requested'}
        version=raw.execute("SELECT COALESCE(MAX(version),0)+1 FROM distribution_artifacts WHERE manuscript_id=? AND kind='editor_source'",(mid,)).fetchone()[0]
        artifact_id=uuid4().hex;grant_id=uuid4().hex;now=_now()
        raw.execute('INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(artifact_id,mid,'editor_source',version,storage_id,digest,len(data),fmt,None,None,uid,now))
        raw.execute('INSERT INTO distribution_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(grant_id,mid,artifact_id,recipient,'editor',req.invitation_id if req.invitation_kind=='initial' else None,req.invitation_id if req.invitation_kind=='final' else None,None,None,uid,'manual','created','not_requested',req.idempotency_key,fingerprint,now))
        if policy:
            raw.execute('INSERT INTO controlled_source_grant_provenance VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (grant_id,policy[0],mid,policy[1],'current_author_manuscript',stored2,digest,recipient,req.invitation_kind,req.invitation_id,None,uid,now))
        raw.execute('INSERT INTO editor_distribution_grant_rounds VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (grant_id,None,mid,*round_evidence,stored2,digest,version,recipient,req.invitation_kind,req.invitation_id,'manual',uid,req.idempotency_key,now))
        raw.execute("INSERT INTO notifications(user_id,manuscript_id,notification_type,message,is_read,created_at) VALUES(?,?,?,?,?,?)",(recipient,mid,'document_distributed','An editorial document is available.',0,now))
        db.commit();return {'grant_id':grant_id,'result':'access_granted','already_exists':False,'email':'not_requested'}
    except HTTPException: db.rollback();raise
    except Exception: db.rollback();raise HTTPException(503,'Outcome may be unknown; retry with the same key') from None


@router.get('/my')
def my_grants(user:User=Depends(require_role('editor')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'editor')
        rows=raw.execute('''SELECT g.grant_id,g.manuscript_id,m.title,a.version,a.format,g.created_at,g.initial_invitation_id,g.final_invitation_id,a.sha256,a.storage_id,a.byte_size FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id JOIN manuscripts m ON m.manuscript_id=g.manuscript_id WHERE g.recipient_id=? AND m.status NOT IN ('draft','revision_required','initial_revision_required') AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=g.grant_id) ORDER BY g.created_at DESC''',(user.user_id,)).fetchall()
        result=[]
        has_auto=bool(raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='030_automatic_processing'").fetchone())
        if has_auto:
            from app.automatic_distribution_processor import validate_processing_schema
            validate_processing_schema(db)
        for gid,mid,title,version,fmt,created,initial,final,digest,storage_id,size in rows:
            try:
                if _invite(raw,mid,'initial' if initial else 'final',initial or final)!=user.user_id: continue
                from app.editor_distribution_rounds import validate_if_present
                round_row=validate_if_present(raw,gid)
                from app.controlled_source_authorization import authorize_source, source_may_be_controlled
                if source_may_be_controlled(db,mid):
                    with _storage() as store: data=store.read_verified(StorageMetadata(storage_id,digest,size,fmt))
                    authorize_source(db,user,mid,data,invitation_kind='initial' if initial else 'final',grant_id=gid)
            except HTTPException as exc:
                if exc.status_code>=500:raise
                continue
            except (StorageError,OSError): continue
            mode='automatic' if has_auto and raw.execute('SELECT 1 FROM controlled_automatic_grant_provenance WHERE grant_id=?',(gid,)).fetchone() else 'manual'
            result.append({'grant_id':gid,'manuscript_id':mid,'title':title,'version':version,'format':fmt,'sha256':digest,'created_at':created,'mode':mode,'round_kind':round_row[1] if round_row else 'historical_unknown','review_round':round_row[2] if round_row else None})
        return result
    finally: db.rollback()


@router.get('/manuscripts/{mid}/history')
def history(mid:int,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');_manuscript(raw,mid)
        rows=raw.execute('''SELECT g.grant_id,a.version,a.format,g.recipient_id,g.initial_invitation_id,g.final_invitation_id,g.created_at,g.notification_state,g.email_state,r.created_at,a.sha256,a.byte_size,g.actor_id FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id LEFT JOIN distribution_revocations r ON r.grant_id=g.grant_id WHERE g.manuscript_id=? ORDER BY g.created_at DESC''',(mid,)).fetchall()
        has_auto=bool(raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='030_automatic_processing'").fetchone())
        if has_auto:
            from app.automatic_distribution_processor import validate_processing_schema
            validate_processing_schema(db)
        has_manual_provenance=bool(raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='027_source_grant_provenance'").fetchone())
        if has_manual_provenance: _provenance_schema(db)
        result=[]
        from app.editor_invitation_revocation import is_revoked_raw
        has_round=bool(raw.execute("SELECT 1 FROM schema_migrations WHERE migration_id='032_editor_distribution_rounds'").fetchone())
        has_round_table=bool(raw.execute("SELECT 1 FROM sqlite_master WHERE name='editor_distribution_grant_rounds'").fetchone())
        if has_round or has_round_table:
            from app.editor_distribution_rounds import require_schema
            require_schema(raw)
        for g,v,f,recipient,initial,final,created,notification,email,revoked,digest,size,actor in rows:
            round_data=raw.execute('SELECT round_kind,review_round FROM editor_distribution_grant_rounds WHERE grant_id=?',(g,)).fetchone() if has_round else None
            round_status='historical_unknown'
            if has_round:
                legacy=raw.execute('SELECT 1 FROM editor_distribution_legacy_grants WHERE grant_id=?',(g,)).fetchone()
                if not legacy:
                    if revoked and round_data:round_status='recorded'
                    else:
                        from app.editor_distribution_rounds import validate_grant
                        try:validate_grant(raw,g);round_status='valid'
                        except HTTPException as exc:
                            if exc.status_code>=500:raise
                            round_status='unavailable'
            provenance=raw.execute('''SELECT p.policy_id,r.policy_id FROM controlled_automatic_grant_provenance p
                LEFT JOIN controlled_source_policy_revocations r ON r.policy_id=p.policy_id WHERE p.grant_id=?''',(g,)).fetchone() if has_auto else None
            mode='automatic' if provenance else 'manual'
            if not provenance and has_manual_provenance:
                provenance=raw.execute('''SELECT p.policy_id,r.policy_id FROM controlled_source_grant_provenance p
                    LEFT JOIN controlled_source_policy_revocations r ON r.policy_id=p.policy_id WHERE p.grant_id=?''',(g,)).fetchone()
            result.append({'grant_id':g,'version':v,'format':f,'recipient_id':recipient,'invitation_kind':'initial' if initial else 'final',
                'invitation_id':initial or final,'actor_id':actor,'created_at':created,'revoked_at':revoked,
                'notification':notification,'email':email,'status':'revoked' if revoked else 'access_granted','sha256':digest,'byte_size':size,
                'mode':mode,'policy_status':('revoked' if provenance[1] else 'active') if provenance else None,
                'invitation_revoked':is_revoked_raw(raw,'initial' if initial else 'final',initial or final),
                'round_kind':round_data[0] if round_data else round_status,'review_round':round_data[1] if round_data else None,
                'round_status':round_status})
        return result
    finally: db.rollback()


@router.get('/grants/{gid}/download')
def download(gid:str,user:User=Depends(require_role('editor')),db:Session=Depends(get_db)):
    if not re.fullmatch('[0-9a-f]{32}',gid): raise HTTPException(404,'Document unavailable')
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'editor')
        row=raw.execute('''SELECT g.manuscript_id,g.recipient_id,g.initial_invitation_id,g.final_invitation_id,a.storage_id,a.sha256,a.byte_size,a.format FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id WHERE g.grant_id=? AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=g.grant_id)''',(gid,)).fetchone()
        if not row or row[1]!=user.user_id: raise HTTPException(404,'Document unavailable')
        mid,_,initial,final,storage_id,digest,size,fmt=row;_manuscript(raw,mid,for_source=True)
        if _invite(raw,mid,'initial' if initial else 'final',initial or final)!=user.user_id: raise HTTPException(404,'Document unavailable')
        from app.editor_distribution_rounds import validate_if_present
        validate_if_present(raw,gid)
        try:
            with _storage() as store: data=store.read_verified(StorageMetadata(storage_id,digest,size,fmt))
        except StorageError: raise HTTPException(409,'Document unavailable') from None
        from app.controlled_source_authorization import authorize_source
        authorize_source(db, user, mid, data, invitation_kind='initial' if initial else 'final',grant_id=gid)
        return Response(data,media_type=ALLOWED_MANUSCRIPT_EXTENSIONS['.'+fmt],headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Disposition':f'attachment; filename="editor-document.{fmt}"'})
    finally: db.rollback()


@router.post('/grants/{gid}/revoke')
def revoke(gid:str,req:RevokeRequest,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    if not req.reason.strip(): raise HTTPException(422,'Reason required')
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');row=raw.execute('SELECT manuscript_id FROM distribution_grants WHERE grant_id=?',(gid,)).fetchone()
        if not row: raise HTTPException(404,'Grant unavailable')
        _manuscript(raw,row[0]);raw.execute('INSERT OR IGNORE INTO distribution_revocations VALUES(?,?,?,?)',(gid,user.user_id,req.reason.strip(),_now()));db.commit();return {'status':'revoked'}
    except HTTPException: db.rollback();raise
    except Exception: db.rollback();raise HTTPException(503,'Revocation outcome may be unknown; refresh history') from None


def _review_assignment(raw, assignment_id, user_id):
    row=raw.execute('''SELECT a.manuscript_id,a.review_round FROM review_assignments a
        JOIN manuscripts m ON m.manuscript_id=a.manuscript_id
        JOIN reviewer_invitations i ON i.assignment_id=a.assignment_id
        JOIN users u ON u.user_id=a.reviewer_id
        WHERE a.assignment_id=? AND a.reviewer_id=? AND u.role='reviewer'
        AND a.status='assigned' AND i.status='accepted' AND a.review_round=m.review_round
        AND m.status IN ('ready_for_peer_review','revised')
        AND NOT EXISTS (SELECT 1 FROM reviewer_invitation_invalidations x WHERE x.assignment_id=a.assignment_id)''',(assignment_id,user_id)).fetchone()
    if not row: raise HTTPException(409,'Active reviewer assignment unavailable')
    return row


def _reviewed_document_owner(raw, assignment_id, user_id):
    # A completed or historical assignment can retain access to its own output,
    # but an invalidated or unaccepted invitation never authorizes access.
    row = raw.execute('''SELECT a.manuscript_id,a.review_round FROM review_assignments a
        JOIN reviewer_invitations i ON i.assignment_id=a.assignment_id
        JOIN users u ON u.user_id=a.reviewer_id
        JOIN manuscripts m ON m.manuscript_id=a.manuscript_id
        WHERE a.assignment_id=? AND a.reviewer_id=? AND u.role='reviewer'
        AND a.status IN ('assigned','completed') AND i.status='accepted'
        AND NOT EXISTS (SELECT 1 FROM reviewer_invitation_invalidations x WHERE x.assignment_id=a.assignment_id)''',
        (assignment_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, 'Reviewed documents unavailable')
    return row


@router.get('/review-assignments/{assignment_id}/documents')
def own_reviewed_documents(assignment_id:int,user:User=Depends(require_role('reviewer')),db:Session=Depends(get_db)):
    raw = _begin(db)
    try:
        _actor(raw,user.user_id,'reviewer')
        mid,round_no = _reviewed_document_owner(raw,assignment_id,user.user_id)
        rows = raw.execute('''SELECT artifact_id,version,format,created_at FROM distribution_artifacts
            WHERE kind='reviewed_document' AND review_assignment_id=? AND manuscript_id=?
            AND review_round=? AND created_by=? ORDER BY version''',
            (assignment_id,mid,round_no,user.user_id)).fetchall()
        return [{'artifact_id':a,'version':v,'format':f,'created_at':c,
                 'review_round':round_no,'assignment_id':assignment_id} for a,v,f,c in rows]
    except sqlite3.Error:
        raise HTTPException(503,'Reviewed documents unavailable') from None
    finally:
        db.rollback()


@router.get('/review-assignments/{assignment_id}/documents/{artifact_id}/download')
def download_own_reviewed_document(assignment_id:int,artifact_id:str,user:User=Depends(require_role('reviewer')),db:Session=Depends(get_db)):
    if not re.fullmatch('[0-9a-f]{32}',artifact_id):
        raise HTTPException(404,'Reviewed document unavailable')
    raw = _begin(db)
    try:
        _actor(raw,user.user_id,'reviewer')
        from app import lifecycle_prototype
        try:
            lifecycle = lifecycle_prototype._state(raw, user.user_id)
        except lifecycle_prototype.PolicyError:
            raise HTTPException(404,'Reviewed document unavailable') from None
        if lifecycle is None or lifecycle.state != 'active':
            raise HTTPException(404,'Reviewed document unavailable')
        try:
            mid,round_no = _review_assignment(raw,assignment_id,user.user_id)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            raise HTTPException(404,'Reviewed document unavailable') from None
        row = raw.execute('''SELECT storage_id,sha256,byte_size,format FROM distribution_artifacts
            WHERE artifact_id=? AND kind='reviewed_document' AND review_assignment_id=?
            AND manuscript_id=? AND review_round=? AND created_by=?''',
            (artifact_id,assignment_id,mid,round_no,user.user_id)).fetchone()
        if not row:
            raise HTTPException(404,'Reviewed document unavailable')
        storage_id,digest,size,fmt = row
        try:
            with _storage() as store:
                data = store.read_verified(StorageMetadata(storage_id,digest,size,fmt))
        except (StorageError,OSError):
            raise HTTPException(409,'Reviewed document unavailable') from None
        return Response(data,media_type=ALLOWED_MANUSCRIPT_EXTENSIONS['.'+fmt],headers={
            'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'Content-Disposition':f'attachment; filename="reviewed-document.{fmt}"'})
    except sqlite3.Error:
        raise HTTPException(503,'Reviewed document unavailable') from None
    finally:
        db.rollback()


@router.get('/review-assignments/{assignment_id}/upload-availability')
def review_upload_availability(assignment_id:int,user:User=Depends(require_role('reviewer')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'reviewer');_review_assignment(raw,assignment_id,user.user_id)
        with _storage(): pass
        return {'available':True}
    finally: db.rollback()


@router.post('/review-assignments/{assignment_id}/documents')
def upload_reviewed(assignment_id:int,file:UploadFile=File(...),idempotency_key:str=Header(...,alias='Idempotency-Key'),user:User=Depends(require_role('reviewer')),db:Session=Depends(get_db)):
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,128}',idempotency_key): raise HTTPException(422,'Invalid idempotency key')
    content=file.file.read(MAX_MANUSCRIPT_FILE_SIZE+1)
    ext,_=validate_manuscript_file(file.filename,content);fmt=ext[1:];digest=hashlib.sha256(content).hexdigest();uid=user.user_id
    raw=_begin(db)
    try:
        _actor(raw,uid,'reviewer');mid,round_no=_review_assignment(raw,assignment_id,uid)
        fingerprint=hashlib.sha256(json.dumps([assignment_id,mid,round_no,digest,fmt],separators=(',',':')).encode()).hexdigest()
        existing=raw.execute('SELECT storage_id,request_fingerprint FROM distribution_reservations WHERE actor_id=? AND idempotency_key=?',(uid,idempotency_key)).fetchone()
        if existing:
            if existing[1]!=fingerprint: raise HTTPException(409,'Idempotency key conflict')
            storage_id=existing[0]
        else:
            storage_id=uuid4().hex
            raw.execute('INSERT INTO distribution_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(storage_id,mid,uid,'reviewed_document',assignment_id,round_no,digest,len(content),fmt,idempotency_key,fingerprint,_now()))
        artifact=raw.execute('SELECT artifact_id,version FROM distribution_artifacts WHERE storage_id=?',(storage_id,)).fetchone()
        db.commit()
        if artifact: return {'artifact_id':artifact[0],'version':artifact[1],'review_round':round_no}
    except HTTPException: db.rollback();raise
    except Exception: db.rollback();raise HTTPException(503,'Reservation outcome may be unknown; retry with the same key') from None
    meta=StorageMetadata(storage_id,digest,len(content),fmt)
    try:
        with _storage() as store:
            try: store.reconcile_reserved(meta)
            except StorageError: store.publish_reserved(storage_id,content,fmt)
            store.reconcile_reserved(meta)
    except (StorageError,OSError): raise HTTPException(503,'Publication outcome unavailable; retry with the same key') from None
    raw=_begin(db)
    try:
        _actor(raw,uid,'reviewer')
        if _review_assignment(raw,assignment_id,uid)!=(mid,round_no): raise HTTPException(409,'Assignment changed; refresh')
        existing=raw.execute('SELECT artifact_id,version FROM distribution_artifacts WHERE storage_id=?',(storage_id,)).fetchone()
        if existing: db.rollback();return {'artifact_id':existing[0],'version':existing[1],'review_round':round_no}
        version=raw.execute("SELECT COALESCE(MAX(version),0)+1 FROM distribution_artifacts WHERE kind='reviewed_document' AND review_assignment_id=?",(assignment_id,)).fetchone()[0]
        artifact_id=uuid4().hex
        raw.execute('INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(artifact_id,mid,'reviewed_document',version,storage_id,digest,len(content),fmt,assignment_id,round_no,uid,_now()))
        db.commit();return {'artifact_id':artifact_id,'version':version,'review_round':round_no}
    except HTTPException: db.rollback();raise
    except Exception: db.rollback();raise HTTPException(503,'Outcome may be unknown; retry with the same key') from None


@router.get('/manuscripts/{mid}/reviewed-documents')
def reviewed_history(mid:int,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');_manuscript(raw,mid)
        rows=raw.execute("SELECT artifact_id,version,review_round,review_assignment_id,format,created_at,sha256,byte_size FROM distribution_artifacts WHERE manuscript_id=? AND kind='reviewed_document' ORDER BY review_round,version",(mid,)).fetchall()
        return [{'artifact_id':a,'version':v,'review_round':r,'assignment_id':i,'format':f,'created_at':c,'sha256':digest,'byte_size':size} for a,v,r,i,f,c,digest,size in rows]
    finally: db.rollback()


@router.get('/reviewed-documents/{artifact_id}/download')
def download_reviewed(artifact_id:str,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic')
        row=raw.execute("SELECT manuscript_id,storage_id,sha256,byte_size,format FROM distribution_artifacts WHERE artifact_id=? AND kind='reviewed_document'",(artifact_id,)).fetchone()
        if not row: raise HTTPException(404,'Document unavailable')
        mid,storage_id,digest,size,fmt=row;_manuscript(raw,mid)
        try:
            with _storage() as store: content=store.read_verified(StorageMetadata(storage_id,digest,size,fmt))
        except StorageError: raise HTTPException(409,'Document unavailable') from None
        return Response(content,media_type=ALLOWED_MANUSCRIPT_EXTENSIONS['.'+fmt],headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Disposition':f'attachment; filename="reviewed-document.{fmt}"'})
    finally: db.rollback()

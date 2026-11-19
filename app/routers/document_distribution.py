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
    return row[0]


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
        data,fmt,digest=_source(mid,stored)
        if digest!=req.source_sha256: raise HTTPException(409,'Document changed; refresh before distributing')
        existing=raw.execute('SELECT grant_id,fingerprint FROM distribution_grants WHERE actor_id=? AND idempotency_key=?',(uid,req.idempotency_key)).fetchone()
        if existing:
            if existing[1]!=fingerprint: raise HTTPException(409,'Idempotency key conflict')
            if raw.execute('SELECT 1 FROM distribution_revocations WHERE grant_id=?',(existing[0],)).fetchone(): raise HTTPException(409,'Grant revoked')
            db.rollback()
            return {'grant_id':existing[0],'result':'access_granted','email':'not_requested'}
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
        if _invite(raw,mid,req.invitation_kind,req.invitation_id)!=recipient or _source(mid,stored2)[2]!=digest: raise HTTPException(409,'Document or invitation changed; refresh')
        prior=raw.execute('SELECT grant_id FROM distribution_grants WHERE actor_id=? AND idempotency_key=?',(uid,req.idempotency_key)).fetchone()
        if prior:
            if raw.execute('SELECT 1 FROM distribution_revocations WHERE grant_id=?',(prior[0],)).fetchone():
                raise HTTPException(409,'Grant revoked')
            db.rollback();return {'grant_id':prior[0],'result':'access_granted','email':'not_requested'}
        col='initial_invitation_id' if req.invitation_kind=='initial' else 'final_invitation_id'
        duplicate=raw.execute(f'SELECT g.grant_id FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id WHERE g.manuscript_id=? AND g.recipient_id=? AND g.{col}=? AND a.sha256=? AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=g.grant_id)',(mid,recipient,req.invitation_id,digest)).fetchone()
        if duplicate: db.rollback();return {'grant_id':duplicate[0],'result':'access_granted','email':'not_requested'}
        version=raw.execute("SELECT COALESCE(MAX(version),0)+1 FROM distribution_artifacts WHERE manuscript_id=? AND kind='editor_source'",(mid,)).fetchone()[0]
        artifact_id=uuid4().hex;grant_id=uuid4().hex;now=_now()
        raw.execute('INSERT INTO distribution_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(artifact_id,mid,'editor_source',version,storage_id,digest,len(data),fmt,None,None,uid,now))
        raw.execute('INSERT INTO distribution_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(grant_id,mid,artifact_id,recipient,'editor',req.invitation_id if req.invitation_kind=='initial' else None,req.invitation_id if req.invitation_kind=='final' else None,None,None,uid,'manual','created','not_requested',req.idempotency_key,fingerprint,now))
        raw.execute("INSERT INTO notifications(user_id,manuscript_id,notification_type,message,is_read,created_at) VALUES(?,?,?,?,?,?)",(recipient,mid,'document_distributed','An editorial document is available.',0,now))
        db.commit();return {'grant_id':grant_id,'result':'access_granted','email':'not_requested'}
    except HTTPException: db.rollback();raise
    except Exception: db.rollback();raise HTTPException(503,'Outcome may be unknown; retry with the same key') from None


@router.get('/my')
def my_grants(user:User=Depends(require_role('editor')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'editor')
        rows=raw.execute('''SELECT g.grant_id,g.manuscript_id,m.title,a.version,a.format,g.created_at,g.initial_invitation_id,g.final_invitation_id,a.sha256 FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id JOIN manuscripts m ON m.manuscript_id=g.manuscript_id WHERE g.recipient_id=? AND m.status NOT IN ('draft','revision_required','initial_revision_required') AND NOT EXISTS(SELECT 1 FROM distribution_revocations r WHERE r.grant_id=g.grant_id) ORDER BY g.created_at DESC''',(user.user_id,)).fetchall()
        result=[]
        for gid,mid,title,version,fmt,created,initial,final,digest in rows:
            try:
                if _invite(raw,mid,'initial' if initial else 'final',initial or final)!=user.user_id: continue
            except HTTPException: continue
            result.append({'grant_id':gid,'manuscript_id':mid,'title':title,'version':version,'format':fmt,'sha256':digest,'created_at':created})
        return result
    finally: db.rollback()


@router.get('/manuscripts/{mid}/history')
def history(mid:int,user:User=Depends(require_role('eic')),db:Session=Depends(get_db)):
    raw=_begin(db)
    try:
        _actor(raw,user.user_id,'eic');_manuscript(raw,mid)
        rows=raw.execute('''SELECT g.grant_id,a.version,a.format,g.recipient_id,g.initial_invitation_id,g.final_invitation_id,g.created_at,g.notification_state,g.email_state,r.created_at,a.sha256,a.byte_size,g.actor_id FROM distribution_grants g JOIN distribution_artifacts a ON a.artifact_id=g.artifact_id LEFT JOIN distribution_revocations r ON r.grant_id=g.grant_id WHERE g.manuscript_id=? ORDER BY g.created_at DESC''',(mid,)).fetchall()
        return [{'grant_id':g,'version':v,'format':f,'recipient_id':recipient,'invitation_kind':'initial' if initial else 'final','invitation_id':initial or final,'actor_id':actor,'created_at':created,'revoked_at':revoked,'notification':notification,'email':email,'status':'revoked' if revoked else 'access_granted','sha256':digest,'byte_size':size} for g,v,f,recipient,initial,final,created,notification,email,revoked,digest,size,actor in rows]
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
        try:
            with _storage() as store: data=store.read_verified(StorageMetadata(storage_id,digest,size,fmt))
        except StorageError: raise HTTPException(409,'Document unavailable') from None
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

"""Optional local DOCX draft editing. Workflow submission remains separate."""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import onlyoffice_docx as svc, online_versions
from app.database import get_db
from app.models import User
from app.routers.users import get_current_user

router = APIRouter(prefix='/onlyoffice', tags=['Online DOCX'])


def begin(db):
    connection = db.connection()
    if connection.dialect.name != 'sqlite' or connection.connection.driver_connection.in_transaction:
        raise HTTPException(503, 'DOCX editing transaction unavailable')
    connection.exec_driver_sql('BEGIN IMMEDIATE')


def state(db, sid):
    row = db.execute(text('SELECT * FROM onlyoffice_sessions WHERE session_id=:id'), {'id': sid}).mappings().first()
    if not row or row['revoked'] or row['expires_at'] < int(time.time()): raise HTTPException(403, 'Editing session unavailable')
    _, _, ref, raw, scope = svc.source(db, row['manuscript_id'], row['actor_id'], row['stage'])
    if ref != row['source_ref'] or hashlib.sha256(raw).hexdigest() != row['source_sha256'] or scope != row['scope_key']:
        raise HTTPException(409, 'Document source changed')
    return row, raw


def rows(db, mid, actor, stage, scope):
    return online_versions.history(db, mid, actor, stage, scope)


def global_head(db, mid, stage, ref, sha):
    return db.execute(text('SELECT version_id FROM online_document_versions WHERE manuscript_id=:mid AND stage=:stage AND source_ref=:ref AND source_sha256=:sha AND scope_key LIKE :scope ORDER BY rowid DESC LIMIT 1'), {'mid':mid,'stage':stage,'ref':ref,'sha':sha,'scope':'docx:%'}).scalar()


def selected_draft(db, mid, actor, stage, vid):
    """Call under the workflow's existing BEGIN IMMEDIATE transaction."""
    svc.config(); svc.require_schema(db)
    _, _, ref, source, scope = svc.source(db, mid, actor, stage)
    history = rows(db, mid, actor, stage, scope)
    if not history or history[-1]['version_id'] != vid or global_head(db,mid,stage,ref,hashlib.sha256(source).hexdigest()) != vid:
        raise HTTPException(409, 'Selected DOCX draft is stale; choose the latest draft')
    item = history[-1]
    return svc.read_draft(item['file_ref'],mid,stage,actor,item['file_sha256'])


def install_author_draft(db, manuscript, user, vid, round_number):
    """Copy a selected draft into the existing submission path under its transaction."""
    content = selected_draft(db, manuscript.manuscript_id, user.user_id, 'author', vid)
    root = svc.BASE_DIR.resolve()
    directory = root / 'uploads' / 'manuscripts' / str(manuscript.manuscript_id)
    svc.editor_text_drafts._reject_symlinks(directory, root / 'uploads')
    if not directory.is_dir(): raise HTTPException(409, 'Manuscript directory unavailable')
    filename = f"round_{round_number}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex}.docx"
    path = directory / filename
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
    except OSError:
        raise HTTPException(503, 'Draft copy unavailable; reconcile before retrying') from None
    # The file is retained if the transaction subsequently fails or is ambiguous.
    manuscript.file_path = str(path.relative_to(root))


@router.get('/manuscripts/{mid}/{stage}/sessions/{sid}/status')
def session_status(mid: int, stage: str, sid: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.config(); svc.require_schema(db)
    session, _ = state(db, sid)
    if session['actor_id'] != user.user_id or session['manuscript_id'] != mid or session['stage'] != stage:
        raise HTTPException(404, 'Session unavailable')
    if global_head(db, mid, stage, session['source_ref'], session['source_sha256']) != session['global_head_id']:
        raise HTTPException(409, 'Draft changed; reopen before saving')
    last = db.execute(text('SELECT status,digest FROM onlyoffice_callbacks WHERE session_id=:sid AND status IN (2,3,6,7) ORDER BY rowid DESC LIMIT 1'), {'sid':sid}).first()
    result = {'state':'waiting', 'closed':bool(session['closed']), 'version':None}
    if last and (last[0] in (3,7) or (last[0] in (2,6) and last[1] is None)): result['state'] = 'error'
    elif last and last[0] in (2,6):
        item = next((v for v in rows(db,mid,user.user_id,stage,session['scope_key']) if v['version_id'] == session['head_id']), None)
        if item:
            svc.read_draft(item['file_ref'],mid,stage,user.user_id,item['file_sha256'])
            result.update(state='saved',version={'id':item['version_id'],'number':item['version_number']})
    return JSONResponse(result, headers={'Cache-Control':'no-store'})


@router.post('/manuscripts/{mid}/{stage}/sessions/{sid}/retry-save')
def retry_save(mid: int, stage: str, sid: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    secret, server, _ = svc.config(); svc.require_schema(db)
    session, _ = state(db, sid)
    if session['actor_id'] != user.user_id or session['manuscript_id'] != mid or session['stage'] != stage:
        raise HTTPException(404, 'Session unavailable')
    if session['closed'] or global_head(db, mid, stage, session['source_ref'], session['source_sha256']) != session['global_head_id']:
        raise HTTPException(409, 'Editing session is closed or stale')
    last = db.execute(text('SELECT status,digest FROM onlyoffice_callbacks WHERE session_id=:sid AND status IN (2,3,6,7) ORDER BY rowid DESC LIMIT 1'), {'sid':sid}).first()
    if not last or not (last[0] in (3,7) or (last[0] in (2,6) and last[1] is None)):
        raise HTTPException(409, 'There is no failed save to retry')
    # Never hold a database transaction while the server may issue a callback.
    db.rollback()
    svc.request_force_save(sid, secret, server)
    return JSONResponse({'state':'requested'}, status_code=202, headers={'Cache-Control':'no-store'})


@router.post('/manuscripts/{mid}/{stage}/versions/{vid}/preview')
def preview(mid: int, stage: str, vid: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    secret, server, origin = svc.config(); svc.require_schema(db)
    _, _, _, _, scope = svc.source(db, mid, user.user_id, stage)
    item = next((v for v in rows(db,mid,user.user_id,stage,scope) if v['version_id'] == vid), None)
    if not item: raise HTTPException(404, 'Draft unavailable')
    svc.read_draft(item['file_ref'],mid,stage,user.user_id,item['file_sha256'])
    capability = jwt.encode({'aud':'docx-preview','exp':int(time.time())+300,'mid':mid,'actor':user.user_id,'stage':stage,'vid':vid,'scope':scope},secret,algorithm='HS256')
    config = {'documentType':'word','document':{'fileType':'docx','key':uuid4().hex,'title':f'draft-{item["version_number"]}.docx','url':f'{origin}/onlyoffice/preview-document?token={capability}','permissions':{'edit':False}},'editorConfig':{'mode':'view','user':{'id':str(user.user_id),'name':user.name}}}
    config['token'] = jwt.encode({**config,'exp':int(time.time())+300},secret,algorithm='HS256')
    return JSONResponse({'editorOrigin':server,'config':config,'number':item['version_number']}, headers={'Cache-Control':'no-store'})


@router.get('/preview-document')
def preview_document(token: str, db: Session = Depends(get_db)):
    secret, _, _ = svc.config(); svc.require_schema(db)
    try: claims = jwt.decode(token,secret,algorithms=['HS256'],audience='docx-preview',options={'require':['aud','exp','mid','actor','stage','vid','scope']})
    except jwt.PyJWTError: raise HTTPException(403,'Invalid preview capability') from None
    mid, actor, stage = claims['mid'], claims['actor'], claims['stage']
    _, _, _, _, scope = svc.source(db,mid,actor,stage)
    if scope != claims['scope']: raise HTTPException(409,'Document source changed')
    item = next((v for v in rows(db,mid,actor,stage,scope) if v['version_id'] == claims['vid']),None)
    if not item: raise HTTPException(404,'Draft unavailable')
    return Response(svc.read_draft(item['file_ref'],mid,stage,actor,item['file_sha256']),media_type=svc.MIME,headers={'Cache-Control':'no-store'})


@router.get('/manuscripts/{mid}/{stage}/availability')
def availability(mid: int, stage: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        svc.config()
    except HTTPException:
        return {'available': False}
    svc.require_schema(db)
    svc.source(db, mid, user.user_id, stage)
    return JSONResponse({'available': True}, headers={'Cache-Control': 'no-store'})


@router.post('/manuscripts/{mid}/{stage}/sessions')
def create_session(mid: int, stage: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    secret, server, app_origin = svc.config()
    try:
        begin(db); svc.require_schema(db)
        _, _, ref, source, scope = svc.source(db, mid, user.user_id, stage)
        history = rows(db, mid, user.user_id, stage, scope)
        head = history[-1]['version_id'] if history else None
        if history: svc.read_draft(history[-1]['file_ref'], mid, stage, user.user_id, history[-1]['file_sha256'])
        sid = uuid4().hex
        sha = hashlib.sha256(source).hexdigest()
        global_id = global_head(db, mid, stage, ref, sha)
        if global_id is not None and global_id != head:
            raise HTTPException(409, 'Another editor has saved a draft for this source; coordinate before editing')
        db.execute(text('''INSERT INTO onlyoffice_sessions(session_id,manuscript_id,actor_id,stage,source_ref,source_sha256,scope_key,head_id,global_head_id,expires_at) VALUES (:id,:mid,:actor,:stage,:ref,:sha,:scope,:head,:global_id,:expiry)'''),
                   {'id':sid,'mid':mid,'actor':user.user_id,'stage':stage,'ref':ref,'sha':sha,'scope':scope,'head':head,'global_id':global_id,'expiry':int(time.time())+3600})
        cap = jwt.encode({'sid':sid,'aud':'docx-download','exp':int(time.time())+300}, secret, algorithm='HS256')
        config = {'documentType':'word', 'document':{'fileType':'docx','key':sid,'title':'manuscript.docx','url':f'{app_origin}/onlyoffice/documents/{sid}?token={cap}'},
                  'editorConfig':{'mode':'edit','customization':{'forcesave':True},'callbackUrl':f'{app_origin}/onlyoffice/callbacks/{sid}','user':{'id':str(user.user_id),'name':user.name}}}
        config['token'] = jwt.encode({**config,'exp':int(time.time())+300}, secret, algorithm='HS256')
        db.commit()
        return JSONResponse({'editorOrigin':server,'config':config,'session':sid}, headers={'Cache-Control':'no-store'})
    except HTTPException:
        db.rollback(); raise
    except (SQLAlchemyError, OSError):
        db.rollback(); raise HTTPException(503, 'Session outcome unavailable; reopen before retrying') from None


@router.get('/documents/{sid}')
def document(sid: str, token: str, db: Session = Depends(get_db)):
    secret, _, _ = svc.config(); svc.require_schema(db)
    try: claims = jwt.decode(token, secret, algorithms=['HS256'], audience='docx-download', options={'require':['aud','exp']})
    except jwt.PyJWTError: raise HTTPException(403, 'Invalid document capability') from None
    if claims.get('sid') != sid: raise HTTPException(403, 'Invalid document capability')
    row, source = state(db, sid)
    if row['closed']: raise HTTPException(403, 'Editing session unavailable')
    history = rows(db, row['manuscript_id'], row['actor_id'], row['stage'], row['scope_key'])
    if row['head_id']:
        current = next((v for v in history if v['version_id'] == row['head_id']), None)
        if not current: raise HTTPException(409, 'Draft unavailable')
        source = svc.read_draft(current['file_ref'], row['manuscript_id'], row['stage'], row['actor_id'], current['file_sha256'])
    return Response(source, media_type=svc.MIME, headers={'Cache-Control':'no-store'})


@router.get('/manuscripts/{mid}/{stage}/versions')
def history(mid: int, stage: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.config(); svc.require_schema(db)
    _, _, _, _, scope = svc.source(db, mid, user.user_id, stage)
    result = rows(db, mid, user.user_id, stage, scope)
    return JSONResponse([{'id':v['version_id'],'number':v['version_number'],'saved_at':v['saved_at'],'sha256':v['file_sha256']} for v in result], headers={'Cache-Control':'no-store'})


@router.get('/manuscripts/{mid}/{stage}/versions/{vid}')
def download(mid: int, stage: str, vid: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.config(); svc.require_schema(db)
    _, _, _, _, scope = svc.source(db, mid, user.user_id, stage)
    item = next((r for r in rows(db, mid, user.user_id, stage, scope) if r['version_id'] == vid), None)
    if not item: raise HTTPException(404, 'Draft unavailable')
    content = svc.read_draft(item['file_ref'], mid, stage, user.user_id, item['file_sha256'])
    return Response(content, media_type=svc.MIME, headers={'Cache-Control':'no-store','Content-Disposition':'attachment; filename="draft.docx"'})


@router.post('/manuscripts/{mid}/{stage}/sessions/{sid}/revoke')
def revoke(mid: int, stage: str, sid: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.config()
    try:
        begin(db); svc.require_schema(db); svc.source(db, mid, user.user_id, stage)
        result = db.execute(text('UPDATE onlyoffice_sessions SET revoked=1 WHERE session_id=:sid AND manuscript_id=:mid AND actor_id=:actor AND stage=:stage'), {'sid':sid,'mid':mid,'actor':user.user_id,'stage':stage})
        if result.rowcount != 1: raise HTTPException(404, 'Session unavailable')
        db.commit(); return {'revoked':True}
    except HTTPException:
        db.rollback(); raise


@router.post('/callbacks/{sid}')
async def callback(sid: str, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    secret, server, _ = svc.config()
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16384: raise HTTPException(413, 'Callback too large')
    try: body = json.loads(raw)
    except (ValueError, UnicodeError): raise HTTPException(400, 'Invalid callback') from None
    if not isinstance(body, dict): raise HTTPException(400, 'Invalid callback')
    token = body.get('token'); nested = token is None
    if token is None: token = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    if not isinstance(token, str): raise HTTPException(403, 'Invalid callback')
    try: claims = jwt.decode(token, secret, algorithms=['HS256'], options={'verify_aud':False})
    except jwt.PyJWTError: raise HTTPException(403, 'Invalid callback') from None
    signed = claims.get('payload') if nested else claims
    if claims.get('operation') != 'callback' or not isinstance(signed, dict) or signed.get('key') != sid or any(k in body and body[k] != signed.get(k) for k in ('key','status','url','forcesavetype')):
        raise HTTPException(403, 'Invalid callback')
    status = signed.get('status')
    if type(status) is not int or status not in (1,2,3,4,6,7): raise HTTPException(400, 'Invalid callback status')
    event = hashlib.sha256(json.dumps(signed, sort_keys=True, separators=(',',':')).encode()).hexdigest()
    try:
        begin(db); svc.require_schema(db)
        session, source = state(db, sid)
        params = {'sid':sid,'event':event}
        if db.execute(text('SELECT 1 FROM onlyoffice_callbacks WHERE session_id=:sid AND event_hash=:event'), params).first():
            db.rollback(); return {'error':0}
        if session['closed']: raise HTTPException(409, 'Editing session closed')
        mid, actor, stage, scope = session['manuscript_id'], session['actor_id'], session['stage'], session['scope_key']
        history = rows(db, mid, actor, stage, scope)
        latest = history[-1]['version_id'] if history else None
        digest = url_hash = None
        if status in (2,6):
            if latest != session['head_id'] or global_head(db, mid, stage, session['source_ref'], session['source_sha256']) != session['global_head_id']:
                raise HTTPException(409, 'Draft changed; reopen before saving')
            failed_head = db.execute(text('SELECT url_hash FROM onlyoffice_callbacks WHERE session_id=:sid AND event_hash=:event'),
                                     {'sid':sid, 'event':'failure:'+event}).scalar()
            if failed_head is not None and failed_head != 'head:'+(latest or ''):
                raise HTTPException(409, 'Draft changed; reopen before saving')
            if status == 6 and (type(signed.get('forcesavetype')) is not int or signed['forcesavetype'] not in (0,1,2,3)): raise HTTPException(400, 'Invalid force-save type')
            url = signed.get('url')
            if not isinstance(url, str): raise HTTPException(400, 'Invalid document URL')
            try:
                content = svc.fetch(url, server)
            except HTTPException as exc:
                if exc.status_code != 503:
                    raise
                # Record the authenticated attempt separately from its event key:
                # a later delivery of the same callback must still be retried.
                db.execute(text('INSERT OR IGNORE INTO onlyoffice_callbacks VALUES (:sid,:event,:status,NULL,:head)'),
                           {'sid':sid, 'event':'failure:'+event, 'status':status, 'head':'head:'+(latest or '')})
                db.commit()
                return JSONResponse({'error':1}, status_code=503)
            digest = hashlib.sha256(content).hexdigest(); url_hash = hashlib.sha256(url.encode()).hexdigest()
            previous = db.execute(text('SELECT digest FROM onlyoffice_callbacks WHERE session_id=:sid AND url_hash=:url LIMIT 1'), {'sid':sid,'url':url_hash}).scalar()
            if previous and previous != digest: raise HTTPException(409, 'Save URL changed content')
            if not history or history[-1]['file_sha256'] != digest:
                directory = svc.BASE_DIR.resolve() / 'uploads' / 'onlyoffice' / str(mid) / stage / str(actor)
                svc.editor_text_drafts._reject_symlinks(directory, svc.BASE_DIR.resolve() / 'uploads')
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                svc.editor_text_drafts._reject_symlinks(directory, svc.BASE_DIR.resolve() / 'uploads')
                path = directory / (uuid4().hex + '.docx')
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os,'O_NOFOLLOW',0), 0o600)
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(content); handle.flush(); os.fsync(handle.fileno())
                saved = online_versions.record(db, mid, actor, stage, scope, session['source_ref'], source, str(path.relative_to(svc.BASE_DIR.resolve())), content)
                db.execute(text('UPDATE onlyoffice_sessions SET head_id=:head, global_head_id=:head WHERE session_id=:sid'), {'head':saved['id'],'sid':sid})
        db.execute(text('INSERT INTO onlyoffice_callbacks VALUES (:sid,:event,:status,:digest,:url)'), {'sid':sid,'event':event,'status':status,'digest':digest,'url':url_hash})
        if status in (2,4): db.execute(text('UPDATE onlyoffice_sessions SET closed=1 WHERE session_id=:sid'), {'sid':sid})
        db.commit(); return {'error':0}
    except HTTPException:
        db.rollback(); raise
    except (OSError, SQLAlchemyError):
        db.rollback(); raise HTTPException(503, 'Save outcome unavailable; reconcile before retrying') from None

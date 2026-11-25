"""Manuscript-scoped, assignment-snapshotted editorial stage dialogue."""
from datetime import datetime, timezone
from importlib import import_module
from typing import Literal
from uuid import uuid4
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.editor_invitation_revocation import is_revoked_raw
from app.editor_distribution_rounds import resolve
from app.routers.users import get_current_user

class NoStoreRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                if request.method == 'POST':
                    try:
                        size = int(request.headers.get('content-length', '0'))
                    except ValueError:
                        raise HTTPException(400, 'Invalid request size') from None
                    if size < 0 or size > 32768:
                        raise HTTPException(413, 'Dialogue request is too large')
                    body = bytearray()
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > 32768:
                            raise HTTPException(413, 'Dialogue request is too large')
                        body.extend(chunk)
                    # Starlette's normal body()/json() parsing uses this cache.
                    # Populate it only after the bounded stream has completed.
                    request._body = bytes(body)
                result = await original(request)
            except RequestValidationError:
                return JSONResponse(status_code=422,content={'detail':'Invalid dialogue request'},headers={'Cache-Control':'no-store'})
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), 'Cache-Control': 'no-store'}
                raise
            result.headers['Cache-Control'] = 'no-store'
            return result
        return handler


router = APIRouter(prefix='/manuscripts', tags=['Stage dialogue'], route_class=NoStoreRoute)

class ThreadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stage: Literal['initial_editing', 'final_editing']

class MessageRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    body: str = Field(min_length=1, max_length=5000)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _begin(db, user):
    conn = db.connection()
    raw = conn.connection.driver_connection
    if conn.dialect.name != 'sqlite' or raw.in_transaction:
        raise HTTPException(503, 'Dialogue unavailable')
    conn.exec_driver_sql('BEGIN IMMEDIATE')
    mod = import_module('migrations.033_stage_dialogue')
    try:
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(mod.MIGRATION_ID,)).fetchone():
            raise HTTPException(503, 'Dialogue migration required')
        for name, expected in mod.DDL.items():
            row = raw.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
            if not row or not row[0] or mod.normalize(row[0]) != mod.normalize(expected):
                raise HTTPException(503, 'Dialogue unavailable')
        actor = raw.execute('SELECT role FROM users WHERE user_id=?',(user.user_id,)).fetchone()
        if not actor or actor[0] != user.role:
            raise HTTPException(403, 'Dialogue unavailable')
        if raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_lifecycle'").fetchone():
            lifecycle = raw.execute('SELECT state FROM account_lifecycle WHERE user_id=?',(user.user_id,)).fetchone()
            if lifecycle and lifecycle[0] != 'active':raise HTTPException(403, 'Dialogue unavailable')
    except HTTPException: raise
    except Exception: raise HTTPException(503, 'Dialogue unavailable') from None
    return raw


def _context(raw, mid, stage, uid):
    manuscript = raw.execute('SELECT author_id FROM manuscripts WHERE manuscript_id=?',(mid,)).fetchone()
    if not manuscript:raise HTTPException(404, 'Dialogue unavailable')
    kind = 'initial' if stage == 'initial_editing' else 'final'
    table = 'initial_editor_invitations' if kind == 'initial' else 'final_editor_invitations'
    candidates = raw.execute(f"SELECT invitation_id,editor_id,invited_by FROM {table} WHERE manuscript_id=? AND status='accepted'",(mid,)).fetchall()
    candidates = [x for x in candidates if not is_revoked_raw(raw,kind,x[0])]
    if len(candidates) != 1:raise HTTPException(409, 'Dialogue assignment unavailable')
    iid, editor, inviter = candidates[0]
    if not raw.execute("SELECT 1 FROM users WHERE user_id=? AND role='editor'",(editor,)).fetchone():raise HTTPException(409, 'Dialogue assignment unavailable')
    eic = inviter if raw.execute("SELECT 1 FROM users WHERE user_id=? AND role IN ('eic','chief_editor','editor_in_chief')",(inviter,)).fetchone() else None
    if uid not in (manuscript[0],editor,eic):raise HTTPException(403, 'Dialogue unavailable')
    if raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_lifecycle'").fetchone():
        for participant in (manuscript[0],editor,eic):
            if participant is not None:
                lifecycle=raw.execute('SELECT state FROM account_lifecycle WHERE user_id=?',(participant,)).fetchone()
                if lifecycle and lifecycle[0]!='active':raise HTTPException(409,'Dialogue audience unavailable')
    actor_role=raw.execute('SELECT role FROM users WHERE user_id=?',(uid,)).fetchone()[0]
    if uid==manuscript[0] and actor_role!='author':raise HTTPException(403,'Dialogue unavailable')
    if uid==editor and actor_role!='editor':raise HTTPException(403,'Dialogue unavailable')
    if uid==eic and actor_role not in ('eic','chief_editor','editor_in_chief'):raise HTTPException(403,'Dialogue unavailable')
    evidence = resolve(raw, mid, kind)
    return (kind,iid,manuscript[0],editor,eic,*evidence)


def _thread(raw, mid, tid, user):
    if not re.fullmatch('[0-9a-f]{32}',tid):raise HTTPException(404, 'Dialogue unavailable')
    row = raw.execute('''SELECT thread_id,manuscript_id,stage,round_kind,review_round,agreement_id,decision_id,
      invitation_kind,invitation_id,author_id,editor_id,eic_id,created_by,created_at
      FROM stage_dialogue_threads WHERE thread_id=? AND manuscript_id=?''',(tid,mid)).fetchone()
    if not row or user.user_id not in row[9:12]:raise HTTPException(404, 'Dialogue unavailable')
    kind, iid, author, editor, eic = row[7:12]
    manuscript = raw.execute('SELECT author_id FROM manuscripts WHERE manuscript_id=?',(mid,)).fetchone()
    if not manuscript or manuscript[0] != author:raise HTTPException(403,'Dialogue unavailable')
    table = 'initial_editor_invitations' if kind == 'initial' else 'final_editor_invitations'
    invite = raw.execute(f'SELECT editor_id,invited_by,status FROM {table} WHERE invitation_id=? AND manuscript_id=?',(iid,mid)).fetchone()
    if not invite or invite[0] != editor or invite[2] != 'accepted':raise HTTPException(403,'Dialogue unavailable')
    if user.user_id == editor and is_revoked_raw(raw,kind,iid):raise HTTPException(403,'Dialogue unavailable')
    if user.user_id == author and user.role != 'author':raise HTTPException(403,'Dialogue unavailable')
    if user.user_id == editor and user.role != 'editor':raise HTTPException(403,'Dialogue unavailable')
    if user.user_id == eic and (invite[1] != eic or user.role not in ('eic','chief_editor','editor_in_chief')):raise HTTPException(403,'Dialogue unavailable')
    return row


def _summary(raw,row):
    labels=[]
    for uid,label in ((row[9],'Author'),(row[10],'Editor'),(row[11],'EIC')):
        if uid is not None:
            name=raw.execute('SELECT name FROM users WHERE user_id=?',(uid,)).fetchone()
            if not name:raise HTTPException(503,'Dialogue unavailable')
            labels.append({'role':label,'name':name[0]})
    return {'thread_id':row[0],'stage':row[2],'round_kind':row[3],'review_round':row[4],
            'participants':labels,'created_at':row[13],'status':'open'}


@router.get('/{mid}/dialogue/audience-preview')
def preview(mid:int, stage:Literal['initial_editing','final_editing'], response:Response, user=Depends(get_current_user), db:Session=Depends(get_db)):
    try:
        response.headers['Cache-Control']='no-store'
        raw=_begin(db,user);kind,iid,author,editor,eic,*round_evidence=_context(raw,mid,stage,user.user_id)
        people=[]
        for uid,label in ((author,'Author'),(editor,'Editor'),(eic,'EIC')):
            if uid is not None:people.append({'role':label,'name':raw.execute('SELECT name FROM users WHERE user_id=?',(uid,)).fetchone()[0]})
        return {'stage':stage,'round_kind':round_evidence[0],'review_round':round_evidence[1],'participants':people}
    finally:db.rollback()


@router.post('/{mid}/dialogue/threads',status_code=201)
def create_thread(mid:int, payload:ThreadRequest, response:Response, user=Depends(get_current_user), db:Session=Depends(get_db)):
    try:
        response.headers['Cache-Control']='no-store';raw=_begin(db,user)
        kind,iid,author,editor,eic,rkind,rnum,agreement,decision=_context(raw,mid,payload.stage,user.user_id)
        existing=raw.execute('SELECT thread_id FROM stage_dialogue_threads WHERE manuscript_id=? AND invitation_kind=? AND invitation_id=?',(mid,kind,iid)).fetchone()
        if existing:
            row=_thread(raw,mid,existing[0],user)
            if tuple(row[2:7]) != (payload.stage,rkind,rnum,agreement,decision):raise HTTPException(409,'Dialogue stage unavailable')
            result=_summary(raw,row);db.rollback();return result
        tid=uuid4().hex
        raw.execute('''INSERT INTO stage_dialogue_threads (thread_id,manuscript_id,stage,round_kind,review_round,agreement_id,decision_id,
            invitation_kind,invitation_id,author_id,editor_id,eic_id,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (tid,mid,payload.stage,rkind,rnum,agreement,decision,kind,iid,author,editor,eic,user.user_id,_stamp()))
        row=_thread(raw,mid,tid,user);result=_summary(raw,row);db.commit();return result
    except HTTPException:db.rollback();raise
    except Exception:db.rollback();raise HTTPException(503,'Dialogue unavailable') from None


@router.get('/{mid}/dialogue/threads')
def list_threads(mid:int, response:Response, user=Depends(get_current_user), db:Session=Depends(get_db)):
    try:
        response.headers['Cache-Control']='no-store';raw=_begin(db,user)
        ids=raw.execute('SELECT thread_id FROM stage_dialogue_threads WHERE manuscript_id=? AND ? IN (author_id,editor_id,eic_id) ORDER BY created_at,thread_id',(mid,user.user_id)).fetchall()
        result=[]
        for (tid,) in ids:
            try:result.append(_summary(raw,_thread(raw,mid,tid,user)))
            except HTTPException as exc:
                if exc.status_code >= 500:raise
        if result:return result
        manuscript=raw.execute('SELECT author_id FROM manuscripts WHERE manuscript_id=?',(mid,)).fetchone()
        if not manuscript:raise HTTPException(404,'Dialogue unavailable')
        if user.role=='author' and manuscript[0]==user.user_id:return []
        for kind,table in (('initial','initial_editor_invitations'),('final','final_editor_invitations')):
            invitations=raw.execute(f"SELECT invitation_id,editor_id,invited_by FROM {table} WHERE manuscript_id=? AND status='accepted'",(mid,)).fetchall()
            for iid,editor,inviter in invitations:
                if is_revoked_raw(raw,kind,iid):continue
                if user.role=='editor' and user.user_id==editor:return []
                if user.role in ('eic','chief_editor','editor_in_chief') and user.user_id==inviter:return []
        raise HTTPException(403,'Dialogue unavailable')
    finally:db.rollback()


@router.get('/{mid}/dialogue/threads/{tid}')
def messages(mid:int,tid:str,response:Response,user=Depends(get_current_user),db:Session=Depends(get_db)):
    try:
        response.headers['Cache-Control']='no-store';raw=_begin(db,user);thread=_thread(raw,mid,tid,user)
        rows=raw.execute('''SELECT m.message_id,m.sender_id,u.name,m.body,m.created_at FROM stage_dialogue_messages m
         JOIN users u ON u.user_id=m.sender_id WHERE m.thread_id=? AND m.manuscript_id=? ORDER BY m.created_at,m.message_id''',(tid,mid)).fetchall()
        return {'thread':_summary(raw,thread),'messages':[{'message_id':m,'sender':name,'body':body,'created_at':stamp} for m,uid,name,body,stamp in rows]}
    finally:db.rollback()


@router.post('/{mid}/dialogue/threads/{tid}/messages',status_code=201)
def send(mid:int,tid:str,payload:MessageRequest,response:Response,user=Depends(get_current_user),db:Session=Depends(get_db)):
    try:
        response.headers['Cache-Control']='no-store';raw=_begin(db,user);thread=_thread(raw,mid,tid,user)
        kind,iid,author,editor,eic,rkind,rnum,agreement,decision=_context(raw,mid,thread[2],user.user_id)
        if (kind,iid,author,editor,eic,rkind,rnum,agreement,decision) != (thread[7],thread[8],thread[9],thread[10],thread[11],thread[3],thread[4],thread[5],thread[6]):
            raise HTTPException(409,'Dialogue stage unavailable')
        body=payload.body.strip()
        if not body:raise HTTPException(422,'Message cannot be empty')
        prior=raw.execute('SELECT message_id,body,created_at FROM stage_dialogue_messages WHERE thread_id=? AND sender_id=? AND idempotency_key=?',(tid,user.user_id,payload.idempotency_key)).fetchone()
        if prior:
            if prior[1]!=body:raise HTTPException(409,'Message request conflicts with an earlier request')
            result={'message_id':prior[0],'body':prior[1],'created_at':prior[2]};db.rollback();return result
        message_id,stamp=uuid4().hex,_stamp()
        raw.execute('INSERT INTO stage_dialogue_messages VALUES (?,?,?,?,?,?,?)',(message_id,tid,mid,user.user_id,body,payload.idempotency_key,stamp))
        db.commit();return {'message_id':message_id,'body':body,'created_at':stamp}
    except HTTPException:db.rollback();raise
    except Exception:db.rollback();raise HTTPException(503,'Dialogue unavailable') from None

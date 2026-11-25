"""Lifecycle administration after explicit offline administrator bootstrap."""
import sqlite3
import json
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field,StrictInt
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app import eic_prospective_proof as proofs
from app.lifecycle_administration import authorize,apply,validated_state,AdministrationError
from app.models import User
from app.protected_eic_auth import require_current_eic
from app.routers.users import bearer_scheme,require_role
from app.database import get_db

router=APIRouter(prefix='/lifecycle-admin',tags=['lifecycle administration'])

class Action(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action: str
    request_id: str = Field(min_length=1,max_length=64)
    reason: str = Field(min_length=1,max_length=1000)
    expected_sequence: StrictInt = Field(ge=0)
    expected_generation: StrictInt = Field(ge=0)


def begin(db,user,credentials):
    raw=proofs.begin(db)
    require_current_eic(raw,db,credentials,user.user_id)
    try:authorize(raw,user.user_id)
    except (AdministrationError,sqlite3.Error,RuntimeError):raise HTTPException(403,'Administrator unavailable') from None
    return raw


@router.get('/successions')
def successions(user:User=Depends(require_role('eic')),credentials=Depends(bearer_scheme),db:Session=Depends(get_db)):
    try:
        raw=begin(db,user,credentials)
        if not raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lifecycle_admin_successions'").fetchone():return []
        rows=raw.execute('SELECT sequence,previous_user_id,next_user_id,event_digest,operator_key_sha256,approval_bundle,created_at FROM lifecycle_admin_successions ORDER BY sequence').fetchall()
        return [{'sequence':r[0],'previous_user_id':r[1],'next_user_id':r[2],'event_digest':r[3],
                 'operator_key_sha256':r[4],'approval_reference':json.loads(r[5])['payload']['approval_reference'],'created_at':r[6]} for r in rows]
    finally:db.rollback()


@router.get('/eics')
def list_eics(q: str = Query('', max_length=100), user:User=Depends(require_role('eic')), credentials=Depends(bearer_scheme),db:Session=Depends(get_db)):
    try:
        raw=begin(db,user,credentials)
        term=q.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        records=raw.execute("SELECT user_id,name FROM users WHERE role='eic' AND (name LIKE ? ESCAPE '\\' OR CAST(user_id AS TEXT) LIKE ? ESCAPE '\\') ORDER BY user_id LIMIT 50",('%'+term+'%','%'+term+'%')).fetchall()
        result=[]
        for uid,name in records:
            try:
                current=validated_state(raw,uid)
                state=current.state if current else 'not_enrolled'
                enrolled=bool(raw.execute('SELECT 1 FROM lifecycle_eic_enrollments WHERE target_user_id=?',(uid,)).fetchone())
                if not enrolled and raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lifecycle_eic_enrollments_v2'").fetchone():
                    enrolled=bool(raw.execute('SELECT 1 FROM lifecycle_eic_enrollments_v2 WHERE target_user_id=?',(uid,)).fetchone())
                if not current and enrolled:state='enrolled_not_active'
                result.append({'user_id':uid,'name':name,'role':'eic','state':state,'sequence':current.sequence if current else 0,'generation':current.generation if current else 0})
            except (AdministrationError,sqlite3.Error):result.append({'user_id':uid,'name':name,'role':'eic','state':'unavailable','sequence':None,'generation':None})
        return result
    finally:db.rollback()


@router.get('/eics/{target_id}/history')
def history(target_id:int,user:User=Depends(require_role('eic')),credentials=Depends(bearer_scheme),db:Session=Depends(get_db)):
    try:
        raw=begin(db,user,credentials)
        if not raw.execute("SELECT 1 FROM users WHERE user_id=? AND role='eic'",(target_id,)).fetchone():raise HTTPException(404,'EIC unavailable')
        try:current=validated_state(raw,target_id)
        except (AdministrationError,sqlite3.Error):raise HTTPException(409,'Lifecycle unavailable') from None
        enrollment=raw.execute('SELECT actor_user_id,request_id,reason,created_at FROM lifecycle_eic_enrollments WHERE target_user_id=?',(target_id,)).fetchone()
        has_v2=bool(raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lifecycle_admin_successions'").fetchone())
        if not enrollment and has_v2:
            enrollment=raw.execute('SELECT actor_user_id,request_id,reason,created_at FROM lifecycle_eic_enrollments_v2 WHERE target_user_id=?',(target_id,)).fetchone()
        events=raw.execute('''SELECT e.event_id,e.sequence,e.from_state,e.to_state,e.auth_generation,e.actor_user_id,e.occurred_at,e.reason_code,
          a.action,a.request_id,a.reason,b.operator_key_sha256,b.approval_ref
          FROM account_lifecycle_events e LEFT JOIN lifecycle_administration_actions a ON a.event_id=e.event_id
          LEFT JOIN lifecycle_admin_bootstrap b ON b.lifecycle_event_id=e.event_id
          WHERE e.user_id=? ORDER BY e.sequence''',(target_id,)).fetchall()
        records=[]
        for row in events:
            item=dict(zip(('event_id','sequence','from_state','to_state','generation','actor_user_id','occurred_at','reason_code','action','request_id','reason','bootstrap_operator_fingerprint','bootstrap_approval_reference'),row))
            if has_v2 and item['action'] is None:
                newer=raw.execute('SELECT action,request_id,reason FROM lifecycle_administration_actions_v2 WHERE event_id=?',(item['event_id'],)).fetchone()
                if newer:item.update(zip(('action','request_id','reason'),newer))
                succession=raw.execute('SELECT operator_key_sha256,approval_bundle FROM lifecycle_admin_successions WHERE successor_lifecycle_event_id=?',(item['event_id'],)).fetchone()
                if succession:
                    item['bootstrap_operator_fingerprint']=succession[0]
                    item['bootstrap_approval_reference']=json.loads(succession[1])['payload']['approval_reference']
            if item['bootstrap_operator_fingerprint'] is not None:
                # 009 requires an in-app user FK; this bootstrap self-reference
                # is the subject, not the separately authenticated operator.
                item['actor_user_id']=None
                item['actor_kind']='offline_operator'
            else:
                item['actor_kind']='administrator'
            records.append(item)
        return {'user_id':target_id,'state':current.state if current else ('enrolled_not_active' if enrollment else 'not_enrolled'),
                'enrollment':{'actor_user_id':enrollment[0],'request_id':enrollment[1],'reason':enrollment[2],'created_at':enrollment[3]} if enrollment else None,
                'events':records}
    finally:db.rollback()


@router.post('/eics/{target_id}/actions')
def action(target_id:int,data:Action,user:User=Depends(require_role('eic')),credentials=Depends(bearer_scheme),db:Session=Depends(get_db)):
    try:
        raw=begin(db,user,credentials)
        result=apply(raw,user.user_id,target_id,data.action,data.request_id,data.reason,data.expected_sequence,data.expected_generation)
        db.commit();return result
    except HTTPException:db.rollback();raise
    except (AdministrationError,sqlite3.IntegrityError):db.rollback();raise HTTPException(409,'Lifecycle action unavailable') from None
    except (sqlite3.Error,SQLAlchemyError,RuntimeError):db.rollback();raise HTTPException(503,'Lifecycle action outcome unavailable') from None
    finally:db.rollback()

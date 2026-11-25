"""Transactional lifecycle administration; callers must authenticate independently."""
from datetime import datetime, timezone
from importlib import import_module
import sqlite3
from uuid import uuid4

from app.lifecycle_integrity import active_actor, LifecycleIntegrityError
from app.lifecycle_prototype import _state, PolicyError

schema=import_module('migrations.039_lifecycle_administration')

class AdministrationError(ValueError):
    pass


def stamp():return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def require_schema(raw):
    if not raw.in_transaction or raw.execute('PRAGMA foreign_keys').fetchone()!=(1,):
        raise AdministrationError('Administration transaction unavailable')
    if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(schema.MIGRATION_ID,)).fetchone():
        raise AdministrationError('Administration schema unavailable')
    try:schema.validate_schema(raw)
    except RuntimeError as exc:raise AdministrationError('Administration schema unavailable') from exc


def authorize(raw, actor_id):
    require_schema(raw)
    try:active_actor(raw,actor_id,'eic')
    except LifecycleIntegrityError as exc:raise AdministrationError('Administrator unavailable') from exc
    from app.lifecycle_succession import current_admin,SuccessionError
    try:current,sequence,_=current_admin(raw)
    except (SuccessionError,sqlite3.Error) as exc:raise AdministrationError('Administrator unavailable') from exc
    if current!=actor_id:
        raise AdministrationError('Administrator unavailable')
    return sequence


def validated_state(raw, target_id):
    """Validate complete active or disabled target history before use."""
    try:
        current=_state(raw,target_id)
        if current is None:return None
        rows=raw.execute('''SELECT e.sequence,e.from_state,e.to_state,e.reason_code,e.occurred_at,u.user_id
            FROM account_lifecycle_events e LEFT JOIN users u ON u.user_id=e.actor_user_id
            WHERE e.user_id=? ORDER BY e.sequence''',(target_id,)).fetchall()
        for seq,before,after,reason,when,actor in rows:
            expected='initial_enrollment' if seq==1 else ('administrative_disable' if (before,after)==('active','disabled') else 'administrative_reactivation')
            if actor is None or reason!=expected or not isinstance(when,str):raise ValueError('Event unavailable')
            if datetime.strptime(when,'%Y-%m-%dT%H:%M:%S.%fZ').strftime('%Y-%m-%dT%H:%M:%S.%fZ')!=when:raise ValueError('Event time unavailable')
        return current
    except (PolicyError,sqlite3.Error,ValueError,TypeError) as exc:
        raise AdministrationError('Lifecycle unavailable') from exc


def apply(raw, actor_id, target_id, action, request_id, reason, expected_sequence, expected_generation):
    """Caller authenticates the actor and owns the immediate transaction."""
    admin_sequence=authorize(raw,actor_id)
    if type(target_id) is not int or target_id<=0 or action not in ('enroll','activate','disable','reactivate'):
        raise AdministrationError('Target or action unavailable')
    if not isinstance(request_id,str) or not 1<=len(request_id)<=64 or not request_id.isascii() or any(not(c.isalnum() or c in '-_') for c in request_id):
        raise AdministrationError('Invalid request ID')
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=1000:
        raise AdministrationError('A reason is required')
    if type(expected_sequence) is not int or type(expected_generation) is not int:
        raise AdministrationError('Expected sequence and generation required')
    if raw.execute('SELECT 1 FROM lifecycle_eic_enrollments WHERE request_id=? UNION ALL SELECT 1 FROM lifecycle_administration_actions WHERE request_id=?',(request_id,request_id)).fetchone():
        raise AdministrationError('Request already recorded')
    has_v2=bool(raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lifecycle_admin_successions'").fetchone())
    if has_v2 and raw.execute('SELECT 1 FROM lifecycle_eic_enrollments_v2 WHERE request_id=? UNION ALL SELECT 1 FROM lifecycle_administration_actions_v2 WHERE request_id=?',(request_id,request_id)).fetchone():
        raise AdministrationError('Request already recorded')
    if raw.execute("SELECT 1 FROM users WHERE user_id=? AND role='eic'",(target_id,)).fetchone() is None:
        raise AdministrationError('Eligible EIC unavailable')
    current=validated_state(raw,target_id)
    if action=='enroll':
        if current is not None or (expected_sequence,expected_generation)!=(0,0):raise AdministrationError('Lifecycle changed')
        if raw.execute('SELECT 1 FROM lifecycle_eic_enrollments WHERE target_user_id=?',(target_id,)).fetchone() or (has_v2 and raw.execute('SELECT 1 FROM lifecycle_eic_enrollments_v2 WHERE target_user_id=?',(target_id,)).fetchone()):raise AdministrationError('Enrollment already recorded')
        if admin_sequence:
            raw.execute('INSERT INTO lifecycle_eic_enrollments_v2 VALUES (?,?,?,?,?,?)',(target_id,actor_id,admin_sequence,request_id,reason.strip(),stamp()))
        else:raw.execute('INSERT INTO lifecycle_eic_enrollments VALUES (?,?,?,?,?)',(target_id,actor_id,request_id,reason.strip(),stamp()))
        return {'status':'enrolled_not_active'}
    if action=='activate':
        enrolled=raw.execute('SELECT 1 FROM lifecycle_eic_enrollments WHERE target_user_id=?',(target_id,)).fetchone() or (has_v2 and raw.execute('SELECT 1 FROM lifecycle_eic_enrollments_v2 WHERE target_user_id=?',(target_id,)).fetchone())
        if current is not None or (expected_sequence,expected_generation)!=(0,0) or not enrolled:
            raise AdministrationError('Enrollment or lifecycle unavailable')
        before,after,seq,gen,code=None,'active',1,1,'initial_enrollment'
    else:
        if current is None or (current.sequence,current.generation)!=(expected_sequence,expected_generation):raise AdministrationError('Lifecycle changed')
        if action=='disable' and target_id==actor_id:raise AdministrationError('Final administrator cannot be disabled')
        if (action,current.state) not in (('disable','active'),('reactivate','disabled')):raise AdministrationError('Transition unavailable')
        before=current.state;after='disabled' if action=='disable' else 'active'
        seq=current.sequence+1;gen=current.generation+1
        code='administrative_disable' if action=='disable' else 'administrative_reactivation'
    event=uuid4().hex;now=stamp()
    raw.execute('INSERT INTO account_lifecycle_events VALUES (?,?,?,?,?,?,?,?,?)',(event,target_id,seq,before,after,gen,actor_id,now,code))
    if current is None:raw.execute('INSERT INTO account_lifecycle VALUES (?,?,?,?,?)',(target_id,after,seq,gen,event))
    else:
        changed=raw.execute('UPDATE account_lifecycle SET state=?,sequence=?,auth_generation=?,last_event_id=? WHERE user_id=? AND sequence=? AND auth_generation=?',(after,seq,gen,event,target_id,current.sequence,current.generation))
        if changed.rowcount!=1:raise AdministrationError('Lifecycle changed')
    if admin_sequence:raw.execute('INSERT INTO lifecycle_administration_actions_v2 VALUES (?,?,?,?,?,?,?,?)',(event,target_id,actor_id,admin_sequence,request_id,action,reason.strip(),now))
    else:raw.execute('INSERT INTO lifecycle_administration_actions VALUES (?,?,?,?,?,?,?)',(event,target_id,actor_id,request_id,action,reason.strip(),now))
    return {'status':after,'sequence':seq,'generation':gen,'event_id':event}

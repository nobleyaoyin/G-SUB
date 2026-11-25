"""Owner-authorized offline administrator succession; no public promotion API."""
import hashlib,json,re,sqlite3,time
from uuid import uuid4
from importlib import import_module
from pathlib import Path
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from app.bootstrap_nonce_ledger import Reservation
from app.lifecycle_integrity import active_actor, LifecycleIntegrityError

schema=import_module('migrations.040_lifecycle_succession')
_FIELDS={'version','purpose','database','device','inode','previous_admin_user_id','previous_digest','sequence','successor_user_id','successor_email_sha256','successor_lifecycle_action','successor_expected_sequence','successor_expected_generation','operator_public_key','approval_reference','issued_at','expires_at','nonce'}
_HEX=re.compile(r'^[0-9a-f]{64}$')

class SuccessionError(ValueError):pass


def validate_approval(bundle,owner_key,*,now=None,db_path=None):
    try:
        if not isinstance(bundle,dict) or set(bundle)!={'payload','owner_signature','operator_signature'} or not isinstance(bundle['payload'],dict):raise ValueError()
        p=bundle['payload']
        if set(p)!=_FIELDS or type(p['version']) is not int or p['version']!=1 or p['purpose']!='succession':raise ValueError()
        for name in ('device','inode','previous_admin_user_id','successor_user_id','sequence','issued_at','expires_at','successor_expected_sequence','successor_expected_generation'):
            if type(p[name]) is not int:raise ValueError()
        if p['successor_expected_sequence']<0 or p['successor_expected_generation']<0 or p['successor_lifecycle_action'] not in ('require_active','activate','reactivate'):raise ValueError()
        if p['previous_admin_user_id']<=0 or p['successor_user_id']<=0 or p['sequence']<=0 or p['previous_admin_user_id']==p['successor_user_id']:raise ValueError()
        for name in ('previous_digest','successor_email_sha256','operator_public_key','nonce'):
            if not isinstance(p[name],str) or not _HEX.fullmatch(p[name]):raise ValueError()
        if not isinstance(p['approval_reference'],str) or not 1<=len(p['approval_reference'].strip())<=200 or p['approval_reference']!=p['approval_reference'].strip():raise ValueError()
        if p['expires_at']<p['issued_at'] or p['expires_at']-p['issued_at']>900:raise ValueError()
        if now is not None and not p['issued_at']<=now<=p['expires_at']:raise ValueError()
        if db_path is not None:
            path=Path(db_path)
            if not path.is_absolute() or path!=path.resolve(strict=True) or not path.is_file():raise ValueError()
            st=path.stat()
            if (p['database'],p['device'],p['inode'])!=(str(path),st.st_dev,st.st_ino):raise ValueError()
        elif not isinstance(p['database'],str) or not Path(p['database']).is_absolute():raise ValueError()
        msg=json.dumps(p,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
        Ed25519PublicKey.from_public_bytes(owner_key).verify(bytes.fromhex(bundle['owner_signature']),b'GSUB-LIFECYCLE-SUCCESSION-OWNER-v1\0'+msg)
        op=bytes.fromhex(p['operator_public_key'])
        Ed25519PublicKey.from_public_bytes(op).verify(bytes.fromhex(bundle['operator_signature']),b'GSUB-LIFECYCLE-SUCCESSION-OPERATOR-v1\0'+msg)
        return p,hashlib.sha256(msg).hexdigest(),hashlib.sha256(owner_key).hexdigest(),hashlib.sha256(op).hexdigest()
    except (InvalidSignature,ValueError,TypeError,KeyError,OSError) as exc:raise SuccessionError('Succession approval unavailable') from exc


def current_admin(raw):
    base=raw.execute('SELECT admin_user_id,approval_sha256,owner_key_sha256 FROM lifecycle_admin_bootstrap WHERE singleton=1').fetchone()
    if not base:raise SuccessionError('Administrator unavailable')
    admin,digest,owner_digest=base;sequence=0
    exists=bool(raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lifecycle_admin_successions'").fetchone())
    applied=bool(raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(schema.MIGRATION_ID,)).fetchone())
    if exists!=applied:raise SuccessionError('Succession schema unavailable')
    if not exists:return admin,sequence,digest
    try:schema.validate_schema(raw)
    except RuntimeError as exc:raise SuccessionError('Succession schema unavailable') from exc
    rows=raw.execute('SELECT sequence,previous_user_id,next_user_id,previous_digest,event_digest,owner_public_key,operator_key_sha256,successor_lifecycle_event_id,approval_bundle FROM lifecycle_admin_successions ORDER BY sequence').fetchall()
    for seq,previous,next_user,prior,event,owner_hex,operator_digest,lifecycle_event,record in rows:
        try:
            key=bytes.fromhex(owner_hex);bundle=json.loads(record)
            p,computed,key_digest,op_digest=validate_approval(bundle,key)
            if (seq,previous,prior)!=(sequence+1,admin,digest) or (p['sequence'],p['previous_admin_user_id'],p['previous_digest'],p['successor_user_id'])!=(seq,previous,prior,next_user) or computed!=event or key_digest!=owner_digest or op_digest!=operator_digest:raise ValueError()
            action=p['successor_lifecycle_action']; before_seq=p['successor_expected_sequence']; before_gen=p['successor_expected_generation']
            if action=='require_active':
                if lifecycle_event is not None or before_seq<1 or before_gen<1:raise ValueError()
            else:
                expected_before=None if action=='activate' else 'disabled'
                reason='initial_enrollment' if action=='activate' else 'administrative_reactivation'
                if action=='activate' and (before_seq,before_gen)!=(0,0):raise ValueError()
                if action=='reactivate' and (before_seq<1 or before_gen<1):raise ValueError()
                found=raw.execute('SELECT user_id,sequence,from_state,to_state,auth_generation,actor_user_id,reason_code FROM account_lifecycle_events WHERE event_id=?',(lifecycle_event,)).fetchone()
                if found!=(next_user,before_seq+1,expected_before,'active',before_gen+1,next_user,reason):raise ValueError()
        except (ValueError,TypeError,KeyError,SuccessionError) as exc:raise SuccessionError('Succession chain unavailable') from exc
        admin,sequence,digest=next_user,seq,event
    return admin,sequence,digest


def succeed(raw,bundle,owner_key,db_path,*,reservation):
    if not raw.in_transaction or raw.execute('PRAGMA foreign_keys').fetchone()!=(1,):raise SuccessionError('Transaction unavailable')
    from app.lifecycle_administration import require_schema
    try:require_schema(raw)
    except ValueError as exc:raise SuccessionError('Administration schema unavailable') from exc
    row=raw.execute('PRAGMA database_list').fetchall()
    if not any(r[1]=='main' and r[2] and Path(r[2]).resolve()==Path(db_path).resolve() for r in row):raise SuccessionError('Database unavailable')
    try:
        schema.validate_schema(raw)
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(schema.MIGRATION_ID,)).fetchone():raise ValueError()
        p,digest,owner_digest,operator_digest=validate_approval(bundle,owner_key,now=int(time.time()),db_path=db_path)
        if type(reservation) is not Reservation:raise ValueError()
        reservation.consume(p['nonce'],digest,operator_digest)
        current,sequence,prior=current_admin(raw)
        owner=raw.execute('SELECT owner_key_sha256 FROM lifecycle_admin_bootstrap WHERE singleton=1').fetchone()
        if not owner or owner[0]!=owner_digest or (p['previous_admin_user_id'],p['sequence'],p['previous_digest'])!=(current,sequence+1,prior):raise ValueError()
        target=p['successor_user_id'];user=raw.execute('SELECT email,role FROM users WHERE user_id=?',(target,)).fetchone()
        if not user or user[1]!='eic' or hashlib.sha256(user[0].strip().lower().encode()).hexdigest()!=p['successor_email_sha256']:raise ValueError()
        from app.lifecycle_administration import stamp
        from app.lifecycle_prototype import _state
        state=_state(raw,target); action=p['successor_lifecycle_action']; expected=(p['successor_expected_sequence'],p['successor_expected_generation'])
        actual=(state.sequence,state.generation) if state else (0,0)
        if actual!=expected:raise ValueError()
        lifecycle_event=None
        if action=='require_active':
            if not state or state.state!='active':raise ValueError()
        else:
            if action=='activate' and state is not None:raise ValueError()
            if action=='reactivate' and (not state or state.state!='disabled'):raise ValueError()
            lifecycle_event=uuid4().hex; before=None if state is None else state.state
            reason='initial_enrollment' if state is None else 'administrative_reactivation'
            raw.execute('INSERT INTO account_lifecycle_events VALUES (?,?,?,?,?,?,?,?,?)',(lifecycle_event,target,actual[0]+1,before,'active',actual[1]+1,target,stamp(),reason))
            if state is None:raw.execute('INSERT INTO account_lifecycle VALUES (?,?,?,?,?)',(target,'active',1,1,lifecycle_event))
            else:
                updated=raw.execute("UPDATE account_lifecycle SET state='active',sequence=?,auth_generation=?,last_event_id=? WHERE user_id=? AND state='disabled' AND sequence=? AND auth_generation=?",(actual[0]+1,actual[1]+1,lifecycle_event,target,*actual))
                if updated.rowcount!=1:raise ValueError()
        active_actor(raw,target,'eic')
        raw.execute('INSERT INTO lifecycle_admin_successions VALUES (?,?,?,?,?,?,?,?,?,?)',(p['sequence'],current,target,prior,digest,owner_key.hex(),operator_digest,lifecycle_event,json.dumps(bundle,sort_keys=True,separators=(',',':')),stamp()))
        if current_admin(raw)!=(target,sequence+1,digest):raise ValueError()
        return {'status':'succeeded','sequence':sequence+1,'admin_user_id':target,'event_digest':digest}
    except (sqlite3.Error,RuntimeError,ValueError,TypeError,LifecycleIntegrityError) as exc:raise SuccessionError('Succession unavailable') from exc

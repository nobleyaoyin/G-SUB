"""Offline bootstrap verification. Production CLI pins the owner trust anchor."""
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from uuid import uuid4
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from app.lifecycle_administration import require_schema, stamp, AdministrationError
from app.lifecycle_integrity import active_actor
from app.bootstrap_nonce_ledger import Reservation

_FIELDS={'version','database','device','inode','target_user_id','target_email_sha256','operator_public_key','approval_reference','issued_at','expires_at','nonce'}
_HEX=re.compile(r'^[0-9a-f]{64}$')


def validate_approval(bundle, owner_public_key, db_path, target_id, approval_reference, *, now=None):
    """Verify owner approval and operator proof-of-possession over the same payload."""
    try:
        if set(bundle)!={'payload','owner_signature','operator_signature'} or not isinstance(bundle['payload'],dict):raise ValueError()
        payload=bundle['payload']
        if (set(payload)!=_FIELDS or type(payload['version']) is not int or payload['version']!=1
            or type(target_id) is not int or target_id<=0 or type(payload['target_user_id']) is not int
            or type(payload['device']) is not int or type(payload['inode']) is not int):raise ValueError()
        path=Path(db_path)
        if not path.is_absolute() or path!=path.resolve(strict=True) or not path.is_file():raise ValueError()
        stat=path.stat()
        if (payload['database']!=str(path) or payload['device']!=stat.st_dev or payload['inode']!=stat.st_ino
            or payload['target_user_id']!=target_id or payload['approval_reference']!=approval_reference):raise ValueError()
        if not isinstance(approval_reference,str) or not 1<=len(approval_reference.strip())<=200 or approval_reference!=approval_reference.strip():raise ValueError()
        for key in ('target_email_sha256','operator_public_key','nonce'):
            if not isinstance(payload[key],str) or not _HEX.fullmatch(payload[key]):raise ValueError()
        current=int(time.time()) if now is None else now
        if any(type(payload[k]) is not int for k in ('issued_at','expires_at')) or not payload['issued_at']<=current<=payload['expires_at'] or payload['expires_at']-payload['issued_at']>900:raise ValueError()
        message=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
        owner=Ed25519PublicKey.from_public_bytes(owner_public_key)
        operator=Ed25519PublicKey.from_public_bytes(bytes.fromhex(payload['operator_public_key']))
        owner.verify(bytes.fromhex(bundle['owner_signature']),b'GSUB-LIFECYCLE-OWNER-v1\0'+message)
        operator.verify(bytes.fromhex(bundle['operator_signature']),b'GSUB-LIFECYCLE-OPERATOR-v1\0'+message)
        return payload,hashlib.sha256(message).hexdigest(),hashlib.sha256(owner_public_key).hexdigest(),hashlib.sha256(bytes.fromhex(payload['operator_public_key'])).hexdigest()
    except (ValueError,TypeError,KeyError,OSError,InvalidSignature) as exc:
        raise AdministrationError('Bootstrap approval unavailable or invalid') from exc


def bootstrap(raw, bundle, owner_public_key, db_path, target_id, approval_reference, *, reservation):
    """Called only by the offline CLI inside an immediate, foreign-key transaction."""
    require_schema(raw)
    database=raw.execute('PRAGMA database_list').fetchall()
    if len([row for row in database if row[1]=='main' and row[2] and Path(row[2]).resolve()==Path(db_path).resolve()]) != 1:
        raise AdministrationError('Bootstrap database identity unavailable')
    payload,approval_sha,owner_sha,operator_sha=validate_approval(bundle,owner_public_key,db_path,target_id,approval_reference)
    if type(reservation) is not Reservation:raise AdministrationError('Approval reservation required')
    try:reservation.consume(payload['nonce'],approval_sha,operator_sha)
    except ValueError as exc:raise AdministrationError('Approval reservation unavailable') from exc
    if raw.execute('SELECT 1 FROM lifecycle_admin_bootstrap').fetchone():raise AdministrationError('Administrator already bootstrapped')
    user=raw.execute('SELECT email,role FROM users WHERE user_id=?',(target_id,)).fetchone()
    if not user or user[1]!='eic' or not isinstance(user[0],str):raise AdministrationError('Eligible existing EIC unavailable')
    if hashlib.sha256(user[0].strip().lower().encode('utf-8')).hexdigest()!=payload['target_email_sha256']:
        raise AdministrationError('Target account identity does not match approval')
    if raw.execute('SELECT 1 FROM account_lifecycle WHERE user_id=? UNION ALL SELECT 1 FROM account_lifecycle_events WHERE user_id=?',(target_id,target_id)).fetchone():raise AdministrationError('Existing lifecycle cannot be bootstrapped')
    eid=uuid4().hex;now=stamp()
    # 009 requires an application user FK. At bootstrap this is a subject
    # self-reference, not the operator; the signed operator is recorded below.
    raw.execute('INSERT INTO account_lifecycle_events VALUES (?,?,?,?,?,?,?,?,?)',(eid,target_id,1,None,'active',1,target_id,now,'initial_enrollment'))
    raw.execute('INSERT INTO account_lifecycle VALUES (?,?,?,?,?)',(target_id,'active',1,1,eid))
    recorded=json.dumps(bundle,sort_keys=True,separators=(',',':'),ensure_ascii=True)
    raw.execute('INSERT INTO lifecycle_admin_bootstrap VALUES (?,?,?,?,?,?,?,?,?)',(1,target_id,eid,operator_sha,owner_sha,approval_reference,approval_sha,recorded,now))
    if active_actor(raw,target_id,'eic')!=1:raise AdministrationError('Bootstrap verification failed')
    return {'status':'active','admin_user_id':target_id,'event_id':eid,'operator_key_sha256':operator_sha}

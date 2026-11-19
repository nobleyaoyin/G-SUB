"""Google OIDC helpers; provider endpoints are fixed and never request-controlled."""
import hashlib
import hmac
import math
import os
import time
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

AUTHORIZE_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
JWKS_URL = 'https://www.googleapis.com/oauth2/v3/certs'

def digest(value): return hashlib.sha256(value.encode('ascii')).hexdigest()

def configuration(required=True):
    values = tuple(os.environ.get(k, '').strip() for k in ('GSUB_GOOGLE_CLIENT_ID','GSUB_GOOGLE_CLIENT_SECRET','GSUB_GOOGLE_REDIRECT_URI'))
    if not all(values):
        if required: raise HTTPException(503, 'Google sign-in is unavailable')
        return None
    url = urlparse(values[2])
    local = url.scheme == 'http' and url.hostname in ('localhost','127.0.0.1','::1')
    if not (url.scheme == 'https' or local) or not url.hostname or url.username or url.password or url.query or url.fragment or url.path != '/api/users/google/callback':
        if required: raise HTTPException(503, 'Google sign-in configuration unavailable')
        return None
    return values

def require_schema(db):
    try:
        if not db.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='015_google_oidc'")).first(): raise ValueError()
        for table, columns in {
            'google_identities': {'subject','user_id','linked_at'},
            'google_oauth_transactions': {'state_hash','browser_hash','nonce','verifier','link_user_id','expires_at'},
            'google_oauth_handoffs': {'receipt_hash','user_id','expires_at'},
        }.items():
            if {r[1] for r in db.connection().exec_driver_sql(f'PRAGMA table_info({table})')} != columns: raise ValueError()
    except (SQLAlchemyError, ValueError):
        raise HTTPException(503, 'Google sign-in storage unavailable') from None

def origin(config):
    url = urlparse(config[2]); return f'{url.scheme}://{url.netloc}'

def check_origin(request, config):
    if request.headers.get('origin') != origin(config): raise HTTPException(403, 'Invalid request origin')

def verify_id_token(token, jwks, client_id, nonce):
    try:
        from authlib.jose import JsonWebToken
        if not isinstance(token, str) or len(token) > 20000: raise ValueError()
        claims = JsonWebToken(['RS256']).decode(token, jwks)
        claims.validate()
        issuer = claims.get('iss'); aud = claims.get('aud'); expiry = claims.get('exp')
        if issuer not in ('https://accounts.google.com','accounts.google.com'): raise ValueError()
        if isinstance(aud, str):
            if aud != client_id: raise ValueError()
        elif not isinstance(aud, list) or not all(isinstance(item,str) for item in aud) or client_id not in aud or (len(aud) > 1 and claims.get('azp') != client_id): raise ValueError()
        if claims.get('azp') is not None and claims['azp'] != client_id: raise ValueError()
        if isinstance(expiry, bool) or not isinstance(expiry, (int,float)) or not math.isfinite(expiry) or expiry <= time.time(): raise ValueError()
        if not isinstance(claims.get('nonce'), str) or not hmac.compare_digest(claims['nonce'], nonce): raise ValueError()
        if claims.get('email_verified') is not True: raise ValueError()
        subject = claims.get('sub'); email = claims.get('email')
        if not isinstance(subject,str) or not 1 <= len(subject) <= 255 or not isinstance(email,str): raise ValueError()
        email = str(TypeAdapter(EmailStr).validate_python(email)).strip().lower()
        if len(email) > 255: raise ValueError()
        name = claims.get('name'); name = name.strip()[:100] if isinstance(name,str) else ''
        return subject, email, name or 'Google user'
    except Exception:
        # Authlib raises multiple JOSE-specific exception types. Never expose token details.
        raise HTTPException(401, 'Google identity verification failed') from None

def exchange_code(config, code, verifier, nonce):
    if not isinstance(code,str) or not 1 <= len(code) <= 4096: raise HTTPException(400, 'Google authorization failed')
    try:
        response = httpx.post(TOKEN_URL, data={'code':code, 'client_id':config[0], 'client_secret':config[1],
            'redirect_uri':config[2], 'grant_type':'authorization_code', 'code_verifier':verifier}, timeout=8.0, follow_redirects=False)
        response.raise_for_status(); data = response.json()
        keys = httpx.get(JWKS_URL, timeout=8.0, follow_redirects=False); keys.raise_for_status()
        return verify_id_token(data['id_token'], keys.json(), config[0], nonce)
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise HTTPException(502, 'Google sign-in could not be completed') from None

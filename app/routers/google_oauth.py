"""Opt-in Google OIDC; all browser handoffs are single use."""
import secrets
import time
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from app import captcha, google_oidc as oidc
from app.config import IS_DEMO
from app.database import get_db
from app.models import User, UserEmailVerification
from app.email.verification_service import is_email_verified
from app.routers.users import get_current_user, limit_login
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix='/users/google', tags=['Google sign-in'])
TX_COOKIE = 'gsub_google_transaction'
RESULT_COOKIE = 'gsub_google_result'

class Start(BaseModel):
    captcha_token: str | None = Field(default=None, max_length=4096)

class Link(BaseModel):
    password: str = Field(min_length=1, max_length=128)

def set_cookie(response, name, value, config, seconds):
    response.set_cookie(name, value, max_age=seconds, httponly=True, secure=config[2].startswith('https://'), samesite='lax', path='/')
    response.headers['Cache-Control'] = 'no-store'

def valid_secret(value):
    return isinstance(value,str) and 20 <= len(value) <= 200 and value.isascii() and all(c.isalnum() or c in '-_' for c in value)

def start_transaction(db, response, config, actor_id=None):
    oidc.require_schema(db)
    state = secrets.token_urlsafe(32); browser = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32); verifier = secrets.token_urlsafe(64)
    try:
        from authlib.oauth2.rfc7636 import create_s256_code_challenge
    except ImportError:
        raise HTTPException(503, 'Google sign-in dependency unavailable') from None
    db.execute(text('INSERT INTO google_oauth_transactions (state_hash,browser_hash,nonce,verifier,link_user_id,expires_at) VALUES (:state,:browser,:nonce,:verifier,:actor,:expires)'),
        {'state':oidc.digest(state),'browser':oidc.digest(browser),'nonce':nonce,'verifier':verifier,'actor':actor_id,'expires':int(time.time())+600})
    db.commit()
    set_cookie(response, TX_COOKIE, browser, config, 600)
    query = urlencode({'client_id':config[0], 'redirect_uri':config[2], 'response_type':'code', 'scope':'openid email profile',
        'state':state,'nonce':nonce,'code_challenge':create_s256_code_challenge(verifier),'code_challenge_method':'S256'})
    return {'authorization_url':oidc.AUTHORIZE_URL+'?'+query}

@router.post('/start')
def start(data: Start, request: Request, response: Response, db: Session = Depends(get_db)):
    config = oidc.configuration(); oidc.check_origin(request,config); limit_login(request); captcha.verify(data.captcha_token)
    return start_transaction(db,response,config)

@router.post('/link/start')
def link_start(data: Link, request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = oidc.configuration(); oidc.check_origin(request,config); limit_login(request)
    if not verify_password(data.password,user.password_hash): raise HTTPException(401,'Password reauthentication failed')
    return start_transaction(db,response,config,user.user_id)

@router.get('/callback')
def callback(request: Request, state: str = '', code: str = '', db: Session = Depends(get_db)):
    config = oidc.configuration(); oidc.require_schema(db)
    browser = request.cookies.get(TX_COOKIE)
    if not valid_secret(state) or not valid_secret(browser): raise HTTPException(400,'Google authorization expired or invalid')
    row = db.execute(text('DELETE FROM google_oauth_transactions WHERE state_hash=:state AND browser_hash=:browser AND expires_at>:now RETURNING nonce,verifier,link_user_id'),
        {'state':oidc.digest(state),'browser':oidc.digest(browser),'now':int(time.time())}).mappings().first()
    if row is None:
        db.rollback(); raise HTTPException(400,'Google authorization expired or invalid')
    db.commit()  # Consume before network calls; ambiguous operations are not retried.
    subject, email, name = oidc.exchange_code(config,code,row['verifier'],row['nonce'])
    existing = db.execute(text('SELECT user_id FROM google_identities WHERE subject=:subject'),{'subject':subject}).scalar_one_or_none()
    actor_id = row['link_user_id']
    try:
        if actor_id is not None:
            if existing is not None and existing != actor_id: raise HTTPException(409,'Google identity is already linked')
            if existing is None:
                db.execute(text('INSERT INTO google_identities(subject,user_id,linked_at) VALUES (:sub,:uid,:now)'),{'sub':subject,'uid':actor_id,'now':int(time.time())})
            user = db.get(User,actor_id)
        elif existing is not None:
            user = db.get(User,existing)
        else:
            # Never attach an existing local account on the basis of email alone.
            if db.scalar(select(User.user_id).where(func.lower(User.email)==email)) is not None:
                raise HTTPException(409,'Sign in with your existing account and link Google explicitly')
            user = User(name=name,email=email,password_hash=hash_password(secrets.token_urlsafe(48)),role='author')
            db.add(user); db.flush()
            db.execute(text('INSERT INTO google_identities(subject,user_id,linked_at) VALUES (:sub,:uid,:now)'),{'sub':subject,'uid':user.user_id,'now':int(time.time())})
        if user is None: raise HTTPException(401,'Account unavailable')
        if not IS_DEMO and db.get(UserEmailVerification,user.user_id) is not None and not is_email_verified(db,user):
            raise HTTPException(403,'Please verify your email address before continuing.')
        receipt = secrets.token_urlsafe(32)
        db.execute(text('INSERT INTO google_oauth_handoffs(receipt_hash,user_id,expires_at) VALUES (:receipt,:uid,:expires)'),
                   {'receipt':oidc.digest(receipt),'uid':user.user_id,'expires':int(time.time())+60})
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,'Google account linking conflict') from None
    except SQLAlchemyError:
        db.rollback(); raise HTTPException(503,'Google account storage unavailable') from None
    except Exception:
        db.rollback(); raise
    response = RedirectResponse('/google-callback',status_code=303)
    response.delete_cookie(TX_COOKIE,path='/')
    set_cookie(response,RESULT_COOKIE,receipt,config,60)
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

@router.post('/exchange')
def exchange(request: Request, response: Response, db: Session = Depends(get_db)):
    config = oidc.configuration(); oidc.check_origin(request,config); oidc.require_schema(db)
    receipt = request.cookies.get(RESULT_COOKIE)
    if not valid_secret(receipt): raise HTTPException(401,'Google sign-in expired')
    row = db.execute(text('DELETE FROM google_oauth_handoffs WHERE receipt_hash=:receipt AND expires_at>:now RETURNING user_id'),
        {'receipt':oidc.digest(receipt),'now':int(time.time())}).first()
    if row is None:
        db.rollback(); raise HTTPException(401,'Google sign-in expired')
    db.commit()
    response.delete_cookie(RESULT_COOKIE,path='/'); response.headers['Cache-Control']='no-store'
    return {'access_token':create_access_token(row[0]),'token_type':'bearer'}

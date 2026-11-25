"""Protected lifecycle validation using only synthetic disposable fixtures."""
import importlib
import sqlite3
import pytest
from test_batch38_eic_proof import fixture

m9 = importlib.import_module('migrations.009_account_invitation_lifecycle')
m23 = importlib.import_module('migrations.023_reviewer_candidate_intake')


def reconciliation(f, actor, headers):
    return f.client.get(f'/eic/manuscripts/{f.mid}/reviewer-candidate-reconciliation', headers=headers(actor))


def test_active_eic_and_wrong_roles(fixture):
    f, chief, headers, _, _, _, _ = fixture
    m23.migrate(f.db_path)
    assert reconciliation(f,chief,headers).status_code==200
    for actor in (f.author,f.editor,f.reviewer):
        assert reconciliation(f,actor,headers).status_code==403
    assert f.client.get('/eic/editors',headers=headers(chief)).status_code==200


def test_missing_immutable_trigger_fails_closed(fixture):
    f, chief, headers, _, _, _, _ = fixture
    m23.migrate(f.db_path)
    assert reconciliation(f,chief,headers).status_code==200
    with sqlite3.connect(f.db_path) as db:
        db.execute('DROP TRIGGER lifecycle_events_no_update')
    assert reconciliation(f,chief,headers).status_code==403
    # Existing ordinary EIC dashboard reads are outside this protected boundary.
    assert f.client.get('/eic/editors',headers=headers(chief)).status_code==200


@pytest.mark.parametrize('field,value', [('auth_generation',2),('occurred_at','2026-99-99T00:00:00.000000Z')])
def test_tampered_history_fails_closed_even_if_trigger_restored(fixture, field, value):
    f, chief, headers, _, _, _, _ = fixture
    m23.migrate(f.db_path)
    assert reconciliation(f,chief,headers).status_code==200
    with sqlite3.connect(f.db_path) as db:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('PRAGMA ignore_check_constraints=ON')
        db.execute('DROP TRIGGER lifecycle_events_no_update')
        db.execute(f'UPDATE account_lifecycle_events SET {field}=? WHERE user_id=?',(value,chief.user_id))
        db.execute(m9.DDL['lifecycle_events_no_update'])
    assert reconciliation(f,chief,headers).status_code==403


def test_eic_login_generation_and_stale_token_fail_closed(fixture):
    from app.models import User
    from app.security import hash_password, create_access_token, SECRET_KEY, ALGORITHM
    from app.lifecycle_prototype import lifecycle_change
    from tests.test_lifecycle_prototype import principal, AUTHORITY
    from datetime import datetime, timedelta, timezone
    import jwt
    f, chief, headers, _, _, _, _ = fixture
    m23.migrate(f.db_path)
    target=User(name='Synthetic lifecycle EIC',email='sprint11-eic@example.com',password_hash=hash_password('synthetic-test-password'),role='eic')
    f.db.add(target); f.db.commit(); uid=target.user_id
    def change(action,sequence,generation):
        with sqlite3.connect(f.db_path, timeout=.2) as raw:
            raw.execute('PRAGMA foreign_keys=ON')
            return lifecycle_change(raw,principal(chief.user_id),uid,action,authority=AUTHORITY,expected_sequence=sequence,expected_generation=generation)
    change('enroll',0,0)
    login=f.client.post('/users/login',json={'email':target.email,'password':'synthetic-test-password'})
    assert login.status_code==200
    old={'Authorization':'Bearer '+login.json()['access_token']}
    endpoint=f'/eic/manuscripts/{f.mid}/reviewer-candidate-reconciliation'
    assert f.client.get(endpoint,headers=old).status_code==200
    assert f.client.get(endpoint,headers={'Authorization':'Bearer '+create_access_token(uid)}).status_code==403
    assert f.client.get(endpoint,headers={'Authorization':'Bearer '+create_access_token(uid,lifecycle_generation=2)}).status_code==403
    for bad in (True, '1', 0):
        token=jwt.encode({'sub':str(uid),'exp':datetime.now(timezone.utc)+timedelta(minutes=2),'lifecycle_generation':bad},SECRET_KEY,algorithm=ALGORITHM)
        assert f.client.get(endpoint,headers={'Authorization':'Bearer '+token}).status_code==403
    change('disable',1,1)
    assert f.client.get(endpoint,headers=old).status_code==403
    change('reactivate',2,2)
    assert f.client.get(endpoint,headers=old).status_code==403
    assert f.client.get('/eic/editors',headers=old).status_code==200
    fresh=f.client.post('/users/login',json={'email':target.email,'password':'synthetic-test-password'})
    assert fresh.status_code==200
    assert f.client.get(endpoint,headers={'Authorization':'Bearer '+fresh.json()['access_token']}).status_code==200


def test_google_handoff_issues_bound_eic_token(fixture, monkeypatch):
    import time
    from app import google_oidc
    from app.security import decode_lifecycle_generation
    f, chief, headers, _, _, _, _ = fixture
    m23.migrate(f.db_path)
    for key,value in {'GSUB_GOOGLE_CLIENT_ID':'synthetic-client','GSUB_GOOGLE_CLIENT_SECRET':'synthetic-secret',
                      'GSUB_GOOGLE_REDIRECT_URI':'http://localhost/api/users/google/callback'}.items():
        monkeypatch.setenv(key,value)
    receipt='synthetic_receipt_for_sprint11_testing'
    with sqlite3.connect(f.db_path) as db:
        db.execute('INSERT INTO google_oauth_handoffs(receipt_hash,user_id,expires_at) VALUES (?,?,?)',
                   (google_oidc.digest(receipt),chief.user_id,int(time.time())+60))
    f.client.cookies.set('gsub_google_result',receipt)
    result=f.client.post('/users/google/exchange',headers={'Origin':'http://localhost'})
    assert result.status_code==200
    token=result.json()['access_token']
    assert decode_lifecycle_generation(token,chief.user_id)==1
    assert f.client.get(f'/eic/manuscripts/{f.mid}/reviewer-candidate-reconciliation',headers={'Authorization':'Bearer '+token}).status_code==200

"""Offline Google OIDC and PKCE regressions using ephemeral test keys only."""
import base64
import hashlib
import time
from urllib.parse import parse_qs, urlparse

import pytest
from authlib.jose import JsonWebToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app import google_oidc
from app.routers import google_oauth


@pytest.fixture(scope='module')
def synthetic_rsa_keys():
    # Generated in memory solely for this run; never used by an account or service.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
    return private, public


@pytest.fixture
def claims():
    return {'iss': 'https://accounts.google.com', 'aud': 'client.example',
            'exp': int(time.time()) + 300, 'nonce': 'synthetic-nonce',
            'email_verified': True, 'sub': 'synthetic-subject',
            'email': 'author@example.org', 'name': 'Synthetic Author'}


def _sign(private, claims):
    return JsonWebToken(['RS256']).encode({'alg': 'RS256'}, claims, private).decode('ascii')


def test_valid_rs256_token_is_accepted(synthetic_rsa_keys, claims):
    private, public = synthetic_rsa_keys
    assert google_oidc.verify_id_token(_sign(private, claims), public, 'client.example',
                                       'synthetic-nonce') == (
                                           'synthetic-subject', 'author@example.org', 'Synthetic Author')


@pytest.mark.parametrize('change', [
    {'iss': 'https://issuer.example.org'},
    {'aud': 'other-client'},
    {'aud': ['client.example', 'other-client']},
    {'exp': 1},
    {'nonce': 'wrong-nonce'},
    {'email_verified': False},
])
def test_invalid_claims_are_rejected(synthetic_rsa_keys, claims, change):
    private, public = synthetic_rsa_keys
    claims.update(change)
    with pytest.raises(HTTPException) as error:
        google_oidc.verify_id_token(_sign(private, claims), public, 'client.example', 'synthetic-nonce')
    assert error.value.status_code == 401


def test_signature_from_untrusted_key_is_rejected(synthetic_rsa_keys, claims):
    private, _ = synthetic_rsa_keys
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_public = other.public_key().public_bytes(serialization.Encoding.PEM,
                                                   serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(HTTPException) as error:
        google_oidc.verify_id_token(_sign(private, claims), other_public, 'client.example', 'synthetic-nonce')
    assert error.value.status_code == 401


def test_non_rs256_algorithm_is_rejected(synthetic_rsa_keys, claims):
    _, public = synthetic_rsa_keys
    token = JsonWebToken(['HS256']).encode({'alg': 'HS256'}, claims, b'synthetic-only-key').decode('ascii')
    with pytest.raises(HTTPException) as error:
        google_oidc.verify_id_token(token, public, 'client.example', 'synthetic-nonce')
    assert error.value.status_code == 401


def test_start_transaction_binds_s256_challenge_to_stored_verifier(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    with Session(engine) as db:
        db.execute(text('CREATE TABLE google_oauth_transactions '
                        '(state_hash TEXT, browser_hash TEXT, nonce TEXT, verifier TEXT, '
                        'link_user_id INTEGER, expires_at INTEGER)'))
        db.commit()
        monkeypatch.setattr(google_oidc, 'require_schema', lambda _db: None)
        response = Response()
        result = google_oauth.start_transaction(db, response,
            ('client.example', 'synthetic-secret', 'http://localhost/api/users/google/callback'))
        params = parse_qs(urlparse(result['authorization_url']).query)
        row = db.execute(text('SELECT state_hash, nonce, verifier FROM google_oauth_transactions')).one()
        expected = base64.urlsafe_b64encode(hashlib.sha256(row.verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
        assert params['code_challenge_method'] == ['S256']
        assert params['code_challenge'] == [expected]
        assert params['state'] != [row.state_hash]
        assert google_oidc.digest(params['state'][0]) == row.state_hash
        assert params['nonce'] == [row.nonce]
        assert response.headers['cache-control'] == 'no-store'
    engine.dispose()


def test_exchange_forwards_pkce_verifier_without_contacting_provider(monkeypatch):
    captured = {}

    class SyntheticResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'id_token': 'synthetic-token'}

    def fake_post(url, *, data, timeout, follow_redirects):
        captured.update(data)
        return SyntheticResponse()

    monkeypatch.setattr(google_oidc.httpx, 'post', fake_post)
    monkeypatch.setattr(google_oidc.httpx, 'get', lambda *args, **kwargs: SyntheticResponse())
    monkeypatch.setattr(google_oidc, 'verify_id_token',
                        lambda token, jwks, client, nonce: ('subject', 'author@example.org', 'Author'))
    result = google_oidc.exchange_code(('client.example', 'synthetic-secret',
                                        'http://localhost/api/users/google/callback'),
                                       'synthetic-code', 'synthetic-verifier', 'synthetic-nonce')
    assert captured['code_verifier'] == 'synthetic-verifier'
    assert result[0] == 'subject'

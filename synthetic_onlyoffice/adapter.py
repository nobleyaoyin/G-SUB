"""Isolated synthetic-only ONLYOFFICE adapter. No G-SUB configuration is loaded."""
from __future__ import annotations

import hashlib
import http.client
import io
import ipaddress
import json
import secrets
import time
import zipfile
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

import jwt
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from synthetic_onlyoffice.store import SyntheticStore

LIMIT = 10 * 1024 * 1024
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def validate_docx(data: bytes) -> None:
    """Bounded structural checks, not malware detection or fidelity validation."""
    if not data or len(data) > LIMIT:
        raise ValueError("Invalid document size")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(i.file_size for i in entries) > 40 * 1024 * 1024:
                raise ValueError("DOCX expansion limit")
            names = set()
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if (entry.filename in names or path.is_absolute() or '..' in path.parts
                        or '\\' in entry.filename or entry.flag_bits & 1
                        or entry.file_size > 10 * 1024 * 1024):
                    raise ValueError("Unsafe DOCX entry")
                names.add(entry.filename)
            required = {'[Content_Types].xml', 'word/document.xml', '_rels/.rels'}
            if not required <= names or archive.testzip() is not None:
                raise ValueError("Invalid DOCX structure")
            for name in required:
                data_xml = archive.read(name)
                if b'<!DOCTYPE' in data_xml.upper() or b'<!ENTITY' in data_xml.upper():
                    raise ValueError("Unsafe XML")
                ElementTree.fromstring(data_xml)
            if b'wordprocessingml.document.main+xml' not in archive.read('[Content_Types].xml'):
                raise ValueError("Invalid content type")
            relationships = ElementTree.fromstring(archive.read('_rels/.rels'))
            office_document = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument'
            if not any(element.get('Type') == office_document and element.get('Target') in ('word/document.xml', '/word/document.xml') for element in relationships):
                raise ValueError("Missing office document relationship")
            if ElementTree.fromstring(archive.read('word/document.xml')).tag != '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document':
                raise ValueError("Invalid document XML")
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError) as exc:
        raise ValueError("Invalid DOCX") from exc


def fetch_saved_document(url: str, allowed_port: int) -> bytes:
    """Pin HTTP to an explicitly configured loopback address; never follow redirects."""
    check_callback_url(url, allowed_port)
    parsed = urlsplit(url)
    try:
        address = ipaddress.ip_address(parsed.hostname or '')
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid callback URL") from exc
    if (parsed.scheme != 'http' or address != ipaddress.ip_address('127.0.0.1')
            or port != allowed_port or parsed.username or parsed.password or parsed.fragment
            or not parsed.path.startswith('/cache/files/') or parsed.path.startswith('//')):
        raise ValueError("Disallowed callback URL")
    target = parsed.path + ('?' + parsed.query if parsed.query else '')
    conn = http.client.HTTPConnection('127.0.0.1', allowed_port, timeout=5)
    try:
        conn.request('GET', target, headers={'Accept': MIME})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError("Document server returned an error or redirect")
        data = response.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("Document too large")
        return data
    finally:
        conn.close()


def create_synthetic_app(source: bytes, *, editor_origin: str = 'http://127.0.0.1:8088',
                         adapter_origin: str = 'http://127.0.0.1:8090',
                         frontend_origin: str = 'http://127.0.0.1:5173', callback_port: int = 8088, fetcher=None,
                         allow_test_host_gateway: bool = False, resume_root=None):
    """Create or reopen an explicitly isolated synthetic fixture.

    Caller receives app plus synthetic bearer tokens. Intended for local test wiring only.
    """
    if source is None and resume_root is None:
        raise ValueError('A new synthetic fixture requires a source')
    if source is not None:
        validate_docx(source)
    for origin in (editor_origin, adapter_origin, frontend_origin):
        p = urlsplit(origin)
        allowed_host = p.hostname == '127.0.0.1' or (origin == adapter_origin and allow_test_host_gateway and p.hostname == 'host.docker.internal')
        if p.scheme != 'http' or not allowed_host or not p.port or p.path not in ('', '/') or p.query or p.fragment or p.username or p.password:
            raise ValueError('Origins must be explicit IPv4 localhost origins')
    if not 1 <= callback_port <= 65535:
        raise ValueError('Invalid callback port')
    store = SyntheticStore(source, resume_root)
    root = store.root
    secret = store.secrets['secret']
    actors = {token: role for role, token in store.secrets['actors'].items()}
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[frontend_origin], allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'])
    def actor(auth, manuscript):
        role = actors.get((auth or '').removeprefix('Bearer ')) if (auth or '').startswith('Bearer ') else None
        if role not in ('author', 'editor') or manuscript != 'synthetic-1':
            raise HTTPException(403, 'Not authorized for this manuscript')
        return role

    def decode(token, audience):
        try:
            return jwt.decode(token, secret, algorithms=['HS256'], audience=audience, options={'require': ['exp', 'aud']})
        except jwt.PyJWTError as exc:
            raise HTTPException(403, 'Invalid or expired token') from exc

    @app.post('/manuscripts/{manuscript}/editor')
    def editor(manuscript: str, authorization: str | None = Header(default=None)):
        role = actor(authorization, manuscript)
        with store.transaction() as c:
            number = c.execute("SELECT MAX(number) FROM versions WHERE manuscript='synthetic-1'").fetchone()[0]
            key = secrets.token_urlsafe(24)
            c.execute('INSERT INTO sessions(key,manuscript,actor,source_version,head,expires) VALUES (?,?,?,?,?,?)', (key, manuscript, role, number, number, time.time() + 3600))
            capability = jwt.encode({'aud': 'document', 'exp': int(time.time()) + 300, 'key': key}, secret, algorithm='HS256')
            config = {'documentType': 'word', 'document': {'fileType': 'docx', 'key': key,
                      'title': 'synthetic.docx', 'url': f'{adapter_origin}/documents/{key}?token={capability}'},
                      'editorConfig': {'mode': 'edit', 'customization': {'forcesave': True}, 'callbackUrl': f'{adapter_origin}/callbacks/{key}',
                                       'user': {'id': role, 'name': f'Synthetic {role.title()}'}}}
            config['token'] = jwt.encode({**config, 'exp': int(time.time()) + 300}, secret, algorithm='HS256')
            return {'editorOrigin': editor_origin, 'config': config}

    @app.get('/documents/{key}')
    def document(key: str, token: str):
        claims = decode(token, 'document')
        with store.transaction() as c:
            session = c.execute('SELECT source_version,expires,closed,revoked FROM sessions WHERE key=?', (key,)).fetchone()
            if claims.get('key') != key or not session or time.time() > session[1] or session[2] or session[3]:
                raise HTTPException(403, 'Invalid document capability')
            version = c.execute("SELECT name,sha256,byte_size FROM versions WHERE manuscript='synthetic-1' AND number=?", (session[0],)).fetchone()
            try:
                data = store.read_file(version)
            except (ValueError, OSError, TypeError):
                raise HTTPException(409, 'Document integrity failure')
            return Response(data, media_type=MIME, headers={'Cache-Control': 'no-store'})

    @app.get('/manuscripts/{manuscript}/versions')
    def versions(manuscript: str, authorization: str | None = Header(default=None)):
        actor(authorization, manuscript)
        with store.transaction() as c:
            return [{'number': n, 'sha256': digest} for n, digest in c.execute('SELECT number,sha256 FROM versions WHERE manuscript=? ORDER BY number', (manuscript,))]

    @app.get('/manuscripts/{manuscript}/versions/{number}')
    def version_download(manuscript: str, number: int, authorization: str | None = Header(default=None)):
        actor(authorization, manuscript)
        with store.transaction() as c:
            version = c.execute('SELECT name,sha256,byte_size FROM versions WHERE manuscript=? AND number=?', (manuscript, number)).fetchone()
            if not version:
                raise HTTPException(404, 'Version not found')
            try:
                data = store.read_file(version)
            except (ValueError, OSError):
                raise HTTPException(409, 'Document integrity failure')
            return Response(data, media_type=MIME, headers={'Cache-Control': 'no-store'})

    @app.post('/manuscripts/{manuscript}/sessions/{key}/revoke')
    def revoke(manuscript: str, key: str, authorization: str | None = Header(default=None)):
        role = actor(authorization, manuscript)
        with store.transaction() as c:
            result = c.execute('UPDATE sessions SET revoked=1 WHERE key=? AND manuscript=? AND actor=?', (key, manuscript, role))
            if result.rowcount != 1:
                raise HTTPException(404, 'Session not found')
            return {'revoked': True}

    @app.post('/callbacks/{key}')
    async def callback(key: str, request: Request, authorization: str | None = Header(default=None)):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16384:
                raise HTTPException(413, 'Callback too large')
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(400, 'Invalid callback body') from exc
        if not isinstance(body, dict):
            raise HTTPException(400, 'Invalid callback body')
        # ONLYOFFICE 10: header token wraps data in payload; optional body token
        # has direct claims. Prefer body token when supplied. Require purpose.
        body_token = body.get('token')
        if body_token is not None:
            if not isinstance(body_token, str):
                raise HTTPException(403, 'Invalid callback signature')
            token = body_token
            header_form = False
        elif authorization and authorization.startswith('Bearer '):
            token = authorization[7:]
            header_form = True
        else:
            raise HTTPException(403, 'Missing callback signature')
        try:
            claims = jwt.decode(token, secret, algorithms=['HS256'], options={'verify_aud': False})
        except jwt.PyJWTError as exc:
            raise HTTPException(403, 'Invalid callback signature') from exc
        signed = claims.get('payload') if header_form else claims
        if claims.get('operation') != 'callback' or not isinstance(signed, dict):
            raise HTTPException(403, 'Invalid callback purpose')
        # Ignore unsigned optional metadata. Security-relevant fields may not
        # differ if duplicated in the JSON body.
        if any(k in body and body[k] != signed.get(k) for k in ('key', 'status', 'url', 'forcesavetype')) or signed.get('key') != key:
            raise HTTPException(403, 'Callback signature mismatch')
        status = signed.get('status')
        if type(status) is not int or status not in (1, 2, 3, 4, 6, 7):
            raise HTTPException(400, 'Unsupported callback status')
        with store.transaction() as c:
            session = c.execute('SELECT head,expires,closed,revoked FROM sessions WHERE key=? AND manuscript=?', (key, 'synthetic-1')).fetchone()
            if not session or time.time() > session[1] or session[3]:
                raise HTTPException(403, 'Unknown document key')
            event = hashlib.sha256(json.dumps(signed, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if c.execute('SELECT 1 FROM callbacks WHERE session_key=? AND event_hash=?', (key, event)).fetchone():
                return {'error': 0}
            if session[2]:
                raise HTTPException(409, 'Editing session is closed')
            if status in (3, 7):
                # Acknowledge notification of an error; do not record a save.
                c.execute('INSERT INTO callbacks VALUES (?,?,?,NULL)', (key, event, status))
                return {'error': 0}
            if status in (1, 4):
                if status == 4:
                    c.execute('UPDATE sessions SET closed=1 WHERE key=?', (key,))
                c.execute('INSERT INTO callbacks VALUES (?,?,?,NULL)', (key, event, status))
                return {'error': 0}
            if not isinstance(signed.get('url'), str):
                raise HTTPException(400, 'Missing saved document URL')
            if status == 6 and (type(signed.get('forcesavetype')) is not int or signed['forcesavetype'] not in (0, 1, 2, 3)):
                raise HTTPException(400, 'Invalid force-save type')
            current_number, current_digest = c.execute("SELECT number,sha256 FROM versions WHERE manuscript='synthetic-1' ORDER BY number DESC LIMIT 1").fetchone()
            if session[0] != current_number:
                raise HTTPException(409, 'Stale editing session')
            try:
                # Validation happens even with an injected synthetic fetcher.
                check_callback_url(signed['url'], callback_port)
                saved = (fetcher or fetch_saved_document)(signed['url'], callback_port)
                validate_docx(saved)
            except (ValueError, OSError, http.client.HTTPException) as exc:
                raise HTTPException(400, 'Invalid saved document') from exc
            digest = hashlib.sha256(saved).hexdigest()
            url_hash = hashlib.sha256(signed['url'].encode()).hexdigest()
            prior = c.execute('SELECT digest FROM save_urls WHERE session_key=? AND url_hash=?', (key, url_hash)).fetchone()
            if prior is not None and prior[0] != digest:
                raise HTTPException(409, 'Reused save URL changed content')
            if digest != current_digest:
                store.write_version(c, saved, current_number + 1)
                c.execute('UPDATE sessions SET head=? WHERE key=?', (current_number + 1, key))
            c.execute('INSERT OR IGNORE INTO save_urls VALUES (?,?,?)', (key, url_hash, digest))
            c.execute('INSERT INTO callbacks VALUES (?,?,?,?)', (key, event, status, digest))
            if status == 2:
                c.execute('UPDATE sessions SET closed=1 WHERE key=?', (key,))
            return {'error': 0}

    # No routes are added to the real application. The private values are for fixture wiring.
    app.state.synthetic_root = root
    app.state.synthetic_secret = secret
    return app, {role: token for token, role in actors.items()}


def check_callback_url(url: str, port: int) -> None:
    """Validate destinations before an injectable fetcher is invoked."""
    p = urlsplit(url)
    try:
        decoded_path = unquote(p.path)
        permitted = (p.scheme == 'http' and p.hostname == '127.0.0.1' and p.port == port
                     and not p.username and not p.password and not p.fragment
                     and p.path.startswith('/cache/files/') and '\\' not in decoded_path
                     and all(part not in ('.', '..') for part in decoded_path.split('/'))
                     and not any(ord(char) < 32 for char in decoded_path))
    except ValueError:
        permitted = False
    if not permitted:
        raise ValueError('Disallowed callback URL')

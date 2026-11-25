"""Default-disabled DOCX editing helpers. No automatic migrations or services."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit

import jwt
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app import editor_text_drafts, online_versions
from app.config import DATA_ROOT, guard_demo_path
from app.models import (FinalEditingSubmission, FinalEditingSubmissionInvitation,
                        FinalEditorInvitation, InitialEditingSubmission, InitialEditorInvitation,
                        Manuscript, PreReviewConfirmation, ReviewAssignment, ReviewRoundFile, User)

BASE_DIR = DATA_ROOT
MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
MAX = 10 * 1024 * 1024


def request_force_save(session_id, secret, server_origin):
    """Ask the configured local document server to save; a callback confirms storage."""
    port = urlsplit(server_origin).port
    command = {'c': 'forcesave', 'key': session_id}
    payload = json.dumps({**command, 'token': jwt.encode(command, secret, algorithm='HS256')})
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        conn.request('POST', '/coauthoring/CommandService.ashx', body=payload,
                     headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        raw = response.read(8193)
        if response.status != 200 or len(raw) > 8192:
            raise HTTPException(503, 'Could not request a save from the document server')
        result = json.loads(raw)
        if not isinstance(result, dict) or type(result.get('error')) is not int:
            raise HTTPException(503, 'Could not request a save from the document server')
        if result['error'] == 4:
            raise HTTPException(409, 'The editor could not produce another save. Keep it open and try Download As.')
        if result['error'] != 0 or (result.get('key') is not None and result['key'] != session_id):
            raise HTTPException(503, 'Could not request a save from the document server')
    except (OSError, ValueError, UnicodeError):
        raise HTTPException(503, 'Could not request a save from the document server') from None
    finally:
        conn.close()


def config():
    if os.environ.get('GSUB_ONLYOFFICE_ENABLED') != '1':
        raise HTTPException(503, 'DOCX online editing is not configured')
    secret = os.environ.get('GSUB_ONLYOFFICE_SECRET', '')
    origins = [os.environ.get('GSUB_ONLYOFFICE_SERVER_ORIGIN', ''), os.environ.get('GSUB_ONLYOFFICE_APP_ORIGIN', '')]
    if len(secret) < 32: raise HTTPException(503, 'DOCX online editing configuration is incomplete')
    for index, value in enumerate(origins):
        try: p = urlsplit(value); port = p.port
        except ValueError: raise HTTPException(503, 'Invalid DOCX editor configuration') from None
        allowed_host = p.hostname == '127.0.0.1' or (index == 1 and p.hostname == 'host.docker.internal')
        if p.scheme != 'http' or not allowed_host or not port or p.path not in (('', '/', '/api') if index == 1 else ('', '/')) or p.query or p.fragment or p.username or p.password:
            raise HTTPException(503, 'DOCX editor origins must be explicit local addresses')
    return secret, origins[0].rstrip('/'), origins[1].rstrip('/')


def require_schema(db):
    online_versions.require_schema(db)
    try:
        if not db.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='016_onlyoffice_sessions'")).first():
            raise HTTPException(503, 'DOCX editor migration is unavailable')
        required = {'onlyoffice_sessions': {'session_id','manuscript_id','actor_id','stage','source_ref','source_sha256','scope_key','head_id','global_head_id','expires_at','closed','revoked'},
                    'onlyoffice_callbacks': {'session_id','event_hash','status','digest','url_hash'}}
        for name, expected in required.items():
            cols = {r[1] for r in db.connection().exec_driver_sql(f'PRAGMA table_info({name})')}
            if cols != expected: raise HTTPException(503, 'DOCX editor schema is incompatible')
    except SQLAlchemyError:
        raise HTTPException(503, 'DOCX editor schema is unavailable') from None


def _read(relative, allowed):
    root = BASE_DIR.resolve()
    path = Path(relative or '')
    if path.is_absolute() or '..' in path.parts or path.suffix.lower() != '.docx':
        raise HTTPException(415, 'A DOCX source is required')
    target = guard_demo_path(root / path)
    editor_text_drafts._reject_symlinks(target, root / 'uploads')
    if target.parent.resolve() not in {p.resolve() for p in allowed}:
        raise HTTPException(409, 'Document unavailable')
    try:
        fd = os.open(target, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1: raise OSError('unsafe')
            content = f.read(MAX + 1)
        from app.routers.manuscripts import validate_manuscript_file
        validate_manuscript_file('document.docx', content)
        return content
    except OSError:
        raise HTTPException(409, 'Document unavailable') from None


def source(db, manuscript_id, actor_id, stage):
    """Resolve only existing author revision or accepted editorial workflows."""
    user, m = db.get(User, actor_id), db.get(Manuscript, manuscript_id)
    if not user or not m: raise HTTPException(404, 'Editing unavailable')
    if stage == 'author':
        if user.role != 'author' or m.author_id != actor_id: raise HTTPException(404, 'Editing unavailable')
        if m.status not in ('draft', 'revision_required', 'initial_revision_required'): raise HTTPException(409, 'Editing unavailable at this stage')
        from app.routers.manuscripts import get_current_review_round
        round_no = get_current_review_round(db, m) + (m.status == 'revision_required')
        if db.scalar(select(ReviewAssignment.assignment_id).where(ReviewAssignment.manuscript_id == manuscript_id, ReviewAssignment.review_round == round_no).limit(1)) is not None:
            raise HTTPException(409, 'Editing unavailable after reviewer assignment')
        ref, invitation = m.file_path, 'author'
    elif stage in ('initial', 'final') and user.role == 'editor':
        from app.editor_invitation_revocation import effective_status
        if stage == 'initial':
            inv = db.scalar(select(InitialEditorInvitation).where(InitialEditorInvitation.manuscript_id == manuscript_id, InitialEditorInvitation.editor_id == actor_id, InitialEditorInvitation.status == 'accepted').order_by(InitialEditorInvitation.invitation_id.desc()).limit(1))
            if not inv or m.status != 'initial_editing': raise HTTPException(404, 'Editing unavailable')
            if effective_status(db, 'initial', inv) != 'accepted': raise HTTPException(403, 'Document unavailable')
            latest = db.scalar(select(InitialEditingSubmission).where(InitialEditingSubmission.manuscript_id == manuscript_id).order_by(InitialEditingSubmission.submission_id.desc()).limit(1))
            if latest:
                confirmation = db.scalar(select(PreReviewConfirmation).where(PreReviewConfirmation.submission_id == latest.submission_id).order_by(PreReviewConfirmation.confirmation_id.desc()).limit(1))
                if not (latest.status.endswith('revision_requested') or (confirmation and confirmation.decision == 'request_revision')): raise HTTPException(409, 'Submission awaiting approval')
            ref = latest.file_path if latest else m.file_path
        else:
            inv = db.scalar(select(FinalEditorInvitation).where(FinalEditorInvitation.manuscript_id == manuscript_id, FinalEditorInvitation.editor_id == actor_id, FinalEditorInvitation.status == 'accepted').order_by(FinalEditorInvitation.invitation_id.desc()).limit(1))
            from app.routers.final_workflow import accepted_current_agreement
            if not inv or m.status != 'final_editing' or not accepted_current_agreement(db, m): raise HTTPException(404, 'Editing unavailable')
            if effective_status(db, 'final', inv) != 'accepted': raise HTTPException(403, 'Document unavailable')
            latest = db.scalar(select(FinalEditingSubmission).join(FinalEditingSubmissionInvitation, FinalEditingSubmissionInvitation.submission_id == FinalEditingSubmission.submission_id).where(FinalEditingSubmission.manuscript_id == manuscript_id).order_by(FinalEditingSubmission.submission_id.desc()).limit(1))
            if latest and latest.status not in ('eic_revision_requested','author_revision_requested'): raise HTTPException(409, 'Submission awaiting approval')
            round_file = db.scalar(select(ReviewRoundFile).where(ReviewRoundFile.manuscript_id == manuscript_id, ReviewRoundFile.review_round == m.review_round))
            if latest: ref = latest.file_path
            else:
                if not round_file: raise HTTPException(409, 'Confirmed source unavailable')
                from app.review_files import validate_round_file
                validate_round_file(round_file, m, db)
                ref = round_file.file_path
        invitation = str(inv.invitation_id)
    else:
        raise HTTPException(404, 'Editing unavailable')
    if not ref: raise HTTPException(404, 'Upload a DOCX document first')
    root = BASE_DIR.resolve() / 'uploads'
    allowed = [root / kind / str(manuscript_id) for kind in ('manuscripts','initial_editing','final_editing')]
    content = _read(ref, allowed)
    if stage in ('initial', 'final') and ref == m.file_path:
        from app.controlled_source_authorization import authorize_source
        authorize_source(db, user, manuscript_id, content, invitation_kind=stage)
    scope = 'docx:' + hashlib.sha256((stage + '\0' + invitation + '\0' + ref).encode() + b'\0' + content).hexdigest()
    return user, m, ref, content, scope


def read_draft(ref, manuscript_id, stage, actor_id, expected):
    root = BASE_DIR.resolve() / 'uploads' / 'onlyoffice' / str(manuscript_id) / stage / str(actor_id)
    content = _read(ref, [root])
    if not re.fullmatch(r'[0-9a-f]{32}\.docx', Path(ref).name) or not hashlib.sha256(content).hexdigest() == expected:
        raise HTTPException(409, 'Draft integrity check failed')
    return content


def fetch(url, server_origin):
    try: p = urlsplit(url); expected = urlsplit(server_origin); port = p.port
    except ValueError: raise HTTPException(400, 'Invalid document URL') from None
    decoded = unquote(p.path)
    if (p.scheme != 'http' or p.hostname != '127.0.0.1' or port != expected.port or p.username or p.password or p.fragment
            or not p.path.startswith('/cache/files/') or '\\' in decoded or any(x in ('.','..') for x in decoded.split('/')) or any(ord(x)<32 for x in decoded)):
        raise HTTPException(400, 'Invalid document URL')
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        conn.request('GET', p.path + ('?' + p.query if p.query else ''))
        response = conn.getresponse()
        if response.status != 200: raise HTTPException(503, 'Document server unavailable')
        content = response.read(MAX + 1)
        from app.routers.manuscripts import validate_manuscript_file
        validate_manuscript_file('document.docx', content)
        return content
    except OSError:
        raise HTTPException(503, 'Document server unavailable') from None
    finally:
        conn.close()

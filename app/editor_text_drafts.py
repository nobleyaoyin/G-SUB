"""Private TXT drafts for the existing accepted editorial workflows."""
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from app.config import guard_demo_path
from app import online_versions
from app.models import (AuthorAgreement, FinalEditorInvitation, FinalEditingSubmission,
    FinalEditingSubmissionInvitation, InitialEditorInvitation, InitialEditingSubmission,
    Manuscript, PreReviewConfirmation, ReviewRoundFile, User)

_NAME = re.compile(r'\d{20}_\d{8}T\d{12}Z_[0-9a-f]{32}\.txt\Z')


def _valid_name(name):
    if not _NAME.fullmatch(name): return False
    try:
        datetime.strptime(name[21:43], '%Y%m%dT%H%M%S%fZ')
        return True
    except ValueError:
        return False


def _reject_symlinks(path, root):
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise HTTPException(409, 'Document unavailable') from None
    current = root
    for part in (None, *relative.parts):
        if part is not None: current = current / part
        if current.is_symlink(): raise HTTPException(409, 'Document unavailable')


def _read(path, root):
    from app.routers.manuscripts import MAX_MANUSCRIPT_FILE_SIZE, validate_manuscript_file
    path = guard_demo_path(path)
    _reject_symlinks(path, root)
    if not path.resolve().is_relative_to(root.resolve()):
        raise HTTPException(409, 'Document unavailable')
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise HTTPException(409, 'Document unavailable')
            content = source.read(MAX_MANUSCRIPT_FILE_SIZE + 1)
        validate_manuscript_file('document.txt', content)
        return content.decode('utf-8')
    except (OSError, UnicodeError):
        raise HTTPException(409, 'Document unavailable') from None


def state(db, root, manuscript_id, actor, stage, *, with_source=False):
    """Recheck manuscript scope, invitation and stage on every access."""
    role = db.scalar(select(User.role).where(User.user_id == actor.user_id))
    manuscript = db.get(Manuscript, manuscript_id)
    if role != 'editor' or manuscript is None or stage not in ('initial', 'final'):
        raise HTTPException(404, 'Editing unavailable')
    if stage == 'initial':
        invitation = db.scalar(select(InitialEditorInvitation).where(
            InitialEditorInvitation.manuscript_id == manuscript_id,
            InitialEditorInvitation.editor_id == actor.user_id,
            InitialEditorInvitation.status == 'accepted').order_by(InitialEditorInvitation.invitation_id.desc()).limit(1))
        if not invitation or manuscript.status != 'initial_editing':
            raise HTTPException(404, 'Editing unavailable')
        latest = db.scalar(select(InitialEditingSubmission).where(
            InitialEditingSubmission.manuscript_id == manuscript_id).order_by(InitialEditingSubmission.submission_id.desc()).limit(1))
        if latest:
            confirmation = db.scalar(select(PreReviewConfirmation).where(
                PreReviewConfirmation.submission_id == latest.submission_id).order_by(PreReviewConfirmation.confirmation_id.desc()).limit(1))
            if not (latest.status.endswith('revision_requested') or (confirmation and confirmation.decision == 'request_revision')):
                raise HTTPException(409, 'An editorial submission is awaiting review or approval')
        source_path = latest.file_path if latest else manuscript.file_path
    else:
        invitation = db.scalar(select(FinalEditorInvitation).where(
            FinalEditorInvitation.manuscript_id == manuscript_id,
            FinalEditorInvitation.editor_id == actor.user_id,
            FinalEditorInvitation.status == 'accepted').order_by(FinalEditorInvitation.invitation_id.desc()).limit(1))
        agreement = db.scalar(select(AuthorAgreement).where(AuthorAgreement.manuscript_id == manuscript_id).order_by(AuthorAgreement.agreement_id.desc()).limit(1))
        if not invitation or manuscript.status != 'final_editing' or not agreement or agreement.status != 'accepted':
            raise HTTPException(404, 'Editing unavailable')
        latest = db.scalar(select(FinalEditingSubmission).join(FinalEditingSubmissionInvitation,
            FinalEditingSubmissionInvitation.submission_id == FinalEditingSubmission.submission_id).where(
            FinalEditingSubmission.manuscript_id == manuscript_id).order_by(FinalEditingSubmission.submission_id.desc()).limit(1))
        if latest and latest.status not in ('eic_revision_requested', 'author_revision_requested'):
            raise HTTPException(409, 'An editorial submission is awaiting review or approval')
        source = db.scalar(select(ReviewRoundFile).where(ReviewRoundFile.manuscript_id == manuscript_id,
            ReviewRoundFile.review_round == manuscript.review_round))
        if latest:
            source_path = latest.file_path
        else:
            if not source: raise HTTPException(409, 'Confirmed review-round document unavailable')
            from app.review_files import validate_round_file
            validate_round_file(source, manuscript, db)
            source_path = source.file_path
    if not source_path: raise HTTPException(409, 'Source document unavailable')
    source = Path(source_path)
    if source.is_absolute() or '..' in source.parts or source.suffix.lower() != '.txt':
        raise HTTPException(415, 'Online editing supports UTF-8 TXT sources only')
    allowed = (root/'uploads'/'manuscripts'/str(manuscript_id), root/'uploads'/'initial_editing'/str(manuscript_id), root/'uploads'/'final_editing'/str(manuscript_id))
    source = root / source
    if not any(source.resolve().parent == parent.resolve() for parent in allowed):
        raise HTTPException(409, 'Source document unavailable')
    text = _read(source, root/'uploads')
    fingerprint = hashlib.sha256((source_path+'\0'+text).encode('utf-8')).hexdigest()
    directory = guard_demo_path(root/'uploads'/'online_editor'/str(manuscript_id)/stage/str(actor.user_id)/str(invitation.invitation_id)/fingerprint)
    _reject_symlinks(directory, root/'uploads')
    if not directory.resolve().is_relative_to((root/'uploads').resolve()):
        raise HTTPException(409, 'Editing unavailable')
    scope = str(directory.relative_to(root))
    rows = online_versions.history(db, manuscript_id, actor.user_id, stage, scope)
    paths = []
    for row in rows:
        path = root / row['file_ref']
        if path.parent != directory or not _valid_name(path.name): raise HTTPException(409, 'Draft unavailable')
        if online_versions.digest(_read(path, directory).encode('utf-8')) != row['file_sha256']:
            raise HTTPException(409, 'Saved draft integrity check failed')
        paths.append(path)
    current = _read(paths[-1], directory) if paths else text
    version = hashlib.sha256((fingerprint+'\0'+(paths[-1].name if paths else '')+'\0'+current).encode('utf-8')).hexdigest()
    result = (directory, paths, current, version)
    return (*result, source_path, text, rows) if with_source else result


def publish(directory, text, uploads_root, number):
    """Publish a new uniquely named draft without overwriting existing files."""
    _reject_symlinks(directory, uploads_root)
    current = uploads_root
    for part in directory.relative_to(uploads_root).parts:
        current = current / part
        current.mkdir(mode=0o700, exist_ok=True)
        if current.is_symlink(): raise HTTPException(409, 'Document unavailable')
    if number < 1 or number >= 10**20: raise HTTPException(409, 'Draft history limit reached')
    filename = f'{number:020d}_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_'+uuid4().hex+'.txt'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=directory, delete=False) as file:
            temporary = Path(file.name); file.write(text.encode('utf-8'))
        os.link(temporary, directory/filename)
        return directory/filename
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)

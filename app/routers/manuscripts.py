from typing import Annotated

from pathlib import Path
from datetime import datetime, timezone
from uuid import UUID, uuid4
import os
import tempfile
import io
import zipfile
import zlib
import sqlite3
import hashlib
import re
import xml.etree.ElementTree as ET
from fastapi import APIRouter, Depends, status, HTTPException, UploadFile, File, Form, Header
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.orm import Session, object_session
from sqlalchemy import inspect, select, update, text
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, Field
from app import online_versions
from app.filename_headers import content_disposition, normalize_upload_filename
from app.controlled_source_authorization import authorize_source, read_bounded_source, source_may_be_controlled, source_path_is_controlled

from app.database import get_db, BASE_DIR
from app.config import IS_DEMO, guard_demo_path, AI_PRESCREENING_ENABLED
from app.ai_submission import try_create_submission_job
from app.models import (
    Manuscript,
    User,
    ReviewAssignment,
    ReviewerInvitationInvalidation,
    Review,
    Notification,
    InitialEditorInvitation,
    InitialEditingSubmission,
    ReviewRoundFile,
    ManuscriptReviewPolicy,
    AuthorAgreement,
    FinalEditorInvitation,
    EICInitialScan,
    PreReviewConfirmation,
    EICDecision,
    FormatterInvitation,
    FinalEditingSubmission,
    FinalEditingSubmissionInvitation,
    FormattingSubmission,
    PrototypePublication,
)
from app.schemas import AuthorManuscriptResponse, ManuscriptCreate, ManuscriptResponse, ManuscriptUpdate, EditorDecision
from app.routers.users import get_current_user, require_role
from app.reviewer_invitations import not_declined, may_review
from app.review_progress import review_progress
from app.participant_tasks import participant_task
from app.email.service import notify_workflow_email
from app.reviewer_metadata_gate import (MetadataMode, MetadataSchemaUnavailable, MetadataAccessDenied,
    ReviewerDetailDTO, ReviewerSingleBlindDetailDTO, ReviewerProgressDTO,
    reviewer_detail_policy, reviewer_metadata_mode, reviewer_metadata_dto)
from app.blind_review_visibility import ReviewerSingleBlindDTO

def _owner_download_name(db, manuscript, current_user, storage_name):
    """Original upload names are private to the manuscript owner."""
    if current_user.role != 'author' or current_user.user_id != manuscript.author_id:
        return None
    if not inspect(db.get_bind()).has_table('manuscript_upload_names'):
        return None
    return db.execute(text('SELECT original_filename FROM manuscript_upload_names WHERE manuscript_id=:id AND storage_name=:name'),
                      {'id': manuscript.manuscript_id, 'name': storage_name}).scalar_one_or_none()

def uses_eic_workflow(db: Session, manuscript_id: int) -> bool:
    """Check whether a manuscript belongs to the EIC-controlled workflow."""
    evidence_models = (
        ManuscriptReviewPolicy,
        EICInitialScan,
        InitialEditorInvitation,
        PreReviewConfirmation,
        EICDecision,
    )

    for model in evidence_models:
        evidence_id = db.scalar(
            select(model.manuscript_id)
            .where(model.manuscript_id == manuscript_id)
            .limit(1)
        )

        if evidence_id is not None:
            return True

    return False

router = APIRouter(
    prefix="/manuscripts",
    tags=["Manuscripts"]
)

# Supported manuscript document formats
ALLOWED_MANUSCRIPT_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".txt": "text/plain",
}

MAX_MANUSCRIPT_FILE_SIZE = 10 * 1024 * 1024


class OnlineTextSave(BaseModel):
    content: str
    expected_version: str = Field(min_length=64, max_length=64)
    change_note: str | None = Field(default=None, max_length=500)


def _online_author_source(db, manuscript_id, user):
    manuscript = db.get(Manuscript, manuscript_id)
    if manuscript is None or user.role != 'author' or manuscript.author_id != user.user_id:
        raise HTTPException(404, 'Manuscript unavailable')
    from app import sample_documents
    sample = sample_documents.registered(db, manuscript_id)
    if manuscript.status not in ('draft', 'revision_required', 'initial_revision_required'):
        raise HTTPException(409, 'Document editing is unavailable at this stage')
    round_no = get_current_review_round(db, manuscript) + (manuscript.status == 'revision_required')
    if db.scalar(select(ReviewAssignment.assignment_id).where(ReviewAssignment.manuscript_id == manuscript_id,
            ReviewAssignment.review_round == round_no).limit(1)) is not None:
        raise HTTPException(409, 'Document editing is unavailable after reviewer assignment')
    if not manuscript.file_path:
        raise HTTPException(404, 'Upload a TXT document first')
    if sample:
        row, content = sample_documents.current(db, manuscript)
        if row['file_format'] != 'txt':
            raise HTTPException(415, 'Online editing currently supports UTF-8 TXT files only')
        try:
            validate_manuscript_file('document.txt', content, historical=True)
            text_content = content.decode('utf-8')
        except UnicodeError:
            raise HTTPException(409, 'Document source unavailable') from None
        version = hashlib.sha256(manuscript.file_path.encode('utf-8') + b'\0' + content).hexdigest()
        return manuscript, round_no, None, text_content, version
    path = resolve_manuscript_file_path(manuscript.file_path)
    directory = guard_demo_path(BASE_DIR / 'uploads' / 'manuscripts' / str(manuscript_id)).resolve()
    if path.suffix.lower() != '.txt':
        raise HTTPException(415, 'Online editing currently supports UTF-8 TXT files only')
    if path.is_symlink() or path.resolve().parent != directory:
        raise HTTPException(409, 'Document source unavailable')
    try:
        with path.open('rb') as handle:
            content = handle.read(MAX_MANUSCRIPT_FILE_SIZE + 1)
        validate_manuscript_file(path.name, content)
        text = content.decode('utf-8')
    except (OSError, UnicodeError):
        raise HTTPException(409, 'Document source unavailable') from None
    version = hashlib.sha256(manuscript.file_path.encode('utf-8') + b'\0' + content).hexdigest()
    return manuscript, round_no, directory, text, version


@router.get('/{manuscript_id}/online-text')
def online_text(manuscript_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    manuscript, _, directory, content, version = _online_author_source(db, manuscript_id, current_user)
    history = online_versions.history(db, manuscript_id, current_user.user_id, 'author')
    current = next((row for row in history if row['file_ref'] == manuscript.file_path), None)
    if current and online_versions.digest(content.encode('utf-8')) != current['file_sha256']:
        raise HTTPException(409, 'Saved draft integrity check failed')
    return JSONResponse({'content': content, 'version': version, 'history': [
        {'id': row['version_id'], 'number': row['version_number'], 'saved_at': row['saved_at'], 'editor': current_user.name, 'filename': Path(row['file_ref']).name,
         'change_note': row['change_note'], 'is_current': manuscript.file_path == row['file_ref']}
        for row in history]}, headers={'Cache-Control': 'no-store'})


@router.get('/{manuscript_id}/online-text/versions/{version_id}')
def online_author_version(manuscript_id: int, version_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, _, directory, _, _ = _online_author_source(db, manuscript_id, current_user)
    row = next((r for r in online_versions.history(db, manuscript_id, current_user.user_id, 'author') if r['version_id'] == version_id), None)
    if row is None: raise HTTPException(404, 'Draft unavailable')
    from app import sample_documents
    if sample_documents.registered(db, manuscript_id):
        _, content = sample_documents.read_identity(db, manuscript_id, row['file_ref'])
        if online_versions.digest(content) != row['file_sha256']:
            raise HTTPException(409, 'Saved draft integrity check failed')
        return Response(content, media_type='text/plain; charset=utf-8', headers={'Cache-Control': 'no-store', 'Content-Disposition': 'attachment; filename="draft.txt"'})
    path = resolve_manuscript_file_path(row['file_ref'])
    if path.is_symlink() or path.parent.resolve() != directory or path.suffix.lower() != '.txt': raise HTTPException(409, 'Draft unavailable')
    path = path.resolve()
    from app.editor_text_drafts import _read
    content = _read(path, directory).encode('utf-8')
    if online_versions.digest(content) != row['file_sha256']: raise HTTPException(409, 'Saved draft integrity check failed')
    return Response(content, media_type='text/plain; charset=utf-8', headers={'Cache-Control': 'no-store', 'Content-Disposition': 'attachment; filename="draft.txt"'})


def _begin_author_submission(db):
    connection = db.connection()
    if connection.dialect.name != 'sqlite' or connection.connection.driver_connection.in_transaction:
        raise HTTPException(503, 'Submission transaction unavailable')
    connection.exec_driver_sql('BEGIN IMMEDIATE')


def _validate_author_online_submission(db, manuscript, current_user, expected):
    # Only the online-file naming convention invokes this check; ordinary uploads
    # retain their existing behavior, including on schemas without migration 014.
    name = Path(manuscript.file_path or '').name
    if not re.fullmatch(r'round_\d+_online_\d{8}T\d{12}Z_[0-9a-f]{32}\.txt', name):
        if expected: raise HTTPException(409, 'Selected draft changed; reopen it before submitting')
        return
    _, _, _, content, token = _online_author_source(db, manuscript.manuscript_id, current_user)
    rows = online_versions.history(db, manuscript.manuscript_id, current_user.user_id, 'author')
    row = next((r for r in rows if r['file_ref'] == manuscript.file_path), None)
    if not expected or expected != token or row is None or row['file_sha256'] != online_versions.digest(content.encode('utf-8')):
        raise HTTPException(409, 'Selected draft changed or is unrecorded; reopen or upload it before submitting')
    source = resolve_manuscript_file_path(row['source_ref'])
    directory = (BASE_DIR / 'uploads' / 'manuscripts' / str(manuscript.manuscript_id)).resolve()
    if source.is_symlink() or source.parent.resolve() != directory:
        raise HTTPException(409, 'Selected draft source unavailable')
    from app.editor_text_drafts import _read
    original = _read(source.resolve(), directory).encode('utf-8')
    if online_versions.digest(original) != row['source_sha256']:
        raise HTTPException(409, 'Selected draft source changed; reopen or upload it before submitting')


def _validate_sample_online_submission(db, manuscript, current_user, expected):
    from app import sample_documents
    rows = online_versions.history(db, manuscript.manuscript_id, current_user.user_id, 'author')
    row = next((item for item in rows if item['file_ref'] == manuscript.file_path), None)
    if row is None:
        if expected:
            raise HTTPException(409, 'Selected draft changed; reopen it before submitting')
        return
    _, current = sample_documents.current(db, manuscript)
    token = hashlib.sha256(manuscript.file_path.encode('utf-8') + b'\0' + current).hexdigest()
    _, source = sample_documents.read_identity(db, manuscript.manuscript_id, row['source_ref'])
    if (not expected or expected != token or online_versions.digest(current) != row['file_sha256']
            or online_versions.digest(source) != row['source_sha256']):
        raise HTTPException(409, 'Selected draft changed or is unrecorded; reopen it before submitting')


@router.post('/{manuscript_id}/online-text')
def save_online_text(manuscript_id: int, data: OnlineTextSave, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        content = data.content.encode('utf-8')
    except UnicodeError:
        raise HTTPException(400, 'Document must contain valid UTF-8 text') from None
    validate_manuscript_file('document.txt', content)
    path = None
    try:
        connection = db.connection()
        if connection.dialect.name != 'sqlite' or connection.connection.driver_connection.in_transaction:
            raise HTTPException(503, 'Editor transaction unavailable')
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        manuscript, round_no, directory, source_text, version = _online_author_source(db, manuscript_id, current_user)
        rows = online_versions.history(db, manuscript_id, current_user.user_id, 'author')
        current = next((row for row in rows if row['file_ref'] == manuscript.file_path), None)
        if current and current['file_sha256'] != online_versions.digest(source_text.encode('utf-8')):
            raise HTTPException(409, 'Saved draft integrity check failed')
        if version != data.expected_version:
            raise HTTPException(409, 'Document changed; reopen it before saving')
        from app import sample_documents
        if sample_documents.registered(db, manuscript_id):
            sample_documents.publish(db, manuscript, current_user, round_no, '.txt', content,
                                     online_source=source_text.encode('utf-8'), change_note=data.change_note)
            return {'message': 'Version saved'}
        filename = f"round_{round_no}_online_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex}.txt"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        with path.open('xb') as handle:
            handle.write(content)
        old_path = manuscript.file_path
        new_path = str(path.relative_to(BASE_DIR.resolve()))
        online_versions.record(db, manuscript_id, current_user.user_id, 'author', 'author', old_path,
                               source_text.encode('utf-8'), new_path, content, data.change_note)
        result = db.execute(update(Manuscript).where(Manuscript.manuscript_id == manuscript_id,
            Manuscript.file_path == old_path, Manuscript.status == manuscript.status).values(file_path=new_path))
        if result.rowcount != 1:
            raise HTTPException(409, 'Document changed; reopen it before saving')
        db.commit()
        return {'message': 'Version saved'}
    except HTTPException:
        db.rollback()
        raise
    except (OSError, SQLAlchemyError, sqlite3.DatabaseError):
        db.rollback()
        # Commit acknowledgement may be ambiguous: retain any unique file for reconciliation.
        raise HTTPException(503, 'Save outcome unavailable; reopen the document before retrying') from None


def validate_manuscript_file(filename: str, content: bytes, *, historical: bool = False) -> tuple[str, str]:
    """
    Validate a manuscript file and return:
    (extension, media_type).
    """
    if historical:
        # Historical storage names were accepted under older rules; do not
        # invalidate their downloads by applying new upload-name policy.
        extension = Path(filename or "").suffix.lower()
    else:
        try:
            safe_name = normalize_upload_filename(filename)
        except ValueError:
            raise HTTPException(status_code=400, detail="Choose a file with a valid filename.") from None
        extension = Path(safe_name).suffix.lower()

    if extension not in ALLOWED_MANUSCRIPT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only PDF, DOCX, DOC, and TXT files are allowed",
        )

    if not content:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty",
        )

    if len(content) > MAX_MANUSCRIPT_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File exceeds the 10 MB limit",
        )

    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=400,
                detail="Invalid PDF file",
            )

    elif extension == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                names = {entry.filename for entry in entries}
                if (len(entries) > 2048 or len(names) != len(entries)
                    or sum(entry.file_size for entry in entries) > 32 * 1024 * 1024
                    or any(entry.file_size > 16 * 1024 * 1024 or entry.flag_bits & 1
                           or entry.filename.startswith(('/', '\\')) or '\\' in entry.filename
                           or '..' in entry.filename.split('/') for entry in entries)):
                    raise ValueError('Unsafe DOCX container')

                if (
                    "[Content_Types].xml" not in names
                    or "word/document.xml" not in names
                ):
                    raise ValueError("Missing DOCX document structure")

                if archive.testzip() is not None:
                    raise ValueError("Corrupted DOCX archive")
                if not historical:
                    for name, root in (("[Content_Types].xml", "{http://schemas.openxmlformats.org/package/2006/content-types}Types"), ("word/document.xml", "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document")):
                        data = archive.read(name)
                        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                            raise ValueError('Unsafe XML')
                        parsed = ET.fromstring(data)
                        if parsed.tag != root:
                            raise ValueError('Invalid DOCX XML')
                        if name == '[Content_Types].xml' and not any(
                            part.tag == '{http://schemas.openxmlformats.org/package/2006/content-types}Override' and part.get('PartName') == '/word/document.xml' and part.get('ContentType') == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
                            for part in parsed
                        ):
                            raise ValueError('Missing Word document content type')

        except (zipfile.BadZipFile, ValueError, RuntimeError, ET.ParseError, NotImplementedError, OSError, EOFError, zlib.error):
            raise HTTPException(
                status_code=400,
                detail="Invalid DOCX file",
            )

    elif extension == ".doc":
        # Legacy Word documents use the OLE Compound File format.
        ole_signature = bytes.fromhex("D0CF11E0A1B11AE1")

        if not content.startswith(ole_signature):
            raise HTTPException(
                status_code=400,
                detail="Invalid DOC file",
            )
        if not historical:
            try:
                import olefile
                with olefile.OleFileIO(io.BytesIO(content), raise_defects=olefile.DEFECT_INCORRECT) as ole:
                    if not ole.exists('WordDocument'):
                        raise ValueError('Missing Word document stream')
                    with ole.openstream('WordDocument') as stream:
                        header = stream.read(12)
                    if len(header) != 12 or header[:2] != b'\xec\xa5':
                        raise ValueError('Invalid Word header')
                    table = '1Table' if int.from_bytes(header[10:12], 'little') & 0x0200 else '0Table'
                    if not ole.exists(table):
                        raise ValueError('Missing Word table stream')
            except ImportError:
                raise HTTPException(status_code=503, detail='Word document validation is unavailable') from None
            except (OSError, ValueError, IndexError, TypeError, OverflowError):
                raise HTTPException(status_code=400, detail='Invalid DOC file') from None

    elif extension == ".txt":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="TXT files must be UTF-8 encoded") from None
        if (not text.strip() or content.startswith((b"%PDF-", b"PK\x03\x04"))
                or any(ord(char) < 32 and char not in "\t\n\r" for char in text)
                or any(127 <= ord(char) <= 159 for char in text)):
            raise HTTPException(status_code=400, detail="Invalid or binary TXT file")

    return extension, ALLOWED_MANUSCRIPT_EXTENSIONS[extension]

# Resolve existing relative paths from the project root.
def resolve_manuscript_file_path(stored_path: str) -> Path:
    path = Path(stored_path)
    if IS_DEMO and path.is_absolute():
        raise HTTPException(status_code=409, detail="Invalid demo file path")
    return guard_demo_path(path if path.is_absolute() else BASE_DIR / path)

def manuscript_has_pdf(manuscript: Manuscript) -> bool:
    """
    Backward-compatible API helper.

    Despite the legacy name, return True when the manuscript
    has a supported PDF or Word document.
    """
    return manuscript_has_file(manuscript)

def manuscript_has_file(manuscript: Manuscript) -> bool:
    """Check whether a supported manuscript document exists."""
    if not manuscript.file_path:
        return False

    if manuscript.file_path.startswith('sample:v1/'):
        from app import sample_documents
        db = object_session(manuscript)
        if db is None:
            return False
        try:
            if not sample_documents.registered(db, manuscript.manuscript_id):
                return False
            sample_documents.current(db, manuscript)
            return True
        except HTTPException:
            return False

    file_path = resolve_manuscript_file_path(manuscript.file_path)

    return (
        file_path.is_file()
        and file_path.suffix.lower() in ALLOWED_MANUSCRIPT_EXTENSIONS
    )

def manuscript_file_type(manuscript: Manuscript) -> str | None:
    """Return the extension of an existing supported manuscript file."""
    if not manuscript.file_path:
        return None

    if manuscript.file_path.startswith('sample:v1/'):
        return Path(manuscript.file_path).suffix.lower().lstrip('.') if manuscript_has_file(manuscript) else None

    file_path = resolve_manuscript_file_path(manuscript.file_path)
    extension = file_path.suffix.lower()

    if not file_path.is_file():
        return None

    if extension not in ALLOWED_MANUSCRIPT_EXTENSIONS:
        return None

    return extension.lstrip(".")


def manuscript_to_response(manuscript: Manuscript) -> ManuscriptResponse:
    """Serialize a manuscript with its computed PDF availability."""
    response = ManuscriptResponse.model_validate(manuscript)
    return response.model_copy(update={
        "has_pdf": manuscript_has_pdf(manuscript),
        "file_type": manuscript_file_type(manuscript),
    })


def get_current_review_round(db: Session, manuscript: Manuscript) -> int:
    """Read the persisted round; older records fall back to assignment history."""
    stored_round = getattr(manuscript, "review_round", None)
    if isinstance(stored_round, int) and stored_round >= 1:
        return stored_round

    latest_round = db.scalar(
        select(ReviewAssignment.review_round)
        .where(ReviewAssignment.manuscript_id == manuscript.manuscript_id)
        .order_by(ReviewAssignment.review_round.desc())
        .limit(1)
    )
    return latest_round or 1



def can_access_manuscript(
    db: Session,
    manuscript: Manuscript,
    user: User,
) -> bool:
    # Authors can access their own manuscripts.
    if manuscript.author_id == user.user_id:
        return True

    # Drafts are private to their authors.
    if manuscript.status == "draft":
        return False

    # EIC can access submitted manuscripts.
    if user.role == "eic":
        return True

    # Editors need an accepted initial editor invitation,
    # or an existing peer-review assignment made by them.
    if user.role == "editor":
        from app.editor_invitation_revocation import is_revoked
        final_invitation = db.scalar(select(FinalEditorInvitation.invitation_id).where(
            FinalEditorInvitation.manuscript_id == manuscript.manuscript_id,
            FinalEditorInvitation.editor_id == user.user_id,
            FinalEditorInvitation.status == 'accepted').limit(1))
        if final_invitation is not None and not is_revoked(db,'final',final_invitation):
            return True
        invitation = db.scalar(
            select(InitialEditorInvitation.invitation_id)
            .where(
                InitialEditorInvitation.manuscript_id
                == manuscript.manuscript_id,
                InitialEditorInvitation.editor_id == user.user_id,
                InitialEditorInvitation.status == "accepted",
            )
            .limit(1)
        )

        if invitation is not None and not is_revoked(db,'initial',invitation):
            return True

        assignment = db.scalar(
            select(ReviewAssignment)
            .where(
                ReviewAssignment.manuscript_id
                == manuscript.manuscript_id,
                ReviewAssignment.assigned_by == user.user_id,
            )
            .limit(1)
        )

        return assignment is not None

    # Reviewers need an assignment.
    if user.role == "reviewer":
        assignments = db.scalars(
            select(ReviewAssignment)
            .where(
                ReviewAssignment.manuscript_id
                == manuscript.manuscript_id,
                ReviewAssignment.reviewer_id == user.user_id,
            )
        ).all()

        return any(may_review(db, assignment) for assignment in assignments)

    return False



def can_access_manuscript_pdf(
    db: Session,
    manuscript: Manuscript,
    user: User,
) -> bool:
    # Authors can always access their own PDFs.
    if manuscript.author_id == user.user_id:
        return True

    # Unsubmitted PDFs remain private to the author.
    if manuscript.status in (
        "draft",
        "revision_required",
        "initial_revision_required",
    ):
        return False

    return can_access_manuscript(db, manuscript, user)

def get_accessible_manuscripts(
    db: Session,
    user: User,
) -> list[Manuscript]:
    """
    Return non-draft manuscripts accessible to an EIC or Editor.
    """

    if user.role not in ("eic", "editor"):
        return []

    manuscripts = db.scalars(
        select(Manuscript)
        .where(Manuscript.status != "draft")
        .order_by(Manuscript.manuscript_id)
    ).all()

    # EIC can access all submitted manuscripts.
    if user.role == "eic":
        return list(manuscripts)

    # Editors can only access manuscripts they are authorized for.
    return [
        manuscript
        for manuscript in manuscripts
        if can_access_manuscript(db, manuscript, user)
    ]

@router.post(
    "/",
    response_model=ManuscriptResponse,
    status_code=status.HTTP_201_CREATED
)
def create_manuscript(
    manuscript_data: ManuscriptCreate,
    current_user: User = Depends(require_role("author")),
    db: Session = Depends(get_db)
):
    # Create a manuscript associated with the logged-in user
    new_manuscript = Manuscript(
        title=manuscript_data.title,
        abstract=manuscript_data.abstract,
        author_id=current_user.user_id,
        status="draft",
        review_round=1
    )

    # Save the manuscript
    db.add(new_manuscript)
    db.commit()
    db.refresh(new_manuscript)

    return manuscript_to_response(new_manuscript)


@router.post(
    "/{manuscript_id}/submit",
    response_model=ManuscriptResponse,
    summary="Submit Draft Manuscript"
)
def submit_draft_manuscript(
    manuscript_id: int,
    expected_online_version: str | None = None,
    selected_docx_version: str | None = None,
    expected_submission_revision: int | None = Header(default=None, alias="X-Expected-Submission-Revision", ge=0),
    submission_request_id: UUID | None = Header(default=None, alias='X-Submission-Request-ID'),
    current_user: User = Depends(require_role("author")),
    db: Session = Depends(get_db)
):
    _begin_author_submission(db)
    manuscript = db.get(Manuscript, manuscript_id)
    if manuscript is None:
        raise HTTPException(status_code=404, detail="Manuscript not found")
    if manuscript.author_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="You can only submit your own drafts")
    if submission_request_id is not None:
        _require_upload_request_schema(db)
        try:
            existing = db.execute(text('SELECT manuscript_id, author_id FROM manuscript_submission_requests WHERE request_id=:id'), {'id': str(submission_request_id)}).mappings().first()
        except SQLAlchemyError:
            raise HTTPException(503, 'Submission recovery is unavailable.') from None
        if existing is not None:
            if existing['manuscript_id'] != manuscript_id or existing['author_id'] != current_user.user_id:
                raise HTTPException(409, 'This submission request conflicts with another manuscript.')
            if manuscript.status == 'draft':
                raise HTTPException(503, 'Submission information is inconsistent.')
            db.rollback()
            return manuscript_to_response(manuscript)
    from app import sample_documents
    sample = sample_documents.registered(db, manuscript_id)
    if manuscript.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft manuscripts can be submitted")
    from app.author_submission_integration import validate_linked_submission
    validate_linked_submission(db, manuscript, expected_submission_revision)
    if not manuscript.title.strip() or not manuscript.abstract.strip():
        raise HTTPException(status_code=409, detail="Title and abstract are required")
    if not manuscript_has_file(manuscript):
        from app.author_submission_integration import linked_draft
        if linked_draft(db, manuscript_id) is not None:
            raise HTTPException(status_code=422, detail={"code": "submission_validation", "errors": [{"step": 5, "field": "manuscript_file", "message": "Upload the manuscript file."}]})
        raise HTTPException(
            status_code=409,
            detail="A PDF, DOCX, DOC, or TXT manuscript file is required before submission",
        )

    if sample and (AI_PRESCREENING_ENABLED or selected_docx_version):
        raise HTTPException(503, 'Sample submission with AI or DOCX online drafts is not yet available')
    if selected_docx_version and expected_online_version:
        raise HTTPException(status_code=409, detail="Select one draft only")

    if selected_docx_version:
        from app.routers.onlyoffice import install_author_draft
        _validate_author_online_submission(db, manuscript, current_user, None)
        install_author_draft(
            db,
            manuscript,
            current_user,
            selected_docx_version,
            get_current_review_round(db, manuscript),
        )
    elif sample:
        _validate_sample_online_submission(db, manuscript, current_user, expected_online_version)
    else:
        _validate_author_online_submission(
            db, manuscript, current_user, expected_online_version
        )

    manuscript.status = "submitted"
    if submission_request_id is not None:
        db.execute(text('INSERT INTO manuscript_submission_requests (request_id, manuscript_id, author_id) VALUES (:request, :id, :author)'), {'request': str(submission_request_id), 'id': manuscript_id, 'author': current_user.user_id})
    db.add(ManuscriptReviewPolicy(manuscript_id=manuscript_id, minimum_completed_reviewers=2))
    # There is no manuscript-specific EIC owner at initial submission. Every
    # current EIC can screen submitted manuscripts under existing access rules.
    for eic_id in db.scalars(select(User.user_id).where(User.role == 'eic')).all():
        db.add(Notification(user_id=eic_id, manuscript_id=manuscript_id,
            notification_type='manuscript_submitted', message='A manuscript was submitted for initial screening.', is_read=False))
    if sample:
        sample_documents.record_submission(db, manuscript, current_user, 'initial', get_current_review_round(db, manuscript))
    else:
        try_create_submission_job(
            db,
            enabled=AI_PRESCREENING_ENABLED,
            manuscript_id=manuscript_id,
            submitted_by=current_user.user_id,
            submission_kind="initial",
            review_round=get_current_review_round(db, manuscript),
            stored_path=manuscript.file_path,
            resolve_path=resolve_manuscript_file_path,
        )
    db.commit()
    db.refresh(manuscript)
    notify_workflow_email(
        "manuscript_submitted",
        current_user.email,
        {"manuscript_id": manuscript.manuscript_id},
    )
    return manuscript_to_response(manuscript)


# Editor: View all manuscripts with optional status filtering
@router.get(
    "/",
    response_model=list[ManuscriptResponse],
    summary="Get Accessible Manuscripts",
)
def get_all_manuscripts(
    status: str | None = None,
    current_user: User = Depends(require_role("editor", "eic")),
    db: Session = Depends(get_db),
):
    # Get only manuscripts the current user can access.
    manuscripts = get_accessible_manuscripts(
        db,
        current_user,
    )

    # Apply optional status filtering.
    if status is not None:
        manuscripts = [
            manuscript
            for manuscript in manuscripts
            if manuscript.status == status
        ]

    return [
        manuscript_to_response(manuscript)
        for manuscript in manuscripts
    ]


# Editor: Dashboard statistics by manuscript status
# Keep this static route before /{manuscript_id}.

@router.get(
    "/statistics",
    summary="Get Manuscript Statistics",
)
def get_manuscript_statistics(
    current_user: User = Depends(require_role("editor", "eic")),
    db: Session = Depends(get_db),
):
    # Get only manuscripts accessible to the current user.
    manuscripts = get_accessible_manuscripts(
        db,
        current_user,
    )

    # Count manuscripts by workflow status.
    counts = {
        "submitted": 0,
        "accepted": 0,
        "rejected": 0,
        "revision_required": 0,
        "revised": 0,
        "initial_scan_passed": 0,
        "initial_revision_required": 0,
        "initial_rejected": 0,
        "initial_editor_invited": 0,
        "initial_editing": 0,
    }

    for manuscript in manuscripts:
        if manuscript.status in counts:
            counts[manuscript.status] += 1

    return {
        "total": len(manuscripts),
        **counts,
    }

@router.get("/dashboard", summary="Get Editor Dashboard")
def get_editor_dashboard(
    current_user: User = Depends(require_role("editor", "eic")),
    db: Session = Depends(get_db)
):
    # Step 1: Get only accessible manuscripts
    manuscripts = get_accessible_manuscripts(
        db,
        current_user,
    )

    dashboard = []

    for manuscript in manuscripts:
        # Step 2: Determine the review round
        review_round = get_current_review_round(db, manuscript)

        # Step 3: Get assignments for the current round
        assignments = db.scalars(
            select(ReviewAssignment).where(
                ReviewAssignment.manuscript_id == manuscript.manuscript_id,
                ReviewAssignment.review_round == review_round,
                not_declined(),
            )
        ).all()

        # Step 4: Count completed reviews
        completed_reviews = 0

        for assignment in assignments:
            review = db.scalar(
                select(Review).where(
                    Review.assignment_id == assignment.assignment_id
                )
            )

            if review is not None:
                completed_reviews += 1

        total_reviewers = len(assignments)
        pending_reviews = total_reviewers - completed_reviews

        # Step 5: Determine review status
        if manuscript.status in ["accepted", "rejected"]:
            review_status = "decision_finalized"

        elif manuscript.status == "revision_required":
            review_status = "revision_required"

        elif total_reviewers == 0:
            review_status = "not_assigned"

        elif pending_reviews > 0:
            review_status = "in_progress"

        else:
            review_status = "completed"

        # Step 6: Build dashboard item
        dashboard.append({
            "manuscript_id": manuscript.manuscript_id,
            "title": manuscript.title,
            "status": manuscript.status,"legacy_editor_decision_allowed": (
                current_user.role == "editor"
                and manuscript.status in ("submitted", "revised")
                and not uses_eic_workflow(db, manuscript.manuscript_id)
            ),
            "has_pdf": manuscript_has_pdf(manuscript),
            "file_type": manuscript_file_type(manuscript),
            "review_round": review_round,
            "decision_progress": review_progress(db, manuscript, review_round),
            "author_agreement_status": db.scalar(select(AuthorAgreement.status).where(AuthorAgreement.manuscript_id == manuscript.manuscript_id).order_by(AuthorAgreement.agreement_id.desc()).limit(1)),
            "total_reviewers": total_reviewers,
            "completed_reviews": completed_reviews,
            "pending_reviews": pending_reviews,
            "review_status": review_status
        })

    return dashboard




# Editor: Summary of manuscript review progress
@router.get(
    "/dashboard/summary",
    summary="Get Editor Dashboard Summary"
)
def get_editor_dashboard_summary(
    current_user: User = Depends(require_role("editor", "eic")),
    db: Session = Depends(get_db)
):
    manuscripts = get_accessible_manuscripts(
        db,
        current_user,
    )

    summary = {
        "total_manuscripts": len(manuscripts),
        "not_assigned": 0,
        "in_progress": 0,
        "ready_for_decision": 0,
        "revision_required": 0,
        "decision_finalized": 0
    }

    for manuscript in manuscripts:
        if manuscript.status in ("accepted", "rejected"):
            summary["decision_finalized"] += 1
            continue

        if manuscript.status == "revision_required":
            summary["revision_required"] += 1
            continue

        # Use the same round calculation as the editor dashboard.
        review_round = get_current_review_round(db, manuscript)

        assignments = db.scalars(
            select(ReviewAssignment).where(
                ReviewAssignment.manuscript_id == manuscript.manuscript_id,
                ReviewAssignment.review_round == review_round,
                not_declined(),
            )
        ).all()

        if not assignments:
            summary["not_assigned"] += 1
            continue

        completed_reviews = sum(
            1 for assignment in assignments
            if db.scalar(
                select(Review.review_id).where(
                    Review.assignment_id == assignment.assignment_id
                )
            ) is not None
        )

        if completed_reviews == len(assignments):
            summary["ready_for_decision"] += 1
        else:
            summary["in_progress"] += 1

    return summary


@router.get(
    "/my",
    response_model=list[AuthorManuscriptResponse],
    summary="Get My Manuscripts"
)
def get_my_manuscripts(
    current_user: User = Depends(require_role("author")),
    db: Session = Depends(get_db)
):
    manuscripts = db.scalars(
        select(Manuscript)
        .where(Manuscript.author_id == current_user.user_id)
        .order_by(Manuscript.manuscript_id)
    ).all()

    links = {}
    if inspect(db.get_bind()).has_table('author_submission_links'):
        links = dict(db.execute(text('SELECT l.manuscript_id, l.draft_id FROM author_submission_links l JOIN author_submission_drafts d ON d.id = l.draft_id WHERE d.author_id = :author'), {'author': current_user.user_id}).all())
    return [AuthorManuscriptResponse(**manuscript_to_response(item).model_dump(), submission_draft_id=links.get(item.manuscript_id)) for item in manuscripts]

PROGRESS_STAGES = (
    "Submission",
    "Initial Screening",
    "Initial Editing",
    "Peer Review",
    "EIC Decision",
    "Author Agreement",
    "Final Editing",
    "Formatting",
    "Proofing",
    "Publication",
)

PROGRESS_STATUS_MAP = {
    "draft": ("Submission", "Upload a manuscript file and submit the draft."),
    "submitted": ("Initial Screening", "Wait for initial screening."),
    "initial_revision_required": ("Initial Screening", "Revise and resubmit the manuscript."),
    "initial_rejected": ("Initial Screening", "Initial screening rejected this manuscript."),
    "initial_scan_passed": ("Initial Editing", "Wait for initial editor assignment."),
    "initial_editor_invited": ("Initial Editing", "Wait for the invited editor."),
    "initial_editing": ("Initial Editing", "Check the Initial Editing workflow."),
    "pre_review_confirmation": ("Initial Editing", "Confirm the pre-review manuscript."),
    "ready_for_peer_review": ("Peer Review", "Wait for reviewer assignments."),
    "revised": ("Peer Review", "Wait for review of the revision."),
    "revision_required": ("Peer Review", "Revise and resubmit the manuscript."),
    "accepted": ("EIC Decision", "Accepted through the legacy editorial workflow."),
    "rejected": ("EIC Decision", "This manuscript was rejected; the workflow has ended."),
    "awaiting_author_agreement": ("Author Agreement", "Review the author agreement."),
    "author_agreement_declined": ("Author Agreement", "Contact the editorial team."),
    "final_editing": ("Final Editing", "Check the Final Editing workflow."),
    "formatting": ("Formatting", "Check the Formatting workflow."),
    "published": ("Publication", "Publication recorded in the local prototype."),
}

INITIAL_EDITING_STEPS = (
    "Editor Invitation",
    "Editor Submission",
    "Author Approval",
    "Editor Approval",
    "EIC Approval",
    "Pre-review Author Confirmation",
)

# These labels describe only an already-validated completion event. They carry
# no names, comments, paths, decisions or transfer information.
PROGRESS_COMPLETION_MILESTONES = {
    'Submission': 'Submission recorded',
    'Initial Screening': 'Initial screening passed',
    'Peer Review': 'Current-round review requirements met',
    'EIC Decision': 'Current-round editorial decision recorded',
    'Author Agreement': 'Author agreement accepted',
    'Final Editing': 'Final editing approvals recorded',
    'Formatting': 'Formatted proof submitted',
    'Proofing': 'Proof approvals recorded',
    'Publication': 'Prototype publication recorded',
}


def progress_completion_evidence(db: Session, manuscript: Manuscript, current_stage: str | None) -> set[str]:
    """Project only recorded completion; never infer history from a later status."""
    if current_stage not in PROGRESS_STAGES:
        return set()
    preceding = set(PROGRESS_STAGES[:PROGRESS_STAGES.index(current_stage)])
    mid = manuscript.manuscript_id
    complete = set()
    if 'Submission' in preceding and db.get(ManuscriptReviewPolicy, mid) is not None:
        complete.add('Submission')
    if 'Initial Screening' in preceding:
        latest_scan = db.scalar(select(EICInitialScan).where(EICInitialScan.manuscript_id == mid).order_by(EICInitialScan.scan_id.desc()).limit(1))
        if latest_scan and latest_scan.decision == 'pass': complete.add('Initial Screening')
    if 'Initial Editing' in preceding:
        confirmation = db.scalar(select(PreReviewConfirmation.confirmation_id).join(InitialEditingSubmission,
            PreReviewConfirmation.submission_id == InitialEditingSubmission.submission_id).where(
            PreReviewConfirmation.manuscript_id == mid, PreReviewConfirmation.author_id == manuscript.author_id,
            PreReviewConfirmation.decision == 'confirm', InitialEditingSubmission.manuscript_id == mid,
            InitialEditingSubmission.status == 'eic_approved',
            PreReviewConfirmation.file_path == InitialEditingSubmission.file_path).limit(1))
        if confirmation is not None: complete.add('Initial Editing')
    decision = None
    if preceding.intersection({'Peer Review', 'EIC Decision', 'Author Agreement'}):
        decision = db.scalar(select(EICDecision).where(EICDecision.manuscript_id == mid,
            EICDecision.review_round == manuscript.review_round).order_by(EICDecision.decision_id.desc()).limit(1))
    if 'Peer Review' in preceding and decision and review_progress(db, manuscript, manuscript.review_round)['can_decide']:
        complete.add('Peer Review')
    if 'EIC Decision' in preceding and decision and decision.decision in ('accept', 'reject', 'revision_required'):
        complete.add('EIC Decision')
    if 'Author Agreement' in preceding and decision and decision.decision == 'accept':
        agreement = db.scalar(select(AuthorAgreement.agreement_id).where(AuthorAgreement.manuscript_id == mid,
            AuthorAgreement.author_id == manuscript.author_id, AuthorAgreement.decision_id == decision.decision_id,
            AuthorAgreement.status == 'accepted', AuthorAgreement.responded_at.is_not(None)).limit(1))
        if agreement is not None: complete.add('Author Agreement')
    if 'Final Editing' in preceding:
        final = db.scalar(select(FinalEditingSubmission.submission_id).join(FinalEditingSubmissionInvitation,
            FinalEditingSubmissionInvitation.submission_id == FinalEditingSubmission.submission_id).join(FinalEditorInvitation,
            FinalEditorInvitation.invitation_id == FinalEditingSubmissionInvitation.invitation_id).where(
            FinalEditingSubmission.manuscript_id == mid, FinalEditorInvitation.manuscript_id == mid,
            FinalEditorInvitation.status == 'accepted', FinalEditorInvitation.editor_id == FinalEditingSubmission.editor_id,
            FinalEditingSubmission.status == 'author_approved', FinalEditingSubmission.author_reviewed_at.is_not(None),
            FinalEditingSubmission.eic_reviewed_at.is_not(None), FinalEditingSubmission.eic_approved_by.is_not(None)).limit(1))
        if final is not None: complete.add('Final Editing')
    if 'Formatting' in preceding:
        proof = db.scalar(select(FormattingSubmission.submission_id).join(FormatterInvitation,
            FormatterInvitation.invitation_id == FormattingSubmission.invitation_id).where(
            FormattingSubmission.manuscript_id == mid, FormatterInvitation.manuscript_id == mid,
            FormatterInvitation.status == 'accepted', FormattingSubmission.status == 'approved',
            FormattingSubmission.author_reviewed_at.is_not(None), FormattingSubmission.eic_reviewed_at.is_not(None),
            FormattingSubmission.eic_id.is_not(None)).limit(1))
        if proof is not None: complete.add('Formatting')
    if 'Proofing' in preceding and 'Formatting' in complete:
        complete.add('Proofing')
    return complete


def initial_editing_progress(db: Session, manuscript_id: int) -> list[dict]:
    """Read-only milestones for the latest initial-editing submission."""
    latest = db.scalar(
        select(InitialEditingSubmission)
        .where(InitialEditingSubmission.manuscript_id == manuscript_id)
        .order_by(InitialEditingSubmission.submission_id.desc())
        .limit(1)
    )

    invitation_query = select(InitialEditorInvitation).where(
        InitialEditorInvitation.manuscript_id == manuscript_id
    )

    # Bind an existing submission to the editor who actually submitted it.
    if latest is not None:
        invitation_query = invitation_query.where(
            InitialEditorInvitation.editor_id == latest.editor_id,
            InitialEditorInvitation.status == "accepted",
        )

    invitation = db.scalar(
        invitation_query.order_by(
            InitialEditorInvitation.invitation_id.desc()
        ).limit(1)
    )

    states = {name: "unknown" for name in INITIAL_EDITING_STEPS}

    if invitation is not None:
        if invitation.status == "accepted":
            states["Editor Invitation"] = "completed"
        elif invitation.status == "pending":
            states["Editor Invitation"] = "current"

    if latest is not None:
        states["Editor Submission"] = "completed"

        status = latest.status

        if status == "pending_author":
            states["Author Approval"] = "current"

        elif status == "author_approved":
            states["Author Approval"] = "completed"
            states["Editor Approval"] = "current"

        elif status == "editor_approved":
            states["Author Approval"] = "completed"
            states["Editor Approval"] = "completed"
            states["EIC Approval"] = "current"

        elif status == "eic_approved":
            states["Author Approval"] = "completed"
            states["Editor Approval"] = "completed"
            states["EIC Approval"] = "completed"

            confirmation = db.scalar(
                select(PreReviewConfirmation)
                .where(
                    PreReviewConfirmation.manuscript_id == manuscript_id,
                    PreReviewConfirmation.submission_id == latest.submission_id,
                )
                .order_by(
                    PreReviewConfirmation.confirmation_id.desc()
                )
                .limit(1)
            )

            if confirmation is None:
                states["Pre-review Author Confirmation"] = "current"
            elif confirmation.decision == "confirm":
                manuscript = db.get(Manuscript, manuscript_id)
                if (manuscript and confirmation.author_id == manuscript.author_id
                        and confirmation.file_path and confirmation.file_path == latest.file_path):
                    states["Pre-review Author Confirmation"] = "completed"
            # A rejected version is not considered completed.

    return [
        {"name": name, "state": states[name]}
        for name in INITIAL_EDITING_STEPS
    ]


@router.get(
    "/{manuscript_id}/progress",
    summary="Get Manuscript Progress",
)
def get_manuscript_progress(
    manuscript_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    metadata_mode: MetadataMode = Depends(reviewer_metadata_mode),
):
    """Read-only, role-authorized manuscript progress summary."""
    if type(metadata_mode) is not MetadataMode:
        raise HTTPException(503, 'Progress unavailable')
    protected_reviewer = current_user.role == 'reviewer' and metadata_mode is MetadataMode.EXPERIMENTAL
    if current_user.role == 'formatter' and metadata_mode is MetadataMode.EXPERIMENTAL:
        try:
            connection = db.connection()
            if connection.dialect.name != 'sqlite': raise MetadataSchemaUnavailable('Progress unavailable')
            raw = connection.connection.driver_connection
            if not raw.in_transaction: connection.exec_driver_sql('BEGIN')
        except (MetadataSchemaUnavailable, sqlite3.DatabaseError, SQLAlchemyError):
            raise HTTPException(503, 'Progress unavailable', headers={'Cache-Control': 'no-store'}) from None
    if protected_reviewer:
        try:
            connection = db.connection()
            if connection.dialect.name != 'sqlite': raise MetadataSchemaUnavailable('Progress unavailable')
            raw = connection.connection.driver_connection
            if not raw.in_transaction: connection.exec_driver_sql('BEGIN')
            reviewer_metadata_dto(raw, manuscript_id, current_user.user_id)
        except MetadataSchemaUnavailable:
            raise HTTPException(503, 'Progress unavailable', headers={'Cache-Control': 'no-store'}) from None
        except (MetadataAccessDenied, sqlite3.DatabaseError, SQLAlchemyError):
            raise HTTPException(404, 'Manuscript not found', headers={'Cache-Control': 'no-store'}) from None
    manuscript = db.get(Manuscript, manuscript_id)
    if manuscript is None:
        raise HTTPException(status_code=404, detail="Manuscript not found")
    if current_user.role == 'formatter':
        # Match the existing formatting workflow's accepted, current final edit.
        from app.routers.formatting import latest_final, ready_final
        invitation = db.scalar(select(FormatterInvitation).where(
            FormatterInvitation.manuscript_id == manuscript_id,
            FormatterInvitation.formatter_id == current_user.user_id,
            FormatterInvitation.status == 'accepted'))
        final = latest_final(db, manuscript_id)
        if not invitation or manuscript.status not in ('formatting', 'published') or not ready_final(final) or invitation.final_submission_id != final.submission_id:
            raise HTTPException(404, 'Manuscript not found')
        if metadata_mode is MetadataMode.EXPERIMENTAL:
            from importlib import import_module
            from app import lifecycle_prototype, blind_policy_store
            try:
                connection = db.connection()
                if connection.dialect.name != 'sqlite': raise ValueError('Unavailable')
                raw = connection.connection.driver_connection
                if not raw.in_transaction: connection.exec_driver_sql('BEGIN')
                migration = import_module('migrations.009_account_invitation_lifecycle')
                if not raw.execute('PRAGMA foreign_keys').fetchone()[0] or not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (migration.MIGRATION_ID,)).fetchone(): raise ValueError('Unavailable')
                migration._validate_own_schema(migration._objects(raw))
                if raw.execute('SELECT role FROM users WHERE user_id=?', (current_user.user_id,)).fetchone() != ('formatter',): raise ValueError('Unavailable')
                state = lifecycle_prototype._state(raw, current_user.user_id)
                policy = blind_policy_store.read_policy(raw, manuscript_id)
                if state is None or state.state != 'active' or not policy or not policy['locked_at']: raise ValueError('Unavailable')
            except Exception:
                raise HTTPException(404, 'Manuscript not found', headers={'Cache-Control': 'no-store'}) from None
    elif current_user.role == 'reviewer' and not protected_reviewer:
        assignments = db.scalars(select(ReviewAssignment).where(ReviewAssignment.manuscript_id == manuscript_id,
            ReviewAssignment.reviewer_id == current_user.user_id, ReviewAssignment.review_round == manuscript.review_round,
            ReviewAssignment.status.in_(['assigned', 'completed']))).all()
        try:
            ledger_available = inspect(db.connection()).has_table('reviewer_invitation_invalidations')
            authorized = ledger_available and any(
                may_review(db, assignment) and not db.scalar(select(ReviewerInvitationInvalidation.invalidation_id).where(
                    ReviewerInvitationInvalidation.assignment_id == assignment.assignment_id).limit(1))
                for assignment in assignments)
        except SQLAlchemyError:
            raise HTTPException(503, 'Progress unavailable', headers={'Cache-Control': 'no-store'}) from None
        if manuscript.status not in ('ready_for_peer_review', 'revised') or not authorized:
            raise HTTPException(404, 'Manuscript not found')
    elif not protected_reviewer and not can_access_manuscript(db, manuscript, current_user):
        formatting_access = False

        if current_user.role == 'editor' and metadata_mode is MetadataMode.DISABLED:
            from app.routers.formatting import latest_final, ready_final

            invitation = db.scalar(select(FormatterInvitation).where(
                FormatterInvitation.manuscript_id == manuscript_id,
                FormatterInvitation.formatter_id == current_user.user_id,
                FormatterInvitation.status == 'accepted',
            ))

            final = latest_final(db, manuscript_id)

            formatting_access = (
                invitation is not None
                and manuscript.status in ('formatting', 'published')
                and ready_final(final)
                and invitation.final_submission_id == final.submission_id
            )

        if not formatting_access:
            raise HTTPException(status_code=404, detail="Manuscript not found")

    status_value = manuscript.status
    current_info = PROGRESS_STATUS_MAP.get(status_value)
    stage = current_info[0] if current_info else None
    # Fail closed when the current formatting evidence is incomplete or
    # inconsistent. This is a read-only projection; no statuses are changed.
    proof_submitted = False
    formatting_substage = None
    if status_value == 'formatting':
        from app.routers.formatting import latest_final, ready_final
        proof = db.scalar(select(FormattingSubmission).where(
            FormattingSubmission.manuscript_id == manuscript_id
        ).order_by(FormattingSubmission.submission_id.desc()).limit(1))
        final = latest_final(db, manuscript_id)
        current_invitation = (db.get(FormatterInvitation, proof.invitation_id) if proof else db.scalar(
            select(FormatterInvitation).where(FormatterInvitation.manuscript_id == manuscript_id)
            .order_by(FormatterInvitation.invitation_id.desc()).limit(1)))
        active_proofs = db.scalars(select(FormattingSubmission.submission_id).where(
            FormattingSubmission.manuscript_id == manuscript_id,
            FormattingSubmission.status.in_(['pending_author', 'pending_eic', 'approved'])
        ).limit(2)).all()
        bound = bool(current_invitation and current_invitation.manuscript_id == manuscript_id
            and ready_final(final) and current_invitation.final_submission_id == final.submission_id
            and len(active_proofs) <= 1 and (not active_proofs or (proof and proof.submission_id == active_proofs[0])))
        evidence = None
        if bound:
            if proof is None and current_invitation.status in ('pending', 'accepted', 'declined'):
                evidence = {'pending': 'formatter_invited', 'accepted': 'awaiting_formatted_proof',
                            'declined': 'formatter_declined'}[current_invitation.status]
            elif proof and current_invitation.status == 'accepted':
                if proof.status == 'pending_author' and not proof.author_reviewed_at and not proof.eic_reviewed_at and not proof.eic_id:
                    evidence = 'pending_author'
                elif proof.status == 'pending_eic' and proof.author_reviewed_at and not proof.eic_reviewed_at and not proof.eic_id:
                    evidence = 'pending_eic'
                elif proof.status == 'approved' and proof.author_reviewed_at and proof.eic_reviewed_at and proof.eic_id:
                    evidence = 'approved'
                elif proof.status == 'author_revision_requested' and proof.author_reviewed_at and not proof.eic_reviewed_at and not proof.eic_id:
                    evidence = 'author_revision_requested'
                elif proof.status == 'eic_revision_requested' and proof.author_reviewed_at and proof.eic_reviewed_at and proof.eic_id:
                    evidence = 'eic_revision_requested'
        proof_submitted = evidence in ('pending_author', 'pending_eic', 'approved')
        stage = 'Proofing' if proof_submitted else 'Formatting' if evidence else None
        permitted = current_user.role in ('author', 'eic') or bool(
            current_user.role in ('editor', 'formatter') and current_invitation
            and current_invitation.formatter_id == current_user.user_id
            and current_invitation.status == 'accepted')
        if permitted:
            formatting_substage = evidence
    action = current_info[1] if current_info else (
        "Revise and resubmit the manuscript."
        if status_value == "revision_required"
        else "Consult the editorial team."
    )

    if status_value == 'formatting' and stage is None:
        action = 'Formatting progress is unavailable because its evidence is incomplete.'

    complete = progress_completion_evidence(db, manuscript, stage)
    if stage == 'Proofing' and proof_submitted:
        complete.add('Formatting')
    publication_verified = False
    if status_value == "published":
        publication_verified = db.scalar(
            select(PrototypePublication.manuscript_id)
            .join(
                FormattingSubmission,
                PrototypePublication.submission_id == FormattingSubmission.submission_id,
            )
            .where(
                PrototypePublication.manuscript_id == manuscript_id,
                FormattingSubmission.manuscript_id == manuscript_id,
                FormattingSubmission.status == "approved",
            )
            .limit(1)
        ) is not None
    stages = []
    for index, name in enumerate(PROGRESS_STAGES):
        state = "unknown"
        if name == "Publication" and status_value == "published" and publication_verified:
            state = "completed"
        elif name == stage:
            state = "current"
        elif name in complete:
            state = "completed"
        elif (
            stage is not None
            and status_value not in {"initial_rejected", "rejected"}
            and index > PROGRESS_STAGES.index(stage)
        ):
            state = "pending"
        item = {"name": name, "state": state}
        if name == "Initial Editing" and current_user.role in ("author", "eic"):
            item["steps"] = initial_editing_progress(db, manuscript_id)
        elif name == 'Proofing' and stage == 'Proofing' and current_user.role in ('author', 'eic'):
            author_state = 'completed' if proof.author_reviewed_at else ('current' if proof.status == 'pending_author' else 'unknown')
            eic_state = 'completed' if proof.eic_reviewed_at and proof.eic_id else ('current' if proof.status == 'pending_eic' and proof.author_reviewed_at else 'unknown')
            item['steps'] = [{'name': 'Author proof review', 'state': author_state},
                             {'name': 'EIC proof review', 'state': eic_state}]
        elif name in PROGRESS_COMPLETION_MILESTONES and current_user.role in ('author', 'eic'):
            recorded = name in complete or (name == 'Publication' and publication_verified)
            item['steps'] = [{'name': PROGRESS_COMPLETION_MILESTONES[name],
                              'state': 'completed' if recorded else 'unknown'}]
        stages.append(item)

    task = (participant_task(db, manuscript, current_user, stage)
            if stage is not None or status_value != 'formatting' else
            {'task_state': 'unavailable', 'task_message': action, 'relevant_stage': None,
             'action_label': None, 'permitted_action_target': None})
    if current_user.role == 'reviewer':
        # The same neutral projection is safe for both policies and unresolved cases.
        reviewer_progress = ReviewerProgressDTO(
            manuscript_id=manuscript.manuscript_id, status=status_value,
            review_round=get_current_review_round(db, manuscript), current_stage=stage,
            next_action=action, stages=[{'name': item['name'], 'state': item['state']} for item in stages], participant_task=task,
        )
        return JSONResponse(content=reviewer_progress.model_dump(mode='json'), headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})
    result = {
        "manuscript_id": manuscript.manuscript_id,
        "title": manuscript.title,
        "status": status_value,
        "review_round": get_current_review_round(db, manuscript),
        "current_stage": stage,
        "next_action": action,
        "participant_task": task,
        "stages": stages,
    }
    if status_value == 'formatting' and current_user.role in ('author', 'eic', 'editor', 'formatter'):
        result['formatting_substage'] = formatting_substage
    if current_user.role == 'formatter' and metadata_mode is MetadataMode.EXPERIMENTAL:
        return JSONResponse(content=result, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})
    return result


@router.get("/{manuscript_id}/timeline", summary="Get role-filtered manuscript activity")
def get_manuscript_timeline(
    manuscript_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    metadata_mode: MetadataMode = Depends(reviewer_metadata_mode),
):
    # Reuse the same role/assignment/policy gate as the progress projection.
    get_manuscript_progress(manuscript_id, current_user, db, metadata_mode)
    from app.manuscript_timeline import role_timeline, reviewer_timeline_assignments
    manuscript = db.get(Manuscript, manuscript_id)
    if current_user.role == 'reviewer':
        try:
            if not reviewer_timeline_assignments(db, manuscript, current_user):
                raise HTTPException(404, 'Manuscript not found')
        except SQLAlchemyError:
            raise HTTPException(503, 'Activity history unavailable') from None
    return JSONResponse({'manuscript_id': manuscript_id, 'events': role_timeline(db, manuscript, current_user),
                         'partial_history': True}, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})


@router.get(
    "/{manuscript_id}",
    response_model=ManuscriptResponse | ReviewerDetailDTO | ReviewerSingleBlindDetailDTO,
    summary="Get Manuscript Details",
)
def get_manuscript(
    manuscript_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    metadata_mode: MetadataMode = Depends(reviewer_metadata_mode),
):
    if type(metadata_mode) is not MetadataMode:
        raise HTTPException(status_code=503, detail="Reviewer metadata unavailable")
    raw = None
    reviewer_dto = None
    if metadata_mode is MetadataMode.EXPERIMENTAL:
        # Authentication used this same session; establish a SQLite read snapshot
        # and reload role before deciding which response is allowed.
        try:
            connection = db.connection()
            if connection.dialect.name != 'sqlite':
                raise MetadataSchemaUnavailable('Reviewer metadata unavailable')
            raw = connection.connection.driver_connection
            if not raw.in_transaction:
                connection.exec_driver_sql('BEGIN')
            row = raw.execute('SELECT role FROM users WHERE user_id=?',(current_user.user_id,)).fetchone()
            if not row or row[0] != current_user.role:
                raise HTTPException(status_code=404, detail="Manuscript not found")
        except (MetadataSchemaUnavailable, sqlite3.DatabaseError, SQLAlchemyError):
            raise HTTPException(status_code=503, detail="Reviewer metadata unavailable") from None
        if current_user.role == 'reviewer':
            try:
                reviewer_dto = reviewer_metadata_dto(raw, manuscript_id, current_user.user_id)
            except MetadataSchemaUnavailable:
                raise HTTPException(status_code=503, detail="Reviewer metadata unavailable") from None
            except MetadataAccessDenied:
                raise HTTPException(status_code=404, detail="Manuscript not found") from None
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Use the centralized manuscript access rules.
    if not can_access_manuscript(db, manuscript, current_user):
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    if current_user.role == 'reviewer':
        policy_mode = 'single_blind' if isinstance(reviewer_dto, ReviewerSingleBlindDTO) else 'double_blind'
        if reviewer_dto is None:
            try:
                connection = db.connection()
                if connection.dialect.name != 'sqlite':
                    raise MetadataSchemaUnavailable('Reviewer metadata unavailable')
                raw = connection.connection.driver_connection
                if not raw.in_transaction:
                    connection.exec_driver_sql('BEGIN')
                policy_mode = reviewer_detail_policy(raw, manuscript_id)
            except MetadataSchemaUnavailable:
                raise HTTPException(status_code=503, detail='Reviewer metadata unavailable', headers={'Cache-Control': 'no-store'}) from None
            except (MetadataAccessDenied, sqlite3.DatabaseError, SQLAlchemyError):
                raise HTTPException(status_code=404, detail='Manuscript not found', headers={'Cache-Control': 'no-store'}) from None
        if type(manuscript.review_round) is not int or manuscript.review_round < 1:
            raise HTTPException(status_code=404, detail='Manuscript not found', headers={'Cache-Control': 'no-store'})
        values = {'manuscript_id': manuscript.manuscript_id, 'review_round': manuscript.review_round}
        if policy_mode == 'single_blind':
            author = db.get(User, manuscript.author_id)
            if not author or author.role != 'author' or not isinstance(author.name, str) or not author.name.strip():
                raise HTTPException(status_code=404, detail='Manuscript not found', headers={'Cache-Control': 'no-store'})
            detail = ReviewerSingleBlindDetailDTO(**values, author_name=author.name)
        else:
            detail = ReviewerDetailDTO(**values)
        return JSONResponse(content=detail.model_dump(), headers={'Cache-Control':'no-store','Pragma':'no-cache'})

    return manuscript_to_response(manuscript)




@router.patch("/{manuscript_id}", response_model=ManuscriptResponse)
def update_manuscript(
    manuscript_id: int,
    update_data: ManuscriptUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    expected_metadata_sha256: str | None = Header(default=None, alias="X-Expected-Metadata-SHA256"),
):
    # Find the manuscript
    manuscript = db.get(Manuscript, manuscript_id, populate_existing=expected_metadata_sha256 is not None)

    if manuscript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manuscript not found"
        )

    # Only the author can update their own manuscript
    if manuscript.author_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own manuscripts"
        )

    # Only allow editing before the first review assignment
    if manuscript.status not in ("draft", "submitted"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manuscript cannot be edited at this stage"
        )

    # Check whether a reviewer has already been assigned
    existing_assignment = db.scalar(
        select(ReviewAssignment).where(
            ReviewAssignment.manuscript_id == manuscript_id
        )
    )

    if existing_assignment is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manuscript cannot be edited after reviewer assignment"
        )


    # Update only the provided fields
    changes = update_data.model_dump(exclude_unset=True)

    from app.author_submission_integration import linked_draft
    if changes and linked_draft(db, manuscript_id) is not None:
        raise HTTPException(status_code=409, detail="Edit this manuscript through its submission draft.")

    if expected_metadata_sha256 is not None:
        if len(changes) != 1 or not re.fullmatch(r"[0-9a-f]{64}", expected_metadata_sha256):
            raise HTTPException(status_code=400, detail="A single metadata field and valid expected digest are required")
        field, value = next(iter(changes.items()))
        if field not in ("title", "abstract") or value is None:
            raise HTTPException(status_code=400, detail="Invalid metadata update")
        original = getattr(manuscript, field)
        if not isinstance(original, str):
            raise HTTPException(status_code=409, detail="This field is unavailable. Reload before saving.")
        if hashlib.sha256(original.encode("utf-8")).hexdigest() != expected_metadata_sha256:
            raise HTTPException(status_code=409, detail="This field changed elsewhere. Reload before saving.")
        column = getattr(Manuscript, field)
        statement = update(Manuscript).where(
            Manuscript.manuscript_id == manuscript_id,
            Manuscript.author_id == current_user.user_id,
            Manuscript.status.in_(("draft", "submitted")),
            column == original,
            ~select(ReviewAssignment.assignment_id).where(ReviewAssignment.manuscript_id == manuscript_id).exists(),
        ).values({field: value})
        result = db.execute(statement.execution_options(synchronize_session=False))
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="This field or manuscript state changed. Reload before saving.")
        db.commit()
        db.refresh(manuscript)
        return manuscript_to_response(manuscript)

    for field, value in changes.items():
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} cannot be null"
            )

        setattr(manuscript, field, value)

    # Save changes to the database
    db.commit()
    db.refresh(manuscript)

    return manuscript_to_response(manuscript)

@router.delete(
    "/{manuscript_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_manuscript(
    manuscript_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db)
):
    # Find the manuscript
    manuscript = db.scalar(
        select(Manuscript).where(
            Manuscript.manuscript_id == manuscript_id
        )
    )

    # Check whether the manuscript exists
    if manuscript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manuscript not found"
        )

    # Only the author can delete their own manuscript
    if manuscript.author_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own manuscripts"
        )

    # Only draft and unassigned legacy submitted manuscripts can be deleted
    if manuscript.status not in ("draft", "submitted"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manuscript cannot be deleted at this stage"
        )

    # Prevent deletion after reviewer assignment
    existing_assignment = db.scalar(
        select(ReviewAssignment).where(
            ReviewAssignment.manuscript_id == manuscript_id
        )
    )

    if existing_assignment is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manuscript cannot be deleted after reviewer assignment"
        )

    # Delete the manuscript from the database
    db.delete(manuscript)
    db.commit()

@router.patch(
    "/{manuscript_id}/decision",
    summary="Editor Decision"
)
def make_editor_decision(
    manuscript_id: int,
    decision_data: EditorDecision,
    current_user: User = Depends(require_role("editor")),
    db: Session = Depends(get_db)
):
    # Step 1: Find the manuscript
    manuscript = db.scalar(
        select(Manuscript).where(
            Manuscript.manuscript_id == manuscript_id
        )
    )

    if manuscript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manuscript not found"
        )

    # First, verify that the editor can access this manuscript.
    if not can_access_manuscript(db, manuscript, current_user):
        raise HTTPException(
            status_code=403,
            detail="You are not an assigned editor",
        )

    # Prevent the legacy Editor Decision endpoint from bypassing EIC.
    if uses_eic_workflow(db, manuscript_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "This manuscript uses the EIC workflow. "
                "The EIC must make the editorial decision."
            ),
        )
    # Step 2: Decisions are permitted only while a round is under review.
    if manuscript.status not in ("submitted", "revised"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manuscript is not ready for an editor decision"
        )
    current_round = get_current_review_round(db, manuscript)

    # Prevent the older editor endpoint from bypassing the prospective policy.
    progress = review_progress(db, manuscript, current_round)
    if progress['policy'] == 'two_reviewers' and not progress['can_decide']:
        raise HTTPException(status_code=409, detail=progress['blocked_reason'])

    # Step 3: Find assignments for the current review round
    assignments = db.scalars(
        select(ReviewAssignment).where(
            ReviewAssignment.manuscript_id == manuscript_id,
            ReviewAssignment.review_round == current_round,
            not_declined(),
        )
    ).all()

    # A manuscript must have at least one reviewer
    if not assignments:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No reviewers have been assigned to this manuscript"
        )

    # Check whether every assigned reviewer has submitted a review
    for assignment in assignments:
        review = db.scalar(
            select(Review).where(
                Review.assignment_id == assignment.assignment_id
            )
        )

        if review is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Not all assigned reviewers have submitted their reviews"
            )

    # Step 4: Update manuscript status
    manuscript.status = decision_data.decision

    # Step 5: Create notification for the author
    decision_messages = {
        "accepted": "has been accepted",
        "rejected": "has been rejected",
        "revision_required": "requires revision",
    }

    decision_text = decision_messages.get(
        decision_data.decision,
        decision_data.decision
    )

    notification = Notification(
        user_id=manuscript.author_id,
        manuscript_id=manuscript.manuscript_id,
        notification_type="editor_decision",
        message=(
            f"Your manuscript #{manuscript.manuscript_id}: "
            f"{manuscript.title} {decision_text} "
            f"(Round {current_round})."
        ),
        is_read=False
    )

    db.add(notification)

    # Step 6: Save changes
    author = db.get(User, manuscript.author_id)
    db.commit()
    db.refresh(manuscript)

    if author is not None:
        if manuscript.status in ("accepted", "rejected"):
            notify_workflow_email(
                "manuscript_decision",
                author.email,
                {
                    "manuscript_id": manuscript.manuscript_id,
                    "decision": manuscript.status,
                },
            )
        elif manuscript.status == "revision_required":
            notify_workflow_email(
                "revision_requested",
                author.email,
                {"manuscript_id": manuscript.manuscript_id},
            )

    # Step 7: Return result
    return {
        "manuscript_id": manuscript.manuscript_id,
        "status": manuscript.status,
        "decided_by": current_user.user_id
    }

@router.post(
    "/{manuscript_id}/resubmit",
    response_model=ManuscriptResponse,
    summary="Resubmit Revised Manuscript"
)
def resubmit_manuscript(
    manuscript_id: int,
    update_data: ManuscriptUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    expected_online_version: str | None = None,
    selected_docx_version: str | None = None,
    db: Session = Depends(get_db)
):
    _begin_author_submission(db)
    # Step 1: Find the manuscript
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manuscript not found"
        )

    # Step 2: Only the author can resubmit
    if manuscript.author_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only resubmit your own manuscripts"
        )
    from app import sample_documents
    sample = sample_documents.registered(db, manuscript_id)

    # Step 3: Only manuscripts requiring revision can be resubmitted
    if manuscript.status != "revision_required":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manuscript does not require revision"
        )
    if sample and (AI_PRESCREENING_ENABLED or selected_docx_version):
        raise HTTPException(503, 'Sample revision with AI or DOCX online drafts is unavailable')
    if sample:
        _validate_sample_online_submission(db, manuscript, current_user, expected_online_version)
    else:
        _validate_author_online_submission(db, manuscript, current_user, expected_online_version)

    if selected_docx_version:
        if expected_online_version: raise HTTPException(409, 'Select one draft only')
        from app.routers.onlyoffice import install_author_draft
        install_author_draft(db, manuscript, current_user, selected_docx_version, get_current_review_round(db, manuscript) + 1)

    # Require a new PDF for the upcoming review round.
    next_round = get_current_review_round(db, manuscript) + 1

    if sample:
        from app.submission_snapshot_history import snapshot_rows
        decision = db.scalar(select(EICDecision).where(EICDecision.manuscript_id == manuscript_id,
            EICDecision.review_round == next_round - 1, EICDecision.decision == 'revision_required')
            .order_by(EICDecision.decision_id.desc()).limit(1))
        version, revised_content = sample_documents.current(db, manuscript)
        prior = snapshot_rows(db, manuscript)
        try:
            uploaded_at = datetime.fromisoformat(version['created_at'])
            decided_at = decision.decided_at if decision else None
            if uploaded_at.tzinfo is None or decided_at is None:
                raise ValueError('Missing decision evidence')
            if decided_at.tzinfo is None:
                decided_at = decided_at.replace(tzinfo=timezone.utc)
            if (version['review_round'] != next_round or uploaded_at <= decided_at or not prior
                    or prior[-1]['file_ref'] == version['storage_identity']):
                raise ValueError('Revision is not new')
            validate_manuscript_file('revision.' + version['file_format'], revised_content, historical=True)
        except (TypeError, ValueError, HTTPException):
            raise HTTPException(409, 'A new authorized round revision is required') from None
    else:
        upload_dir = guard_demo_path(BASE_DIR / "uploads" / "manuscripts" / str(manuscript_id))
        current_pdf = resolve_manuscript_file_path(manuscript.file_path) if manuscript.file_path else None
        if (current_pdf is None or not current_pdf.is_file() or current_pdf.parent.resolve() != upload_dir.resolve()
                or current_pdf.suffix.lower() not in ALLOWED_MANUSCRIPT_EXTENSIONS
                or not current_pdf.name.startswith(f"round_{next_round}_")):
            raise HTTPException(status_code=409, detail="Upload a revised PDF, DOCX, DOC, or TXT file before resubmitting")
        try:
            with current_pdf.open("rb") as revised_file:
                revised_content = revised_file.read(MAX_MANUSCRIPT_FILE_SIZE + 1)
        except OSError:
            raise HTTPException(status_code=409, detail="Revised manuscript file is unavailable")
        validate_manuscript_file(current_pdf.name, revised_content, historical=True)

    # Step 4: Update manuscript fields
    changes = update_data.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one field to revise"
        )

    for field, value in changes.items():
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} cannot be null"
            )

        setattr(manuscript, field, value)

    # Step 5: Advance exactly once when the author formally resubmits.
    # PDF uploads for revisions are saved under this upcoming round.
    existing_round_file = db.scalar(select(ReviewRoundFile).where(
        ReviewRoundFile.manuscript_id == manuscript_id,
        ReviewRoundFile.review_round == next_round,
    ))
    if existing_round_file is not None:
        raise HTTPException(status_code=409, detail="A file is already recorded for this review round")
    db.add(ReviewRoundFile(
        manuscript_id=manuscript_id,
        review_round=next_round,
        source_kind="author_revision",
        confirmation_id=None,
        file_path=manuscript.file_path,
    ))
    manuscript.review_round = next_round
    manuscript.status = "revised"

    # Notify only the EIC who requested this revision and participating editors.
    previous_round = next_round - 1
    decision_eic = db.scalar(select(EICDecision.eic_id).where(EICDecision.manuscript_id == manuscript_id,
        EICDecision.review_round == previous_round, EICDecision.decision == 'revision_required').order_by(EICDecision.decision_id.desc()).limit(1))
    editor_ids = set(db.scalars(select(InitialEditorInvitation.editor_id).where(
        InitialEditorInvitation.manuscript_id == manuscript_id, InitialEditorInvitation.status == 'accepted')).all())
    editor_ids.update(db.scalars(select(ReviewAssignment.assigned_by).where(
        ReviewAssignment.manuscript_id == manuscript_id, ReviewAssignment.review_round == previous_round)).all())
    candidate_ids = editor_ids | ({decision_eic} if decision_eic is not None else set())
    if candidate_ids:
        participants = db.scalars(select(User.user_id).where(User.user_id.in_(candidate_ids), User.role.in_(['eic', 'editor']))).all()
        for recipient in participants:
            db.add(Notification(user_id=recipient, manuscript_id=manuscript_id,
                notification_type='revision_submitted', message=f'A revised manuscript was submitted for round {next_round}.', is_read=False))

    # Step 6: Save changes
    if sample:
        sample_documents.record_submission(db, manuscript, current_user, 'peer_revision', get_current_review_round(db, manuscript))
    else:
        try_create_submission_job(
            db, enabled=AI_PRESCREENING_ENABLED, manuscript_id=manuscript_id,
            submitted_by=current_user.user_id, submission_kind="peer_revision",
            review_round=get_current_review_round(db, manuscript), stored_path=manuscript.file_path,
            resolve_path=resolve_manuscript_file_path,
        )
    db.commit()
    db.refresh(manuscript)

    return manuscript_to_response(manuscript)



def _require_upload_request_schema(db):
    try:
        inspector = inspect(db.connection())
        if not all(inspector.has_table(name) for name in ('schema_migrations', 'manuscript_upload_names', 'manuscript_upload_requests', 'manuscript_submission_requests')):
            raise HTTPException(503, 'Upload recovery is unavailable.')
        if db.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='045_manuscript_upload_requests'")).first() is None:
            raise HTTPException(503, 'Upload recovery is unavailable.')
    except SQLAlchemyError:
        raise HTTPException(503, 'Upload recovery is unavailable.') from None


def _upload_receipt(db, manuscript, author_id, request_id):
    _require_upload_request_schema(db)
    try:
        row = db.execute(text('SELECT manuscript_id, author_id, storage_name, original_filename, size, sha256 FROM manuscript_upload_requests WHERE request_id=:id'), {'id': str(request_id)}).mappings().first()
    except SQLAlchemyError:
        raise HTTPException(503, 'Upload recovery is unavailable.') from None
    if row is None:
        return None
    if row['manuscript_id'] != manuscript.manuscript_id or row['author_id'] != author_id:
        raise HTTPException(409, 'This upload request conflicts with another upload.')
    storage_name = row['storage_name']
    if not storage_name or Path(storage_name).name != storage_name:
        raise HTTPException(409, 'Uploaded file is unavailable.')
    raw_directory = guard_demo_path(BASE_DIR / 'uploads' / 'manuscripts' / str(manuscript.manuscript_id))
    if raw_directory.is_symlink():
        raise HTTPException(409, 'Uploaded file is unavailable.')
    directory = raw_directory.resolve()
    if directory.parent != guard_demo_path(BASE_DIR / 'uploads' / 'manuscripts').resolve():
        raise HTTPException(409, 'Uploaded file is unavailable.')
    path = directory / storage_name
    if path.parent != directory:
        raise HTTPException(409, 'Uploaded file is unavailable.')
    content = read_bounded_source(path, MAX_MANUSCRIPT_FILE_SIZE)
    if len(content) != row['size'] or hashlib.sha256(content).hexdigest() != row['sha256']:
        raise HTTPException(409, 'Uploaded file is unavailable.')
    return {'request_id': str(request_id), 'manuscript_id': manuscript.manuscript_id,
            'original_filename': row['original_filename'], 'size': row['size'],
            'sha256': row['sha256'],
            'is_current': bool(manuscript.file_path and Path(manuscript.file_path).name == storage_name)}


@router.get('/{manuscript_id}/upload-recovery')
def manuscript_upload_recovery_capability(manuscript_id: int, current_user: User = Depends(require_role('author')), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if manuscript is None or manuscript.author_id != current_user.user_id:
        raise HTTPException(404, 'Manuscript not found.')
    try:
        inspector = inspect(db.connection())
        present = inspector.has_table('manuscript_upload_requests')
        submission_present = inspector.has_table('manuscript_submission_requests')
        recorded = inspector.has_table('schema_migrations') and db.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id='045_manuscript_upload_requests'")).first() is not None
        if present != recorded or submission_present != recorded or (recorded and not inspector.has_table('manuscript_upload_names')):
            raise HTTPException(503, 'Upload recovery is unavailable.')
        return JSONResponse({'available': present}, headers={'Cache-Control': 'no-store'})
    except SQLAlchemyError:
        raise HTTPException(503, 'Upload recovery is unavailable.') from None


@router.get('/{manuscript_id}/upload-requests/{request_id}')
def manuscript_upload_receipt(manuscript_id: int, request_id: UUID, current_user: User = Depends(require_role('author')), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if manuscript is None or manuscript.author_id != current_user.user_id:
        raise HTTPException(404, 'Manuscript not found.')
    receipt = _upload_receipt(db, manuscript, current_user.user_id, request_id)
    if receipt is None:
        raise HTTPException(404, 'Upload request not found.')
    return JSONResponse(receipt, headers={'Cache-Control': 'no-store'})


@router.post("/{manuscript_id}/upload", summary="Upload Manuscript File")
def upload_manuscript(
    manuscript_id: int,
    file: UploadFile = File(...),
    request_id: UUID | None = Form(default=None),
    current_user: User = Depends(require_role("author")),
    db: Session = Depends(get_db)
):
    if request_id is not None:
        _begin_author_submission(db)
    # Step 1: Find the manuscript
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found"
        )

    # Step 2: Check ownership
    if manuscript.author_id != current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only upload files to your own manuscripts"
        )

    try:
        original_name = normalize_upload_filename(file.filename)
    except ValueError:
        raise HTTPException(400, 'Choose a file with a valid filename.') from None

    if request_id is not None:
        existing = _upload_receipt(db, manuscript, current_user.user_id, request_id)
        if existing is not None:
            content = file.file.read(MAX_MANUSCRIPT_FILE_SIZE + 1)
            validate_manuscript_file(file.filename, content)
            row = db.execute(text('SELECT sha256 FROM manuscript_upload_requests WHERE request_id=:id'), {'id': str(request_id)}).mappings().one()
            try:
                matching_name = normalize_upload_filename(existing['original_filename']) == original_name
            except ValueError:
                matching_name = False
            if not matching_name or existing['size'] != len(content) or row['sha256'] != hashlib.sha256(content).hexdigest():
                raise HTTPException(409, 'This upload request conflicts with another upload.')
            db.rollback()
            return existing

    from app import sample_documents
    sample = sample_documents.registered(db, manuscript_id)

    # Step 3: PDFs can be changed only before formal submission or while
    # preparing a revision requested by the editor.
    if manuscript.status not in (
            "draft",
            "revision_required",
            "initial_revision_required",
    ):
        raise HTTPException(
            status_code=409,
            detail="File uploads are only allowed for drafts or manuscripts requiring revision"
        )

    # Step 4: Prevent uploading after reviewer assignment in the target round.
    # For a revision, upload the PDF for the *next* review round.
    review_round = (
        get_current_review_round(db, manuscript) + 1
        if manuscript.status == "revision_required"
        else get_current_review_round(db, manuscript)
    )

    existing_assignment = db.scalar(
        select(ReviewAssignment).where(
            ReviewAssignment.manuscript_id == manuscript_id,
            ReviewAssignment.review_round == review_round
        )
    )

    if existing_assignment is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot upload a file after reviewer assignment"
        )


    # Step 5: Read the uploaded document (maximum 10 MB)
    content = file.file.read(MAX_MANUSCRIPT_FILE_SIZE + 1)

    # Step 6: Validate PDF, DOCX, or DOC
    extension, media_type = validate_manuscript_file(
        file.filename,
        content,
    )

    if sample:
        if request_id is not None:
            raise HTTPException(503, 'Upload recovery is unavailable for this manuscript.')
        version = sample_documents.publish(db, manuscript, current_user, review_round, extension, content)
        return {'manuscript_id': manuscript_id, 'version_id': version,
                'filename': version + extension, 'message': 'Manuscript file uploaded successfully'}

    # Each upload gets a unique filename. Older files remain untouched.
    # Existing legacy uploads/paper.pdf files are also preserved.
    upload_dir = guard_demo_path(BASE_DIR / "uploads" / "manuscripts" / str(manuscript_id))
    upload_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    filename = f"round_{review_round}_{timestamp}_{uuid4().hex[:8]}{extension}"

    file_path = upload_dir / filename

    # Write to a temporary file, then atomically publish the completed PDF.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=upload_dir, suffix=".tmp", delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(content)
        os.replace(temp_path, file_path)
    except OSError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not save manuscript file")

    manuscript.file_path = str(file_path.relative_to(BASE_DIR))
    commit_attempted = False
    try:
        # Newer installations may record the original name separately. The
        # ledger is owner-visible only; old versions remain unnamed.
        if (inspect(db.get_bind()).has_table('manuscript_upload_names') and original_name
                and len(original_name) <= 255 and original_name not in ('.', '..')
                and not re.search(r'[\\/\x00-\x1f\x7f]', original_name)):
            db.execute(text('INSERT INTO manuscript_upload_names (manuscript_id, storage_name, original_filename) VALUES (:id, :storage, :original)'), {'id': manuscript_id, 'storage': filename, 'original': original_name})
        if request_id is not None:
            name = original_name
            if not name or len(name) > 255 or name in ('.', '..') or re.search(r'[\\/\x00-\x1f\x7f]', name):
                raise HTTPException(400, 'Choose a file with a valid filename.')
            db.execute(text('INSERT INTO manuscript_upload_requests (request_id, manuscript_id, author_id, storage_name, original_filename, size, sha256) VALUES (:request, :id, :author, :storage, :name, :size, :digest)'), {'request': str(request_id), 'id': manuscript_id, 'author': current_user.user_id, 'storage': filename, 'name': name, 'size': len(content), 'digest': hashlib.sha256(content).hexdigest()})
        commit_attempted = True
        db.commit()
        db.refresh(manuscript)
    except Exception:
        db.rollback()
        # A commit exception may occur after the database committed. Never
        # remove a file once a commit was attempted; reconcile it first.
        if not commit_attempted:
            file_path.unlink(missing_ok=True)
        raise

    return {
        "manuscript_id": manuscript.manuscript_id,
        "filename": filename,
        "file_path": manuscript.file_path,
        "message": "Manuscript file uploaded successfully"
    }



@router.get(
    "/{manuscript_id}/download",
    summary="Download Manuscript File"
)
def download_manuscript(
    manuscript_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db)
):
    if current_user.role == "reviewer":
        raise HTTPException(status_code=403, detail="Use your review assignment to download the assigned file")
    # Step 1: Find the manuscript
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found"
        )

    # Step 2: Check PDF download permission
    if not can_access_manuscript_pdf(db, manuscript, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to download this PDF",
        )

    # Step 3: Check if a PDF has been uploaded
    if manuscript.file_path is None:
        raise HTTPException(
            status_code=404,
            detail="No PDF file has been uploaded for this manuscript"
        )

    from app import sample_documents
    sample = sample_documents.registered(db, manuscript_id)
    if sample:
        row, content = sample_documents.current(db, manuscript)
        if current_user.role == 'editor' and source_may_be_controlled(db, manuscript_id):
            authorize_source(db, current_user, manuscript_id, content)
        return Response(content, media_type=ALLOWED_MANUSCRIPT_EXTENSIONS['.' + row['file_format']],
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'Content-Disposition': f'attachment; filename="manuscript_{manuscript_id}.{row["file_format"]}"'})
    if manuscript.file_path.startswith('sample:v1/'):
        raise HTTPException(404, 'Document unavailable')

    # Step 4: Check if the file exists
    file_path = resolve_manuscript_file_path(manuscript.file_path)

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="PDF file not found on server"
        )


    # Step 5: Return the manuscript in its original format
    extension = file_path.suffix.lower()

    media_type = ALLOWED_MANUSCRIPT_EXTENSIONS.get(extension)

    if media_type is None:
        raise HTTPException(
            status_code=400,
            detail="Unsupported manuscript file format",
        )

    if current_user.role == 'editor' and source_may_be_controlled(db, manuscript_id):
        content = read_bounded_source(file_path, MAX_MANUSCRIPT_FILE_SIZE)
        decision = authorize_source(db, current_user, manuscript_id, content)
        if decision.mode != 'legacy':
            return Response(content, media_type=media_type, headers={
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Content-Disposition': f'attachment; filename="manuscript_{manuscript_id}{extension}"'})

    fallback = f"manuscript_{manuscript_id}{extension}"
    owner_name = _owner_download_name(db, manuscript, current_user, file_path.name)
    return FileResponse(
        path=file_path,
        media_type=media_type,
        headers={'Content-Disposition': content_disposition(owner_name, fallback)} if owner_name else None,
        filename=None if owner_name else fallback,
    )

@router.get('/{manuscript_id}/generation-history')
def author_generation_history(manuscript_id: int, response: Response, current_user: User = Depends(require_role('author')), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if not manuscript or manuscript.author_id != current_user.user_id:
        raise HTTPException(404, 'Manuscript unavailable')
    from app.author_generation_history import generation_history
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return generation_history(db, manuscript)


@router.get('/{manuscript_id}/generation-history/formatting/{submission_id}/download')
def author_generation_formatting_download(manuscript_id: int, submission_id: int,
        current_user: User = Depends(require_role('author')), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if not manuscript or manuscript.author_id != current_user.user_id:
        raise HTTPException(404, 'Document unavailable')
    submission = db.scalar(select(FormattingSubmission).join(FormatterInvitation,
        FormatterInvitation.invitation_id == FormattingSubmission.invitation_id).where(
        FormattingSubmission.submission_id == submission_id,
        FormattingSubmission.manuscript_id == manuscript_id,
        FormatterInvitation.manuscript_id == manuscript_id, FormatterInvitation.status == 'accepted',
        FormattingSubmission.status == 'approved', FormattingSubmission.author_reviewed_at.is_not(None),
        FormattingSubmission.eic_reviewed_at.is_not(None), FormattingSubmission.eic_id.is_not(None)))
    if not submission:
        raise HTTPException(404, 'Document unavailable')
    from app.formatting_artifact_read import read_formatting_artifact
    content, extension = read_formatting_artifact(submission, manuscript_id, BASE_DIR,
        ALLOWED_MANUSCRIPT_EXTENSIONS, MAX_MANUSCRIPT_FILE_SIZE, db=db)
    return Response(content, media_type=ALLOWED_MANUSCRIPT_EXTENSIONS[extension], headers={
        'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
        'Content-Disposition':f'attachment; filename="approved-document{extension}"'})


def read_final_history_file(submission, manuscript_id, base_dir, *, db=None):
    """Bounded read; legacy final-edit records do not contain a trusted digest."""
    try:
        from app import sample_documents
        if db is not None and sample_documents.registered(db, manuscript_id):
            from app import sample_stage_artifacts
            row, content = sample_stage_artifacts.read(db, 'final_editing', submission)
            return content, '.' + row['file_format']
        if isinstance(submission.file_path, str) and submission.file_path.startswith('sample:v1/'):
            raise HTTPException(409, 'Document unavailable')
        path = guard_demo_path(base_dir / submission.file_path)
        root = guard_demo_path(base_dir / 'uploads' / 'final_editing' / str(manuscript_id)).resolve()
        extension = path.suffix.lower()
        if path.parent.resolve() != root or extension not in ALLOWED_MANUSCRIPT_EXTENSIONS:
            raise HTTPException(409, 'Document unavailable')
        content = read_bounded_source(path, MAX_MANUSCRIPT_FILE_SIZE)
    except HTTPException:
        raise
    except (OSError, ValueError, TypeError, RuntimeError):
        raise HTTPException(409, 'Document unavailable') from None
    return content, extension


@router.get('/{manuscript_id}/generation-history/final-editing/{submission_id}/download')
def author_generation_final_download(manuscript_id: int, submission_id: int,
        current_user: User = Depends(require_role('author')), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if not manuscript or manuscript.author_id != current_user.user_id:
        raise HTTPException(404, 'Document unavailable')
    from app.author_generation_history import approved_final_submissions
    submission = next((item for item in approved_final_submissions(db, manuscript_id)
                       if item.submission_id == submission_id), None)
    if submission is None:
        raise HTTPException(404, 'Document unavailable')
    content, extension = read_final_history_file(submission, manuscript_id, BASE_DIR, db=db)
    return Response(content, media_type=ALLOWED_MANUSCRIPT_EXTENSIONS[extension], headers={
        'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
        'Content-Disposition':f'attachment; filename="approved-final-document{extension}"'})


@router.get('/{manuscript_id}/generation-history/submissions/{snapshot_id}/download')
def author_generation_submission_download(manuscript_id: int, snapshot_id: str,
        current_user: User = Depends(require_role('author')), db: Session = Depends(get_db)):
    manuscript = db.get(Manuscript, manuscript_id)
    if not manuscript or manuscript.author_id != current_user.user_id:
        raise HTTPException(404, 'Document unavailable')
    from app.submission_snapshot_history import read_snapshot
    content, extension = read_snapshot(db, manuscript, snapshot_id, BASE_DIR,
        ALLOWED_MANUSCRIPT_EXTENSIONS, MAX_MANUSCRIPT_FILE_SIZE)
    return Response(content, media_type=ALLOWED_MANUSCRIPT_EXTENSIONS[extension], headers={
        'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
        'Content-Disposition':f'attachment; filename="submitted-document{extension}"'})


# List all saved PDF uploads for a manuscript, including legacy paper.pdf.
@router.get("/{manuscript_id}/versions", summary="List Manuscript File Versions")
def list_manuscript_versions(
    manuscript_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db)
):
    if current_user.role == "reviewer":
        raise HTTPException(status_code=403, detail="Reviewers cannot access manuscript version history")
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found"
        )

    if not can_access_manuscript_pdf(db, manuscript, current_user):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view PDF versions"
        )

    from app import sample_documents
    if sample_documents.registered(db, manuscript_id):
        return [{'filename': row['version_id'] + '.' + row['file_format'], 'version_id': row['version_id'],
                 'is_current': manuscript.file_path == row['storage_identity'], 'size_bytes': row['byte_size']}
                for row in sample_documents.versions(db, manuscript_id)]

    upload_dir = guard_demo_path(BASE_DIR / "uploads" / "manuscripts" / str(manuscript_id))
    versions = []
    original_names = {}
    if current_user.role == 'author' and current_user.user_id == manuscript.author_id and inspect(db.get_bind()).has_table('manuscript_upload_names'):
        original_names = dict(db.execute(text('SELECT storage_name, original_filename FROM manuscript_upload_names WHERE manuscript_id=:id'), {'id': manuscript_id}).all())
    if upload_dir.is_dir():

        for path in upload_dir.iterdir():
            guard_demo_path(path)
            if (
                not path.is_file()
                or path.suffix.lower() not in ALLOWED_MANUSCRIPT_EXTENSIONS
            ):
                continue

            versions.append({
                "filename": path.name,
                **({'original_filename': original_names[path.name]} if path.name in original_names else {}),
                "is_current": (
                    manuscript.file_path is not None
                    and resolve_manuscript_file_path(manuscript.file_path).resolve()
                    == path.resolve()
                ),
                "size_bytes": path.stat().st_size
            })

    return sorted(versions, key=lambda item: item["filename"])


@router.get(
    "/{manuscript_id}/versions/{filename}",
    summary="Download Historical Manuscript File"
)
def download_manuscript_version(
    manuscript_id: int,
    filename: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db)
):
    if current_user.role == "reviewer":
        raise HTTPException(status_code=403, detail="Reviewers cannot access manuscript version history")
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found"
        )

    if not can_access_manuscript_pdf(db, manuscript, current_user):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to download this PDF version"
        )

    # Only allow a single basename within this manuscript's upload folder.

    if (
        Path(filename).name != filename
        or Path(filename).suffix.lower() not in ALLOWED_MANUSCRIPT_EXTENSIONS
        or filename in (".", "..")
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid manuscript filename",
        )

    from app import sample_documents
    if sample_documents.registered(db, manuscript_id):
        version = filename.rsplit('.', 1)[0]
        row, content = sample_documents.read_version(db, manuscript_id, version)
        if filename != row['version_id'] + '.' + row['file_format']:
            raise HTTPException(404, 'Document unavailable')
        if current_user.role == 'editor' and source_may_be_controlled(db, manuscript_id):
            authorize_source(db, current_user, manuscript_id, content)
        return Response(content, media_type=ALLOWED_MANUSCRIPT_EXTENSIONS['.' + row['file_format']],
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'Content-Disposition': f'attachment; filename="{filename}"'})


    upload_dir = guard_demo_path(BASE_DIR / "uploads" / "manuscripts" / str(manuscript_id)).resolve()
    file_path = guard_demo_path(upload_dir / filename).resolve()
    if file_path.parent != upload_dir or not file_path.is_file():
        raise HTTPException(status_code=404, detail="PDF version not found")

    if current_user.role == 'editor' and source_may_be_controlled(db, manuscript_id) and (
        (manuscript.file_path and file_path == resolve_manuscript_file_path(manuscript.file_path).resolve())
        or source_path_is_controlled(db, manuscript_id, file_path, BASE_DIR)
    ):
        content = read_bounded_source(file_path, MAX_MANUSCRIPT_FILE_SIZE)
        decision = authorize_source(db, current_user, manuscript_id, content)
        if decision.mode != 'legacy':
            return Response(content, media_type=ALLOWED_MANUSCRIPT_EXTENSIONS[file_path.suffix.lower()], headers={
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Content-Disposition': f'attachment; filename="{filename}"'})

    fallback = f'manuscript_{manuscript_id}{file_path.suffix.lower()}'
    owner_name = _owner_download_name(db, manuscript, current_user, filename)
    return FileResponse(
        path=file_path,
        media_type=ALLOWED_MANUSCRIPT_EXTENSIONS[
            file_path.suffix.lower()
        ],
        headers={'Content-Disposition': content_disposition(owner_name, fallback)} if owner_name else None,
        filename=None if owner_name else filename,
    )


@router.post(
    "/{manuscript_id}/initial-resubmit",
    response_model=ManuscriptResponse,
    summary="Resubmit Manuscript for EIC Initial Scan",
)
def initial_resubmit_manuscript(
    manuscript_id: int,
    update_data: ManuscriptUpdate,
    expected_online_version: str | None = None,
    selected_docx_version: str | None = None,
    current_user: User = Depends(require_role("author")),
    db: Session = Depends(get_db),
):
    _begin_author_submission(db)
    # Find the manuscript.
    manuscript = db.get(Manuscript, manuscript_id)

    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail="Manuscript not found",
        )

    # Only the original author can resubmit.
    if manuscript.author_id != current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only resubmit your own manuscript",
        )
    from app import sample_documents
    sample = sample_documents.registered(db, manuscript_id)

    # Only manuscripts awaiting initial revision are eligible.
    if manuscript.status != "initial_revision_required":
        raise HTTPException(
            status_code=409,
            detail="Manuscript does not require initial revision",
        )
    if sample and (AI_PRESCREENING_ENABLED or selected_docx_version):
        raise HTTPException(503, 'Sample revision with AI or DOCX online drafts is not yet available')
    if sample:
        _validate_sample_online_submission(db, manuscript, current_user, expected_online_version)
    else:
        _validate_author_online_submission(db, manuscript, current_user, expected_online_version)

    if selected_docx_version:
        if expected_online_version: raise HTTPException(409, 'Select one draft only')
        from app.routers.onlyoffice import install_author_draft
        install_author_draft(db, manuscript, current_user, selected_docx_version, get_current_review_round(db, manuscript))

    # Initial revision must happen before peer review.
    existing_assignment = db.scalar(
        select(ReviewAssignment.assignment_id)
        .where(ReviewAssignment.manuscript_id == manuscript_id)
        .limit(1)
    )

    if existing_assignment is not None:
        raise HTTPException(
            status_code=409,
            detail="Peer review has already started",
        )

    # Verify that the author uploaded a new manuscript file after the
    # most recent EIC initial scan.
    from app.models import EICInitialScan

    latest_scan = db.scalar(
        select(EICInitialScan)
        .where(EICInitialScan.manuscript_id == manuscript_id)
        .order_by(
            EICInitialScan.created_at.desc(),
            EICInitialScan.scan_id.desc(),
        )
        .limit(1)
    )

    if latest_scan is None or latest_scan.decision != "revision_required":
        raise HTTPException(
            status_code=409,
            detail="No pending EIC revision request",
        )

    if not manuscript_has_file(manuscript):
        raise HTTPException(
            status_code=409,
            detail="Upload a revised PDF, DOCX, DOC, or TXT file before resubmitting",
        )

    if sample:
        from app.submission_snapshot_history import snapshot_rows
        version, _ = sample_documents.current(db, manuscript)
        prior = snapshot_rows(db, manuscript)
        try:
            uploaded_at = datetime.fromisoformat(version['created_at'])
            scan_at = latest_scan.created_at
            if uploaded_at.tzinfo is None:
                raise ValueError('Missing timezone')
            if scan_at.tzinfo is None:
                scan_at = scan_at.replace(tzinfo=timezone.utc)
            if (uploaded_at <= scan_at or not prior or prior[-1]['file_ref'] == version['storage_identity']
                    or version['review_round'] != get_current_review_round(db, manuscript)):
                raise ValueError('Sample revision is not new')
        except (TypeError, ValueError):
            raise HTTPException(409, 'Upload a new revised manuscript before resubmitting') from None
    else:
        current_file = resolve_manuscript_file_path(manuscript.file_path)

    # Uploaded manuscript files use UTC timestamps in their filenames.
    # The file must belong to this manuscript and be newer
    # than the latest EIC revision request.
    if not sample:
        upload_dir = guard_demo_path(BASE_DIR / "uploads" / "manuscripts" / str(manuscript_id)).resolve()
        if current_file.parent.resolve() != upload_dir:
            raise HTTPException(409, "Upload a revised PDF, DOCX, DOC, or TXT file before resubmitting")
        try:
            timestamp_text = current_file.name.split("_")[2]
            upload_time = datetime.strptime(timestamp_text, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
            scan_time = latest_scan.created_at
            if scan_time.tzinfo is None:
                scan_time = scan_time.replace(tzinfo=timezone.utc)
            if upload_time <= scan_time:
                raise ValueError("Manuscript file predates the EIC revision request")
        except (ValueError, IndexError):
            raise HTTPException(409, "Upload a new revised PDF, DOCX, DOC, or TXT file before resubmitting")

    # Update optional manuscript metadata.
    changes = update_data.model_dump(exclude_unset=True)

    for field, value in changes.items():
        if value is None:
            raise HTTPException(
                status_code=422,
                detail=f"{field} cannot be null",
            )

        setattr(manuscript, field, value)

    # Return to EIC screening without advancing review_round.
    manuscript.status = "submitted"

    # Notify the EIC who requested the revision.
    db.add(
        Notification(
            user_id=latest_scan.eic_id,
            manuscript_id=manuscript_id,
            notification_type="initial_resubmission",
            message=(
                f"Manuscript #{manuscript_id} has been "
                "resubmitted for EIC initial screening."
            ),
        )
    )

    if sample:
        sample_documents.record_submission(db, manuscript, current_user, 'initial_revision', get_current_review_round(db, manuscript))
    else:
        try_create_submission_job(
            db, enabled=AI_PRESCREENING_ENABLED, manuscript_id=manuscript_id,
            submitted_by=current_user.user_id, submission_kind="initial_revision",
            review_round=get_current_review_round(db, manuscript), stored_path=manuscript.file_path,
            resolve_path=resolve_manuscript_file_path,
        )
    db.commit()
    db.refresh(manuscript)

    return manuscript_to_response(manuscript)

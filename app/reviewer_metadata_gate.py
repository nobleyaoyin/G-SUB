"""Internal experimental metadata gate; never enabled by runtime input."""
from enum import Enum
from datetime import datetime
from importlib import import_module
import sqlite3
from pydantic import BaseModel, ConfigDict

from app import blind_policy_store, blind_review_visibility, lifecycle_prototype


class MetadataMode(str, Enum):
    DISABLED = 'disabled'
    EXPERIMENTAL = 'experimental'


def reviewer_metadata_mode() -> MetadataMode:
    # Only an explicit dependency override in an isolated test may enable this.
    return MetadataMode.DISABLED


class MetadataSchemaUnavailable(ValueError):
    pass


class MetadataAccessDenied(ValueError):
    pass


class ReviewerDetailDTO(BaseModel):
    """Reviewer detail allowlist: no unreviewed text or author identity."""
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    manuscript_id: int
    review_round: int


class ReviewerSingleBlindDetailDTO(ReviewerDetailDTO):
    """Single-blind policy permits the author name, never the author ID."""
    author_name: str


class ReviewerProgressStageDTO(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    name: str
    state: str


class ReviewerProgressDTO(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    manuscript_id: int
    status: str
    review_round: int
    current_stage: str | None
    next_action: str
    stages: list[ReviewerProgressStageDTO]


class ReviewerSafeAssignmentDTO(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    assignment_id: int
    manuscript_id: int
    review_round: int
    status: str
    invitation_status: str
    assigned_at: datetime
    manuscript_status: str
    has_pdf: bool
    review_file_available: bool
    review_file_status: str


def reviewer_detail_policy(raw: sqlite3.Connection, manuscript_id: int):
    """Require an explicit, locked and internally consistent review policy."""
    if not isinstance(raw, sqlite3.Connection) or not raw.in_transaction:
        raise MetadataSchemaUnavailable('Reviewer metadata unavailable')
    try:
        policy = blind_policy_store.read_policy(raw, manuscript_id)
    except blind_policy_store.SchemaUnavailable as error:
        raise MetadataSchemaUnavailable('Reviewer metadata unavailable') from error
    except (blind_policy_store.PolicyError, sqlite3.DatabaseError) as error:
        raise MetadataAccessDenied('Manuscript not found') from error
    if not policy or not policy.get('locked_at') or policy.get('mode') not in ('single_blind', 'double_blind'):
        raise MetadataAccessDenied('Manuscript not found')
    return policy['mode']


class ReviewerAssignmentDoubleDTO(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    assignment_id: int
    manuscript_id: int
    review_round: int
    status: str
    invitation_status: str


class ReviewerAssignmentSingleDTO(ReviewerAssignmentDoubleDTO):
    author_id: int


def _security_context(raw: sqlite3.Connection, actor_id: int):
    """Verify schema and reviewer in the caller's explicit SQLite snapshot."""
    lifecycle_schema = import_module('migrations.009_account_invitation_lifecycle')
    try:
        if not isinstance(raw, sqlite3.Connection) or not raw.in_transaction or raw.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise MetadataSchemaUnavailable('Reviewer metadata unavailable')
        if not raw.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(lifecycle_schema.MIGRATION_ID,)).fetchone():
            raise MetadataSchemaUnavailable('Reviewer metadata unavailable')
        lifecycle_schema._validate_own_schema(lifecycle_schema._objects(raw))
        blind_policy_store._schema(raw)
    except (sqlite3.DatabaseError, RuntimeError, blind_policy_store.PolicyError) as error:
        raise MetadataSchemaUnavailable('Reviewer metadata unavailable') from error
    try:
        role=raw.execute('SELECT role FROM users WHERE user_id=?',(actor_id,)).fetchone()
        if not role or role[0]!='reviewer': raise MetadataAccessDenied('Manuscript not found')
        lifecycle=lifecycle_prototype._state(raw,actor_id)
        if lifecycle is None or lifecycle.state!='active': raise MetadataAccessDenied('Manuscript not found')
    except (sqlite3.DatabaseError, lifecycle_prototype.PolicyError) as error:
        raise MetadataAccessDenied('Manuscript not found') from error


def reviewer_metadata_dto(raw: sqlite3.Connection, manuscript_id: int, actor_id: int):
    """Use a single caller-owned snapshot; actor must come from verified auth."""
    _security_context(raw,actor_id)
    try:
        assignment=raw.execute('''SELECT 1 FROM review_assignments a
          JOIN reviewer_invitations i ON i.assignment_id=a.assignment_id
          JOIN manuscripts m ON m.manuscript_id=a.manuscript_id
          WHERE a.manuscript_id=? AND a.reviewer_id=? AND a.review_round=m.review_round
            AND a.status IN ('assigned','completed') AND i.status='accepted'
            AND m.status IN ('ready_for_peer_review','revised')
            AND NOT EXISTS (SELECT 1 FROM reviewer_invitation_invalidations v WHERE v.assignment_id=a.assignment_id)
          LIMIT 1''',(manuscript_id,actor_id)).fetchone()
        if not assignment: raise MetadataAccessDenied('Manuscript not found')
        return blind_review_visibility.reviewer_manuscript_dto(raw,manuscript_id,actor_id)
    except (sqlite3.DatabaseError, blind_review_visibility.VisibilityError) as error:
        raise MetadataAccessDenied('Manuscript not found') from error


def reviewer_assignment_dtos(raw: sqlite3.Connection, actor_id: int):
    """All-or-nothing list; pending invitations expose only neutral identifiers."""
    _security_context(raw,actor_id)
    try:
        rows=raw.execute('''SELECT a.assignment_id,a.manuscript_id,a.review_round,a.status,i.status,m.review_round,m.status,
          EXISTS(SELECT 1 FROM reviewer_invitation_invalidations v WHERE v.assignment_id=a.assignment_id)
          FROM review_assignments a LEFT JOIN reviewer_invitations i ON i.assignment_id=a.assignment_id
          LEFT JOIN manuscripts m ON m.manuscript_id=a.manuscript_id
          WHERE a.reviewer_id=? ORDER BY a.assignment_id''',(actor_id,)).fetchall()
        results=[]
        for aid,mid,rnd,assignment_status,invitation_status,current_round,manuscript_status,invalidated in rows:
            # Completed current-round reviews remain visible without restoring download permission.
            if (type(aid) is not int or type(mid) is not int or type(rnd) is not int or rnd<1 or
                assignment_status not in ('assigned','completed') or invitation_status not in ('accepted','pending') or
                (assignment_status == 'completed' and invitation_status != 'accepted') or rnd!=current_round or
                manuscript_status not in ('ready_for_peer_review','revised') or invalidated):
                raise MetadataAccessDenied('Reviewer assignments unavailable')
            if invitation_status == 'pending':
                policy = blind_policy_store.read_policy(raw, mid)
                if not policy or not policy['locked_at'] or policy['mode'] not in ('single_blind','double_blind'):
                    raise MetadataAccessDenied('Reviewer assignments unavailable')
                results.append(ReviewerAssignmentDoubleDTO(assignment_id=aid, manuscript_id=mid,
                    review_round=rnd, status='assigned', invitation_status='pending').model_dump())
                continue
            manuscript=reviewer_metadata_dto(raw,mid,actor_id)
            values={'assignment_id':aid,'manuscript_id':mid,'review_round':rnd,'status':assignment_status,'invitation_status':'accepted'}
            if isinstance(manuscript,blind_review_visibility.ReviewerSingleBlindDTO):
                # Reviewer-facing assignment metadata must not include author IDs.
                result=ReviewerAssignmentDoubleDTO(**values)
            elif type(manuscript) is blind_review_visibility.ReviewerDoubleBlindDTO:
                result=ReviewerAssignmentDoubleDTO(**values)
            else: raise MetadataAccessDenied('Reviewer assignments unavailable')
            results.append(result.model_dump())
        return results
    except (sqlite3.DatabaseError, blind_review_visibility.VisibilityError, blind_policy_store.PolicyError) as error:
        raise MetadataAccessDenied('Reviewer assignments unavailable') from error

"""Disconnected structured-field visibility prototype; not an authentication boundary.

Callers must obtain actor_id from verified authentication, use the same SQLite
connection within an explicit read transaction, and perform endpoint-specific
authorization. No live route imports this module. Text and files are not scrubbed.
"""
from dataclasses import dataclass
from typing import Literal
import sqlite3

from pydantic import BaseModel, ConfigDict

from app.blind_policy_store import PolicyError, read_policy


class VisibilityError(ValueError):
    """Context is unavailable, inconsistent or unauthorized."""


@dataclass(frozen=True)
class Visibility:
    audience: Literal['author', 'reviewer', 'editor', 'eic', 'formatter']
    mode: Literal['single_blind', 'double_blind', 'legacy']
    can_view_author_identity: bool
    can_view_reviewer_identities: bool
    policy_locked: bool


class ReviewerDoubleBlindDTO(BaseModel):
    """No nested models, free text, participant identities or internal references."""
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    manuscript_id: int
    review_round: int


class ReviewerSingleBlindDTO(ReviewerDoubleBlindDTO):
    author_id: int
    author_name: str


def resolve_visibility(db: sqlite3.Connection, manuscript_id: int, actor_id: int) -> Visibility:
    """Resolve a conservative audience from current DB facts in one read snapshot.

    The caller must already have authenticated actor_id; this is not proof of
    identity. This intentionally narrows legacy reviewer/editor access and is
    not a drop-in replacement for any existing endpoint's authorization.
    """
    if not isinstance(db, sqlite3.Connection) or not db.in_transaction:
        raise VisibilityError('An explicit SQLite read transaction is required')
    if type(manuscript_id) is not int or manuscript_id < 1 or type(actor_id) is not int or actor_id < 1:
        raise VisibilityError('Visibility context unavailable')
    try:
        user = db.execute('SELECT role FROM users WHERE user_id=?', (actor_id,)).fetchone()
        manuscript = db.execute('SELECT author_id,status,review_round FROM manuscripts WHERE manuscript_id=?', (manuscript_id,)).fetchone()
        if not user or not manuscript: raise VisibilityError('Visibility context unavailable')
        role, (author_id, status, current_round) = user[0], manuscript
        if type(current_round) is not int or current_round < 1: raise VisibilityError('Visibility context unavailable')
        audience = None
        if role == 'author' and author_id == actor_id:
            audience = 'author'
        elif status != 'draft' and role == 'eic':
            audience = 'eic'
        elif status != 'draft' and role == 'editor':
            initial = db.execute("SELECT 1 FROM initial_editor_invitations WHERE manuscript_id=? AND editor_id=? AND status='accepted' LIMIT 1", (manuscript_id, actor_id)).fetchone()
            final = db.execute("SELECT 1 FROM final_editor_invitations WHERE manuscript_id=? AND editor_id=? AND status='accepted' LIMIT 1", (manuscript_id, actor_id)).fetchone()
            if initial or final:
                audience = 'editor'
            else:
                formatting = db.execute(
                    "SELECT 1 FROM formatter_invitations WHERE manuscript_id=? AND formatter_id=? AND status='accepted' LIMIT 1",
                    (manuscript_id, actor_id),
                ).fetchone()
                if formatting:
                    audience = 'formatter'
        elif status in ('ready_for_peer_review', 'revised') and role == 'reviewer':
            assigned = db.execute("""SELECT 1 FROM review_assignments a JOIN reviewer_invitations i ON i.assignment_id=a.assignment_id
                WHERE a.manuscript_id=? AND a.reviewer_id=? AND a.review_round=?
                AND a.status IN ('assigned','completed') AND i.status='accepted' LIMIT 1""", (manuscript_id, actor_id, current_round)).fetchone()
            if assigned: audience = 'reviewer'
        elif status != 'draft' and role == 'formatter':
            assigned = db.execute("SELECT 1 FROM formatter_invitations WHERE manuscript_id=? AND formatter_id=? AND status='accepted' LIMIT 1", (manuscript_id, actor_id)).fetchone()
            if assigned: audience = 'formatter'
        if audience is None: raise VisibilityError('Visibility context unavailable')
        policy = read_policy(db, manuscript_id)
        mode = policy['mode'] if policy else 'legacy'
        if mode not in ('single_blind', 'double_blind', 'legacy'): raise VisibilityError('Visibility context unavailable')
        return Visibility(
            audience=audience, mode=mode,
            can_view_author_identity=audience in ('author', 'editor', 'eic') or (audience == 'reviewer' and mode == 'single_blind'),
            can_view_reviewer_identities=audience in ('editor', 'eic'),
            policy_locked=bool(policy and policy['locked_at']),
        )
    except (sqlite3.DatabaseError, PolicyError) as error:
        raise VisibilityError('Visibility context unavailable') from error


def reviewer_manuscript_dto(db: sqlite3.Connection, manuscript_id: int, actor_id: int) -> ReviewerSingleBlindDTO | ReviewerDoubleBlindDTO:
    """Build only explicit-mode, locked, currently authorized reviewer data."""
    visibility = resolve_visibility(db, manuscript_id, actor_id)
    if visibility.audience != 'reviewer' or visibility.mode == 'legacy' or not visibility.policy_locked:
        raise VisibilityError('Reviewer view unavailable')
    row = db.execute('SELECT author_id,review_round FROM manuscripts WHERE manuscript_id=?', (manuscript_id,)).fetchone()
    if not row or type(row[0]) is not int or type(row[1]) is not int or row[1] < 1:
        raise VisibilityError('Reviewer view unavailable')
    if visibility.mode == 'single_blind':
        author = db.execute('SELECT name FROM users WHERE user_id=? AND role=\'author\'', (row[0],)).fetchone()
        if not author or not isinstance(author[0], str) or not author[0].strip():
            raise VisibilityError('Reviewer view unavailable')
        return ReviewerSingleBlindDTO(manuscript_id=manuscript_id, review_round=row[1], author_id=row[0], author_name=author[0])
    return ReviewerDoubleBlindDTO(manuscript_id=manuscript_id, review_round=row[1])

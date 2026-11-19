"""Transaction-bound reviewer artifact authorities for Main.

Construct only from the authenticated User supplied by the server's existing
request dependency. These authorities do not provide proof or release files.
"""
import sqlite3

from sqlalchemy.orm import object_session

from app import lifecycle_prototype
from app.models import User


class AuthorityUnavailable(ValueError):
    """The authenticated actor or requested scope could not be verified."""


class _RequestAuthority:
    role = None
    action = None

    def __init__(self, authenticated_user):
        if not isinstance(authenticated_user, User) or object_session(authenticated_user) is None:
            raise AuthorityUnavailable('Authenticated request required')
        self._principal = authenticated_user
        self._session = object_session(authenticated_user)

    def authorize(self, db, principal, action, manuscript_id, *, prepared_by=None):
        try:
            if (principal is not self._principal or object_session(principal) is not self._session
                or action != self.action or type(manuscript_id) is not int or manuscript_id < 1
                or self._session.new or self._session.dirty or self._session.deleted
                or not db.in_transaction):
                raise AuthorityUnavailable('Authority unavailable')
            connection = self._session.connection()
            if connection.dialect.name != 'sqlite' or connection.connection.driver_connection is not db:
                raise AuthorityUnavailable('Authority unavailable')
            actor_id = principal.user_id
            if type(actor_id) is not int or actor_id < 1:
                raise AuthorityUnavailable('Authority unavailable')
            role = db.execute('SELECT role FROM users WHERE user_id=?', (actor_id,)).fetchone()
            state = lifecycle_prototype._state(db, actor_id)
            if role != (self.role,) or state is None or state.state != 'active':
                raise AuthorityUnavailable('Authority unavailable')
            if not self._scope(db, actor_id, manuscript_id):
                raise AuthorityUnavailable('Authority unavailable')
            return actor_id
        except (sqlite3.Error, lifecycle_prototype.PolicyError, ValueError, TypeError):
            raise AuthorityUnavailable('Authority unavailable') from None


class AuthenticatedReviewerAuthority(_RequestAuthority):
    role = 'reviewer'
    action = 'read_artifact'

    def _scope(self, db, actor_id, manuscript_id):
        return db.execute('''SELECT 1 FROM review_assignments a
            JOIN manuscripts m ON m.manuscript_id=a.manuscript_id
            JOIN reviewer_invitations i ON i.assignment_id=a.assignment_id
            WHERE a.reviewer_id=? AND a.manuscript_id=? AND a.status='assigned'
              AND i.status='accepted' AND a.review_round=m.review_round
              AND m.status IN ('ready_for_peer_review','revised')
              AND NOT EXISTS (SELECT 1 FROM reviewer_invitation_invalidations v
                              WHERE v.assignment_id=a.assignment_id) LIMIT 1''',
            (actor_id, manuscript_id)).fetchone() is not None


class AuthenticatedEditorialAuthority(_RequestAuthority):
    role = 'eic'
    action = 'bind'

    def _scope(self, db, actor_id, manuscript_id):
        # Existing Main EIC source scope excludes drafts; actor is rechecked above.
        return db.execute("SELECT 1 FROM manuscripts WHERE manuscript_id=? AND status!='draft'",
                          (manuscript_id,)).fetchone() is not None

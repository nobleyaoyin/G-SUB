"""Non-routed source scope check; never a durable authorization capability.

An eventual source operation must perform authentication and this scope check
in its own transaction. No source write or artifact release is provided here.
"""
from fastapi import HTTPException
from sqlalchemy import select

from app.models import InitialEditorInvitation, Manuscript, User
from app.routers.users import get_current_user


def authorize_source_scope(db, credentials, manuscript_id):
    """Authenticate bearer credentials, then check persisted role and scope.

    `credentials` must come from the server bearer dependency, never an actor
    or role field. The returned ORM user is not an unforgeable authorization
    token; consumers must reauthenticate/recheck in their own operation.
    """
    if type(manuscript_id) is not int or manuscript_id < 1:
        raise HTTPException(404, 'Manuscript unavailable')
    if db.new or db.dirty or db.deleted:
        raise HTTPException(503, 'Clean session required')
    actor = get_current_user(credentials, db)
    actor = db.get(User, actor.user_id, populate_existing=True)
    if actor is None:
        raise HTTPException(403, 'Source access denied')
    if actor.role not in ('eic', 'editor'):
        raise HTTPException(403, 'Source access denied')
    manuscript = db.get(Manuscript, manuscript_id, populate_existing=True)
    if manuscript is None or manuscript.status == 'draft':
        raise HTTPException(404, 'Manuscript unavailable')
    if actor.role == 'editor':
        assigned = db.scalar(select(InitialEditorInvitation.invitation_id).where(
            InitialEditorInvitation.manuscript_id == manuscript_id,
            InitialEditorInvitation.editor_id == actor.user_id,
            InitialEditorInvitation.status == 'accepted').limit(1))
        if assigned is None:
            raise HTTPException(403, 'Source access denied')
    return actor

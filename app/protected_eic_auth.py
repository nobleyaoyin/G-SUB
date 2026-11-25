"""Generation-bound authentication for already protected EIC artifacts."""
from fastapi import HTTPException
from app.lifecycle_integrity import active_actor, LifecycleIntegrityError
from app.routers.users import get_current_user
from app.security import decode_lifecycle_generation


def require_current_eic(raw, db, credentials, expected_id):
    """Reauthenticate and compare the token against the current validated chain."""
    user = get_current_user(credentials, db)
    try:
        if user.user_id != expected_id or user.role != 'eic' or credentials is None:
            raise ValueError('EIC unavailable')
        generation = decode_lifecycle_generation(credentials.credentials, user.user_id)
        if generation is None or generation != active_actor(raw, user.user_id, 'eic'):
            raise ValueError('Session unavailable')
    except (LifecycleIntegrityError, ValueError):
        raise HTTPException(403, 'EIC proof authority unavailable') from None
    return user

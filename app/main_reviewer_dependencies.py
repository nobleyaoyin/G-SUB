"""Authenticated request dependencies for Main's reviewer authorities.

These dependencies do not provide artifact proof, storage or release access.
Consumers must call authorize in the same transaction as their operation.
"""
from typing import Annotated

from fastapi import Depends

from app.main_reviewer_authority import (
    AuthenticatedEditorialAuthority,
    AuthenticatedReviewerAuthority,
)
from app.models import User
from app.routers.users import require_role


async def reviewer_authority(
    principal: Annotated[User, Depends(require_role('reviewer'))],
) -> AuthenticatedReviewerAuthority:
    return AuthenticatedReviewerAuthority(principal)


async def editorial_authority(
    principal: Annotated[User, Depends(require_role('eic'))],
) -> AuthenticatedEditorialAuthority:
    return AuthenticatedEditorialAuthority(principal)

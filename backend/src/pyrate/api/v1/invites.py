"""API endpoints for invite management"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ...api.dependencies import CurrentSuperuser, DatabaseSession
from ...api.rate_limit import rate_limit
from ...auth.dependencies import get_current_user
from ...auth.jwt_handler import jwt_handler
from ...config import settings
from ...models.user import User
from ...schemas.invite import (
    InviteCreate,
    InviteResponse,
    InviteUpdate,
    InviteValidation,
    PaginatedInviteListResponse,
)
from ...services.invite import InviteService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    invite_create: InviteCreate,
    db: DatabaseSession,
    current_user: User = Depends(get_current_user),
):
    """Create a new invite code"""

    if not settings.invites.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invite system is disabled"
        )

    # Check if user is allowed to create invites
    if settings.invites.require_admin_creation and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can create invites",
        )

    try:
        invite = await InviteService(db).create_invite_with_token(
            invite_create=invite_create,
            created_by_user_id=current_user.guid,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    logger.info("User %s created invite %s", current_user.guid, invite.guid)
    return invite


@router.get("", response_model=PaginatedInviteListResponse)
async def list_invites(
    db: DatabaseSession,
    page: int = 1,
    size: int = 100,
    include_expired: bool = False,
    current_user: User = Depends(get_current_user),
):
    """List invites created by current user"""

    if not settings.invites.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invite system is disabled"
        )

    skip = (page - 1) * size

    # Superusers can see all invites, regular users only their own
    if current_user.is_superuser:
        invites, total = await InviteService(db).get_all_paginated(
            skip=skip, limit=size, include_expired=include_expired
        )
    else:
        invites, total = await InviteService(db).get_by_user_paginated(
            user_id=current_user.guid, skip=skip, limit=size
        )

    return PaginatedInviteListResponse(
        items=invites,
        total=total,
        page=page,
        size=size,
    )


@router.get("/{invite_id}", response_model=InviteResponse)
async def get_invite(
    invite_id: UUID, db: DatabaseSession, current_user: User = Depends(get_current_user)
):
    """Get a specific invite by ID"""

    if not settings.invites.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invite system is disabled"
        )

    invite = await InviteService(db).get_by_id(invite_id=invite_id)

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found"
        )

    # Check permissions: owner or superuser
    if invite.created_by_user_id != current_user.guid and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    return invite


@router.put("/{invite_id}", response_model=InviteResponse)
async def update_invite(
    invite_id: UUID,
    invite_update: InviteUpdate,
    db: DatabaseSession,
    current_user: User = Depends(get_current_user),
):
    """Update an invite"""

    if not settings.invites.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invite system is disabled"
        )

    invite = await InviteService(db).get_by_id(invite_id=invite_id)

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found"
        )

    # Check permissions: owner or superuser
    if invite.created_by_user_id != current_user.guid and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    updated_invite = await InviteService(db).update(
        invite_id=invite_id, invite_update=invite_update
    )

    return updated_invite


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invite(
    invite_id: UUID, db: DatabaseSession, current_user: User = Depends(get_current_user)
):
    """Delete an invite"""

    if not settings.invites.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invite system is disabled"
        )

    invite = await InviteService(db).get_by_id(invite_id=invite_id)

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found"
        )

    # Check permissions: owner or superuser
    if invite.created_by_user_id != current_user.guid and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    success = await InviteService(db).delete(invite_id=invite_id)
    logger.info("User %s deleted invite %s", current_user.guid, invite_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete invite",
        )


@router.post(
    "/validate",
    status_code=status.HTTP_200_OK,
    dependencies=[
        # Public endpoint → tight per-IP limit so someone can't brute-force
        # invite tokens. 20/min is generous for legitimate retries.
        Depends(rate_limit(max_calls=20, window_seconds=60, scope="invite_validate")),
    ],
)
async def validate_invite(invite_validation: InviteValidation, db: DatabaseSession):
    """Validate an invite token (public endpoint)"""

    if not settings.invites.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invite system is disabled"
        )

    # Verify the JWT token
    invite_data = jwt_handler.verify_invite_token(invite_validation.token)
    if not invite_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid invite token"
        )

    # Check if invite exists and is valid
    invite = await InviteService(db).get_valid_by_token(token=invite_validation.token)

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite token is invalid, expired, or already used",
        )

    return {
        "valid": True,
        "expires_at": invite.expires_at,
        "created_by": {
            "first_name": invite.created_by.first_name,
            "last_name": invite.created_by.last_name,
        }
        if invite.created_by
        else None,
    }


@router.post("/cleanup", status_code=status.HTTP_200_OK)
async def cleanup_expired_invites(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    """Cleanup expired invites (admin only)"""
    cleaned_count = await InviteService(db).cleanup_expired()

    return {"message": f"Cleaned up {cleaned_count} expired invites"}

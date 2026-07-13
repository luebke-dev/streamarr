"""Banner API endpoints."""

import logging
import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from streamarr.api.dependencies import CurrentSuperuser, DatabaseSession, get_current_user
from streamarr.models.user import User
from streamarr.schemas.banner import (
    BannerCreate,
    BannerListResponse,
    BannerRead,
    BannerUpdate,
)
from streamarr.services.banner import BannerService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["banners"])


@router.get("", response_model=BannerListResponse)
async def get_banners(
    db: DatabaseSession,
    current_user: Annotated[User, Depends(get_current_user)],
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    is_active: bool | None = Query(None),
    show_dismissed: bool = Query(False, description="Show dismissed banners"),
):
    """
    Get all banners with pagination.
    Regular users only see active banners they haven't dismissed.
    Superusers can see all banners and filter by active status.
    """
    banner_service = BannerService(db)

    if current_user.is_superuser:
        # Admins see all banners
        banners, total = await banner_service.get_all_banners(
            page=page, per_page=per_page, is_active=is_active
        )
    else:
        # Regular users only see active banners
        if show_dismissed:
            # User requested to see all their banners including dismissed ones
            banners, total = await banner_service.get_all_banners(
                page=page, per_page=per_page, is_active=True
            )
        else:
            # Default: only show non-dismissed active banners
            banners, total = await banner_service.get_active_banners(
                user_guid=current_user.guid, page=page, per_page=per_page
            )

    dismissed_guids = await banner_service.get_dismissed_banner_guids(
        [banner.guid for banner in banners], current_user.guid
    )
    banner_reads = []
    for banner in banners:
        banner_read = BannerRead.model_validate(banner)
        banner_read.is_dismissed = banner.guid in dismissed_guids
        banner_reads.append(banner_read)

    total_pages = math.ceil(total / per_page) if total > 0 else 1

    return BannerListResponse(
        items=banner_reads,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get("/active", response_model=list[BannerRead])
async def get_active_banners(
    db: DatabaseSession,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Get all active banners for the current user (excluding dismissed ones)."""
    banner_service = BannerService(db)
    banners, _ = await banner_service.get_active_banners(user_guid=current_user.guid)

    # Convert to BannerRead with is_dismissed flag
    banner_reads = []
    for banner in banners:
        banner_read = BannerRead.model_validate(banner)
        banner_read.is_dismissed = False  # These are non-dismissed banners
        banner_reads.append(banner_read)

    return banner_reads


@router.get("/{banner_guid}", response_model=BannerRead)
async def get_banner(
    banner_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Get a specific banner by GUID."""
    banner_service = BannerService(db)
    banner = await banner_service.get_banner(banner_guid)

    if not banner:
        raise HTTPException(status_code=404, detail="Banner not found")

    # Check if dismissed by current user
    is_dismissed = await banner_service.is_banner_dismissed(
        banner.guid, current_user.guid
    )

    banner_read = BannerRead.model_validate(banner)
    banner_read.is_dismissed = is_dismissed
    return banner_read


@router.post("", response_model=BannerRead, status_code=201)
async def create_banner(
    banner_data: BannerCreate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Create a new banner (superuser only)."""
    banner_service = BannerService(db)
    banner = await banner_service.create_banner(banner_data, current_user.guid)

    banner_read = BannerRead.model_validate(banner)
    banner_read.is_dismissed = False
    logger.info("Admin %s created banner %s", current_user.guid, banner.guid)
    return banner_read


@router.put("/{banner_guid}", response_model=BannerRead)
async def update_banner(
    banner_guid: uuid.UUID,
    banner_data: BannerUpdate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Update a banner (superuser only)."""
    banner_service = BannerService(db)
    banner = await banner_service.update_banner(banner_guid, banner_data)

    if not banner:
        raise HTTPException(status_code=404, detail="Banner not found")

    is_dismissed = await banner_service.is_banner_dismissed(
        banner.guid, current_user.guid
    )

    banner_read = BannerRead.model_validate(banner)
    banner_read.is_dismissed = is_dismissed
    logger.info("Admin %s updated banner %s", current_user.guid, banner_guid)
    return banner_read


@router.delete("/{banner_guid}", status_code=204)
async def delete_banner(
    banner_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Delete a banner (superuser only)."""
    banner_service = BannerService(db)
    success = await banner_service.delete_banner(banner_guid)

    if not success:
        raise HTTPException(status_code=404, detail="Banner not found")
    logger.info("Admin %s deleted banner %s", current_user.guid, banner_guid)


@router.post("/{banner_guid}/dismiss", status_code=204)
async def dismiss_banner(
    banner_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Dismiss a banner for the current user."""
    banner_service = BannerService(db)

    # Check if banner exists
    banner = await banner_service.get_banner(banner_guid)
    if not banner:
        raise HTTPException(status_code=404, detail="Banner not found")

    await banner_service.dismiss_banner(banner_guid, current_user.guid)
    logger.info("User %s dismissed banner %s", current_user.guid, banner_guid)

"""Central media access policy helpers.

Routers should call these helpers instead of open-coding library and
parental-control checks. They intentionally stay small and dependency-free so
they can be reused from API handlers, services, and tests.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import MediaItem, MediaType
from streamarr.models.user import User
from streamarr.schemas.group import EffectivePermissions
from streamarr.services.permission import MEDIA_TYPE_TO_LIBRARY
from streamarr.utils.age_rating import is_allowed


def _media_type_value(media_type: MediaType | str | None) -> str | None:
    if media_type is None:
        return None
    return media_type.value if hasattr(media_type, "value") else str(media_type)


def library_for_media_type(media_type: MediaType | str | None) -> str | None:
    """Return the permission library key for a media type."""
    media_type_value = _media_type_value(media_type)
    if media_type_value is None:
        return None
    return MEDIA_TYPE_TO_LIBRARY.get(media_type_value.upper())


def max_age_for_user(user: User) -> int | None:
    """Return the effective parental gate for read/play queries."""
    return None if user.is_superuser else user.parental_max_age


def allowed_media_types_for_permissions(
    user: User,
    permissions: EffectivePermissions,
) -> list[MediaType] | None:
    """Return media types visible to the user.

    ``None`` means unrestricted. Superusers bypass per-user library filtering;
    disabled-library filtering still belongs to the data service.
    """
    if user.is_superuser:
        return None
    allowed_libraries = set(permissions.allowed_libraries)
    return [
        media_type
        for media_type in MediaType
        if library_for_media_type(media_type) in allowed_libraries
    ]


def can_access_library(
    user: User,
    permissions: EffectivePermissions,
    media_type: MediaType | str | None,
) -> bool:
    """Return whether the user can access the library for a media type."""
    if user.is_superuser:
        return True
    library_name = library_for_media_type(media_type)
    return library_name is None or library_name in permissions.allowed_libraries


def can_read_media(
    user: User,
    permissions: EffectivePermissions,
    media_item: MediaItem,
) -> bool:
    """Return whether a user may see a media item."""
    return can_access_library(user, permissions, media_item.media_type) and is_allowed(
        media_item.min_age,
        max_age_for_user(user),
    )


def can_mutate_media(user: User, _media_item: MediaItem | None = None) -> bool:
    """Return whether a user may mutate global media/library data."""
    return user.is_superuser


def require_media_mutation_access(
    user: User,
    media_item: MediaItem | None = None,
) -> None:
    """Raise 403 when a user may not mutate global media/library data."""
    if can_mutate_media(user, media_item):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Media mutation requires administrator privileges",
    )


def require_library_access_for_media_type(
    user: User,
    permissions: EffectivePermissions,
    media_type: MediaType | str | None,
) -> None:
    """Raise 403 when a user cannot access the library for a media type."""
    if can_access_library(user, permissions, media_type):
        return
    library_name = library_for_media_type(media_type) or "media"
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Access denied to {library_name} library",
    )


def require_library_access(
    user: User,
    permissions: EffectivePermissions,
    library_name: str | None,
) -> None:
    """Raise 403 when a user cannot access a library by its permission key.

    Use this when the caller already resolved a library key (e.g. from a search
    type) rather than from a media type. Superusers bypass the check.
    """
    if user.is_superuser or library_name is None or library_name in permissions.allowed_libraries:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Access denied to {library_name} library",
    )


def require_media_read_access(
    user: User,
    permissions: EffectivePermissions,
    media_item: MediaItem,
    *,
    hide_age_denials: bool = False,
) -> None:
    """Raise when a user may not read a media item."""
    require_library_access_for_media_type(user, permissions, media_item.media_type)
    if is_allowed(media_item.min_age, max_age_for_user(user)):
        return
    if hide_age_denials:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media item not found",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Blocked by parental control",
    )


def require_media_play_access(
    user: User,
    permissions: EffectivePermissions,
    media_item: MediaItem,
) -> None:
    """Raise when a user may not play a media item."""
    require_media_read_access(user, permissions, media_item)


def require_media_offline_access(
    user: User,
    permissions: EffectivePermissions,
    media_item: MediaItem,
) -> None:
    """Raise when a user may not request an offline copy of a media item."""
    require_media_read_access(user, permissions, media_item)


async def get_visible_media_item(
    db: AsyncSession,
    item_guid: uuid.UUID,
    user: User,
    permissions: EffectivePermissions,
    *,
    hide_age_denials: bool = True,
) -> MediaItem:
    """Fetch a media item and enforce read access, or raise 404/403.

    Single source of truth for the ``fetch + require_media_read_access`` gate
    that every per-item media sub-router needs. Routers should call this instead
    of re-deriving the check so a change to visibility rules applies everywhere.
    """
    media_item = await db.get(MediaItem, item_guid)
    if media_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media item not found",
        )
    require_media_read_access(
        user,
        permissions,
        media_item,
        hide_age_denials=hide_age_denials,
    )
    return media_item

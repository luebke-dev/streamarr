"""Shared media-visibility query helpers (library + parental-age gate).

These build the ``MediaItem`` filter conditions that enforce the same
library-access and ``parental_max_age`` rules the search and suggestion
endpoints apply. They live in a service module so the suggestions router and
the page-layout renderer share one implementation instead of the renderer
reaching into the router's private helpers — the layering gap that let the
list/trending/favorite rows skip the gate.
"""

from __future__ import annotations

from sqlalchemy import or_

from pyrate.models.media import MediaItem, MediaType
from pyrate.services.media_access import (
    allowed_media_types_for_permissions,
    max_age_for_user,
    require_library_access_for_media_type,
)


def allowed_media_types(
    current_user,
    permissions,
    requested_type: MediaType | None = None,
) -> list[MediaType]:
    """Media types the user may see; raises 403 for an explicit denied type."""
    if requested_type:
        require_library_access_for_media_type(current_user, permissions, requested_type)
        return [requested_type]

    allowed = allowed_media_types_for_permissions(current_user, permissions)
    return list(MediaType) if allowed is None else allowed


def visibility_conditions(current_user, permissions, media_type: MediaType | None):
    """SQLAlchemy conditions gating ``MediaItem`` by library + parental age."""
    conditions = [
        MediaItem.media_type.in_(
            allowed_media_types(current_user, permissions, media_type)
        )
    ]
    max_age = max_age_for_user(current_user)
    if max_age is not None:
        conditions.append(
            or_(
                MediaItem.min_age.is_(None),
                MediaItem.min_age <= max_age,
            )
        )
    return conditions

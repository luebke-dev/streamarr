"""Discoverable item filter values."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from pyrate.api.dependencies import CurrentUser, DatabaseSession, UserPermissionsDep
from pyrate.models.media import MediaItem, MediaType
from pyrate.services.filter import FilterService
from pyrate.services.permission import MEDIA_TYPE_TO_LIBRARY
from pyrate.utils.age_rating import age_filter_clause

router = APIRouter()


class FilterOption(BaseModel):
    id: int | str
    name: str


class FiltersResponse(BaseModel):
    media_types: list[str]
    genres: list[FilterOption]
    platforms: list[FilterOption]
    persons: list[FilterOption]
    years: list[int]
    studios: list[str]
    containers: list[str]
    content_ratings: list[str]


def _visible_media_types(current_user, permissions) -> list[MediaType]:
    if current_user.is_superuser:
        return list(MediaType)
    allowed = set(permissions.allowed_libraries)
    return [
        media_type
        for media_type in MediaType
        if MEDIA_TYPE_TO_LIBRARY.get(media_type.value) in allowed
    ]


@router.get("", response_model=FiltersResponse)
async def get_filters(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
):
    """Return filter options visible to the current user."""
    media_types = _visible_media_types(current_user, permissions)
    conditions = [MediaItem.media_type.in_(media_types)]
    if not current_user.is_superuser and current_user.parental_max_age is not None:
        conditions.append(age_filter_clause(current_user.parental_max_age))

    service = FilterService(db)
    return FiltersResponse(
        media_types=[media_type.value for media_type in media_types],
        genres=[
            FilterOption(id=i, name=n) for i, n in await service.genre_options(conditions)
        ],
        platforms=[
            FilterOption(id=i, name=n)
            for i, n in await service.platform_options(conditions)
        ],
        persons=[
            FilterOption(id=i, name=n) for i, n in await service.person_options(conditions)
        ],
        years=await service.years(conditions),
        studios=await service.studios(conditions),
        containers=await service.containers(conditions),
        content_ratings=await service.content_ratings(conditions),
    )

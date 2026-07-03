"""Discoverable item filter values."""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import distinct, extract, select

from pyrate.api.dependencies import CurrentUser, DatabaseSession, UserPermissionsDep
from pyrate.models.genre import Genre
from pyrate.models.media import (
    MediaFile,
    MediaItem,
    MediaType,
    media_genre_table,
    media_platform_table,
)
from pyrate.models.person import MediaCast, Person
from pyrate.models.platform import Platform
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


def _extract_studio_names(extra_data: str | dict | None) -> set[str]:
    if not extra_data:
        return set()
    if isinstance(extra_data, dict):
        data = extra_data
    else:
        try:
            data = json.loads(extra_data)
        except (TypeError, ValueError):
            return set()
    if not isinstance(data, dict):
        return set()

    raw_values = []
    for key in ("studio", "studios", "production_company", "production_companies"):
        value = data.get(key)
        if value:
            raw_values.append(value)

    names: set[str] = set()
    for value in raw_values:
        if isinstance(value, str):
            names.update(part.strip() for part in value.split(",") if part.strip())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    names.add(item.strip())
                elif isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name.strip():
                        names.add(name.strip())
    return names


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

    genre_rows = await db.execute(
        select(Genre.id, Genre.name)
        .join(media_genre_table, Genre.id == media_genre_table.c.genre_id)
        .join(MediaItem, MediaItem.guid == media_genre_table.c.media_item_guid)
        .where(*conditions)
        .group_by(Genre.id, Genre.name)
        .order_by(Genre.name)
    )
    platform_rows = await db.execute(
        select(Platform.id, Platform.name)
        .join(media_platform_table, Platform.id == media_platform_table.c.platform_id)
        .join(MediaItem, MediaItem.guid == media_platform_table.c.media_item_guid)
        .where(*conditions)
        .group_by(Platform.id, Platform.name)
        .order_by(Platform.name)
    )
    person_rows = await db.execute(
        select(Person.guid, Person.name)
        .join(MediaCast, MediaCast.person_guid == Person.guid)
        .join(MediaItem, MediaItem.guid == MediaCast.media_item_guid)
        .where(*conditions)
        .group_by(Person.guid, Person.name)
        .order_by(Person.name)
    )
    year_rows = await db.execute(
        select(distinct(extract("year", MediaItem.release_date)))
        .where(*conditions, MediaItem.release_date.isnot(None))
        .order_by(extract("year", MediaItem.release_date).desc())
    )
    rating_rows = await db.execute(
        select(distinct(MediaItem.content_rating))
        .where(*conditions, MediaItem.content_rating.isnot(None), MediaItem.content_rating != "")
        .order_by(MediaItem.content_rating.asc())
    )
    studio_rows = await db.execute(
        select(MediaItem.extra_data).where(*conditions, MediaItem.extra_data.isnot(None))
    )
    container_rows = await db.execute(
        select(distinct(MediaFile.format))
        .join(MediaItem, MediaItem.guid == MediaFile.media_item_guid)
        .where(*conditions, MediaFile.format.isnot(None), MediaFile.format != "")
        .order_by(MediaFile.format.asc())
    )
    studios = sorted(
        {
            studio_name
            for row in studio_rows.all()
            for studio_name in _extract_studio_names(row[0])
        },
        key=str.casefold,
    )

    return FiltersResponse(
        media_types=[media_type.value for media_type in media_types],
        genres=[FilterOption(id=row.id, name=row.name) for row in genre_rows.all()],
        platforms=[FilterOption(id=row.id, name=row.name) for row in platform_rows.all()],
        persons=[FilterOption(id=str(row.guid), name=row.name) for row in person_rows.all()],
        years=[int(row[0]) for row in year_rows.all() if row[0] is not None],
        studios=studios,
        containers=[row[0] for row in container_rows.all() if row[0]],
        content_ratings=[row[0] for row in rating_rows.all() if row[0]],
    )

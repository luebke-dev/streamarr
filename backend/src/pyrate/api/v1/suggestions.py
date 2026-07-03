"""Suggestion and instant-mix endpoints."""

import json
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import selectinload

from pyrate.api.dependencies import CurrentUser, DatabaseSession, UserPermissionsDep
from pyrate.models.genre import Genre
from pyrate.models.list import List, ListItem, ListType
from pyrate.models.media import MediaItem, MediaType, media_genre_table
from pyrate.models.person import MediaCast, Person
from pyrate.models.viewing_history import ViewingHistory
from pyrate.schemas.media import MediaItemSummary
from pyrate.services.permission import MEDIA_TYPE_TO_LIBRARY

router = APIRouter()


class SuggestionsResponse(BaseModel):
    """Suggested media items for a user."""

    items: list[MediaItemSummary]
    total: int
    reason: str


class InstantMixResponse(BaseModel):
    """Anchor-based instant mix queue."""

    seed_guid: uuid.UUID
    items: list[MediaItemSummary]
    total: int
    reason: str


class AutocompleteResponse(BaseModel):
    """Search-term autocomplete suggestions."""

    query: str
    items: list[MediaItemSummary]
    total: int


class LatestItemsResponse(BaseModel):
    """Latest visible media items for a user."""

    items: list[MediaItemSummary]
    total: int


class TypedAutocompleteItem(BaseModel):
    """One typed autocomplete suggestion across search domains."""

    type: Literal["media", "genre", "person", "studio", "year"]
    label: str
    value: str
    media_type: str | None = None
    item: MediaItemSummary | None = None
    count: int | None = None


class TypedAutocompleteResponse(BaseModel):
    """Typed autocomplete suggestions across media, genres, people, studios, and years."""

    query: str
    items: list[TypedAutocompleteItem]
    total: int


def _allowed_media_types(
    current_user,
    permissions,
    requested_type: MediaType | None = None,
) -> list[MediaType]:
    if requested_type:
        library_name = MEDIA_TYPE_TO_LIBRARY.get(requested_type.value)
        if (
            not current_user.is_superuser
            and library_name
            and library_name not in permissions.allowed_libraries
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Access denied to {library_name} library",
            )
        return [requested_type]

    if current_user.is_superuser:
        return list(MediaType)

    return [
        media_type
        for media_type in MediaType
        if MEDIA_TYPE_TO_LIBRARY.get(media_type.value) in permissions.allowed_libraries
    ]


def _visibility_conditions(current_user, permissions, media_type: MediaType | None):
    conditions = [MediaItem.media_type.in_(_allowed_media_types(current_user, permissions, media_type))]
    if not current_user.is_superuser and current_user.parental_max_age is not None:
        conditions.append(
            or_(
                MediaItem.min_age.is_(None),
                MediaItem.min_age <= current_user.parental_max_age,
            )
        )
    return conditions


async def _summaries(
    db: DatabaseSession,
    items: list[MediaItem],
    user_language: str | None,
) -> list[MediaItemSummary]:
    summaries = [MediaItemSummary.model_validate(item) for item in items]
    from pyrate.services.translation import TranslationService

    await TranslationService(db).apply_translations(summaries, user_language)
    return summaries


async def _user_seed_genre_ids(db: DatabaseSession, user_guid: uuid.UUID) -> list[int]:
    favorite_genres = (
        select(media_genre_table.c.genre_id)
        .join(ListItem, ListItem.item_guid == media_genre_table.c.media_item_guid)
        .join(List, List.guid == ListItem.list_guid)
        .where(
            List.list_type == ListType.FAVORITES,
            List.owner_guid == user_guid,
        )
    )
    watched_genres = (
        select(media_genre_table.c.genre_id)
        .join(
            ViewingHistory,
            ViewingHistory.media_item_guid == media_genre_table.c.media_item_guid,
        )
        .where(ViewingHistory.user_guid == user_guid)
    )
    result = await db.execute(favorite_genres.union(watched_genres))
    return [genre_id for (genre_id,) in result.all()]


async def _user_seed_item_guids(db: DatabaseSession, user_guid: uuid.UUID) -> set[uuid.UUID]:
    favorite_items = (
        select(ListItem.item_guid)
        .join(List, List.guid == ListItem.list_guid)
        .where(
            List.list_type == ListType.FAVORITES,
            List.owner_guid == user_guid,
        )
    )
    watched_items = select(ViewingHistory.media_item_guid).where(
        ViewingHistory.user_guid == user_guid
    )
    result = await db.execute(favorite_items.union(watched_items))
    return {item_guid for (item_guid,) in result.all()}


def _release_year(value: date | None) -> str | None:
    return str(value.year) if value else None


def _media_studios(media_item: MediaItem) -> list[str]:
    if not media_item.extra_data:
        return []
    try:
        extra_data = json.loads(media_item.extra_data)
    except (TypeError, ValueError):
        return []
    raw_values = (
        extra_data.get("studios")
        or extra_data.get("production_companies")
        or extra_data.get("studio")
        or []
    )
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    if not isinstance(raw_values, list):
        return []
    studios = []
    for raw in raw_values:
        if isinstance(raw, dict):
            value = raw.get("name")
        else:
            value = raw
        if isinstance(value, str) and value.strip():
            studios.append(value.strip())
    return studios


@router.get("/autocomplete", response_model=AutocompleteResponse)
async def autocomplete_suggestions(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    q: str = Query(..., min_length=1, max_length=100),
    media_type: MediaType | None = Query(None, description="Filter by media type"),
    limit: int = Query(10, ge=1, le=50),
):
    """Return visible media suggestions matching a partial search term."""
    term = q.strip()
    if not term:
        return AutocompleteResponse(query=q, items=[], total=0)

    pattern = f"%{term}%"
    query = (
        select(MediaItem)
        .options(selectinload(MediaItem.genres), selectinload(MediaItem.platforms))
        .where(
            *_visibility_conditions(current_user, permissions, media_type),
            or_(
                MediaItem.title.ilike(pattern),
                MediaItem.original_title.ilike(pattern),
                MediaItem.description.ilike(pattern),
            ),
        )
        .order_by(MediaItem.title.asc())
        .limit(limit)
    )
    result = await db.execute(query)
    items = list(result.scalars().unique().all())
    return AutocompleteResponse(
        query=term,
        items=await _summaries(db, items, current_user.ui_language),
        total=len(items),
    )


@router.get("/autocomplete/typed", response_model=TypedAutocompleteResponse)
async def typed_autocomplete_suggestions(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    q: str = Query(..., min_length=1, max_length=100),
    media_type: MediaType | None = Query(None, description="Filter by media type"),
    limit: int = Query(20, ge=1, le=100),
):
    """Return typed autocomplete suggestions across visible search domains."""
    term = q.strip()
    if not term:
        return TypedAutocompleteResponse(query=q, items=[], total=0)

    pattern = f"%{term}%"
    visibility = _visibility_conditions(current_user, permissions, media_type)
    per_type_limit = max(3, min(limit, 10))

    media_result = await db.execute(
        select(MediaItem)
        .options(selectinload(MediaItem.genres), selectinload(MediaItem.platforms))
        .where(
            *visibility,
            or_(
                MediaItem.title.ilike(pattern),
                MediaItem.original_title.ilike(pattern),
                MediaItem.description.ilike(pattern),
            ),
        )
        .order_by(MediaItem.title.asc())
        .limit(per_type_limit)
    )
    media_items = list(media_result.scalars().unique().all())
    summaries = await _summaries(db, media_items, current_user.ui_language)

    suggestions: list[TypedAutocompleteItem] = [
        TypedAutocompleteItem(
            type="media",
            label=summary.title,
            value=str(summary.guid),
            media_type=summary.media_type.value if hasattr(summary.media_type, "value") else str(summary.media_type),
            item=summary,
        )
        for summary in summaries
    ]

    genre_result = await db.execute(
        select(Genre.name, func.count(MediaItem.guid))
        .join(media_genre_table, media_genre_table.c.genre_id == Genre.id)
        .join(MediaItem, MediaItem.guid == media_genre_table.c.media_item_guid)
        .where(*visibility, Genre.name.ilike(pattern))
        .group_by(Genre.name)
        .order_by(Genre.name.asc())
        .limit(per_type_limit)
    )
    suggestions.extend(
        TypedAutocompleteItem(
            type="genre",
            label=name,
            value=name,
            count=count,
        )
        for name, count in genre_result.all()
    )

    person_result = await db.execute(
        select(Person.name, Person.guid, func.count(MediaItem.guid))
        .join(MediaCast, MediaCast.person_guid == Person.guid)
        .join(MediaItem, MediaItem.guid == MediaCast.media_item_guid)
        .where(*visibility, Person.name.ilike(pattern))
        .group_by(Person.guid, Person.name)
        .order_by(Person.name.asc())
        .limit(per_type_limit)
    )
    suggestions.extend(
        TypedAutocompleteItem(
            type="person",
            label=name,
            value=str(person_guid),
            count=count,
        )
        for name, person_guid, count in person_result.all()
    )

    domain_result = await db.execute(
        select(MediaItem)
        .where(*visibility)
        .order_by(MediaItem.title.asc())
        .limit(500)
    )
    for item in domain_result.scalars().all():
        for studio in _media_studios(item):
            if term.lower() in studio.lower() and all(
                suggestion.type != "studio" or suggestion.value.lower() != studio.lower()
                for suggestion in suggestions
            ):
                suggestions.append(
                    TypedAutocompleteItem(type="studio", label=studio, value=studio)
                )
        year = _release_year(item.release_date)
        if year and term in year and all(
            suggestion.type != "year" or suggestion.value != year
            for suggestion in suggestions
        ):
            suggestions.append(TypedAutocompleteItem(type="year", label=year, value=year))

    return TypedAutocompleteResponse(
        query=term,
        items=suggestions[:limit],
        total=min(len(suggestions), limit),
    )


@router.get("", response_model=SuggestionsResponse)
async def get_suggestions(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    media_type: MediaType | None = Query(None, description="Filter by media type"),
    limit: int = Query(20, ge=1, le=100),
    include_played: bool = Query(False, description="Include completed items"),
):
    """Return user-scoped media suggestions.

    Uses the current user's favorites and watch history as lightweight seeds.
    If there are no seeds, it falls back to recent visible library items.
    """
    conditions = _visibility_conditions(current_user, permissions, media_type)
    seed_genre_ids = await _user_seed_genre_ids(db, current_user.guid)
    seed_item_guids = await _user_seed_item_guids(db, current_user.guid)

    if seed_item_guids:
        conditions.append(MediaItem.guid.notin_(seed_item_guids))
    if not include_played:
        completed = select(ViewingHistory.media_item_guid).where(
            ViewingHistory.user_guid == current_user.guid,
            ViewingHistory.is_completed.is_(True),
        )
        conditions.append(MediaItem.guid.notin_(completed))

    query = (
        select(MediaItem)
        .options(selectinload(MediaItem.genres), selectinload(MediaItem.platforms))
        .where(*conditions)
        .order_by(desc(MediaItem.release_date).nulls_last(), desc(MediaItem.created_at))
        .limit(limit)
    )
    reason = "recent"
    if seed_genre_ids:
        query = query.where(MediaItem.genres.any(Genre.id.in_(seed_genre_ids)))
        reason = "because_of_your_activity"

    result = await db.execute(query)
    items = list(result.scalars().unique().all())
    return SuggestionsResponse(
        items=await _summaries(db, items, current_user.ui_language),
        total=len(items),
        reason=reason,
    )


@router.get("/latest", response_model=LatestItemsResponse)
async def get_latest_items(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    media_type: MediaType | None = Query(None, description="Filter by media type"),
    parent_guid: uuid.UUID | None = Query(None, description="Filter by parent item"),
    limit: int = Query(20, ge=1, le=100),
):
    """Return latest visible library items for the current user."""
    conditions = _visibility_conditions(current_user, permissions, media_type)
    if parent_guid is not None:
        conditions.append(MediaItem.parent_guid == parent_guid)
    else:
        conditions.append(MediaItem.parent_guid.is_(None))

    result = await db.execute(
        select(MediaItem)
        .options(selectinload(MediaItem.genres), selectinload(MediaItem.platforms))
        .where(*conditions)
        .order_by(desc(MediaItem.created_at), desc(MediaItem.release_date).nulls_last())
        .limit(limit)
    )
    items = list(result.scalars().unique().all())
    return LatestItemsResponse(
        items=await _summaries(db, items, current_user.ui_language),
        total=len(items),
    )


@router.get("/instant-mix/{item_guid}", response_model=InstantMixResponse)
async def get_instant_mix(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
    limit: int = Query(25, ge=1, le=100),
):
    """Build an anchor-based instant mix queue."""
    result = await db.execute(
        select(MediaItem)
        .options(selectinload(MediaItem.genres), selectinload(MediaItem.platforms))
        .where(MediaItem.guid == item_guid)
    )
    seed = result.scalars().unique().one_or_none()
    if not seed:
        raise HTTPException(status_code=404, detail="Media item not found")

    seed_library = MEDIA_TYPE_TO_LIBRARY.get(seed.media_type.value)
    if (
        not current_user.is_superuser
        and seed_library
        and seed_library not in permissions.allowed_libraries
    ):
        raise HTTPException(
            status_code=403,
            detail=f"Access denied to {seed_library} library",
        )
    if (
        not current_user.is_superuser
        and current_user.parental_max_age is not None
        and seed.min_age is not None
        and seed.min_age > current_user.parental_max_age
    ):
        raise HTTPException(status_code=403, detail="Blocked by parental control")

    seed_genre_ids = [genre.id for genre in seed.genres]
    related_conditions = [
        MediaItem.guid != seed.guid,
        *_visibility_conditions(current_user, permissions, seed.media_type),
    ]
    related_match = []
    if seed_genre_ids:
        related_match.append(MediaItem.genres.any(Genre.id.in_(seed_genre_ids)))
    if seed.parent_guid:
        related_match.append(MediaItem.parent_guid == seed.parent_guid)
    if related_match:
        related_conditions.append(or_(*related_match))

    related_query = (
        select(MediaItem)
        .options(selectinload(MediaItem.genres), selectinload(MediaItem.platforms))
        .where(and_(*related_conditions))
        .order_by(MediaItem.sequence_number.asc().nulls_last(), desc(MediaItem.release_date).nulls_last())
        .limit(max(0, limit - 1))
    )
    related_result = await db.execute(related_query)
    related = list(related_result.scalars().unique().all())
    items = [seed, *related][:limit]

    return InstantMixResponse(
        seed_guid=seed.guid,
        items=await _summaries(db, items, current_user.ui_language),
        total=len(items),
        reason="genre_and_album_match" if related_match else "same_media_type",
    )

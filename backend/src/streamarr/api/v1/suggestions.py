"""Suggestion and instant-mix endpoints."""

import json
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select

from streamarr.api.dependencies import CurrentUser, DatabaseSession, UserPermissionsDep
from streamarr.models.genre import Genre
from streamarr.models.media import MediaItem, MediaType
from streamarr.models.viewing_history import ViewingHistory
from streamarr.schemas.media import MediaItemSummary
from streamarr.services.media_access import require_media_read_access
from streamarr.services.media_visibility import (
    visibility_conditions as _visibility_conditions,
)
from streamarr.services.suggestion import SuggestionService

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


async def _summaries(
    db: DatabaseSession,
    items: list[MediaItem],
    user_language: str | None,
) -> list[MediaItemSummary]:
    summaries = [MediaItemSummary.model_validate(item) for item in items]
    from streamarr.services.translation import TranslationService

    await TranslationService(db).apply_translations(summaries, user_language)
    return summaries


def _extra_data_studios(ed) -> list[str]:
    if not ed:
        return []
    if isinstance(ed, dict):
        extra_data = ed
    else:
        try:
            extra_data = json.loads(ed)
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
    items = await SuggestionService(db).search_media(
        _visibility_conditions(current_user, permissions, media_type), pattern, limit
    )
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
    service = SuggestionService(db)

    media_items = await service.search_media(visibility, pattern, per_type_limit)
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

    suggestions.extend(
        TypedAutocompleteItem(
            type="genre",
            label=name,
            value=name,
            count=count,
        )
        for name, count in await service.search_genres(
            visibility, pattern, per_type_limit
        )
    )

    suggestions.extend(
        TypedAutocompleteItem(
            type="person",
            label=name,
            value=str(person_guid),
            count=count,
        )
        for name, person_guid, count in await service.search_people(
            visibility, pattern, per_type_limit
        )
    )

    for extra_data in await service.scan_studio_facets(visibility):
        for studio in _extra_data_studios(extra_data):
            if term.lower() in studio.lower() and all(
                suggestion.type != "studio" or suggestion.value.lower() != studio.lower()
                for suggestion in suggestions
            ):
                suggestions.append(
                    TypedAutocompleteItem(type="studio", label=studio, value=studio)
                )

    for year_value in await service.facet_years(visibility):
        year = str(year_value)
        if term in year and all(
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
    service = SuggestionService(db)
    seed_genre_ids = await service.seed_genre_ids(current_user.guid)
    seed_item_guids = await service.seed_item_guids(current_user.guid)

    if seed_item_guids:
        conditions.append(MediaItem.guid.notin_(seed_item_guids))
    if not include_played:
        completed = select(ViewingHistory.media_item_guid).where(
            ViewingHistory.user_guid == current_user.guid,
            ViewingHistory.is_completed.is_(True),
        )
        conditions.append(MediaItem.guid.notin_(completed))

    reason = "because_of_your_activity" if seed_genre_ids else "recent"
    items = await service.recommended(conditions, seed_genre_ids, limit)
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

    items = await SuggestionService(db).latest(conditions, limit)
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
    service = SuggestionService(db)
    seed = await service.get_item(item_guid)
    if not seed:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_read_access(current_user, permissions, seed)

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

    related = await service.related(related_conditions, max(0, limit - 1))
    items = [seed, *related][:limit]

    return InstantMixResponse(
        seed_guid=seed.guid,
        items=await _summaries(db, items, current_user.ui_language),
        total=len(items),
        reason="genre_and_album_match" if related_match else "same_media_type",
    )

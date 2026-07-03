# genre service
import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from pyrate.api.dependencies import (
    CurrentSuperuser,
    CurrentUser,
    DatabaseSession,
    UserPermissionsDep,
)
from pyrate.models.media import MediaType
from pyrate.schemas.genre import GenreCreate, GenreRead, GenreUpdate, GenreWithItems
from pyrate.schemas.media import MediaItemSummary
from pyrate.services.genre import GenreService
from pyrate.services.library import LibraryService
from pyrate.services.media_access import (
    allowed_media_types_for_permissions,
    max_age_for_user,
    require_library_access_for_media_type,
)

router = APIRouter()

# Map frontend library names to actual MediaType enum values
_MEDIA_TYPE_ALIASES = {
    "MUSIC": "ARTISTS",
}


@router.get("/with-items", response_model=list[GenreWithItems])
async def list_genres_with_items(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    library_guid: uuid.UUID | None = Query(None, description="Filter by library"),
    media_type: str | None = Query(None, description="Filter by media type"),
    max_items_per_genre: int = Query(10, ge=1, le=50, description="Max items per genre"),
):
    """Get all genres with their media items in a single query (optimized)."""
    genre_service = GenreService(db)
    library_service = LibraryService(db)

    # Resolve media type aliases (e.g. MUSIC -> ALBUMS)
    resolved_type = None
    if media_type:
        resolved = _MEDIA_TYPE_ALIASES.get(media_type.upper(), media_type.upper())
        try:
            resolved_type = MediaType(resolved)
        except ValueError:
            return []
        require_library_access_for_media_type(current_user, permissions, resolved_type)

    # Get disabled media types once to pass into the single query
    disabled_types = await library_service.get_disabled_media_types()

    genres_dict = await genre_service.get_genres_with_items(
        media_type=resolved_type,
        max_items_per_genre=max_items_per_genre,
        library_guid=library_guid,
        disabled_media_types=disabled_types if disabled_types else None,
        allowed_media_types=allowed_media_types_for_permissions(current_user, permissions),
        max_age=max_age_for_user(current_user),
    )

    result = [
        GenreWithItems(
            id=data["id"],
            name=data["name"],
            items=[MediaItemSummary.model_validate(item) for item in data["items"]],
        )
        for data in genres_dict.values()
        if data["items"]
    ]

    # Apply translations based on user language
    from pyrate.services.translation import TranslationService
    ts = TranslationService(db)
    all_items = [item for genre_data in result for item in genre_data.items]
    await ts.apply_translations(all_items, current_user.ui_language)

    return result


class BatchGenreItemsRequest(BaseModel):
    """Request body for batch genre items endpoint."""

    genre_ids: list[int] = Field(..., description="List of genre IDs to fetch items for")
    max_items: int = Field(10, ge=1, le=50, description="Max items per genre")
    media_type: str | None = Field(None, description="Filter by media type")


class BatchGenreItemsResponse(BaseModel):
    """Response for batch genre items endpoint."""

    genres: dict[int, list[MediaItemSummary]] = Field(
        default_factory=dict,
        description="Items grouped by genre ID",
    )


@router.post("/batch-items", response_model=BatchGenreItemsResponse)
async def batch_genre_items(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    request: BatchGenreItemsRequest,
):
    """Get media items for multiple genres in a single request.

    This endpoint is optimized for frontends that need items for a specific
    set of genres with optional filters, avoiding per-genre round-trips.
    """
    genre_service = GenreService(db)
    library_service = LibraryService(db)

    disabled_types = await library_service.get_disabled_media_types()

    # Resolve media type aliases
    resolved_type = None
    if request.media_type:
        resolved = _MEDIA_TYPE_ALIASES.get(request.media_type.upper(), request.media_type.upper())
        try:
            resolved_type = MediaType(resolved)
        except ValueError:
            return BatchGenreItemsResponse(genres={})
        require_library_access_for_media_type(current_user, permissions, resolved_type)

    grouped = await genre_service.get_items_for_genre_ids(
        genre_ids=request.genre_ids,
        media_type=resolved_type,
        max_items=request.max_items,
        disabled_media_types=disabled_types if disabled_types else None,
        allowed_media_types=allowed_media_types_for_permissions(current_user, permissions),
        max_age=max_age_for_user(current_user),
    )

    # Validate items through the schema
    result: dict[int, list[MediaItemSummary]] = {}
    all_items: list[MediaItemSummary] = []
    for genre_id, items in grouped.items():
        summaries = [MediaItemSummary.model_validate(item) for item in items]
        result[genre_id] = summaries
        all_items.extend(summaries)

    # Apply translations based on user language
    from pyrate.services.translation import TranslationService
    ts = TranslationService(db)
    await ts.apply_translations(all_items, current_user.ui_language)

    return BatchGenreItemsResponse(genres=result)


@router.get("", response_model=list[GenreRead])
async def list_genres(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    media_type: str | None = Query(None, description="Only genres with items of this type"),
):
    """Get all genres, optionally filtered to those with items of a given media type."""
    service = GenreService(db)
    if media_type:
        resolved = _MEDIA_TYPE_ALIASES.get(media_type.upper(), media_type.upper())
        try:
            mt = MediaType(resolved)
        except ValueError:
            return []
        require_library_access_for_media_type(current_user, permissions, mt)
        return await service.get_all_with_items_of_type(mt)
    return await service.get_all()


@router.get("/{genre_id}", response_model=GenreRead)
async def get_genre(db: DatabaseSession, genre_id: int, current_user: CurrentUser):
    """Get a specific genre by ID."""
    service = GenreService(db)
    genre = await service.get_by_id(genre_id)
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")
    return genre


@router.post("", response_model=GenreRead)
async def create_genre(
    db: DatabaseSession, genre: GenreCreate, current_user: CurrentSuperuser
):
    """Create a new genre (Admin only)."""
    service = GenreService(db)
    # Check if genre already exists
    existing_genre = await service.get_by_id(genre.id)
    if existing_genre:
        raise HTTPException(status_code=400, detail="Genre with this ID already exists")

    return await service.create(genre)


@router.put("/{genre_id}", response_model=GenreRead)
async def update_genre(
    db: DatabaseSession,
    genre_id: int,
    genre_update: GenreUpdate,
    current_user: CurrentSuperuser,
):
    """Update a genre (Admin only)."""
    service = GenreService(db)
    genre = await service.get_by_id(genre_id)
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")

    return await service.update(genre, genre_update)


@router.delete("/{genre_id}", status_code=204)
async def delete_genre(
    db: DatabaseSession, genre_id: int, current_user: CurrentSuperuser
):
    """Delete a genre (Admin only)."""
    service = GenreService(db)
    genre = await service.get_by_id(genre_id)
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")

    await service.delete(genre)

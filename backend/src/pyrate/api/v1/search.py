"""Unified search API endpoint covering all content types.

The search works as follows:
1. Results are primarily fetched from the metadata provider (TMDB).
2. If the provider is unreachable, fall back to the local database.
3. Discovered media items are automatically queued for metadata import.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from pyrate.api.dependencies import (
    CurrentSuperuser,
    CurrentUser,
    DatabaseSession,
    UserPermissionsDep,
)
from pyrate.schemas.search import SearchRequest, SearchResponse
from pyrate.services.media_access import (
    max_age_for_user,
    require_library_access_for_media_type,
)
from pyrate.services.search import SearchService

router = APIRouter()

logger = logging.getLogger(__name__)


SEARCH_TYPE_TO_LIBRARY = {
    "movies": "movies",
    "shows": "series",
    "games": "games",
    "music": "music",
    "books": "books",
}


@router.post("/", response_model=SearchResponse)
async def search_all_content(
    db: DatabaseSession,
    search_request: SearchRequest,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
) -> dict[str, Any]:
    """Unified search over all content types (movies and shows).

    Results are primarily sourced from the metadata provider (TMDB/IGDB) so
    that items not yet present in the local database can also be returned.

    On network errors or when the provider is unreachable, the search falls
    back to the local Elasticsearch index automatically.

    Discovered media items are queued for metadata import so they become
    available immediately when the user wants to add them.

    Args:
        db: Database session.
        search_request: The full search request with parameters.
        current_user: The current user.

    Returns:
        SearchResponse: Search results with pagination and metadata.

    Raises:
        HTTPException: On hard failures.
    """
    search_service = SearchService(db)

    try:
        # If no query but filters are present → browse local DB
        has_query = search_request.query and search_request.query.strip()
        has_filters = (
            search_request.genre_id
            or search_request.genre_ids
            or search_request.genres
            or search_request.exclude_genre_ids
            or search_request.exclude_genres
            or search_request.platform_id
            or search_request.platform_ids
            or search_request.exclude_platform_ids
            or search_request.media_type
            or search_request.library_guid
            or search_request.availability
            or search_request.has_poster is not None
            or search_request.has_backdrop is not None
            or search_request.has_description is not None
            or search_request.is_favorite is not None
            or search_request.is_played is not None
            or search_request.person_guid is not None
            or search_request.person_name
            or search_request.exclude_person_guid is not None
            or search_request.exclude_person_name
            or search_request.studio_name
            or search_request.container
            or search_request.exclude_containers
            or search_request.content_rating
            or search_request.exclude_content_ratings
            or search_request.years
            or search_request.exclude_years
            or search_request.year_from is not None
            or search_request.year_to is not None
            or search_request.sort_by.value != "_score"
            or search_request.sort_order.value != "desc"
        )

        if not has_query and has_filters:
            if search_request.media_type:
                require_library_access_for_media_type(
                    current_user,
                    permissions,
                    search_request.media_type,
                )
            result = await search_service.browse_local(
                search_request,
                current_user.guid,
                max_age=max_age_for_user(current_user),
                allowed_libraries=permissions.allowed_libraries,
            )
            logger.info(
                f"Browse with filters returned {result.get('total', 0)} results"
            )
            return result

        requested_library = SEARCH_TYPE_TO_LIBRARY.get(search_request.search_type.value)
        if (
            not current_user.is_superuser
            and requested_library
            and requested_library not in permissions.allowed_libraries
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to {requested_library} library",
            )

        # Provider-first search with automatic local fallback
        result = await search_service.search(
            search_request,
            queue_import=True,
            allowed_libraries=permissions.allowed_libraries,
        )

        # Always enrich with library status
        if result.get("hits"):
            result["hits"] = await search_service.enrich_with_library_status(
                result["hits"]
            )

        # Search lists alongside media items
        if has_query:
            list_hits = await search_service.search_lists(
                search_request.query, current_user.guid
            )
            if list_hits:
                result["list_hits"] = list_hits

        logger.info(
            f"Search for '{search_request.query}' returned {result.get('total', 0)} results "
            f"({len(result.get('list_hits', []))} lists) "
            f"from {result.get('source', 'unknown')} ({result.get('provider', 'unknown')})"
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Search error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search failed",
        )
    finally:
        await search_service.close()


@router.post("/local", response_model=SearchResponse)
async def search_local_content(
    db: DatabaseSession,
    search_request: SearchRequest,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
) -> dict[str, Any]:
    """Search the local database only.

    Useful when callers explicitly want to limit results to already-imported
    media items.

    Args:
        search_request: The search request with all parameters.
        current_user: The current user.

    Returns:
        SearchResponse: Search results from the local database.
    """
    search_service = SearchService(db)
    try:
        requested_library = SEARCH_TYPE_TO_LIBRARY.get(search_request.search_type.value)
        if (
            not current_user.is_superuser
            and requested_library
            and requested_library not in permissions.allowed_libraries
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to {requested_library} library",
            )
        if search_request.media_type:
            require_library_access_for_media_type(
                current_user,
                permissions,
                search_request.media_type,
            )
        return await search_service.browse_local(
            search_request,
            current_user.guid,
            max_age=max_age_for_user(current_user),
            allowed_libraries=permissions.allowed_libraries,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Local search error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Local search failed",
        )
    finally:
        await search_service.close()


class GetOrImportRequest(BaseModel):
    """Request body for synchronous get-or-import endpoint."""

    tmdb_id: int | None = None
    igdb_id: int | None = None
    spotify_id: str | None = None
    media_type: str  # "MOVIES", "SHOWS", "GAMES", or "MUSIC"


class GetOrImportResponse(BaseModel):
    """Response from the get-or-import endpoint."""

    guid: str
    library_guid: str | None = None


@router.post("/get-or-import", response_model=GetOrImportResponse)
async def get_or_import_media_item(
    db: DatabaseSession,
    request: GetOrImportRequest,
    current_user: CurrentSuperuser,  # noqa: ARG001 - Required for admin auth
) -> GetOrImportResponse:
    """Check whether a media item already exists in the local DB and, if not,
    synchronously import it from the provider before returning.

    Args:
        db: Database session.
        request: Provider id and media type.
        current_user: The current user.

    Returns:
        GetOrImportResponse: guid and library_guid of the imported/existing item.

    Raises:
        HTTPException 400: When media_type is invalid or no id is supplied.
        HTTPException 404: When the import failed.
    """
    if request.media_type.upper() not in (
        "MOVIES", "SHOWS", "GAMES", "MUSIC", "ARTISTS", "ALBUMS", "SONGS",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid media_type '{request.media_type}'. "
            "Allowed: MOVIES, SHOWS, GAMES, MUSIC, ARTISTS, ALBUMS, SONGS",
        )

    if request.media_type.upper() == "GAMES" and not request.igdb_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="igdb_id is required for media_type GAMES",
        )

    if request.media_type.upper() in ("MUSIC", "ARTISTS", "ALBUMS", "SONGS") and not request.spotify_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="spotify_id is required for media_type MUSIC",
        )

    if request.media_type.upper() in ("MOVIES", "SHOWS") and not request.tmdb_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tmdb_id is required for media_type MOVIES/SHOWS",
        )

    search_service = SearchService(db)
    try:
        result = await search_service.get_or_import_item(
            tmdb_id=request.tmdb_id,
            igdb_id=request.igdb_id,
            spotify_id=request.spotify_id,
            media_type_str=request.media_type.upper(),
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not import item. "
                "There may be no active library for this media type.",
            )
        return GetOrImportResponse(
            guid=result["guid"],
            library_guid=result.get("library_guid"),
        )
    finally:
        await search_service.close()

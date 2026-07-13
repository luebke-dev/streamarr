"""Local database-backed search and browse helpers."""

import logging
import math
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import MediaType
from streamarr.schemas.search import SearchRequest, SearchType
from streamarr.services.external_ids import extract_external_ids
from streamarr.services.library import LibraryService
from streamarr.services.permission import MEDIA_TYPE_TO_LIBRARY

logger = logging.getLogger(__name__)


class LocalSearchService:
    """Search local media rows without provider or import side effects."""

    #: Media type each facet key counts. Mirrors :meth:`_media_type_from_string`
    #: so a facet count matches what selecting that type tab actually returns.
    FACET_TYPES: dict[str, MediaType] = {
        "movies": MediaType.MOVIES,
        "shows": MediaType.SHOWS,
        "games": MediaType.GAMES,
        "music": MediaType.ARTISTS,
        "books": MediaType.BOOKS,
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self._library_service = LibraryService(db)

    async def browse_local(
        self,
        request: SearchRequest,
        user_guid: uuid.UUID | None = None,
        max_age: int | None = None,
        allowed_libraries: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Browse local DB with filters and return results in SearchHit format.
        """
        offset = (request.page - 1) * request.per_page
        media_type_enum = await self._resolve_media_type(request)
        allowed_media_types = self._allowed_media_types(allowed_libraries)
        order_by, order_desc = self._order_by(request)

        filter_kwargs = self._filter_kwargs(
            request=request,
            media_type_enum=media_type_enum,
            user_guid=user_guid,
            max_age=max_age,
            allowed_media_types=allowed_media_types,
        )

        items = await self._library_service.list_media_items(
            **filter_kwargs,
            limit=request.per_page,
            offset=offset,
            order_by=order_by,
            order_desc=order_desc,
        )
        total = await self._library_service.count_media_items(**filter_kwargs)

        response: dict[str, Any] = {
            "hits": [self._to_search_hit(item) for item in items],
            "total": total,
            "page": request.page,
            "per_page": request.per_page,
            "total_pages": math.ceil(total / request.per_page) if request.per_page else 0,
            "query": request.query or "",
            "search_type": request.search_type.value,
            "took": 0,
            "source": "local",
            "provider": "database",
        }
        if request.with_facets:
            response["facets"] = {"types": await self._type_facets(filter_kwargs)}
        return response

    async def _type_facets(self, filter_kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        """Count matches per media type for the search page's type tabs.

        Counted with the active filters but *without* the media-type filter, so
        selecting one tab does not zero out the others. The counts run
        sequentially: they share one AsyncSession, which is not safe to use
        concurrently.
        """
        facets = []
        for key, media_type in self.FACET_TYPES.items():
            count = await self._library_service.count_media_items(
                **{**filter_kwargs, "media_type": media_type}
            )
            if count:
                facets.append({"key": key, "doc_count": count})
        return facets

    async def _resolve_media_type(self, request: SearchRequest) -> MediaType | None:
        """Resolve explicit or implied media type filters."""
        media_type_enum = self._media_type_from_string(request.media_type)

        if not media_type_enum and request.search_type != SearchType.ALL:
            search_type_map = {
                SearchType.MOVIES: MediaType.MOVIES,
                SearchType.SHOWS: MediaType.SHOWS,
                SearchType.GAMES: MediaType.GAMES,
                SearchType.MUSIC: MediaType.ARTISTS,
                SearchType.BOOKS: MediaType.BOOKS,
            }
            media_type_enum = search_type_map.get(request.search_type)

        # Platform filter implies games.
        if not media_type_enum and (request.platform_id or request.platform_ids):
            media_type_enum = MediaType.GAMES

        if not media_type_enum and request.library_guid:
            library = await self._library_service.get_library(request.library_guid)
            if library:
                media_type_enum = self._media_type_from_string(library.type)

        return media_type_enum

    @staticmethod
    def _media_type_from_string(media_type: str | None) -> MediaType | None:
        if not media_type:
            return None
        type_map = {
            "MOVIES": MediaType.MOVIES,
            "SHOWS": MediaType.SHOWS,
            "GAMES": MediaType.GAMES,
            # Browsing is top-level only, and an album hangs below its artist —
            # mapping MUSIC to ALBUMS therefore always matched zero rows.
            "MUSIC": MediaType.ARTISTS,
            "BOOKS": MediaType.BOOKS,
        }
        return type_map.get(media_type.upper())

    @staticmethod
    def _allowed_media_types(
        allowed_libraries: list[str] | None,
    ) -> list[MediaType] | None:
        if allowed_libraries is None:
            return None

        allowed = set(allowed_libraries)
        return [
            media_type
            for media_type in MediaType
            if MEDIA_TYPE_TO_LIBRARY.get(media_type.value) in allowed
        ]

    @staticmethod
    def _order_by(request: SearchRequest) -> tuple[str, bool]:
        order_by_map = {
            "_score": "title",
            "title.keyword": "title",
            "release_date": "year",
            "first_air_date": "year",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
        return order_by_map.get(request.sort_by.value, "title"), request.sort_order.value == "desc"

    @staticmethod
    def _filter_kwargs(
        *,
        request: SearchRequest,
        media_type_enum: MediaType | None,
        user_guid: uuid.UUID | None,
        max_age: int | None,
        allowed_media_types: list[MediaType] | None,
    ) -> dict[str, Any]:
        return {
            "media_type": media_type_enum,
            "genre_id": request.genre_id,
            "genre_ids": request.genre_ids,
            "genre_names": request.genres,
            "exclude_genre_ids": request.exclude_genre_ids,
            "exclude_genre_names": request.exclude_genres,
            "platform_id": request.platform_id,
            "platform_ids": request.platform_ids,
            "exclude_platform_ids": request.exclude_platform_ids,
            "top_level_only": True,
            "allowed_media_types": allowed_media_types,
            "availability": request.availability,
            "has_poster": request.has_poster,
            "has_backdrop": request.has_backdrop,
            "has_description": request.has_description,
            "is_favorite": request.is_favorite,
            "is_played": request.is_played,
            "user_guid": user_guid,
            "person_guid": request.person_guid,
            "person_name": request.person_name,
            "exclude_person_guid": request.exclude_person_guid,
            "exclude_person_name": request.exclude_person_name,
            "search_term": request.query,
            "years": request.years,
            "exclude_years": request.exclude_years,
            "start_year": request.year_from,
            "end_year": request.year_to,
            "content_rating": request.content_rating,
            "exclude_content_ratings": request.exclude_content_ratings,
            "studio_name": request.studio_name,
            "container": request.container,
            "exclude_containers": request.exclude_containers,
            "max_age": max_age,
        }

    @classmethod
    def _to_search_hit(cls, item) -> dict[str, Any]:
        type_map = {
            MediaType.MOVIES: SearchType.MOVIES,
            MediaType.SHOWS: SearchType.SHOWS,
            MediaType.GAMES: SearchType.GAMES,
            MediaType.ALBUMS: SearchType.MUSIC,
            MediaType.ARTISTS: SearchType.MUSIC,
            MediaType.BOOKS: SearchType.BOOKS,
        }
        hit_type = type_map.get(item.media_type, SearchType.MOVIES)
        tmdb_id, igdb_id, spotify_id = extract_external_ids(item.external_ids)

        return {
            "id": str(item.guid),
            "tmdb_id": tmdb_id,
            "igdb_id": igdb_id,
            "spotify_id": spotify_id,
            "type": hit_type.value,
            "score": 0.0,
            "title": item.title or "",
            "original_title": item.original_title,
            "description": item.description,
            "tagline": item.tagline,
            "poster_path": item.poster_path,
            "backdrop_path": item.backdrop_path,
            "release_date": item.release_date.isoformat() if item.release_date else None,
            "first_air_date": (
                item.release_date.isoformat()
                if item.release_date and hit_type == SearchType.SHOWS
                else None
            ),
            "genres": [g.name for g in (item.genres or [])],
            "genre_ids": [g.id for g in (item.genres or [])],
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "source": "local",
            "in_library": True,
            "library_id": None,
        }

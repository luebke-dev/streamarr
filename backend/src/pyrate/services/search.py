"""
Search Service - Provider-first search with local fallback.

This service implements a search strategy that:
1. First queries metadata providers (TMDB, IGDB, etc.)
2. Falls back to local database/Elasticsearch if provider is unavailable
3. Queues found items for metadata import
4. Only searches for media types that have active libraries
5. Uses Redis locks to prevent duplicate import queueing
"""

import asyncio
import logging
import uuid
from typing import Any

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.config import settings
from pyrate.models.library import Library
from pyrate.models.media import MediaExternalId, MediaItem, MediaType
from pyrate.metadata.tmdb import TMDB
from pyrate.metadata.igdb import IGDB
from pyrate.metadata.spotify import Spotify
from pyrate.schemas.search import SearchRequest, SearchType
from pyrate.services.elasticsearch import elasticsearch_service
from pyrate.services.media import MediaService
from pyrate.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Redis key prefix for import locks
IMPORT_LOCK_PREFIX = "pyrate:import_lock:"
IMPORT_LOCK_TTL_SECONDS = 300  # 5 minutes
TRANSIENT_SEARCH_ERRORS = (httpx.HTTPError, TimeoutError, ConnectionError, OSError)


async def _none() -> None:
    """Awaitable placeholder used in gather() when a client isn't needed."""
    return None


class SearchService:
    """Service for unified search across metadata providers and local database."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._tmdb: TMDB | None = None
        self._igdb: IGDB | None = None
        self._spotify: Spotify | None = None
        self._settings_service = SettingsService(db)
        self._active_library_types: set[str] | None = None
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def _acquire_import_lock(self, media_type: str, external_id: int | str) -> bool:
        """
        Try to acquire a lock for importing a media item.

        Returns True if lock was acquired (item should be queued for import).
        Returns False if lock already exists (item is already being imported).
        """
        redis = await self._get_redis()
        lock_key = f"{IMPORT_LOCK_PREFIX}{media_type}:{external_id}"

        # SET with NX (only set if not exists) and EX (expiry in seconds)
        result = await redis.set(lock_key, "1", nx=True, ex=IMPORT_LOCK_TTL_SECONDS)

        if result:
            logger.debug("Acquired import lock for %s %s", media_type, external_id)
            return True
        else:
            logger.debug("Import lock already exists for %s %s", media_type, external_id)
            return False

    async def _release_import_lock(self, media_type: str, external_id: int | str) -> None:
        """Release a previously acquired import lock."""
        redis = await self._get_redis()
        await redis.delete(f"{IMPORT_LOCK_PREFIX}{media_type}:{external_id}")

    # ── Generic client helper ────────────────────────────────────────────

    async def _get_or_create_client(
        self,
        cache_attr: str,
        load_credentials,
        factory,
        label: str,
    ):
        """
        Generic helper for cached client initialisation.

        Args:
            cache_attr: Instance attribute name used as cache (e.g. "_tmdb").
            load_credentials: Async callable returning credentials.
                              May return a single value or a tuple.
            factory: Callable that receives unpacked credentials and returns a
                     client instance.
            label: Human-readable name for log messages.

        Returns:
            The cached or newly-created client, or None when credentials
            are missing.
        """
        cached = getattr(self, cache_attr)
        if cached is not None:
            return cached

        creds = await load_credentials()

        # Normalise: single value -> tuple, tuple stays tuple
        if not isinstance(creds, tuple):
            creds = (creds,)

        if not all(creds):
            logger.debug("%s credentials not configured, skipping", label)
            return None

        logger.debug("Creating %s client", label)
        client = factory(*creds)
        setattr(self, cache_attr, client)
        return client

    async def _get_tmdb_client(self) -> TMDB | None:
        """Get or create TMDB client with API key from settings."""
        return await self._get_or_create_client(
            cache_attr="_tmdb",
            load_credentials=self._settings_service.get_tmdb_api_key,
            factory=lambda api_key: TMDB(api_key=api_key),
            label="TMDB",
        )

    async def _get_igdb_client(self) -> IGDB | None:
        """Get or create IGDB client with credentials from settings."""
        return await self._get_or_create_client(
            cache_attr="_igdb",
            load_credentials=self._settings_service.get_igdb_credentials,
            factory=lambda cid, csec: IGDB(client_id=cid, client_secret=csec),
            label="IGDB",
        )

    async def _get_spotify_client(self) -> Spotify | None:
        """Get or create Spotify client with credentials from settings."""
        return await self._get_or_create_client(
            cache_attr="_spotify",
            load_credentials=self._settings_service.get_spotify_credentials,
            factory=lambda cid, csec: Spotify(client_id=cid, client_secret=csec),
            label="Spotify",
        )

    # ── Active-library helpers ───────────────────────────────────────────

    async def _get_active_library_types(self) -> set[str]:
        """
        Get the set of media types that have active (enabled) libraries.

        Returns:
            set[str]: Set of active library types (e.g., {"MOVIES", "SHOWS"})
        """
        if self._active_library_types is not None:
            return self._active_library_types

        from pyrate.models.library import Library

        result = await self.db.execute(
            select(Library.type).where(Library.enabled == True).distinct()  # noqa: E712
        )
        self._active_library_types = {row[0].upper() for row in result.fetchall()}

        logger.debug("Active library types: %s", self._active_library_types)
        return self._active_library_types

    async def _should_search_movies(self, search_type: SearchType) -> bool:
        """Check if movies should be included in search."""
        if search_type in (SearchType.SHOWS, SearchType.GAMES, SearchType.MUSIC, SearchType.BOOKS):
            return False
        active_types = await self._get_active_library_types()
        return "MOVIES" in active_types

    async def _should_search_shows(self, search_type: SearchType) -> bool:
        """Check if shows should be included in search."""
        if search_type in (SearchType.MOVIES, SearchType.GAMES, SearchType.MUSIC, SearchType.BOOKS):
            return False
        active_types = await self._get_active_library_types()
        return "SHOWS" in active_types

    async def _should_search_games(self, search_type: SearchType) -> bool:
        """Check if games should be included in search."""
        if search_type in (SearchType.MOVIES, SearchType.SHOWS, SearchType.MUSIC, SearchType.BOOKS):
            return False
        active_types = await self._get_active_library_types()
        return "GAMES" in active_types

    async def _should_search_music(self, search_type: SearchType) -> bool:
        """Check if music should be included in search."""
        if search_type in (SearchType.MOVIES, SearchType.SHOWS, SearchType.GAMES, SearchType.BOOKS):
            return False
        active_types = await self._get_active_library_types()
        return "MUSIC" in active_types

    async def _should_search_books(self, search_type: SearchType) -> bool:
        """Check if books should be included in search."""
        if search_type in (SearchType.MOVIES, SearchType.SHOWS, SearchType.GAMES, SearchType.MUSIC):
            return False
        active_types = await self._get_active_library_types()
        return "BOOKS" in active_types

    async def browse_local(
        self,
        request: SearchRequest,
        user_guid: uuid.UUID | None = None,
        max_age: int | None = None,
        allowed_libraries: list[str] | None = None,
    ) -> dict[str, Any]:
        """Browse local DB through the side-effect-free local search service."""
        from pyrate.services.local_search import LocalSearchService

        return await LocalSearchService(self.db).browse_local(
            request,
            user_guid=user_guid,
            max_age=max_age,
            allowed_libraries=allowed_libraries,
        )

    async def search_lists(self, query: str, user_guid) -> list[dict]:
        """Search lists by name. Returns system lists, own lists, and public lists."""
        from pyrate.models.list import List, ListItem, ListType, ListVisibility
        from pyrate.models.user import User

        from sqlalchemy import or_, and_

        # Visibility rules:
        # - System lists: always visible
        # - Own lists: always visible (incl. private)
        # - Other users' lists: only public
        visibility_filter = or_(
            List.list_type == ListType.SYSTEM,
            List.owner_guid == user_guid,
            and_(
                List.visibility == ListVisibility.PUBLIC,
                List.list_type == ListType.USER,
            ),
        )

        result = await self.db.execute(
            select(List)
            .where(
                List.name.ilike(f"%{query}%"),
                List.deleted_at.is_(None),
                List.is_active,
                visibility_filter,
            )
            .options(selectinload(List.owner))
            .order_by(List.item_count.desc())
            .limit(10)
        )
        lists = result.scalars().all()

        # Get item_types for each list
        list_guids = [l.guid for l in lists]
        item_types_map: dict[str, list[str]] = {}
        if list_guids:
            types_result = await self.db.execute(
                select(ListItem.list_guid, ListItem.item_type)
                .where(ListItem.list_guid.in_(list_guids))
                .distinct()
            )
            for row in types_result.all():
                guid_str = str(row[0])
                if guid_str not in item_types_map:
                    item_types_map[guid_str] = []
                item_types_map[guid_str].append(row[1])

        return [
            {
                "guid": str(l.guid),
                "name": l.name,
                "description": l.description,
                "list_type": l.list_type.value if hasattr(l.list_type, "value") else str(l.list_type),
                "visibility": l.visibility.value if hasattr(l.visibility, "value") else str(l.visibility),
                "owner_name": f"{l.owner.first_name} {l.owner.last_name}".strip() if l.owner else None,
                "item_count": l.item_count,
                "like_count": l.like_count,
                "poster_path": l.poster_path,
                "item_types": item_types_map.get(str(l.guid), []),
            }
            for l in lists
        ]

    @staticmethod
    def _resolve_hit_provider(hit: dict, fallback_type: "SearchType | None" = None):
        """
        Resolve a search hit to (external_id, provider, type_str, media_type).

        Returns a tuple or None when the external_id is missing.
        Requires ``from pyrate.models.media import MediaType`` at call site;
        imports are done lazily so the helper stays cheap when unused.
        """
        from pyrate.models.media import MediaType

        hit_type = hit.get("type", fallback_type)

        if hit_type == SearchType.BOOKS:
            external_id = hit.get("openlibrary_id")
            return (external_id, "openlibrary", "BOOKS", MediaType.BOOKS) if external_id else None

        if hit_type == SearchType.GAMES:
            external_id = hit.get("igdb_id")
            return (external_id, "igdb", "GAMES", MediaType.GAMES) if external_id else None

        if hit_type == SearchType.MUSIC:
            music_type = hit.get("music_type", "album")
            external_id = hit.get("spotify_id")
            if music_type == "artist":
                media_type = MediaType.ARTISTS
            elif music_type == "track":
                # For tracks, prefer the parent album ID for import
                external_id = hit.get("album_spotify_id") or external_id
                media_type = MediaType.ALBUMS
            else:
                media_type = MediaType.ALBUMS
            return (external_id, "spotify", "MUSIC", media_type) if external_id else None

        # TMDB-backed (movies / shows)
        external_id = hit.get("tmdb_id")
        if hit_type == SearchType.MOVIES:
            return (external_id, "tmdb", "MOVIES", MediaType.MOVIES) if external_id else None
        return (external_id, "tmdb", "SHOWS", MediaType.SHOWS) if external_id else None

    @staticmethod
    def _parse_spotify_date(date_str: str | None):
        """Parse a Spotify date string (YYYY, YYYY-MM, or YYYY-MM-DD) to a date or None."""
        from pyrate.utils.dates import parse_spotify_date

        return parse_spotify_date(date_str)

    @staticmethod
    def _extract_external_ids(external_ids) -> tuple:
        """Extract (tmdb_id, igdb_id, spotify_id) from a list of external ID objects."""
        tmdb_id = None
        igdb_id = None
        spotify_id = None
        for ext in (external_ids or []):
            if ext.provider == "tmdb":
                try:
                    tmdb_id = int(ext.external_id)
                except (ValueError, TypeError):
                    logger.debug("Non-integer TMDB external ID: %s", ext.external_id)
            elif ext.provider == "igdb":
                try:
                    igdb_id = int(ext.external_id)
                except (ValueError, TypeError):
                    logger.debug("Non-integer IGDB external ID: %s", ext.external_id)
            elif ext.provider == "spotify":
                spotify_id = ext.external_id
        return tmdb_id, igdb_id, spotify_id

    @staticmethod
    def _parse_date(date_str: str | None, fmt: str = "%Y-%m-%d", label: str = "date"):
        """Parse a date string to a date object or None."""
        if not date_str:
            return None
        from datetime import datetime as dt
        try:
            return dt.strptime(date_str, fmt).date()
        except (ValueError, TypeError):
            logger.debug("Invalid %s: %s", label, date_str)
            return None

    async def close(self):
        """Clean up resources."""
        if self._tmdb:
            await self._tmdb.close()
            self._tmdb = None
        if self._igdb:
            await self._igdb.close()
            self._igdb = None
        if self._spotify:
            await self._spotify.close()
            self._spotify = None
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def search(
        self,
        request: SearchRequest,
        queue_import: bool = True,
        allowed_libraries: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Search for media items using metadata providers with local fallback.

        Args:
            request: Search request parameters
            queue_import: If True, queue found items for metadata import

        Returns:
            dict: Search results with hits, total count, and metadata
        """
        try:
            # Try metadata provider first
            provider_results = await self._search_provider(request, allowed_libraries)

            if provider_results and provider_results.get("hits"):
                # Queue items for import if requested
                if queue_import and provider_results.get("hits"):
                    await self._queue_imports(
                        provider_results["hits"], request.search_type
                    )
                return provider_results

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.warning("Metadata provider search failed, falling back to local: %s", e)

        # Fall back to local search (Elasticsearch)
        local_results = await self._search_local(request)
        return self._filter_results_by_allowed_libraries(
            local_results,
            allowed_libraries,
        )

    async def _search_provider(
        self,
        request: SearchRequest,
        allowed_libraries: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Search metadata providers (TMDB, IGDB, Spotify). Only searches types with active libraries."""
        search_flags = await self._provider_search_flags(
            request.search_type,
            allowed_libraries,
        )
        if not any(search_flags.values()):
            logger.info("No active libraries for requested search types")
            return self._no_active_provider_result(request)

        try:
            tmdb, igdb, spotify = await self._provider_clients(search_flags)
            tasks = self._provider_tasks(
                request,
                search_flags=search_flags,
                tmdb=tmdb,
                igdb=igdb,
                spotify=spotify,
            )

            if tmdb:
                logger.debug(
                    "Searching TMDB for: '%s' (type: %s, movies: %s, shows: %s)",
                    request.query,
                    request.search_type,
                    search_flags["movies"],
                    search_flags["shows"],
                )

            hits, errors = await self._collect_provider_results(tasks)
            if not hits and not tmdb and not search_flags["music"] and not search_flags["books"]:
                logger.warning("No provider clients available, skipping provider search")
                return None

            hits = self._filter_hits_by_allowed_libraries(hits, allowed_libraries)
            return self._provider_response(request, hits, errors)

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("TMDB search error: %s", e)
            return None

    async def _provider_search_flags(
        self,
        search_type: SearchType,
        allowed_libraries: list[str] | None,
    ) -> dict[str, bool]:
        flags = {
            "movies": await self._should_search_movies(search_type),
            "shows": await self._should_search_shows(search_type),
            "games": await self._should_search_games(search_type),
            "music": await self._should_search_music(search_type),
            "books": await self._should_search_books(search_type),
        }
        if allowed_libraries is None:
            return flags

        allowed = set(allowed_libraries)
        return {
            "movies": flags["movies"] and "movies" in allowed,
            "shows": flags["shows"] and "series" in allowed,
            "games": flags["games"] and "games" in allowed,
            "music": flags["music"] and "music" in allowed,
            "books": flags["books"] and "books" in allowed,
        }

    @staticmethod
    def _no_active_provider_result(request: SearchRequest) -> dict[str, Any]:
        return {
            "hits": [],
            "total": 0,
            "page": request.page,
            "per_page": request.per_page,
            "total_pages": 0,
            "query": request.query,
            "search_type": request.search_type,
            "took": 0,
            "source": "provider",
            "provider": "tmdb",
            "message": "No active libraries for the requested media types",
        }

    async def _provider_clients(self, search_flags: dict[str, bool]):
        return await asyncio.gather(
            self._get_tmdb_client()
            if (search_flags["movies"] or search_flags["shows"])
            else _none(),
            self._get_igdb_client() if search_flags["games"] else _none(),
            self._get_spotify_client() if search_flags["music"] else _none(),
        )

    def _provider_tasks(
        self,
        request: SearchRequest,
        *,
        search_flags: dict[str, bool],
        tmdb,
        igdb,
        spotify,
    ) -> dict[str, Any]:
        tasks: dict[str, Any] = {}
        if tmdb and search_flags["movies"]:
            tasks["tmdb_movies"] = self._search_tmdb_movies(tmdb, request)
        if tmdb and search_flags["shows"]:
            tasks["tmdb_shows"] = self._search_tmdb_shows(tmdb, request)
        if igdb and search_flags["games"]:
            tasks["igdb_games"] = self._search_igdb_games(igdb, request)
        if spotify and search_flags["music"]:
            tasks["spotify_artists"] = self._search_spotify_artists(spotify, request)
        if search_flags["books"]:
            tasks["openlibrary_books"] = self._search_openlibrary_books(request)
        return tasks

    async def _collect_provider_results(
        self,
        tasks: dict[str, Any],
    ) -> tuple[list[dict], list[str]]:
        hits: list[dict] = []
        errors: list[str] = []
        if not tasks:
            return hits, errors

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for label, result in zip(tasks.keys(), results, strict=True):
            if isinstance(result, TRANSIENT_SEARCH_ERRORS):
                logger.warning("Provider search %s unavailable: %s", label, result)
                errors.append(label)
                continue
            if isinstance(result, Exception):
                logger.error(
                    "Provider search %s failed unexpectedly",
                    label,
                    exc_info=(type(result), result, result.__traceback__),
                )
                raise result
            if result is None:
                continue
            if result.get("error"):
                logger.warning("Provider search %s returned error: %s", label, result["error"])
                errors.append(label)
                continue
            logger.debug("%s results: %s found", label, len(result.get("hits", [])))
            hits.extend(result.get("hits", []))
        return hits, errors

    @staticmethod
    def _provider_response(
        request: SearchRequest,
        hits: list[dict],
        errors: list[str] | None = None,
    ) -> dict[str, Any]:
        if request.search_type == SearchType.ALL:
            hits.sort(key=lambda x: x.get("score", 0), reverse=True)

        total = len(hits)
        start_idx = (request.page - 1) * request.per_page
        end_idx = start_idx + request.per_page
        response: dict[str, Any] = {
            "hits": hits[start_idx:end_idx],
            "total": total,
            "page": request.page,
            "per_page": request.per_page,
            "total_pages": (total + request.per_page - 1) // request.per_page,
            "query": request.query,
            "search_type": request.search_type,
            "took": 0,
            "source": "provider",
            "provider": "tmdb",
        }
        if errors:
            response["partial"] = True
            response["errors"] = errors
        return response

    @staticmethod
    def _filter_hits_by_allowed_libraries(
        hits: list[dict],
        allowed_libraries: list[str] | None,
    ) -> list[dict]:
        """Return only the hits for libraries the current user can access."""
        if allowed_libraries is None:
            return hits

        type_to_library = {
            SearchType.MOVIES.value: "movies",
            SearchType.SHOWS.value: "series",
            SearchType.GAMES.value: "games",
            SearchType.MUSIC.value: "music",
            SearchType.BOOKS.value: "books",
        }
        allowed = set(allowed_libraries)
        return [
            hit for hit in hits
            if type_to_library.get(str(hit.get("type"))) in allowed
        ]

    @staticmethod
    def _filter_results_by_allowed_libraries(
        results: dict[str, Any],
        allowed_libraries: list[str] | None,
    ) -> dict[str, Any]:
        """Remove hits for libraries the current user cannot access."""
        if allowed_libraries is None or not isinstance(results, dict):
            return results

        original = results.get("hits", [])
        hits = SearchService._filter_hits_by_allowed_libraries(
            original, allowed_libraries
        )
        removed = len(original) - len(hits)

        filtered = dict(results)
        filtered["hits"] = hits
        filtered["total"] = max(0, (results.get("total") or len(original)) - removed)
        per_page = filtered.get("per_page") or len(hits) or 1
        filtered["total_pages"] = (filtered["total"] + per_page - 1) // per_page
        return filtered

    async def _search_tmdb_movies(
        self, tmdb: TMDB, request: SearchRequest
    ) -> dict[str, Any]:
        """Search TMDB for movies."""
        try:
            year = None
            if request.year_from and request.year_from == request.year_to:
                year = request.year_from

            logger.debug("Calling TMDB search_movies: query='%s', year=%s", request.query, year)
            results = await tmdb.search_movies(request.query, year=year)
            logger.debug(
                "TMDB search_movies raw result: %s - keys: %s",
                type(results), results.keys() if isinstance(results, dict) else 'N/A',
            )

            if not results or "results" not in results:
                logger.warning("TMDB search_movies returned no 'results' key: %s", results)
                return {"hits": [], "total": 0}

            hits = []
            for idx, movie in enumerate(results.get("results", [])):
                hit = self._transform_tmdb_movie(movie, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": results.get("total_results", len(hits)),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("TMDB movie search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    async def _search_tmdb_shows(
        self, tmdb: TMDB, request: SearchRequest
    ) -> dict[str, Any]:
        """Search TMDB for TV shows."""
        try:
            # TMDB uses different endpoint for TV search
            params = {"query": request.query}
            if request.year_from and request.year_from == request.year_to:
                params["first_air_date_year"] = request.year_from

            logger.debug("Calling TMDB search/tv: params=%s", params)
            results = await tmdb._request("search/tv", params=params)
            logger.debug(
                "TMDB search/tv raw result: %s - keys: %s",
                type(results), results.keys() if isinstance(results, dict) else 'N/A',
            )

            if not results or "results" not in results:
                logger.warning("TMDB search/tv returned no 'results' key: %s", results)
                return {"hits": [], "total": 0}

            hits = []
            for idx, show in enumerate(results.get("results", [])):
                hit = self._transform_tmdb_show(show, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": results.get("total_results", len(hits)),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("TMDB show search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    # ── Search-hit builder ─────────────────────────────────────────────

    @staticmethod
    def _relevance_score(raw: float, index: int, divisor: float = 100) -> float:
        """Compute a 0-10 relevance score from a raw value and result position."""
        base = (raw or 0) / divisor
        position_boost = max(0, 1 - (index * 0.05))
        return min(base + position_boost, 10.0)

    @staticmethod
    def _build_search_hit(*, overrides: dict[str, Any]) -> dict[str, Any]:
        """
        Return a search-hit dict with sensible defaults.

        Callers pass only the fields that differ from the defaults via
        *overrides*.
        """
        hit: dict[str, Any] = {
            "id": None,
            "tmdb_id": None,
            "igdb_id": None,
            "spotify_id": None,
            "type": SearchType.MOVIES,
            "score": 0.0,
            "title": "",
            "original_title": None,
            "description": None,
            "tagline": None,
            "poster_path": None,
            "backdrop_path": None,
            "release_date": None,
            "first_air_date": None,
            "genres": [],
            "genre_ids": [],
            "created_at": None,
            "updated_at": None,
            "status": None,
            "number_of_seasons": None,
            "number_of_episodes": None,
            "popularity": None,
            "vote_average": None,
            "vote_count": None,
            "source": "provider",
            "in_library": False,
        }
        hit.update(overrides)
        return hit

    # ── Transform helpers ────────────────────────────────────────────────

    def _transform_tmdb_movie(self, movie: dict, index: int) -> dict[str, Any]:
        """Transform TMDB movie result to unified search hit format."""
        return self._build_search_hit(overrides={
            "tmdb_id": movie.get("id"),
            "type": SearchType.MOVIES,
            "score": self._relevance_score(movie.get("popularity", 0), index),
            "title": movie.get("title", ""),
            "original_title": movie.get("original_title"),
            "description": movie.get("overview"),
            "poster_path": movie.get("poster_path"),
            "backdrop_path": movie.get("backdrop_path"),
            "release_date": movie.get("release_date"),
            "genre_ids": movie.get("genre_ids", []),
            "popularity": movie.get("popularity"),
            "vote_average": movie.get("vote_average"),
            "vote_count": movie.get("vote_count"),
            "source": "tmdb",
        })

    def _transform_tmdb_show(self, show: dict, index: int) -> dict[str, Any]:
        """Transform TMDB show result to unified search hit format."""
        return self._build_search_hit(overrides={
            "tmdb_id": show.get("id"),
            "type": SearchType.SHOWS,
            "score": self._relevance_score(show.get("popularity", 0), index),
            "title": show.get("name", ""),
            "original_title": show.get("original_name"),
            "description": show.get("overview"),
            "poster_path": show.get("poster_path"),
            "backdrop_path": show.get("backdrop_path"),
            "first_air_date": show.get("first_air_date"),
            "genre_ids": show.get("genre_ids", []),
            "popularity": show.get("popularity"),
            "vote_average": show.get("vote_average"),
            "vote_count": show.get("vote_count"),
            "source": "tmdb",
        })

    async def _search_igdb_games(
        self, igdb: IGDB, request: SearchRequest
    ) -> dict[str, Any]:
        """Search IGDB for games."""
        try:
            logger.debug("Calling IGDB search_games: query='%s'", request.query)
            results = await igdb.search_games(request.query, limit=20)

            if not results:
                return {"hits": [], "total": 0}

            hits = []
            for idx, game in enumerate(results):
                hit = self._transform_igdb_game(game, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": len(hits),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("IGDB game search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    @staticmethod
    def _igdb_cover_url(cover: dict | None) -> str | None:
        """Build a poster URL from an IGDB cover dict."""
        if isinstance(cover, dict) and cover.get("image_id"):
            return f"https://images.igdb.com/igdb/image/upload/t_cover_big/{cover['image_id']}.jpg"
        return None

    @staticmethod
    def _igdb_release_date(timestamp: int | None) -> str | None:
        """Convert a UNIX timestamp to a YYYY-MM-DD string."""
        if not timestamp:
            return None
        from datetime import UTC, datetime as dt
        try:
            return dt.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d")
        except (OSError, ValueError):
            return None

    def _transform_igdb_game(self, game: dict, index: int) -> dict[str, Any]:
        """Transform IGDB game result to unified search hit format."""
        genres = [g.get("name") for g in game.get("genres", []) if g.get("name")]

        return self._build_search_hit(overrides={
            "igdb_id": game.get("id"),
            "type": SearchType.GAMES,
            "score": self._relevance_score(game.get("rating", 0), index, divisor=10),
            "title": game.get("name", ""),
            "description": game.get("summary"),
            "poster_path": self._igdb_cover_url(game.get("cover")),
            "release_date": self._igdb_release_date(game.get("first_release_date")),
            "genres": genres,
            "vote_average": game.get("rating"),
            "vote_count": game.get("rating_count"),
            "source": "igdb",
        })

    async def _search_openlibrary_books(
        self, request: SearchRequest
    ) -> dict[str, Any]:
        """Search Open Library for books."""
        try:
            from pyrate.metadata.openlibrary import OpenLibrary

            client = OpenLibrary()
            try:
                results = await client.search(request.query, limit=20)
            finally:
                await client.close()

            if not results:
                return {"hits": [], "total": 0}

            hits = []
            for idx, book in enumerate(results):
                author_str = ", ".join(book.get("authors", []))
                year = book.get("year")
                hit = self._build_search_hit(overrides={
                    "openlibrary_id": book.get("id"),
                    "type": SearchType.BOOKS,
                    "score": max(0.0, 10.0 - idx * 0.5),
                    "title": book.get("title", ""),
                    "description": author_str,
                    "poster_path": book.get("cover_url"),
                    "release_date": f"{year}-01-01" if year else None,
                    "genres": book.get("subjects", [])[:5],
                    "vote_average": None,
                    "source": "openlibrary",
                })
                hits.append(hit)

            return {"hits": hits, "total": len(hits)}

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("Open Library book search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    async def _search_spotify_albums(
        self, spotify: Spotify, request: SearchRequest
    ) -> dict[str, Any]:
        """Search Spotify for music albums."""
        try:
            logger.debug("Calling Spotify search_albums: query='%s'", request.query)
            results = await spotify.search_albums(request.query, limit=20)

            if not results:
                return {"hits": [], "total": 0}

            hits = []
            for idx, album in enumerate(results):
                hit = self._transform_spotify_album(album, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": len(hits),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("Spotify album search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    @staticmethod
    def _spotify_image_url(images: list[dict]) -> str | None:
        """Return the URL of the first (largest) Spotify image, or None."""
        return images[0].get("url") if images else None

    @staticmethod
    def _artist_names_str(artists: list[dict]) -> str | None:
        """Join artist names into a comma-separated string."""
        names = [a.get("name") for a in artists if a.get("name")]
        return ", ".join(names) if names else None

    def _transform_spotify_album(self, album: dict, index: int) -> dict[str, Any]:
        """Transform Spotify album result to unified search hit format."""
        return self._build_search_hit(overrides={
            "spotify_id": album.get("id"),
            "type": SearchType.MUSIC,
            "score": self._relevance_score(album.get("popularity", 0), index),
            "title": album.get("name", ""),
            "description": self._artist_names_str(album.get("artists", [])),
            "poster_path": self._spotify_image_url(album.get("images", [])),
            "release_date": album.get("release_date"),
            "status": album.get("album_type"),
            "number_of_episodes": album.get("total_tracks"),
            "popularity": album.get("popularity"),
            "source": "spotify",
        })

    async def _search_spotify_artists(
        self, spotify: Spotify, request: SearchRequest
    ) -> dict[str, Any]:
        """Search Spotify for artists."""
        try:
            logger.debug("Calling Spotify search_artists: query='%s'", request.query)
            results = await spotify.search_artists(request.query, limit=10)

            if not results:
                return {"hits": [], "total": 0}

            hits = []
            for idx, artist in enumerate(results):
                hit = self._transform_spotify_artist(artist, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": len(hits),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("Spotify artist search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    def _transform_spotify_artist(self, artist: dict, index: int) -> dict[str, Any]:
        """Transform Spotify artist result to unified search hit format."""
        return self._build_search_hit(overrides={
            "spotify_id": artist.get("id"),
            "type": SearchType.MUSIC,
            "music_type": "artist",
            "score": self._relevance_score(artist.get("popularity", 0), index),
            "title": artist.get("name", ""),
            "poster_path": self._spotify_image_url(artist.get("images", [])),
            "genres": artist.get("genres", []),
            "popularity": artist.get("popularity"),
            "source": "spotify",
        })

    async def _search_spotify_tracks(
        self, spotify: Spotify, request: SearchRequest
    ) -> dict[str, Any]:
        """Search Spotify for tracks."""
        try:
            logger.debug("Calling Spotify search_tracks: query='%s'", request.query)
            results = await spotify.search_tracks(request.query, limit=10)

            if not results:
                return {"hits": [], "total": 0}

            hits = []
            for idx, track in enumerate(results):
                hit = self._transform_spotify_track(track, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": len(hits),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("Spotify track search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    def _transform_spotify_track(self, track: dict, index: int) -> dict[str, Any]:
        """Transform Spotify track result to unified search hit format."""
        album = track.get("album", {})

        return self._build_search_hit(overrides={
            "spotify_id": track.get("id"),
            "album_spotify_id": album.get("id"),
            "type": SearchType.MUSIC,
            "music_type": "track",
            "score": self._relevance_score(track.get("popularity", 0), index),
            "title": track.get("name", ""),
            "description": self._artist_names_str(track.get("artists", [])),
            "poster_path": self._spotify_image_url(album.get("images", [])),
            "release_date": album.get("release_date"),
            "popularity": track.get("popularity"),
            "source": "spotify",
        })

    async def _search_local(self, request: SearchRequest) -> dict[str, Any]:
        """Fall back to local Elasticsearch search."""
        try:
            if request.search_type == SearchType.MOVIES:
                result = await elasticsearch_service.search_movies(request)
            elif request.search_type == SearchType.SHOWS:
                result = await elasticsearch_service.search_shows(request)
            else:
                result = await elasticsearch_service.search_all(request)

            # Mark results as from local source
            if isinstance(result, dict):
                result["source"] = "local"
                result["provider"] = "elasticsearch"

            return result

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("Local search error: %s", e)
            # Return empty results on failure
            return {
                "hits": [],
                "total": 0,
                "page": request.page,
                "per_page": request.per_page,
                "total_pages": 0,
                "query": request.query,
                "search_type": request.search_type,
                "took": 0,
                "source": "local",
                "provider": "elasticsearch",
                "error": str(e),
            }

    async def _exists_in_library(self, provider: str, external_id, media_type) -> bool:
        """Check whether a media item with the given external ID already exists locally."""
        from pyrate.models.media import MediaExternalId, MediaItem

        result = await self.db.execute(
            select(MediaItem.guid)
            .join(MediaExternalId)
            .where(MediaExternalId.external_id == str(external_id))
            .where(MediaExternalId.provider == provider)
            .where(MediaItem.media_type == media_type)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def _dispatch_import(hit_type, hit: dict, external_id) -> None:
        """Send a single item to the appropriate import worker task."""
        from pyrate.worker import import_album, import_artist, import_book, import_game, import_movie, import_show

        if hit_type == SearchType.BOOKS:
            await import_book.kiq(external_id)
            logger.debug("Queued book import: OpenLibrary %s", external_id)
        elif hit_type == SearchType.MOVIES:
            await import_movie.kiq(external_id)
            logger.debug("Queued movie import: TMDB %s", external_id)
        elif hit_type == SearchType.SHOWS:
            await import_show.kiq(external_id)
            logger.debug("Queued show import: TMDB %s", external_id)
        elif hit_type == SearchType.GAMES:
            await import_game.kiq(external_id)
            logger.debug("Queued game import: IGDB %s", external_id)
        elif hit_type == SearchType.MUSIC:
            if hit.get("music_type") == "artist":
                await import_artist.kiq(external_id)
                logger.debug("Queued artist import: Spotify %s", external_id)
            else:
                await import_album.kiq(external_id)
                logger.debug("Queued album import: Spotify %s", external_id)

    async def _queue_imports(self, hits: list[dict], search_type: SearchType) -> None:
        """
        Queue search results for metadata import.

        Only queues items that:
        1. Have an active library for their type
        2. Don't already exist in the library
        3. Don't have an existing import lock (not already queued)
        """
        try:
            active_types = await self._get_active_library_types()

            for hit in hits:
                resolved = self._resolve_hit_provider(hit, fallback_type=search_type)
                if not resolved:
                    continue
                external_id, provider, type_str, media_type = resolved

                if type_str not in active_types:
                    logger.info(
                        "Skipping import for %s %s - no active %s library (active: %s)",
                        provider, external_id, type_str, active_types,
                    )
                    continue

                try:
                    if await self._exists_in_library(provider, external_id, media_type):
                        logger.debug("Skipping import for %s %s - already in library", provider, external_id)
                        continue

                    if not await self._acquire_import_lock(type_str, external_id):
                        logger.info("Skipping import for %s %s - already queued (lock exists)", provider, external_id)
                        continue

                    hit_type = hit.get("type", search_type)
                    logger.info("Dispatching import: type=%s provider=%s id=%s", hit_type, provider, external_id)
                    await self._dispatch_import(hit_type, hit, external_id)

                except Exception as e:
                    logger.warning("Failed to queue import for %s %s: %s", provider, external_id, e)

        except ImportError as e:
            logger.warning("Could not import worker tasks for queuing: %s", e)
        except Exception as e:
            logger.error("Error queuing imports: %s", e)

    async def enrich_with_library_status(self, hits: list[dict]) -> list[dict]:
        """Enrich search results with library status (presence of a local row).

        Replaces the previous N+1 — one ``SELECT MediaItem JOIN MediaExternalId``
        per hit — with a single batched query keyed on
        ``(provider, external_id, media_type)``. For a typical 50-hit result
        set that's 1 round-trip instead of 50.
        """
        if not hits:
            return hits

        keys, hit_keys = self._library_status_keys(hits)
        if not keys:
            return hits

        try:
            lookup = await self._library_status_lookup(keys)
        except Exception as e:
            logger.warning("Batched library-status enrichment failed: %s", e)
            return hits

        self._apply_library_status(hits, hit_keys, lookup)
        return hits

    def _library_status_keys(
        self,
        hits: list[dict],
    ) -> tuple[list[tuple[str, str, Any]], list[tuple[str, str, Any] | None]]:
        keys: list[tuple[str, str, Any]] = []
        hit_keys: list[tuple[str, str, Any] | None] = []
        for hit in hits:
            resolved = self._resolve_hit_provider(hit)

            # Special case: for library-status we want to look up the
            # track itself (SONGS), not the parent album.
            if (
                hit.get("type") == SearchType.MUSIC
                and hit.get("music_type") == "track"
            ):
                ext_id = hit.get("spotify_id")
                resolved = (ext_id, "spotify", "MUSIC", MediaType.SONGS) if ext_id else None

            if not resolved:
                hit_keys.append(None)
                continue

            external_id, provider, _type_str, media_type = resolved
            key = (provider, str(external_id), media_type)
            keys.append(key)
            hit_keys.append(key)
        return keys, hit_keys

    async def _library_status_lookup(
        self,
        keys: list[tuple[str, str, Any]],
    ) -> dict[tuple[str, str, Any], str]:
        providers_and_ids_by_type: dict[Any, list[tuple[str, str]]] = {}
        for provider, ext_id, media_type in keys:
            providers_and_ids_by_type.setdefault(media_type, []).append(
                (provider, ext_id)
            )

        lookup: dict[tuple[str, str, Any], str] = {}
        for media_type, pairs in providers_and_ids_by_type.items():
            if not pairs:
                continue
            unique_pairs = list(set(pairs))
            stmt = (
                select(
                    MediaExternalId.provider,
                    MediaExternalId.external_id,
                    MediaItem.guid,
                )
                .join(MediaItem, MediaItem.guid == MediaExternalId.media_item_guid)
                .where(
                    tuple_(
                        MediaExternalId.provider,
                        MediaExternalId.external_id,
                    ).in_(unique_pairs)
                )
                .where(MediaItem.media_type == media_type)
            )
            result = await self.db.execute(stmt)
            for provider, external_id, guid in result.all():
                lookup[(provider, external_id, media_type)] = str(guid)
        return lookup

    @staticmethod
    def _apply_library_status(
        hits: list[dict],
        hit_keys: list[tuple[str, str, Any] | None],
        lookup: dict[tuple[str, str, Any], str],
    ) -> None:
        for hit, key in zip(hits, hit_keys, strict=True):
            if key is None:
                continue
            guid = lookup.get(key)
            if guid:
                hit["in_library"] = True
                hit["id"] = guid

    # ── Per-provider synchronous import helpers ───────────────────────────

    async def _import_igdb_game(self, external_id, media_service) -> Any:
        """Fetch and persist a game from IGDB. Returns the new MediaItem."""
        from datetime import UTC, datetime as dt
        from pyrate.models.media import AvailabilityStatus, MediaType

        igdb = await self._get_igdb_client()
        if not igdb:
            logger.error("IGDB client not available for synchronous import")
            return None

        details = await igdb.get_game_details(int(external_id))
        if not details:
            logger.error("IGDB returned no details for game %s", external_id)
            return None

        release_date = None
        if details.get("first_release_date"):
            try:
                release_date = dt.fromtimestamp(details["first_release_date"], tz=UTC).date()
            except (OSError, ValueError):
                logger.debug("Invalid IGDB timestamp: %s", details["first_release_date"])

        media_item = await media_service.create_media_item(
            media_type=MediaType.GAMES,
            title=details.get("name", "Unknown"),
            description=details.get("summary"),
            release_date=release_date,
            poster_path=self._igdb_cover_url(details.get("cover")),
            availability_status=AvailabilityStatus.DOWNLOADABLE,
            commit=False,
        )

        await media_service.add_external_id(
            media_item_guid=media_item.guid,
            provider="igdb",
            external_id=str(external_id),
            commit=False,
        )

        genres = [g.get("name") for g in details.get("genres", []) if g.get("name")]
        if genres:
            await media_service.set_genres(media_item.guid, genres, commit=False)

        return media_item

    async def _import_spotify_album(self, external_id, media_service) -> Any:
        """Fetch and persist an album from Spotify. Returns the new MediaItem."""
        from pyrate.models.media import AvailabilityStatus, MediaType

        spotify = await self._get_spotify_client()
        if not spotify:
            logger.error("Spotify client not available for synchronous import")
            return None

        details = await spotify.get_album_details(str(external_id))
        if not details:
            logger.error("Spotify returned no details for album %s", external_id)
            return None

        release_date = self._parse_spotify_date(details.get("release_date"))

        artists = details.get("artists", [])
        artist_names = [a.get("name") for a in artists if a.get("name")]
        description = ", ".join(artist_names) if artist_names else None

        media_item = await media_service.create_media_item(
            media_type=MediaType.ALBUMS,
            title=details.get("name", "Unknown"),
            description=description,
            release_date=release_date,
            poster_path=self._spotify_image_url(details.get("images", [])),
            availability_status=AvailabilityStatus.DOWNLOADABLE,
            commit=False,
        )

        await media_service.add_external_id(
            media_item_guid=media_item.guid,
            provider="spotify",
            external_id=str(external_id),
            commit=False,
        )

        # Spotify rarely populates genres at album level;
        # fall back to the primary artist's genres.
        genres = details.get("genres", [])
        if not genres and artists:
            primary_artist_id = artists[0].get("id")
            if primary_artist_id:
                artist_details = await spotify.get_artist_details(primary_artist_id)
                genres = artist_details.get("genres", [])
        if genres:
            await media_service.set_genres(media_item.guid, genres, commit=False)

        return media_item

    async def _import_spotify_artist(self, external_id, media_service) -> Any:
        """Fetch and persist an artist from Spotify. Returns the new MediaItem."""
        from pyrate.models.media import AvailabilityStatus, MediaType

        spotify = await self._get_spotify_client()
        if not spotify:
            logger.error("Spotify client not available for synchronous import")
            return None

        details = await spotify.get_artist_details(str(external_id))
        if not details:
            logger.error("Spotify returned no details for artist %s", external_id)
            return None

        media_item = await media_service.create_media_item(
            media_type=MediaType.ARTISTS,
            title=details.get("name", "Unknown"),
            poster_path=self._spotify_image_url(details.get("images", [])),
            availability_status=AvailabilityStatus.DOWNLOADABLE,
            commit=False,
        )

        await media_service.add_external_id(
            media_item_guid=media_item.guid,
            provider="spotify",
            external_id=str(external_id),
            commit=False,
        )

        genres = details.get("genres", [])
        if genres:
            await media_service.set_genres(media_item.guid, genres, commit=False)

        # Queue album imports for this artist in the background
        try:
            from pyrate.worker import import_album as import_album_task

            artist_albums = await spotify.get_artist_albums(str(external_id), limit=20)
            for album in artist_albums:
                album_id = album.get("id")
                if album_id:
                    await import_album_task.kiq(album_id)
        except Exception as e:
            logger.warning("Failed to queue artist album imports: %s", e)

        return media_item

    async def _import_spotify_song(self, external_id) -> dict[str, str] | None:
        """Import a song by importing its parent album, then look up the track."""
        from pyrate.models.media import MediaExternalId, MediaItem, MediaType

        spotify = await self._get_spotify_client()
        if not spotify:
            logger.error("Spotify client not available for synchronous import")
            return None

        track_details = await spotify.get_track_details(str(external_id))
        if not track_details:
            logger.error("Spotify returned no details for track %s", external_id)
            return None

        album_spotify_id = track_details.get("album", {}).get("id")
        if not album_spotify_id:
            logger.error("Track %s has no parent album", external_id)
            return None

        # Import the full album hierarchy (creates artist -> album -> songs)
        from pyrate.worker import import_album as _sync_import_album
        await _sync_import_album(album_spotify_id)

        result = await self.db.execute(
            select(MediaItem.guid)
            .join(MediaExternalId)
            .where(MediaExternalId.external_id == str(external_id))
            .where(MediaExternalId.provider == "spotify")
            .where(MediaItem.media_type == MediaType.SONGS)
            .limit(1)
        )
        row = result.first()
        if row:
            await self.db.commit()
            return {"guid": str(row[0]), "library_guid": None}

        logger.error("Song %s not found after album import", external_id)
        return None

    async def _import_tmdb_movie(self, tmdb_id, media_service) -> Any:
        """Fetch and persist a movie from TMDB. Returns the new MediaItem."""
        from pyrate.models.media import AvailabilityStatus, MediaType

        tmdb = await self._get_tmdb_client()
        if not tmdb:
            logger.error("TMDB client not available for synchronous import")
            return None

        details = await tmdb.get_movie_details(str(tmdb_id))
        if not details:
            logger.error("TMDB returned no details for movie %s", tmdb_id)
            return None

        media_item = await media_service.create_media_item(
            media_type=MediaType.MOVIES,
            title=details.get("title", "Unknown"),
            original_title=details.get("original_title"),
            description=details.get("overview"),
            release_date=self._parse_date(details.get("release_date"), label="TMDB release date"),
            poster_path=details.get("poster_path"),
            backdrop_path=details.get("backdrop_path"),
            extra_data=details.get("original_language"),
            availability_status=AvailabilityStatus.DOWNLOADABLE,
            commit=False,
        )

        await media_service.add_external_id(
            media_item_guid=media_item.guid,
            provider="tmdb",
            external_id=str(tmdb_id),
            commit=False,
        )
        external_ids = details.get("external_ids", {})
        if external_ids.get("imdb_id"):
            await media_service.add_external_id(
                media_item_guid=media_item.guid,
                provider="imdb",
                external_id=external_ids["imdb_id"],
                commit=False,
            )

        genres = [g.get("name") for g in details.get("genres", []) if g.get("name")]
        if genres:
            await media_service.set_genres(media_item.guid, genres, commit=False)

        return media_item

    async def _import_tmdb_show(self, tmdb_id, media_service) -> Any:
        """Fetch and persist a show from TMDB. Returns the new MediaItem."""
        from pyrate.models.media import AvailabilityStatus, MediaType

        tmdb = await self._get_tmdb_client()
        if not tmdb:
            logger.error("TMDB client not available for synchronous import")
            return None

        details = await tmdb.get_show_details(str(tmdb_id))
        if not details:
            logger.error("TMDB returned no details for show %s", tmdb_id)
            return None

        media_item = await media_service.create_media_item(
            media_type=MediaType.SHOWS,
            title=details.get("name", "Unknown"),
            original_title=details.get("original_name"),
            description=details.get("overview"),
            release_date=self._parse_date(details.get("first_air_date"), label="TMDB first_air_date"),
            poster_path=details.get("poster_path"),
            backdrop_path=details.get("backdrop_path"),
            extra_data=details.get("original_language"),
            availability_status=AvailabilityStatus.DOWNLOADABLE,
            commit=False,
        )

        await media_service.add_external_id(
            media_item_guid=media_item.guid,
            provider="tmdb",
            external_id=str(tmdb_id),
            commit=False,
        )
        external_ids = details.get("external_ids", {})
        if external_ids.get("tvdb_id"):
            await media_service.add_external_id(
                media_item_guid=media_item.guid,
                provider="tvdb",
                external_id=str(external_ids["tvdb_id"]),
                commit=False,
            )
        if external_ids.get("imdb_id"):
            await media_service.add_external_id(
                media_item_guid=media_item.guid,
                provider="imdb",
                external_id=external_ids["imdb_id"],
                commit=False,
            )

        genres = [g.get("name") for g in details.get("genres", []) if g.get("name")]
        if genres:
            await media_service.set_genres(media_item.guid, genres, commit=False)

        return media_item

    # ── Public import entry point ───────────────────────────────────────

    async def get_or_import_item(
        self,
        tmdb_id: int | None = None,
        igdb_id: int | None = None,
        spotify_id: str | None = None,
        media_type_str: str = "",
    ) -> dict[str, str] | None:
        """
        Get a media item from the local DB or import it synchronously from a provider.

        Args:
            tmdb_id: TMDB ID of the item (for movies/shows)
            igdb_id: IGDB ID of the item (for games)
            spotify_id: Spotify ID of the item (for music albums)
            media_type_str: "MOVIES", "SHOWS", "GAMES", or "MUSIC"

        Returns:
            dict with guid and library_guid, or None on failure
        """
        type_upper = media_type_str.upper()
        media_type, external_id, provider = self._resolve_import_target(
            type_upper=type_upper,
            tmdb_id=tmdb_id,
            igdb_id=igdb_id,
            spotify_id=spotify_id,
        )

        if not external_id:
            logger.error("No external ID provided for %s import", type_upper)
            return None

        existing = await self._existing_imported_item(
            media_type=media_type,
            provider=provider,
            external_id=external_id,
        )
        if existing:
            logger.info(
                "%s %s already in library, returning existing item",
                provider,
                external_id,
            )
            return existing

        if not await self._active_library_exists(type_upper):
            logger.error(
                "No active library for %s, cannot import %s %s",
                type_upper,
                provider,
                external_id,
            )
            return None

        if not await self._acquire_import_lock(type_upper, external_id):
            logger.info(
                "Import already in progress for %s %s, returning existing if present",
                provider,
                external_id,
            )
            return await self._existing_imported_item(
                media_type=media_type,
                provider=provider,
                external_id=external_id,
            )

        try:
            return await self._import_external_item(
                type_upper=type_upper,
                media_type=media_type,
                provider=provider,
                external_id=external_id,
            )
        except IntegrityError:
            logger.info(
                "Concurrent import created %s %s, returning existing item",
                provider,
                external_id,
            )
            await self.db.rollback()
            return await self._existing_imported_item(
                media_type=media_type,
                provider=provider,
                external_id=external_id,
            )
        except Exception as e:
            logger.error(
                "Synchronous import failed for %s %s: %s",
                provider,
                external_id,
                e,
            )
            await self.db.rollback()
            return None
        finally:
            await self._release_import_lock(type_upper, external_id)

    @staticmethod
    def _resolve_import_target(
        *,
        type_upper: str,
        tmdb_id: int | None,
        igdb_id: int | None,
        spotify_id: str | None,
    ) -> tuple[MediaType, int | str | None, str]:
        type_map: dict[str, tuple] = {
            "GAMES":   (MediaType.GAMES,   igdb_id,     "igdb"),
            "MUSIC":   (MediaType.ALBUMS,  spotify_id,  "spotify"),
            "ALBUMS":  (MediaType.ALBUMS,  spotify_id,  "spotify"),
            "ARTISTS": (MediaType.ARTISTS, spotify_id,  "spotify"),
            "SONGS":   (MediaType.SONGS,   spotify_id,  "spotify"),
            "MOVIES":  (MediaType.MOVIES,  tmdb_id,     "tmdb"),
        }
        return type_map.get(
            type_upper, (MediaType.SHOWS, tmdb_id, "tmdb")
        )

    async def _existing_imported_item(
        self,
        *,
        media_type: MediaType,
        provider: str,
        external_id: int | str,
    ) -> dict[str, str] | None:
        result = await self.db.execute(
            select(MediaItem.guid)
            .join(MediaExternalId)
            .where(MediaExternalId.external_id == str(external_id))
            .where(MediaExternalId.provider == provider)
            .where(MediaItem.media_type == media_type)
            .limit(1)
        )
        row = result.first()
        return {"guid": str(row[0]), "library_guid": None} if row else None

    async def _active_library_exists(self, type_upper: str) -> bool:
        library_type = "MUSIC" if type_upper in ("ARTISTS", "SONGS", "MUSIC") else type_upper
        lib_result = await self.db.execute(
            select(Library.guid)
            .where(Library.type.ilike(library_type))
            .where(Library.enabled == True)  # noqa: E712
            .limit(1)
        )
        return lib_result.scalar_one_or_none() is not None

    async def _import_external_item(
        self,
        *,
        type_upper: str,
        media_type: MediaType,
        provider: str,
        external_id: int | str,
    ) -> dict[str, str] | None:
        if media_type == MediaType.SONGS:
            return await self._import_spotify_song(external_id)

        media_service = MediaService(self.db)
        import_dispatch = {
            MediaType.GAMES: lambda: self._import_igdb_game(external_id, media_service),
            MediaType.ALBUMS: lambda: self._import_spotify_album(
                external_id,
                media_service,
            ),
            MediaType.ARTISTS: lambda: self._import_spotify_artist(
                external_id,
                media_service,
            ),
            MediaType.MOVIES: lambda: self._import_tmdb_movie(
                external_id,
                media_service,
            ),
            MediaType.SHOWS: lambda: self._import_tmdb_show(external_id, media_service),
        }
        handler = import_dispatch.get(media_type)
        if not handler:
            logger.error("No import handler for media type %s", media_type)
            return None

        media_item = await handler()
        if not media_item:
            return None

        await self.db.commit()
        logger.info(
            "Synchronously imported %s %s %s -> %s",
            type_upper,
            provider,
            external_id,
            media_item.guid,
        )
        if type_upper == "SHOWS":
            await self._queue_show_import(media_item.guid, int(external_id))
        return {"guid": str(media_item.guid), "library_guid": None}

    @staticmethod
    async def _queue_show_import(media_item_guid, external_id: int) -> None:
        from pyrate.worker import import_show

        await import_show.kiq(external_id)
        logger.info("Queued show import for %s (TMDB %s)", media_item_guid, external_id)

"""
Search Service - Provider-first search with local fallback.

This service implements a search strategy that:
1. First queries metadata providers (TMDB, IGDB, etc.)
2. Falls back to local database/Elasticsearch if provider is unavailable
3. Queues found items for metadata import
4. Only searches for media types that have active libraries
5. Uses Redis locks to prevent duplicate import queueing

``SearchService`` is a thin facade / orchestrator. Two responsibilities have
been extracted into mixins to keep this module focused on orchestration and
the shared client/DB/Redis state:

* :class:`pyrate.services.provider_search.ProviderSearchMixin` — provider
  transforms and per-provider search calls.
* :class:`pyrate.services.search_import_queue.SearchImportQueueMixin` — import
  locking, background import-queue dispatch and synchronous provider imports.

The public API is unchanged: ``SearchService`` and the module-level names
(``IMPORT_LOCK_PREFIX``, ``IMPORT_LOCK_TTL_SECONDS``, ``TRANSIENT_SEARCH_ERRORS``,
client classes …) remain importable from ``pyrate.services.search``.
"""

import asyncio
import logging
import uuid
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.config import settings
from pyrate.metadata.igdb import IGDB
from pyrate.metadata.spotify import Spotify
from pyrate.metadata.tmdb import TMDB
from pyrate.models.library import Library
from pyrate.models.media import MediaExternalId, MediaItem, MediaType
from pyrate.schemas.search import SearchRequest, SearchType
from pyrate.services.elasticsearch import elasticsearch_service
from pyrate.services.media import MediaService
from pyrate.services.provider_search import TRANSIENT_SEARCH_ERRORS, ProviderSearchMixin
from pyrate.services.search_import_queue import (
    IMPORT_LOCK_PREFIX,
    IMPORT_LOCK_TTL_SECONDS,
    SearchImportQueueMixin,
)
from pyrate.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Re-exported for backward compatibility (previously defined here).
__all__ = [
    "SearchService",
    "IMPORT_LOCK_PREFIX",
    "IMPORT_LOCK_TTL_SECONDS",
    "TRANSIENT_SEARCH_ERRORS",
]


async def _none() -> None:
    """Awaitable placeholder used in gather() when a client isn't needed."""
    return None


class SearchService(ProviderSearchMixin, SearchImportQueueMixin):
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
        from sqlalchemy import and_, or_

        from pyrate.models.list import List, ListItem, ListType, ListVisibility

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
        list_guids = [lst.guid for lst in lists]
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
                "guid": str(lst.guid),
                "name": lst.name,
                "description": lst.description,
                "list_type": lst.list_type.value if hasattr(lst.list_type, "value") else str(lst.list_type),
                "visibility": lst.visibility.value if hasattr(lst.visibility, "value") else str(lst.visibility),
                "owner_name": f"{lst.owner.first_name} {lst.owner.last_name}".strip() if lst.owner else None,
                "item_count": lst.item_count,
                "like_count": lst.like_count,
                "poster_path": lst.poster_path,
                "item_types": item_types_map.get(str(lst.guid), []),
            }
            for lst in lists
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

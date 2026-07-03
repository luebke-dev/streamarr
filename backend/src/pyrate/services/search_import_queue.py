"""
Import-queue and locking behaviour for the search service.

This module extracts the *import-queue* responsibility out of the search God
module (``pyrate.services.search``): Redis import locks, the background
import-queue dispatch, and the per-provider synchronous import fetchers.

The behaviour is intentionally identical to the original ``SearchService``
methods — this is a pure move. ``SearchService`` mixes this class in, so all
methods bind to the same instance (``self``) and keep sharing the client
cache, DB session and Redis connection held on the facade. Cross-cutting
helpers that stay on the facade (``_get_redis``, ``_get_*_client``,
``_exists_in_library``, ``_resolve_hit_provider`` …) are reached via ``self``.
"""

import logging
from typing import Any

from sqlalchemy import select

from pyrate.schemas.search import SearchType

logger = logging.getLogger(__name__)

# Redis key prefix / TTL for import locks. Defined here (single source of
# truth) and re-exported by pyrate.services.search for the public API.
IMPORT_LOCK_PREFIX = "pyrate:import_lock:"
IMPORT_LOCK_TTL_SECONDS = 300  # 5 minutes


class SearchImportQueueMixin:
    """Import locking, queue dispatch and synchronous provider imports.

    Mixed into :class:`pyrate.services.search.SearchService`.
    """

    # ── Redis import locks ───────────────────────────────────────────────

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

    # ── Background import queue ───────────────────────────────────────────

    @staticmethod
    async def _dispatch_import(hit_type, hit: dict, external_id) -> None:
        """Send a single item to the appropriate import worker task."""
        from pyrate.worker import (
            import_album,
            import_artist,
            import_book,
            import_game,
            import_movie,
            import_show,
        )

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

    # ── Per-provider synchronous import helpers ───────────────────────────

    async def _import_igdb_game(self, external_id, media_service) -> Any:
        """Fetch and persist a game from IGDB. Returns the new MediaItem."""
        from datetime import UTC
        from datetime import datetime as dt

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
            extra_data=(
                {"original_language": details["original_language"]}
                if details.get("original_language")
                else None
            ),
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
            extra_data=(
                {"original_language": details["original_language"]}
                if details.get("original_language")
                else None
            ),
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

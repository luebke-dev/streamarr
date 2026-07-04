"""TrendingService – manages trending media import and list maintenance."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from pyrate.models.list import List, ListItem, ListItemType, ListType, ListVisibility
from pyrate.models.media import MediaExternalId, MediaItem, MediaRelease, MediaReleaseLink, MediaType
from pyrate.metadata.igdb import IGDB
from pyrate.metadata.spotify import Spotify
from pyrate.metadata.tmdb import TMDB
from pyrate.services.settings import (
    get_country,
    get_igdb_credentials,
    get_spotify_credentials,
    get_tmdb_api_key,
)

logger = logging.getLogger(__name__)


class TrendingService:
    """Service for importing trending media from TMDB and maintaining trending lists."""

    def __init__(self, db) -> None:
        self.db = db
        self._tmdb: TMDB | None = None
        self._igdb: IGDB | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_tmdb(self) -> TMDB:
        if self._tmdb is None:
            api_key = await get_tmdb_api_key(self.db)
            self._tmdb = TMDB(api_key=api_key)
        return self._tmdb

    async def _get_igdb(self) -> IGDB:
        if self._igdb is None:
            client_id, client_secret = await get_igdb_credentials(self.db)
            if not client_id or not client_secret:
                raise ValueError("IGDB credentials not configured")
            self._igdb = IGDB(client_id=client_id, client_secret=client_secret)
        return self._igdb

    async def _get_spotify(self) -> Spotify:
        if not hasattr(self, "_spotify") or self._spotify is None:
            client_id, client_secret = await get_spotify_credentials(self.db)
            if not client_id or not client_secret:
                raise ValueError("Spotify credentials not configured")
            self._spotify = Spotify(client_id=client_id, client_secret=client_secret)
        return self._spotify

    async def _get_or_create_system_list(
        self,
        *,
        update_source: str,
        name: str,
        description: str,
    ) -> List:
        """Return the singleton SYSTEM list for ``update_source``, creating it race-safely.

        Backed by ``uq_list_global_update_source`` — the partial unique
        index for singleton (owner_guid NULL) system lists. Postgres only
        infers a partial unique index for ON CONFLICT when the statement
        repeats the predicate, so we mirror it in ``index_where=``.
        """
        stmt = (
            pg_insert(List)
            .values(
                name=name,
                description=description,
                list_type=ListType.SYSTEM,
                owner_guid=None,
                visibility=ListVisibility.PUBLIC,
                auto_update=True,
                update_source=update_source,
            )
            .on_conflict_do_nothing(
                index_elements=["update_source"],
                index_where=(
                    List.owner_guid.is_(None) & List.update_source.isnot(None)
                ),
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()

        result = await self.db.execute(
            select(List).where(List.update_source == update_source)
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Public API – discovery
    # ------------------------------------------------------------------

    async def _existing_external_id(
        self,
        provider: str,
        external_id: str,
        media_type: MediaType,
    ) -> bool:
        """Return True if a MediaItem already exists for (provider, external_id, type)."""
        result = await self.db.execute(
            select(MediaItem)
            .join(MediaExternalId)
            .where(MediaExternalId.external_id == external_id)
            .where(MediaExternalId.provider == provider)
            .where(MediaItem.media_type == media_type)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_new_trending_movie_ids(self) -> list[int]:
        """Return TMDB IDs of trending movies that are not yet in the database."""
        tmdb = await self._get_tmdb()
        trending = await tmdb.get_trending_movies()
        new_ids: list[int] = []

        for movie in trending.get("results", []):
            tmdb_id = movie.get("id")
            if await self._existing_external_id("tmdb", str(tmdb_id), MediaType.MOVIES):
                logger.info("Trending movie TMDB ID %s already in database", tmdb_id)
            else:
                new_ids.append(tmdb_id)
                logger.info("Queuing import for trending movie TMDB ID %s", tmdb_id)

        return new_ids

    async def get_new_trending_show_ids(self) -> list[int]:
        """Return TMDB IDs of trending shows that are not yet in the database."""
        tmdb = await self._get_tmdb()
        trending = await tmdb.get_trending_shows()
        new_ids: list[int] = []

        for show in trending.get("results", []):
            tmdb_id = show.get("id")
            if await self._existing_external_id("tmdb", str(tmdb_id), MediaType.SHOWS):
                logger.info("Trending show TMDB ID %s already in database", tmdb_id)
            else:
                new_ids.append(tmdb_id)
                logger.info("Queuing import for trending show TMDB ID %s", tmdb_id)

        return new_ids

    async def get_new_trending_game_ids(self) -> list[int]:
        """Return IGDB IDs of trending games that are not yet in the database."""
        igdb = await self._get_igdb()
        trending = await igdb.get_trending_games()
        new_ids: list[int] = []

        for game in trending:
            igdb_id = game.get("id")
            if await self._existing_external_id("igdb", str(igdb_id), MediaType.GAMES):
                logger.info("Trending game IGDB ID %s already in database", igdb_id)
            else:
                new_ids.append(igdb_id)
                logger.info("Queuing import for trending game IGDB ID %s", igdb_id)

        return new_ids

    async def get_new_trending_music_ids(self) -> list[str]:
        """Return Spotify album IDs from the charts that are not yet in the database."""
        spotify = await self._get_spotify()
        trending_albums = await spotify.get_trending_albums(limit=50, country=await get_country(self.db))
        new_ids: list[str] = []

        for album in trending_albums:
            spotify_id = album.get("id")
            if not spotify_id:
                continue
            result = await self.db.execute(
                select(MediaItem)
                .join(MediaExternalId)
                .where(MediaExternalId.external_id == spotify_id)
                .where(MediaExternalId.provider == "spotify")
                .where(MediaItem.media_type == MediaType.ALBUMS)
                .limit(1)
            )
            if result.scalar_one_or_none() is None:
                new_ids.append(spotify_id)
                logger.info("Queuing import for trending album Spotify ID %s (%s)", spotify_id, album.get("name"))
            else:
                logger.debug("Trending album Spotify ID %s already in database", spotify_id)

        await spotify.close()
        return new_ids

    # ------------------------------------------------------------------
    # Public API – list management
    # ------------------------------------------------------------------

    async def update_trending_music_list(self) -> None:
        """Update (or create) the trending music list using Spotify charts."""
        try:
            trending_list = await self._get_or_create_system_list(
                update_source="trending_music",
                name="Trending Music",
                description="Currently trending albums from Spotify Charts",
            )

            # Get trending albums from Spotify
            spotify = await self._get_spotify()
            trending_albums = await spotify.get_trending_albums(limit=50, country=await get_country(self.db))
            trending_spotify_ids = [a["id"] for a in trending_albums if a.get("id")]
            await spotify.close()

            # Find matching albums in DB
            albums = []
            for spotify_id in trending_spotify_ids:
                result = await self.db.execute(
                    select(MediaItem)
                    .join(MediaExternalId)
                    .where(MediaExternalId.provider == "spotify")
                    .where(MediaExternalId.external_id == spotify_id)
                    .where(MediaItem.media_type == MediaType.ALBUMS)
                    .limit(1)
                )
                album = result.scalar_one_or_none()
                if album:
                    albums.append(album)

            # Clear existing list items
            existing = await self.db.execute(
                select(ListItem).where(ListItem.list_guid == trending_list.guid)
            )
            for item in existing.scalars().all():
                await self.db.delete(item)

            for i, album in enumerate(albums[:20]):
                self.db.add(
                    ListItem(
                        list_guid=trending_list.guid,
                        item_type=ListItemType.MUSIC,
                        item_guid=album.guid,
                        order_index=i,
                    )
                )

            trending_list.item_count = len(albums[:20])
            trending_list.last_auto_update = datetime.now(UTC)
            await self.db.commit()
            logger.info(
                "Updated trending music list: %s items (from %s Spotify trending)",
                len(albums[:20]), len(trending_spotify_ids),
            )

        except Exception as e:
            logger.error("Failed to update trending music list: %s", e)
            raise

    async def update_trending_movies_list(self) -> None:
        """Update (or create) the trending movies list using actual TMDB trending data."""
        try:
            trending_list = await self._get_or_create_system_list(
                update_source="trending_movies",
                name="Trending Movies",
                description="Currently trending movies from TMDB",
            )

            # Get actual trending movies from TMDB
            tmdb = await self._get_tmdb()
            trending = await tmdb.get_trending_movies()
            trending_tmdb_ids = [str(m["id"]) for m in trending.get("results", [])]

            # Find matching movies in DB by TMDB external ID, preserving trending order
            movies = []
            for tmdb_id in trending_tmdb_ids:
                result = await self.db.execute(
                    select(MediaItem)
                    .join(MediaExternalId)
                    .where(MediaExternalId.provider == "tmdb")
                    .where(MediaExternalId.external_id == tmdb_id)
                    .where(MediaItem.media_type == MediaType.MOVIES)
                    .limit(1)
                )
                movie = result.scalar_one_or_none()
                if movie:
                    movies.append(movie)

            # Search releases for movies that don't have any yet
            from pyrate.worker import search_media_item_releases

            for movie in movies:
                # Eagerly load releases for this movie
                result = await self.db.execute(
                    select(MediaItem)
                    .where(MediaItem.guid == movie.guid)
                    .options(
                        selectinload(MediaItem.releases).selectinload(MediaRelease.links)
                    )
                )
                loaded = result.scalar_one_or_none()
                if loaded and not loaded.releases:
                    try:
                        await search_media_item_releases(str(movie.guid))
                    except Exception as e:
                        logger.warning("Failed to search releases for trending movie %s: %s", movie.guid, e)

            # Clear existing list items
            existing = await self.db.execute(
                select(ListItem).where(ListItem.list_guid == trending_list.guid)
            )
            for item in existing.scalars().all():
                await self.db.delete(item)

            # Add all trending movies that exist in DB (regardless of releases)
            for i, movie in enumerate(movies[:20]):
                self.db.add(
                    ListItem(
                        list_guid=trending_list.guid,
                        item_type=ListItemType.MOVIE,
                        item_guid=movie.guid,
                        order_index=i,
                    )
                )

            trending_list.item_count = len(movies[:20])
            trending_list.last_auto_update = datetime.now(UTC)
            await self.db.commit()
            logger.info(
                "Updated trending movies list: %s items (from %s TMDB trending)",
                len(movies[:20]), len(trending_tmdb_ids),
            )

        except Exception as e:
            logger.error("Failed to update trending movies list: %s", e)
            raise

    async def update_trending_shows_list(self) -> None:
        """Update (or create) the trending shows list using actual TMDB trending data."""
        try:
            trending_list = await self._get_or_create_system_list(
                update_source="trending_shows",
                name="Trending TV Shows",
                description="Currently trending TV shows from TMDB",
            )

            # Get actual trending shows from TMDB
            tmdb = await self._get_tmdb()
            trending = await tmdb.get_trending_shows()
            trending_tmdb_ids = [str(s["id"]) for s in trending.get("results", [])]

            # Find matching shows in DB by TMDB external ID
            shows = []
            for tmdb_id in trending_tmdb_ids:
                result = await self.db.execute(
                    select(MediaItem)
                    .join(MediaExternalId)
                    .where(MediaExternalId.provider == "tmdb")
                    .where(MediaExternalId.external_id == tmdb_id)
                    .where(MediaItem.media_type == MediaType.SHOWS)
                    .limit(1)
                )
                show = result.scalar_one_or_none()
                if show:
                    shows.append(show)

            # Clear existing list items
            existing = await self.db.execute(
                select(ListItem).where(ListItem.list_guid == trending_list.guid)
            )
            for item in existing.scalars().all():
                await self.db.delete(item)

            for i, show in enumerate(shows[:20]):
                self.db.add(
                    ListItem(
                        list_guid=trending_list.guid,
                        item_type=ListItemType.SHOW,
                        item_guid=show.guid,
                        order_index=i,
                    )
                )

            trending_list.item_count = len(shows[:20])
            trending_list.last_auto_update = datetime.now(UTC)
            await self.db.commit()
            logger.info(
                "Updated trending shows list: %s items (from %s TMDB trending)",
                len(shows[:20]), len(trending_tmdb_ids),
            )

        except Exception as e:
            logger.error("Failed to update trending shows list: %s", e)
            raise

    async def update_trending_games_list(self) -> None:
        """Update (or create) the trending games list using actual IGDB trending data."""
        try:
            trending_list = await self._get_or_create_system_list(
                update_source="trending_games",
                name="Trending Games",
                description="Currently trending games from IGDB",
            )

            # Get actual trending games from IGDB
            igdb = await self._get_igdb()
            trending = await igdb.get_trending_games()
            trending_igdb_ids = [str(g["id"]) for g in trending]

            # Find matching games in DB
            games = []
            for igdb_id in trending_igdb_ids:
                result = await self.db.execute(
                    select(MediaItem)
                    .join(MediaExternalId)
                    .where(MediaExternalId.provider == "igdb")
                    .where(MediaExternalId.external_id == igdb_id)
                    .where(MediaItem.media_type == MediaType.GAMES)
                    .limit(1)
                )
                game = result.scalar_one_or_none()
                if game:
                    games.append(game)

            # Clear existing list items
            existing = await self.db.execute(
                select(ListItem).where(ListItem.list_guid == trending_list.guid)
            )
            for item in existing.scalars().all():
                await self.db.delete(item)

            for i, game in enumerate(games[:20]):
                self.db.add(
                    ListItem(
                        list_guid=trending_list.guid,
                        item_type=ListItemType.GAME,
                        item_guid=game.guid,
                        order_index=i,
                    )
                )

            trending_list.item_count = len(games[:20])
            trending_list.last_auto_update = datetime.now(UTC)
            await self.db.commit()
            logger.info(
                "Updated trending games list: %s items (from %s IGDB trending)",
                len(games[:20]), len(trending_igdb_ids),
            )

        except Exception as e:
            logger.error("Failed to update trending games list: %s", e)
            raise

    async def get_or_create_trending_movies_list(self) -> List:
        """Get or create the SYSTEM trending movies list (used by list-based APIs)."""
        return await self._get_or_create_system_list(
            update_source="trending_movies",
            name="Trending Movies",
            description="Daily trending movies from TMDB, updated hourly",
        )

    async def get_or_create_trending_shows_list(self) -> List:
        """Get or create the SYSTEM trending shows list (used by list-based APIs)."""
        return await self._get_or_create_system_list(
            update_source="trending_shows",
            name="Trending TV Shows",
            description="Daily trending TV shows from TMDB, updated hourly",
        )

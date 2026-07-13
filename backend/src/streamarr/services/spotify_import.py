"""Service for importing music metadata from Spotify.

Handles artist, album, and track import with deduplication, external ID
management, and genre assignment.  The worker tasks are thin wrappers
that delegate to this service and queue follow-up tasks.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import (
    AvailabilityStatus,
    MediaReleaseLink,
    MediaType,
)
from streamarr.services.library import LibraryService
from streamarr.services.media import MediaService
from streamarr.services.settings import SettingsService

logger = logging.getLogger(__name__)


class SpotifyMusicImportService:
    """Imports artists, albums and songs from Spotify into the unified media model."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.media_service = MediaService(db)
        self.settings_service = SettingsService(db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def import_artist(self, spotify_id: str) -> dict | None:
        """Import an artist by Spotify ID.

        Returns a dict with ``artist_title`` and ``album_ids`` (list of
        Spotify album IDs to queue), or *None* when the import is skipped
        (e.g. already exists, missing credentials/library).
        """
        existing = await self.media_service.get_by_external_id(
            provider="spotify",
            external_id=spotify_id,
            media_type=MediaType.ARTISTS,
        )
        if existing:
            logger.info(
                "Artist with Spotify ID %s already exists as '%s', skipping",
                spotify_id,
                existing.title,
            )
            return None

        if not await self._ensure_music_library():
            logger.error("Cannot import artist %s - no active MUSIC library", spotify_id)
            return None

        spotify = await self._get_spotify_client()
        if spotify is None:
            return None

        try:
            details = await spotify.get_artist_details(spotify_id)
            if not details:
                logger.error("Failed to fetch artist details from Spotify for ID %s", spotify_id)
                return None

            poster_path = self._extract_poster(details.get("images", []))

            artist_item = await self.media_service.create_media_item(
                media_type=MediaType.ARTISTS,
                title=details.get("name", "Unknown"),
                poster_path=poster_path,
                availability_status=AvailabilityStatus.DOWNLOADABLE,
            )

            await self.media_service.add_external_id(
                media_item_guid=artist_item.guid,
                provider="spotify",
                external_id=spotify_id,
            )

            genres = details.get("genres", [])
            if genres:
                await self.media_service.set_genres(artist_item.guid, genres)

            await self.db.commit()
            logger.info("Imported artist: %s (Spotify %s)", artist_item.title, spotify_id)

            # Collect album IDs so the worker can queue follow-up tasks
            albums = await spotify.get_artist_albums(spotify_id, limit=20)
            album_ids = [a["id"] for a in albums if a.get("id")]

            return {
                "artist_title": artist_item.title,
                "album_ids": album_ids,
            }
        finally:
            await spotify.close()

    async def import_album(self, spotify_id: str) -> dict | None:
        """Import an album (and its artists/tracks) by Spotify ID.

        Returns a dict with ``album_title`` and ``track_count``, or *None*
        when the import is skipped.
        """
        existing_album = await self.media_service.get_by_external_id(
            provider="spotify",
            external_id=spotify_id,
            media_type=MediaType.ALBUMS,
        )
        if existing_album:
            logger.info(
                "Album with Spotify ID %s already exists as '%s', skipping",
                spotify_id,
                existing_album.title,
            )
            return None

        if not await self._ensure_music_library():
            logger.error("Cannot import album %s - no active MUSIC library", spotify_id)
            return None

        spotify = await self._get_spotify_client()
        if spotify is None:
            return None

        try:
            album_details = await spotify.get_album_details(spotify_id)
            if not album_details:
                logger.error("Failed to fetch album details from Spotify for ID %s", spotify_id)
                return None

            release_date = self._parse_spotify_date(album_details.get("release_date"))
            poster_path = self._extract_poster(album_details.get("images", []))

            # --- 1) Import Artists ---
            artists = album_details.get("artists", [])
            artist_names = [a.get("name") for a in artists if a.get("name")]
            primary_artist_item = None
            cached_artist_genres: dict[str, list[str]] = {}

            for artist_data in artists:
                artist_item, artist_genres = await self._create_or_get_artist(
                    artist_data, spotify,
                )
                if artist_item is None:
                    continue

                if artist_genres is not None:
                    cached_artist_genres[artist_data["id"]] = artist_genres

                if primary_artist_item is None:
                    primary_artist_item = artist_item

            # --- 2) Import Album (as child of primary artist) ---
            description = ", ".join(artist_names) if artist_names else None

            album_item = await self.media_service.create_media_item(
                media_type=MediaType.ALBUMS,
                title=album_details.get("name", "Unknown"),
                description=description,
                release_date=release_date,
                poster_path=poster_path,
                availability_status=AvailabilityStatus.DOWNLOADABLE,
                parent_guid=primary_artist_item.guid if primary_artist_item else None,
            )

            await self.media_service.add_external_id(
                media_item_guid=album_item.guid,
                provider="spotify",
                external_id=spotify_id,
            )

            # Genres — fall back to cached artist genres when album-level genres are empty.
            genres = album_details.get("genres", [])
            if not genres:
                for artist_data in artists:
                    aid = artist_data.get("id")
                    if aid and aid in cached_artist_genres and cached_artist_genres[aid]:
                        genres = cached_artist_genres[aid]
                        break
            if genres:
                await self.media_service.set_genres(album_item.guid, genres)

            # --- 3) Import Tracks/Songs ---
            tracks = await spotify.get_album_tracks(spotify_id)
            for track in tracks:
                await self._import_track(track, album_item.guid)

            logger.info(
                "Successfully imported album: %s with %s tracks (Spotify %s)",
                album_item.title,
                len(tracks),
                spotify_id,
            )

            return {
                "album_title": album_item.title,
                "track_count": len(tracks),
            }
        finally:
            await spotify.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_spotify_client(self):
        """Load credentials and return a configured Spotify client, or *None*."""
        client_id, client_secret = await self.settings_service.get_spotify_credentials()
        if not client_id or not client_secret:
            logger.error("Spotify credentials not configured")
            return None

        from streamarr.metadata.spotify import Spotify

        return Spotify(client_id=client_id, client_secret=client_secret)

    async def _ensure_music_library(self) -> bool:
        """Return True when a MUSIC library exists."""
        library = await LibraryService(self.db).get_library_by_type("MUSIC")
        return library is not None

    async def _create_or_get_artist(self, artist_data: dict, spotify):
        """Return ``(MediaItem, genres | None)`` for an artist.

        If the artist already exists by Spotify external ID, the existing
        item is returned and ``genres`` will be *None* (no fetch needed).
        If the artist is newly created, ``genres`` contains the list
        fetched from Spotify (possibly empty).
        """
        artist_spotify_id = artist_data.get("id")
        artist_name = artist_data.get("name")
        if not artist_spotify_id or not artist_name:
            return None, None

        artist_item = await self.media_service.get_by_external_id(
            provider="spotify",
            external_id=artist_spotify_id,
            media_type=MediaType.ARTISTS,
        )

        if artist_item:
            return artist_item, None

        # Fetch full artist details for image and genres
        artist_full = await spotify.get_artist_details(artist_spotify_id)

        artist_poster = self._extract_poster(artist_full.get("images", []))

        artist_item = await self.media_service.create_media_item(
            media_type=MediaType.ARTISTS,
            title=artist_name,
            poster_path=artist_poster,
            availability_status=AvailabilityStatus.DOWNLOADABLE,
        )

        await self.media_service.add_external_id(
            media_item_guid=artist_item.guid,
            provider="spotify",
            external_id=artist_spotify_id,
        )

        artist_genres = artist_full.get("genres", [])
        if artist_genres:
            await self.media_service.set_genres(artist_item.guid, artist_genres)

        logger.info(
            "Imported artist: %s (Spotify %s)",
            artist_name,
            artist_spotify_id,
        )

        return artist_item, artist_genres

    async def _import_track(self, track: dict, album_guid) -> None:
        """Create a single song MediaItem from a Spotify track dict."""
        track_spotify_id = track.get("id")
        track_name = track.get("name")
        track_number = track.get("track_number")
        disc_number = track.get("disc_number", 1)
        if not track_spotify_id or not track_name:
            return

        existing_track = await self.media_service.get_by_external_id(
            provider="spotify",
            external_id=track_spotify_id,
            media_type=MediaType.SONGS,
        )
        if existing_track:
            return

        track_artists = track.get("artists", [])
        track_artist_names = [a.get("name") for a in track_artists if a.get("name")]
        track_description = ", ".join(track_artist_names) if track_artist_names else None

        duration_ms = track.get("duration_ms")

        extra = {"disc_number": disc_number}
        if duration_ms:
            extra["duration_ms"] = duration_ms

        song_item = await self.media_service.create_media_item(
            media_type=MediaType.SONGS,
            title=track_name,
            description=track_description,
            parent_guid=album_guid,
            sequence_number=track_number,
            availability_status=AvailabilityStatus.DOWNLOADABLE,
            extra_data=extra,
        )

        await self.media_service.add_external_id(
            media_item_guid=song_item.guid,
            provider="spotify",
            external_id=track_spotify_id,
        )

        # Create a release with Spotify link so spotdl can download it
        spotify_url = f"https://open.spotify.com/track/{track_spotify_id}"
        release = await self.media_service.create_media_release(
            media_item_guid=song_item.guid,
            title=track_name,
            size=duration_ms * 20 if duration_ms else None,  # rough estimate
        )
        release_link = MediaReleaseLink(
            guid=uuid.uuid4(),
            media_release_guid=release.guid,
            link=spotify_url,
            link_type="spotify",
        )
        self.db.add(release_link)
        await self.db.commit()

    # ------------------------------------------------------------------
    # Pure helpers (no I/O)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_poster(images: list[dict]) -> str | None:
        """Return the URL of the first (largest) image, or *None*."""
        if images:
            return images[0].get("url")
        return None

    @staticmethod
    def _parse_spotify_date(date_str: str | None) -> datetime | None:
        """Parse Spotify date strings which can be YYYY, YYYY-MM, or YYYY-MM-DD."""
        from streamarr.utils.dates import parse_spotify_date

        return parse_spotify_date(date_str)

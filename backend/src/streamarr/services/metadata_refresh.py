"""Unified service for importing and refreshing media metadata from external providers."""

import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from streamarr.metadata.base import MetadataBase, NormalizedMetadata
from streamarr.models.media import (
    AvailabilityStatus,
    MediaExternalId,
    MediaItem,
    MediaType,
)

logger = logging.getLogger(__name__)


class MetadataService:
    """Imports and refreshes metadata for media items from external providers.

    Handles both initial import (create) and refresh (update) using the same
    normalized provider data. The provider is responsible for returning data
    in a unified format via get_normalized_details().
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def import_media(
        self,
        plugin: MetadataBase,
        external_id: str,
        provider_name: str,
        media_type: MediaType,
    ) -> MediaItem | None:
        """Import a new media item from a provider.

        If the item already exists (by external ID), returns None.
        For shows, also imports seasons and episodes.
        """
        from streamarr.services.media import MediaService

        # Check if already exists
        existing = await self.db.execute(
            select(MediaItem)
            .join(MediaExternalId)
            .where(MediaExternalId.external_id == str(external_id))
            .where(MediaExternalId.provider == provider_name)
            .where(MediaItem.media_type == media_type)
            .limit(1)
        )
        existing_item = existing.scalar_one_or_none()

        media_type_str = self._get_provider_media_type(media_type)
        # External IDs can be numeric (TMDB, IGDB) or string (Open Library, Spotify)
        try:
            ext_id_parsed = int(external_id)
        except (ValueError, TypeError):
            ext_id_parsed = str(external_id)
        normalized = await plugin.get_normalized_details(ext_id_parsed, media_type_str)
        if not normalized.title:
            logger.warning("No metadata found for %s ID %s", provider_name, external_id)
            return None

        media_service = MediaService(self.db)

        if existing_item:
            # Show exists but may need seasons — check children
            if media_type == MediaType.SHOWS:
                children = await self.db.execute(
                    select(MediaItem)
                    .where(MediaItem.parent_guid == existing_item.guid)
                    .limit(1)
                )
                if children.scalar_one_or_none():
                    logger.info("%s already fully imported, skipping", existing_item.title)
                    return None
                # Fall through to import seasons for existing show
                media_item = existing_item
            else:
                logger.info("%s already exists, skipping", existing_item.title)
                return None
        else:
            # Create the media item
            media_item = await media_service.create_media_item(
                media_type=media_type,
                title=normalized.title or "Unknown",
                original_title=normalized.original_title,
                description=normalized.description,
                release_date=self._parse_date(normalized.release_date),
                poster_path=normalized.poster_path,
                backdrop_path=normalized.backdrop_path,
                content_rating=normalized.content_rating,
                min_age=normalized.min_age,
                availability_status=AvailabilityStatus.DOWNLOADABLE,
            )

            # Add external IDs
            await media_service.add_external_id(
                media_item_guid=media_item.guid,
                provider=provider_name,
                external_id=str(external_id),
            )
            await self._import_external_ids(media_item, media_service, normalized.extra)

            # Add genres and platforms
            await self._import_genres(media_item, media_service, normalized.extra)
            await self._import_platforms(media_item, media_service, normalized.extra)

        # Credits
        if normalized.credits:
            await self._refresh_credits(media_item, normalized.credits)

        # Seasons and episodes (shows only)
        if media_type == MediaType.SHOWS and normalized.seasons:
            await self._refresh_seasons(media_item, plugin, external_id, normalized.seasons)

        # Translations
        if media_type in [MediaType.MOVIES, MediaType.SHOWS]:
            await self._refresh_translations(
                media_item, plugin, external_id, media_type_str
            )

        await self.db.commit()
        logger.info("Imported %s: %s (%s)", media_type.value, media_item.title, media_item.guid)
        return media_item

    async def refresh(
        self,
        media_item_guid: uuid.UUID,
        plugin: MetadataBase,
        external_id: str,
    ) -> MediaItem | None:
        """Refresh all metadata for an existing media item.

        Updates: title, description, poster, backdrop, tagline, release_date,
        extra_data, cast/crew, seasons/episodes (for shows), and translations.
        """
        result = await self.db.execute(
            select(MediaItem)
            .options(selectinload(MediaItem.external_ids))
            .where(MediaItem.guid == media_item_guid)
        )
        media_item = result.scalars().first()
        if not media_item:
            logger.warning("Media item %s not found", media_item_guid)
            return None

        media_type_str = self._get_provider_media_type(media_item.media_type)
        # External IDs can be numeric (TMDB, IGDB) or string (Open Library, Spotify)
        try:
            ext_id_parsed = int(external_id)
        except (ValueError, TypeError):
            ext_id_parsed = str(external_id)
        normalized = await plugin.get_normalized_details(ext_id_parsed, media_type_str)
        if not normalized.title:
            logger.warning("No metadata found for external ID %s", external_id)
            return None

        # Update core fields
        self._apply_normalized(media_item, normalized)
        self._merge_extra_data(media_item, normalized.extra)

        # Credits (top-level only)
        if media_item.parent_guid is None and normalized.credits:
            await self._refresh_credits(media_item, normalized.credits)

        # Seasons and episodes
        if (
            media_item.media_type == MediaType.SHOWS
            and media_item.parent_guid is None
            and normalized.seasons
        ):
            await self._refresh_seasons(
                media_item, plugin, external_id, normalized.seasons
            )

        # Translations (top-level only)
        if (
            media_item.media_type in [MediaType.MOVIES, MediaType.SHOWS]
            and media_item.parent_guid is None
        ):
            await self._refresh_translations(
                media_item, plugin, external_id, media_type_str
            )

        # Genres and platforms (refresh from extra data)
        if media_item.parent_guid is None:
            from streamarr.services.media import MediaService
            ms = MediaService(self.db)
            await self._import_genres(media_item, ms, normalized.extra)
            await self._import_platforms(media_item, ms, normalized.extra)

        await self.db.commit()
        await self.db.refresh(media_item)
        logger.info("Refreshed metadata for %s", media_item.title)
        return media_item

    async def refresh_season(
        self,
        season_guid: uuid.UUID,
        plugin: MetadataBase,
        show_external_id: str,
        season_number: int,
    ) -> MediaItem | None:
        """Refresh one season and upsert all episodes from the parent show provider ID."""
        result = await self.db.execute(
            select(MediaItem).where(MediaItem.guid == season_guid)
        )
        season_item = result.scalars().first()
        if not season_item:
            logger.warning("Season %s not found", season_guid)
            return None
        if not season_item.parent_guid:
            logger.warning("Media item %s is not a season child", season_guid)
            return None

        show_result = await self.db.execute(
            select(MediaItem).where(MediaItem.guid == season_item.parent_guid)
        )
        show = show_result.scalars().first()
        if not show:
            logger.warning("Parent show for season %s not found", season_guid)
            return None

        try:
            show_id = int(show_external_id)
        except (TypeError, ValueError):
            show_id = show_external_id

        season_details = await plugin.get_show_season(show_id, str(season_number))
        if not season_details:
            logger.warning(
                "No season metadata found for show %s season %s",
                show_external_id,
                season_number,
            )
            return None

        from streamarr.services.media import MediaService

        media_service = MediaService(self.db)
        refreshed_season = await self._upsert_season(
            show, media_service, season_number, season_details
        )

        episodes_updated = 0
        for ep_data in season_details.get("episodes", []):
            ep_number = ep_data.get("episode_number")
            if ep_number is None:
                continue
            await self._upsert_episode(
                refreshed_season, media_service, ep_number, ep_data
            )
            episodes_updated += 1

        await self.db.commit()
        await self.db.refresh(refreshed_season)
        logger.info(
            "Refreshed season %s for %s with %s episodes",
            season_number,
            show.title,
            episodes_updated,
        )
        return refreshed_season

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_provider_media_type(media_type: MediaType) -> str:
        return {
            MediaType.MOVIES: "movie",
            MediaType.SHOWS: "tv",
            MediaType.GAMES: "game",
        }.get(media_type, "movie")

    @staticmethod
    def _apply_normalized(media_item: MediaItem, n: NormalizedMetadata) -> None:
        media_item.title = n.title or media_item.title
        media_item.original_title = n.original_title or media_item.original_title
        media_item.description = n.description or media_item.description
        media_item.tagline = n.tagline or media_item.tagline
        media_item.release_date = n.release_date or media_item.release_date
        media_item.poster_path = n.poster_path or media_item.poster_path
        media_item.backdrop_path = n.backdrop_path or media_item.backdrop_path
        if n.content_rating:
            media_item.content_rating = n.content_rating
        if n.min_age is not None:
            media_item.min_age = n.min_age
        media_item.updated_at = datetime.now(UTC)

    @staticmethod
    def _merge_extra_data(media_item: MediaItem, extra: dict) -> None:
        existing: dict = {}
        ed = media_item.extra_data
        if ed:
            existing = dict(ed) if isinstance(ed, dict) else json.loads(ed)
        skip = {"title", "original_title", "description", "tagline",
                "release_date", "poster_path", "backdrop_path",
                "name", "original_name", "overview", "first_air_date"}
        for key, value in extra.items():
            if key not in skip:
                existing[key] = value
        media_item.extra_data = existing

    async def _import_external_ids(self, media_item, media_service, extra: dict) -> None:
        """Import additional external IDs (IMDB, TVDB) from provider response."""
        ext_ids = extra.get("external_ids", {})
        for provider, key in [("imdb", "imdb_id"), ("tvdb", "tvdb_id")]:
            value = ext_ids.get(key) or extra.get(key)
            if value:
                await media_service.add_external_id(
                    media_item_guid=media_item.guid,
                    provider=provider,
                    external_id=str(value),
                )

    async def _import_genres(self, media_item, media_service, extra: dict) -> None:
        genres = extra.get("genres", [])
        if genres:
            genre_names = [g.get("name") for g in genres if isinstance(g, dict) and g.get("name")]
            if genre_names:
                await media_service.set_genres(media_item.guid, genre_names)

    async def _import_platforms(self, media_item, media_service, extra: dict) -> None:
        platforms = extra.get("platforms", [])
        if platforms:
            platform_data = []
            for p in platforms:
                if isinstance(p, dict) and p.get("name"):
                    entry = {"name": p["name"]}
                    if p.get("id"):
                        entry["id"] = p["id"]
                    # IGDB platform logo
                    if p.get("platform_logo") and isinstance(p["platform_logo"], dict):
                        logo = p["platform_logo"]
                        if logo.get("image_id"):
                            entry["logo_url"] = f"https://images.igdb.com/igdb/image/upload/t_logo_med/{logo['image_id']}.png"
                    platform_data.append(entry)
            if platform_data:
                await media_service.set_platforms(media_item.guid, platform_data)

    async def _refresh_credits(self, media_item: MediaItem, credits_data: dict) -> None:
        from streamarr.models.person import MediaCast
        from streamarr.services.person import PersonService

        existing = await self.db.execute(
            select(MediaCast).where(MediaCast.media_item_guid == media_item.guid)
        )
        for entry in existing.scalars().all():
            await self.db.delete(entry)
        await self.db.flush()

        if credits_data:
            person_service = PersonService(self.db)
            entries = await person_service.import_cast_from_tmdb(
                media_item_guid=media_item.guid,
                credits_data=credits_data,
            )
            logger.info("Set %s cast/crew for %s", len(entries), media_item.title)

    async def _refresh_seasons(
        self, show: MediaItem, plugin: MetadataBase, external_id: str,
        seasons_data: list[dict],
    ) -> tuple[int, int]:
        from streamarr.services.media import MediaService
        media_service = MediaService(self.db)
        seasons_updated = 0
        episodes_updated = 0

        for season_data in seasons_data:
            season_number = season_data.get("season_number")
            if season_number is None or season_number == 0:
                continue

            try:
                season_details = await plugin.get_show_season(
                    int(external_id), str(season_number)
                )
                if not season_details:
                    continue

                season_item = await self._upsert_season(
                    show, media_service, season_number, season_details
                )
                seasons_updated += 1

                for ep_data in season_details.get("episodes", []):
                    ep_number = ep_data.get("episode_number")
                    if ep_number is None:
                        continue
                    await self._upsert_episode(
                        season_item, media_service, ep_number, ep_data
                    )
                    episodes_updated += 1

            except Exception as e:
                logger.error("Failed to process season %s: %s", season_number, e, exc_info=True)
                continue

        logger.info(
            "Processed %s seasons, %s episodes for %s",
            seasons_updated, episodes_updated, show.title,
        )
        return seasons_updated, episodes_updated

    async def _upsert_season(self, show, media_service, season_number, details):
        result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.parent_guid == show.guid)
            .where(MediaItem.sequence_number == season_number)
        )
        existing = result.scalars().first()
        title = details.get("name", f"Season {season_number}")

        if existing:
            existing.title = title
            existing.description = details.get("overview")
            existing.poster_path = details.get("poster_path")
            existing.extra_data = details
            existing.updated_at = datetime.now(UTC)
            await self._ensure_external_id(existing.guid, "tmdb", details.get("id"))
            return existing

        item = await media_service.create_media_item(
            media_type=MediaType.SHOWS,
            title=title,
            parent_guid=show.guid,
            sequence_number=season_number,
            description=details.get("overview"),
            poster_path=details.get("poster_path"),
            release_date=self._parse_date(details.get("air_date")),
            extra_data=details,
            availability_status=AvailabilityStatus.DOWNLOADABLE,
        )
        await self._ensure_external_id(item.guid, "tmdb", details.get("id"))
        return item

    async def _upsert_episode(self, season, media_service, episode_number, data):
        result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.parent_guid == season.guid)
            .where(MediaItem.sequence_number == episode_number)
        )
        existing = result.scalars().first()
        title = data.get("name", f"Episode {episode_number}")
        air_date = self._parse_date(data.get("air_date"))

        if existing:
            existing.title = title
            existing.description = data.get("overview")
            existing.poster_path = data.get("still_path")
            existing.release_date = air_date
            existing.extra_data = data
            existing.updated_at = datetime.now(UTC)
            await self._ensure_external_id(existing.guid, "tmdb", data.get("id"))
            return existing

        item = await media_service.create_media_item(
            media_type=MediaType.SHOWS,
            title=title,
            parent_guid=season.guid,
            sequence_number=episode_number,
            description=data.get("overview"),
            poster_path=data.get("still_path"),
            release_date=air_date,
            extra_data=data,
            availability_status=AvailabilityStatus.DOWNLOADABLE,
        )
        await self._ensure_external_id(item.guid, "tmdb", data.get("id"))
        return item

    async def _ensure_external_id(self, media_item_guid, provider, ext_id):
        if not ext_id:
            return
        result = await self.db.execute(
            select(MediaExternalId)
            .where(MediaExternalId.media_item_guid == media_item_guid)
            .where(MediaExternalId.provider == provider)
        )
        if not result.scalars().first():
            from streamarr.services.media import MediaService
            await MediaService(self.db).add_external_id(
                media_item_guid=media_item_guid,
                provider=provider,
                external_id=str(ext_id),
            )

    async def _refresh_translations(
        self, media_item, plugin, external_id, media_type_str,
    ) -> None:
        try:
            from streamarr.services.translation import TranslationService

            translations = await plugin.get_translations(int(external_id), media_type_str)
            if not translations:
                return

            configured_langs = await self._get_configured_languages(media_item.media_type)
            filtered = {k: v for k, v in translations.items() if k in configured_langs}
            if filtered:
                ts = TranslationService(self.db)
                count = await ts.set_translations_from_provider(media_item.guid, filtered)
                logger.info("Set %s translations for %s", count, media_item.title)
        except Exception as e:
            logger.warning("Failed to set translations for %s: %s", media_item.title, e)

    async def _get_configured_languages(self, media_type: MediaType) -> list[str]:
        default = ["de", "en"]
        try:
            from streamarr.models.library import Library
            lib_type = {
                MediaType.MOVIES: "MOVIES",
                MediaType.SHOWS: "SHOWS",
            }.get(media_type)
            if not lib_type:
                return default
            result = await self.db.execute(
                select(Library).where(Library.type == lib_type)
            )
            library = result.scalars().first()
            if library and library.settings:
                return json.loads(library.settings).get("languages", default)
        except Exception as e:
            logger.debug("Could not read library language settings: %s", e)
        return default

    @staticmethod
    def _parse_date(date_str):
        if not date_str:
            return None
        try:
            from datetime import datetime as dt
            return dt.fromisoformat(date_str).date()
        except (ValueError, AttributeError):
            return None

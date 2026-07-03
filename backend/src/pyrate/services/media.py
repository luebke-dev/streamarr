"""Unified media service for all content types (movies, shows, games, music, etc.)."""

import glob
import logging
import uuid
from pathlib import Path
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.media import (
    AvailabilityStatus,
    MediaExternalId,
    MediaFile,
    MediaItem,
    MediaRelease,
    MediaType,
)
from pyrate.libraries import get_plugin_instance

logger = logging.getLogger(__name__)


class MediaService:
    """
    Unified service for all media types.

    Replaces MovieService, ShowService, EpisodeService, GameService, MusicService, etc.
    Uses MediaType discriminator and library plugins for type-specific behavior.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_root_guid(
        self, parent_guid: uuid.UUID, *, max_depth: int = 3
    ) -> uuid.UUID | None:
        """Walk up the ``parent_guid`` chain and return the top-level guid.

        Single recursive-CTE round-trip instead of one query per level.
        Use this anywhere the previous code did a ``while parent.parent_guid:
        parent = SELECT ...`` loop.

        Returns the root guid, or ``None`` if the starting guid does not
        exist. When ``parent_guid`` is itself a root item the same guid is
        returned.
        """
        from sqlalchemy import literal_column

        anchor = (
            select(
                MediaItem.guid,
                MediaItem.parent_guid,
                literal_column("1").label("depth"),
            )
            .where(MediaItem.guid == parent_guid)
            .cte(name="ancestors", recursive=True)
        )

        recursive = (
            select(
                MediaItem.guid,
                MediaItem.parent_guid,
                (anchor.c.depth + 1).label("depth"),
            )
            .join(anchor, MediaItem.guid == anchor.c.parent_guid)
            .where(anchor.c.depth < max_depth)
        )

        cte = anchor.union_all(recursive)
        root_query = (
            select(cte.c.guid).order_by(cte.c.depth.desc()).limit(1)
        )
        result = await self.db.execute(root_query)
        return result.scalar_one_or_none()

    async def _persist(
        self,
        entity: Any,
        *,
        refresh: bool = True,
        commit: bool = True,
    ) -> None:
        """Add and persist an entity, optionally refreshing it.

        Pass ``refresh=False`` for fire-and-forget inserts where callers do
        not consume server-side defaults (timestamps, sequence values, ...).
        Skipping the refresh saves a round-trip per insert — meaningful for
        bulk-import paths.

        ``commit=False`` is for callers that own a larger unit of work. It
        flushes instead of committing so the entity has a primary key while the
        outer transaction can still roll back the whole workflow.
        """
        self.db.add(entity)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        if refresh:
            await self.db.refresh(entity)

    async def _upsert_by_names(self, model_class, names: list[str], extra_values_fn=None):
        """Fetch existing rows by name, create missing ones, return a dict keyed by name.

        Args:
            model_class: SQLAlchemy model with a ``name`` column and a unique
                constraint on it.
            names: List of name strings to ensure exist.
            extra_values_fn: Optional callable ``(name) -> dict`` returning
                additional column values for INSERT of missing rows.

        Returns:
            dict mapping name -> model instance for every requested name.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        result = await self.db.execute(
            select(model_class).where(model_class.name.in_(names))
        )
        existing = {row.name: row for row in result.scalars().all()}

        missing = [n for n in names if n not in existing]
        if missing:
            for name in missing:
                values = {"name": name}
                if extra_values_fn:
                    values.update(extra_values_fn(name))
                stmt = (
                    pg_insert(model_class)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["name"])
                )
                await self.db.execute(stmt)
            await self.db.flush()

            result = await self.db.execute(
                select(model_class).where(model_class.name.in_(names))
            )
            existing = {row.name: row for row in result.scalars().all()}

        return existing

    # ==================== CREATE ====================

    async def create_media_item(
        self,
        media_type: MediaType,
        title: str,
        library_guid: uuid.UUID | None = None,
        parent_guid: uuid.UUID | None = None,
        sequence_number: int | None = None,
        commit: bool = True,
        **kwargs: Any,
    ) -> MediaItem:
        """
        Create a new media item.

        Args:
            media_type: Type of media (MOVIES, SERIES, GAMES, etc.)
            title: Media title
            library_guid: Deprecated, ignored. Media type determines library.
            parent_guid: Parent media item (for episodes, tracks, etc.)
            sequence_number: Order within parent (season #, episode #, track #)
            commit: Commit immediately, or only flush for caller-owned UoW
            **kwargs: Additional fields (description, poster_path, metadata, etc.)
        """
        media_item = MediaItem(
            guid=uuid.uuid4(),  # Generate GUID client-side for reliability
            media_type=media_type,
            title=title,
            parent_guid=parent_guid,
            sequence_number=sequence_number,
            **kwargs,
        )

        await self._persist(media_item, commit=commit)

        logger.info(
            "Created %s media item: %s (%s)", media_type.value, title, media_item.guid
        )
        return media_item

    async def create_media_file(
        self,
        media_item_guid: uuid.UUID,
        file_path: str,
        commit: bool = True,
        **kwargs: Any,
    ) -> MediaFile:
        """Create a media file entry."""
        media_file = MediaFile(
            guid=uuid.uuid4(),  # Generate client-side GUID
            media_item_guid=media_item_guid,
            file_path=file_path,
            **kwargs,
        )

        await self._persist(media_file, commit=commit)

        return media_file

    async def create_media_release(
        self,
        media_item_guid: uuid.UUID,
        title: str,
        commit: bool = True,
        **kwargs: Any,
    ) -> MediaRelease:
        """Create a media release entry."""
        release = MediaRelease(
            guid=uuid.uuid4(),  # Generate client-side GUID
            media_item_guid=media_item_guid,
            title=title,
            **kwargs,
        )

        await self._persist(release, commit=commit)

        return release

    async def add_external_id(
        self,
        media_item_guid: uuid.UUID,
        provider: str,
        external_id: str,
        commit: bool = True,
    ) -> MediaExternalId:
        """Add external ID mapping (TMDB, IGDB, etc.).

        Skips the post-insert refresh — every caller fire-and-forgets the
        return value and the only DB-default field (``created_at``) is
        irrelevant to library import flows. Halves DB round-trips on the
        bulk metadata-import path.
        """
        ext_id = MediaExternalId(
            guid=uuid.uuid4(),  # Generate client-side GUID
            media_item_guid=media_item_guid,
            provider=provider,
            external_id=external_id,
        )

        await self._persist(ext_id, refresh=False, commit=commit)

        return ext_id

    async def set_genres(
        self,
        media_item_guid: uuid.UUID,
        genre_names: list[str],
        commit: bool = True,
    ) -> MediaItem | None:
        """
        Set genres for a media item by name.

        Creates genres that don't exist yet, handling race conditions.

        Args:
            media_item_guid: The media item GUID
            genre_names: List of genre names to set

        Returns:
            The updated media item or None if not found
        """
        from pyrate.models.genre import Genre

        result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.guid == media_item_guid)
            .options(selectinload(MediaItem.genres))
        )
        media_item = result.scalars().first()
        if not media_item:
            return None

        existing = await self._upsert_by_names(Genre, genre_names)
        genres = [existing[n] for n in genre_names if n in existing]

        media_item.genres = genres
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        await self.db.refresh(media_item)

        logger.info(
            "Set %s genres for %s: %s", len(genres), media_item.title, [g.name for g in genres]
        )
        return media_item

    async def set_platforms(
        self,
        media_item_guid: uuid.UUID,
        platform_data: list[dict],
        commit: bool = True,
    ) -> MediaItem | None:
        """Set platforms for a media item.

        Args:
            media_item_guid: The media item GUID
            platform_data: List of dicts with 'name' and optionally 'id' (igdb_id),
                          'logo_url'. Creates platforms that don't exist yet.
        """
        from pyrate.models.platform import Platform

        result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.guid == media_item_guid)
            .options(selectinload(MediaItem.platforms))
        )
        media_item = result.scalars().first()
        if not media_item:
            return None

        platform_names = [p.get("name") for p in platform_data if p.get("name")]
        if not platform_names:
            return media_item

        # Build lookup for extra data (logo, igdb_id)
        data_by_name = {p["name"]: p for p in platform_data if p.get("name")}

        def _extra_values(name: str) -> dict:
            extra = data_by_name.get(name, {})
            return {"igdb_id": extra.get("id"), "logo_url": extra.get("logo_url")}

        existing = await self._upsert_by_names(Platform, platform_names, extra_values_fn=_extra_values)

        # Update logo_url for existing platforms if we have new data
        for name, platform in existing.items():
            extra = data_by_name.get(name, {})
            if extra.get("logo_url") and not platform.logo_url:
                platform.logo_url = extra["logo_url"]
            if extra.get("id") and not platform.igdb_id:
                platform.igdb_id = extra["id"]

        platforms = [existing[n] for n in platform_names if n in existing]
        media_item.platforms = platforms
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        await self.db.refresh(media_item)

        logger.info(
            "Set %s platforms for %s: %s", len(platforms), media_item.title, [p.name for p in platforms]
        )
        return media_item

    # ==================== READ ====================

    async def get_by_id(
        self,
        guid: uuid.UUID,
        load_files: bool = False,
        load_releases: bool = False,
        load_external_ids: bool = False,
    ) -> MediaItem | None:
        """Get media item by GUID with optional eager loading."""
        query = select(MediaItem).where(MediaItem.guid == guid)
        query = query.options(
            selectinload(MediaItem.genres),
            selectinload(MediaItem.platforms),
        )

        if load_files:
            query = query.options(selectinload(MediaItem.files))
        if load_releases:
            from pyrate.models.media import MediaRelease

            query = query.options(
                selectinload(MediaItem.releases).selectinload(MediaRelease.links)
            )
        if load_external_ids:
            query = query.options(selectinload(MediaItem.external_ids))

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_external_id(
        self,
        provider: str,
        external_id: str,
        media_type: MediaType | None = None,
    ) -> MediaItem | None:
        """Get media item by external ID (e.g., TMDB ID)."""
        query = (
            select(MediaItem)
            .join(MediaExternalId)
            .where(
                MediaExternalId.provider == provider,
                MediaExternalId.external_id == external_id,
            )
        )

        if media_type:
            query = query.where(MediaItem.media_type == media_type)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def list_by_type(
        self,
        media_type: MediaType,
        library_guid: uuid.UUID | None = None,
        parent_guid: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> list[MediaItem]:
        """
        List media items by type with filtering.

        Args:
            media_type: Type of media to list
            library_guid: Filter by library
            parent_guid: Filter by parent (e.g., episodes of a season)
            limit: Max results
            offset: Pagination offset
            order_by: Field to order by
            order_desc: Descending order if True
        """
        query = select(MediaItem).where(MediaItem.media_type == media_type)

        # library_guid filter removed - use media_type filter instead

        if parent_guid is not None:
            query = query.where(MediaItem.parent_guid == parent_guid)

        # Order by
        order_field = getattr(MediaItem, order_by, MediaItem.created_at)
        if order_desc:
            order_field = order_field.desc()
        query = query.order_by(order_field)

        query = query.limit(limit).offset(offset)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def search(
        self,
        query_string: str,
        media_type: MediaType | None = None,
        library_guid: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[MediaItem]:
        """
        Search media items by title.

        Args:
            query_string: Search query
            media_type: Optional filter by type
            library_guid: Optional filter by library
            limit: Max results
        """
        query = select(MediaItem).where(
            or_(
                MediaItem.title.ilike(f"%{query_string}%"),
                MediaItem.original_title.ilike(f"%{query_string}%"),
            )
        )

        if media_type:
            query = query.where(MediaItem.media_type == media_type)

        # library_guid filter removed - use media_type filter instead

        query = query.limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_children(
        self,
        parent_guid: uuid.UUID,
        order_by_sequence: bool = True,
    ) -> list[MediaItem]:
        """
        Get child media items (e.g., seasons of a show, episodes of a season, tracks of an album).

        Args:
            parent_guid: Parent media item GUID
            order_by_sequence: Order by sequence_number if True
        """
        query = select(MediaItem).where(MediaItem.parent_guid == parent_guid)

        if order_by_sequence:
            query = query.order_by(MediaItem.sequence_number)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_child_by_sequence(
        self,
        parent_guid: uuid.UUID,
        sequence_number: int,
    ) -> MediaItem | None:
        """
        Get a single child media item by parent and sequence number.

        Used for deduplication during import: seasons by season number,
        episodes by episode number within a season.

        Args:
            parent_guid: Parent media item GUID
            sequence_number: The sequence number to look up (season #, episode #, etc.)
        """
        query = select(MediaItem).where(
            and_(
                MediaItem.parent_guid == parent_guid,
                MediaItem.sequence_number == sequence_number,
            )
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def count_by_type(
        self,
        media_type: MediaType,
        library_guid: uuid.UUID | None = None,
    ) -> int:
        """Count media items by type."""
        query = select(func.count(MediaItem.guid)).where(
            MediaItem.media_type == media_type
        )

        # library_guid filter removed - use media_type filter instead

        result = await self.db.execute(query)
        return result.scalar() or 0

    # ==================== UPDATE ====================

    async def update(
        self,
        guid: uuid.UUID,
        commit: bool = True,
        **kwargs: Any,
    ) -> MediaItem | None:
        """Update media item fields."""
        media_item = await self.get_by_id(guid)
        if not media_item:
            return None

        for key, value in kwargs.items():
            if hasattr(media_item, key):
                setattr(media_item, key, value)

        media_item.updated_at = datetime.now(UTC)

        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        await self.db.refresh(media_item)

        return media_item

    async def update_availability_status(
        self,
        guid: uuid.UUID,
        status: AvailabilityStatus,
        commit: bool = True,
    ) -> MediaItem | None:
        """Update availability status."""
        return await self.update(guid, commit=commit, availability_status=status)

    async def mark_metadata_updated(
        self,
        guid: uuid.UUID,
        commit: bool = True,
    ) -> MediaItem | None:
        """Mark metadata as recently updated."""
        return await self.update(
            guid,
            commit=commit,
            last_metadata_updated_at=datetime.now(UTC),
        )

    async def mark_searched(
        self,
        guid: uuid.UUID,
        commit: bool = True,
    ) -> MediaItem | None:
        """Mark as recently searched for releases."""
        return await self.update(guid, commit=commit, last_searched_at=datetime.now(UTC))

    # ==================== DELETE ====================

    async def delete(self, guid: uuid.UUID, *, commit: bool = True) -> bool:
        """Delete media item (cascades to files, releases, etc.)."""
        media_item = await self.get_by_id(guid)
        if not media_item:
            return False

        await self.db.delete(media_item)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

        logger.info("Deleted media item: %s (%s)", media_item.title, guid)
        return True

    async def delete_file(self, file_guid: uuid.UUID, *, commit: bool = True) -> bool:
        """Delete a media file."""
        result = await self.db.execute(
            select(MediaFile).where(MediaFile.guid == file_guid)
        )
        media_file = result.scalars().first()

        if not media_file:
            return False

        await self.db.delete(media_file)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

        return True

    async def delete_release(
        self,
        release_guid: uuid.UUID,
        *,
        media_item_guid: uuid.UUID | None = None,
        commit: bool = True,
    ) -> bool:
        """Delete a media release."""
        stmt = select(MediaRelease).where(MediaRelease.guid == release_guid)
        if media_item_guid is not None:
            stmt = stmt.where(MediaRelease.media_item_guid == media_item_guid)
        result = await self.db.execute(stmt)
        release = result.scalars().first()

        if not release:
            return False

        await self.db.delete(release)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

        return True

    async def delete_all_releases(
        self,
        media_item_guid: uuid.UUID,
        *,
        commit: bool = True,
    ) -> int:
        """Delete all releases for a media item. Returns number of deleted releases."""
        from sqlalchemy import delete as sa_delete

        result = await self.db.execute(
            sa_delete(MediaRelease).where(
                MediaRelease.media_item_guid == media_item_guid
            )
        )
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        return result.rowcount

    # ==================== TYPE-SPECIFIC HELPERS ====================

    async def get_top_level_items(
        self,
        media_type: MediaType,
        library_guid: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MediaItem]:
        """
        Get top-level items only (no episodes, tracks, etc.).

        Useful for listing movies, shows (not episodes), games, albums (not tracks).
        """
        query = select(MediaItem).where(
            and_(
                MediaItem.media_type == media_type,
                MediaItem.parent_guid.is_(None),
            )
        )

        # library_guid is a deprecated non-persisted compatibility shim; media_type
        # determines the library in the unified model.
        _ = library_guid

        query = query.order_by(MediaItem.created_at.desc()).limit(limit).offset(offset)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_with_files(
        self,
        guid: uuid.UUID,
    ) -> MediaItem | None:
        """Get media item with all files loaded."""
        return await self.get_by_id(guid, load_files=True)

    async def get_with_releases(
        self,
        guid: uuid.UUID,
    ) -> MediaItem | None:
        """Get media item with all releases loaded."""
        return await self.get_by_id(guid, load_releases=True)

    async def has_files(self, guid: uuid.UUID) -> bool:
        """Check if media item has any files."""
        result = await self.db.execute(
            select(func.count(MediaFile.guid)).where(MediaFile.media_item_guid == guid)
        )
        count = result.scalar() or 0
        return count > 0

    async def has_releases(self, guid: uuid.UUID) -> bool:
        """Check if media item has any releases."""
        result = await self.db.execute(
            select(func.count(MediaRelease.guid)).where(
                MediaRelease.media_item_guid == guid
            )
        )
        count = result.scalar() or 0
        return count > 0

    # ==================== PLUGIN INTEGRATION ====================

    async def get_library_plugin(self, media_type: MediaType):
        """Get the library plugin for this media type."""
        return get_plugin_instance(media_type.value)

    async def validate_with_plugin(
        self,
        media_type: MediaType,
        file_path: str,
    ) -> bool:
        """Validate file using library plugin."""
        plugin = await self.get_library_plugin(media_type)
        if plugin:
            return await plugin.validate_path(file_path)
        return True

    # ==================== FILE VALIDATION ====================

    @staticmethod
    def is_valid_video_file(f: Path) -> bool:
        """Check if a path points to a valid video file for import.

        Args:
            f: Path object representing the file

        Returns:
            True if the file is a valid video file, False otherwise
        """
        if not f.is_file():
            return False
        if f.suffix.lower() not in {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".mpg", ".mpeg"}:
            return False
        if "sample" in f.name.lower():
            return False
        return True

    # ==================== RELEASE SELECTION ====================

    async def select_best_release(
        self,
        media_item: MediaItem,
        releases: list[MediaRelease],
        user_preferences: dict[str, Any] | None = None,
        user_languages: list[str] | None = None,
        allowed_languages: list[str] | None = None,
        supported_video_codecs: list[str] | None = None,
        supported_audio_codecs: list[str] | None = None,
        codec_match_bonus: int = 0,
        codec_mismatch_penalty: int = 0,
    ) -> MediaRelease | None:
        """Select the best release for a media item using quality scoring.

        Args:
            media_item: The media item
            releases: List of available releases
            user_preferences: Optional user quality preferences (overrides DB config)
            user_languages: Ordered list of ISO 639-1 language codes (e.g. ['de', 'en'])
            allowed_languages: List of ISO 639-1 codes allowed by the library admin

        Returns:
            The best matching release, or None if no releases are provided
        """
        from pyrate.services.settings import SettingsService

        if not releases:
            return None

        # Resolve the library plugin. MOVIES/SHOWS keep their dedicated
        # scoring plugins; MUSIC/BOOKS/GAMES use their plugin too (flat
        # additive base score) so they can be quality-profile gated.
        from pyrate.services.quality_profile import (
            QualityProfileService,
            plugin_key_for,
        )

        plugin_key = plugin_key_for(media_item.media_type)
        library_plugin = (
            get_plugin_instance(plugin_key) if plugin_key else None
        )

        # Effective quality profile. Gate selection only when a profile is
        # explicitly configured (favorites variant wins for favorite-monitored
        # items) AND no explicit per-call user_preferences were passed;
        # otherwise behaviour is unchanged (legacy additive selection).
        qp_service = QualityProfileService(self.db)
        try:
            profile, profile_explicit = await qp_service.effective(media_item)
        except Exception as e:
            logger.warning("Could not resolve quality profile: %s", e)
            profile, profile_explicit = None, False
        use_profile = profile_explicit and user_preferences is None

        if library_plugin is None and not use_profile:
            logger.warning(
                "No library plugin found for media type %s", media_item.media_type
            )
            return releases[0]

        # Load scoring preferences: explicit user_preferences >
        # profile.scoring (when profile-gated) > DB config > None (defaults)
        scoring_preferences = user_preferences
        if scoring_preferences is None and use_profile and profile is not None:
            scoring_preferences = qp_service.to_scoring_preferences(profile)
        if scoring_preferences is None:
            try:
                media_type_str = (
                    media_item.media_type.value
                    if hasattr(media_item.media_type, "value")
                    else str(media_item.media_type)
                ).lower()
                settings_service = SettingsService(self.db)
                config_key = f"scoring.config.{media_type_str}"
                scoring_preferences = await settings_service.get(config_key, None)
            except Exception as e:
                logger.warning("Could not load scoring config: %s", e)

        # Inject language context into scoring preferences
        if user_languages or allowed_languages is not None:
            if scoring_preferences is None:
                scoring_preferences = {}
            if user_languages:
                scoring_preferences["user_languages"] = user_languages
            if allowed_languages is not None:
                scoring_preferences["allowed_languages"] = allowed_languages

        # Inject codec compatibility preferences into scoring preferences
        if supported_video_codecs or supported_audio_codecs or codec_match_bonus or codec_mismatch_penalty:
            if scoring_preferences is None:
                scoring_preferences = {}
            if supported_video_codecs:
                scoring_preferences.setdefault("supported_video_codecs", supported_video_codecs)
            if supported_audio_codecs:
                scoring_preferences.setdefault("supported_audio_codecs", supported_audio_codecs)
            if codec_match_bonus:
                scoring_preferences.setdefault("codec_match_bonus", codec_match_bonus)
            if codec_mismatch_penalty:
                scoring_preferences.setdefault("codec_mismatch_penalty", codec_mismatch_penalty)

        scored_releases = []
        for release in releases:
            try:
                if release.release_metadata:
                    metadata = release.release_metadata
                elif library_plugin is not None:
                    metadata = await library_plugin.extract_release_metadata(release.title)
                else:
                    metadata = {}
                # Inject publish_date for age-based scoring
                if hasattr(release, "publish_date") and release.publish_date:
                    metadata["publish_date"] = release.publish_date.isoformat()
                if library_plugin is not None:
                    score = await library_plugin.score_release(metadata, scoring_preferences)
                else:
                    score = 50.0
                logger.debug("Release '%s' scored %.1f/100", release.title, score)
                scored_releases.append({"release": release, "score": score, "metadata": metadata})
            except Exception as e:
                logger.warning("Failed to score release %s: %s", release.title, e)
                scored_releases.append({"release": release, "score": 25.0, "metadata": {}})

        # Filter out releases with score 0 (hard-rejected, e.g. wrong
        # language / blocked group / over-retention-age).
        scored_releases = [r for r in scored_releases if r["score"] > 0]
        if not scored_releases:
            return None

        if use_profile and profile is not None:
            # Profile-gated: keep only releases whose parsed quality is an
            # allowed rung, then order by profile rung (Sonarr-style),
            # then revision (proper/repack), then additive score.
            from pyrate.libraries.quality import parse_quality

            gated = []
            for r in scored_releases:
                q = parse_quality(
                    r["metadata"] or {},
                    media_type=media_item.media_type,
                    title=r["release"].title,
                )
                pos = qp_service.profile_position(profile, q.id)
                if pos is None:
                    continue  # quality not allowed by the profile
                r["qpos"] = pos
                r["qrev"] = q.revision
                gated.append(r)
            if not gated:
                logger.info(
                    "No release within quality profile '%s' for %s",
                    profile.name, media_item.guid,
                )
                return None
            gated.sort(
                key=lambda x: (x["qpos"], x["qrev"], x["score"]), reverse=True
            )
            best = gated[0]
            logger.info(
                "Selected best release (profile '%s'): '%s' qpos=%d score=%.1f",
                profile.name, best["release"].title, best["qpos"], best["score"],
            )
            return best["release"]

        scored_releases.sort(key=lambda x: x["score"], reverse=True)
        best = scored_releases[0]
        logger.info(
            "Selected best release: '%s' with score %.1f/100", best['release'].title, best['score']
        )
        return best["release"]

    # ==================== CLEANUP ====================

    async def cleanup_temp_files(self, session_id: str) -> dict:
        """
        Clean up temporary transcoding files for a session.

        Args:
            session_id: The transcoding session ID

        Returns:
            dict with cleanup results
        """
        result = {
            "temp_files_deleted": 0,
            "temp_files_failed": 0,
            "errors": [],
        }

        # Find all temp files for this session
        temp_patterns = [
            f"/temp/{session_id}.m3u8",
            f"/temp/{session_id}_*.ts",
        ]

        for pattern in temp_patterns:
            temp_files = glob.glob(pattern)
            for temp_file in temp_files:
                try:
                    Path(temp_file).unlink(missing_ok=True)
                    result["temp_files_deleted"] += 1
                    logger.debug("Deleted temp file: %s", temp_file)
                except Exception as e:
                    result["temp_files_failed"] += 1
                    result["errors"].append(f"Failed to delete {temp_file}: {e}")
                    logger.warning("Failed to delete temp file %s: %s", temp_file, e)

        # Clean up trickplay sprite directory
        import shutil

        trickplay_dir = Path(f"/temp/{session_id}_trickplay")
        if trickplay_dir.exists():
            try:
                shutil.rmtree(trickplay_dir)
                logger.debug("Deleted trickplay directory: %s", trickplay_dir)
            except Exception as e:
                result["errors"].append(f"Failed to delete trickplay dir: {e}")
                logger.warning("Failed to delete trickplay dir %s: %s", trickplay_dir, e)

        logger.info(
            "Temp cleanup for session %s: deleted %s, failed %s",
            session_id, result['temp_files_deleted'], result['temp_files_failed']
        )

        return result

    async def cleanup_media_file(
        self,
        media_item_guid: UUID | str,
        file_path: str | None = None,
        delete_media_item: bool = True,
    ) -> dict:
        """
        Clean up a media file from disk and database.

        Args:
            media_item_guid: The GUID of the media item
            file_path: Optional specific file path (if known from session)
            delete_media_item: Whether to delete the MediaItem if no files remain

        Returns:
            dict with cleanup results
        """
        if isinstance(media_item_guid, str):
            media_item_guid = UUID(media_item_guid)

        result = {
            "files_deleted_from_disk": 0,
            "files_deleted_from_db": 0,
            "media_item_deleted": False,
            "errors": [],
        }

        try:
            # Get all media files for this item
            files_result = await self.db.execute(
                select(MediaFile).where(MediaFile.media_item_guid == media_item_guid)
            )
            media_files = files_result.scalars().all()

            # Delete DB rows first, then touch disk. Committing the DB before
            # unlinking guarantees we never leave the DB pointing at a file we
            # already deleted (or a file-less torso) if the transaction rolls back.
            paths_to_delete: list[Path] = []
            for media_file in media_files:
                # If specific file_path provided, only delete that one
                if file_path and media_file.file_path != file_path:
                    continue

                paths_to_delete.append(Path(media_file.file_path))
                await self.db.delete(media_file)
                result["files_deleted_from_db"] += 1
                logger.info("Deleted media file from DB: %s", media_file.guid)

            # Delete the media item in the same transaction when no files remain.
            if delete_media_item:
                await self.db.flush()
                remaining_result = await self.db.execute(
                    select(MediaFile).where(
                        MediaFile.media_item_guid == media_item_guid
                    )
                )
                if remaining_result.scalars().first() is None:
                    media_item_result = await self.db.execute(
                        select(MediaItem).where(MediaItem.guid == media_item_guid)
                    )
                    media_item = media_item_result.scalars().first()
                    if media_item:
                        await self.db.delete(media_item)
                        result["media_item_deleted"] = True
                        logger.info(
                            "Deleted media item from DB: %s (%s)", media_item.guid, media_item.title
                        )

            await self.db.commit()

            # DB is now consistent; remove the physical files it no longer references.
            for file_path_obj in paths_to_delete:
                if file_path_obj.exists():
                    try:
                        file_path_obj.unlink()
                        result["files_deleted_from_disk"] += 1
                        logger.info("Deleted media file from disk: %s", file_path_obj)
                        # Also try to remove empty parent directories
                        self._cleanup_empty_dirs(file_path_obj.parent)
                    except Exception as e:
                        result["errors"].append(
                            f"Failed to delete {file_path_obj}: {e}"
                        )
                        logger.warning(
                            "Failed to delete media file %s: %s", file_path_obj, e
                        )
                else:
                    logger.debug(
                        "Media file not on disk (already deleted?): %s", file_path_obj
                    )

        except Exception as e:
            result["errors"].append(f"Database error: {e}")
            logger.error("Error during media cleanup: %s", e, exc_info=True)
            await self.db.rollback()

        return result

    def _cleanup_empty_dirs(self, directory: Path, stop_at: str = "/library") -> None:
        """
        Remove empty directories up to a stop point.

        Args:
            directory: Starting directory to check
            stop_at: Stop removing when reaching this path
        """
        try:
            current = directory
            while str(current) != stop_at and current != current.parent:
                if current.exists() and current.is_dir():
                    # Check if directory is empty
                    if not any(current.iterdir()):
                        current.rmdir()
                        logger.debug("Removed empty directory: %s", current)
                        current = current.parent
                    else:
                        break
                else:
                    break
        except Exception as e:
            logger.debug("Could not clean up directories: %s", e)

    async def cleanup_orphaned_temp_files(self, max_age_hours: int = 2) -> dict:
        """
        Clean up orphaned temp files that are older than max_age_hours.

        This is a background cleanup job that runs periodically.

        Args:
            max_age_hours: Maximum age of temp files in hours

        Returns:
            dict with cleanup results
        """
        import time

        result = {
            "files_scanned": 0,
            "files_deleted": 0,
            "errors": [],
        }

        max_age_seconds = max_age_hours * 3600
        current_time = time.time()

        try:
            # Find all .ts and .m3u8 files in /temp
            temp_files = glob.glob("/temp/*.ts") + glob.glob("/temp/*.m3u8")
            result["files_scanned"] = len(temp_files)

            for temp_file in temp_files:
                try:
                    file_path = Path(temp_file)
                    file_age = current_time - file_path.stat().st_mtime

                    if file_age > max_age_seconds:
                        file_path.unlink(missing_ok=True)
                        result["files_deleted"] += 1
                        logger.debug(
                            "Deleted orphaned temp file: %s (age: %.1fh)",
                            temp_file, file_age / 3600
                        )
                except Exception as e:
                    result["errors"].append(f"Failed to process {temp_file}: {e}")

            logger.info(
                "Orphaned temp cleanup: scanned %s, deleted %s",
                result['files_scanned'], result['files_deleted']
            )

        except Exception as e:
            result["errors"].append(f"Cleanup error: {e}")
            logger.error("Error during orphaned temp cleanup: %s", e)

        return result

    # ==================== Hierarchical Navigation ====================

    async def _get_item_light(self, guid: UUID) -> MediaItem | None:
        """Get a media item without eager-loading relationships."""
        result = await self.db.execute(
            select(MediaItem).where(MediaItem.guid == guid)
        )
        return result.scalars().first()

    async def get_next_sibling(self, item_guid: UUID) -> dict | None:
        """Get the next item in sequence (e.g. next episode, next track).

        If at the end of the current parent (season/album), returns the
        first child of the next parent (next season/next album).

        Returns dict with guid, title, sequence_number, season_number
        or None if no next item exists.
        """
        current = await self._get_item_light(item_guid)
        if not current or not current.parent_guid:
            return None

        # Next item in same parent
        result = await self.db.execute(
            select(MediaItem)
            .where(
                MediaItem.parent_guid == current.parent_guid,
                MediaItem.sequence_number > current.sequence_number,
            )
            .order_by(MediaItem.sequence_number.asc())
            .limit(1)
        )
        next_item = result.scalars().first()

        # Load parent for season_number
        parent = await self._get_item_light(current.parent_guid)

        if next_item:
            return self._nav_response(next_item, parent_seq=parent.sequence_number if parent else None)
        if not parent or not parent.parent_guid:
            return None

        result = await self.db.execute(
            select(MediaItem)
            .where(
                MediaItem.parent_guid == parent.parent_guid,
                MediaItem.sequence_number > parent.sequence_number,
            )
            .order_by(MediaItem.sequence_number.asc())
            .limit(1)
        )
        next_parent = result.scalars().first()
        if not next_parent:
            return None

        result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.parent_guid == next_parent.guid)
            .order_by(MediaItem.sequence_number.asc())
            .limit(1)
        )
        first_child = result.scalars().first()
        if first_child:
            return self._nav_response(first_child, parent_seq=next_parent.sequence_number)
        return None

    async def get_previous_sibling(self, item_guid: UUID) -> dict | None:
        """Get the previous item in sequence.

        If at the start of the current parent, returns the last child
        of the previous parent.
        """
        current = await self._get_item_light(item_guid)
        if not current or not current.parent_guid:
            return None

        # Previous item in same parent
        result = await self.db.execute(
            select(MediaItem)
            .where(
                MediaItem.parent_guid == current.parent_guid,
                MediaItem.sequence_number < current.sequence_number,
            )
            .order_by(MediaItem.sequence_number.desc())
            .limit(1)
        )
        prev_item = result.scalars().first()

        # Load parent for season_number
        parent = await self._get_item_light(current.parent_guid)

        if prev_item:
            return self._nav_response(prev_item, parent_seq=parent.sequence_number if parent else None)
        if not parent or not parent.parent_guid:
            return None

        result = await self.db.execute(
            select(MediaItem)
            .where(
                MediaItem.parent_guid == parent.parent_guid,
                MediaItem.sequence_number < parent.sequence_number,
            )
            .order_by(MediaItem.sequence_number.desc())
            .limit(1)
        )
        prev_parent = result.scalars().first()
        if not prev_parent:
            return None

        result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.parent_guid == prev_parent.guid)
            .order_by(MediaItem.sequence_number.desc())
            .limit(1)
        )
        last_child = result.scalars().first()
        if last_child:
            return self._nav_response(last_child, parent_seq=prev_parent.sequence_number)
        return None

    @staticmethod
    def _nav_response(item: MediaItem, parent_seq: int | None) -> dict:
        return {
            "guid": str(item.guid),
            "title": item.title,
            "sequence_number": item.sequence_number,
            "season_number": parent_seq,
            "poster_path": item.poster_path,
        }


async def cleanup_stream_on_stop(
    db: AsyncSession,
    session_id: str,
    content_id: str | UUID | None = None,
    input_path: str | None = None,
    delete_library_file: bool = False,
) -> dict:
    """
    Full cleanup when a stream is stopped.

    Cleans up temp transcoding files. We do NOT touch the source media file —
    it lives on the rclone mount backing multiple future playbacks, and
    deleting it here propagates a remote delete. The retention task owns
    source-file lifecycle.

    Args:
        db: Database session
        session_id: Transcoding session ID
        content_id: Media item GUID (kept for API compatibility)
        input_path: Original file path (kept for API compatibility)
        delete_library_file: Ignored — retained for backward compatibility.

    Returns:
        dict with all cleanup results
    """
    media_service = MediaService(db)
    result = {
        "session_id": session_id,
        "temp_cleanup": {},
        "library_cleanup": {},
    }

    # Clean up temp files only. The source file is the original rclone-backed
    # media_file and must survive — retention handles its lifecycle.
    result["temp_cleanup"] = await media_service.cleanup_temp_files(session_id)

    _ = (content_id, input_path, delete_library_file)

    return result

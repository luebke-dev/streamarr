"""Auto-download service - selects and dispatches the best release for a media item."""

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.downloads import Download, DownloadStatus
from pyrate.models.media import (
    MediaFile,
    MediaItem,
    MediaRelease,
    MediaReleaseLink,
    MediaType,
)
from pyrate.models.user import User
from pyrate.services.downloader import DownloaderService
from pyrate.services.media import MediaService
from pyrate.services.settings import SettingsService

logger = logging.getLogger(__name__)


class AutoDownloadService:
    """Handles eligibility checks, release selection, and download dispatch."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def auto_download(
        self,
        media_item_guid: str,
        user_preferences: dict[str, Any] | None = None,
        user_guid: str | None = None,
        *,
        upgrade: bool = False,
        replace_media_file_guid: str | None = None,
        backfill: bool = False,
        platform: str | None = None,
    ) -> dict[str, Any] | None:
        """Automatically download the best available release for a media item.

        Returns a dict with download info on success, or None if no download was created.

        Args:
            media_item_guid: GUID of the media item
            user_preferences: Optional user quality preferences
            user_guid: Optional GUID of the requesting user (used for language scoring)
            upgrade: When True this is a quality upgrade — an existing file is
                allowed (and will be replaced on successful import). The new
                release must still be a profile-allowed improvement.
            replace_media_file_guid: GUID of the MediaFile this upgrade replaces.
            backfill: When True this is part of a deliberate favorites backfill
                (acquire-missing only; does not bypass the file-exists check).
        """
        logger.info("Starting auto-download for media item %s", media_item_guid)

        # Load media item with releases
        media_item = await self._load_media_item(media_item_guid)
        if not media_item:
            logger.warning("Media item %s not found", media_item_guid)
            return None

        # Check eligibility
        if not await self._is_eligible(media_item, upgrade=upgrade):
            return None

        # Filter blacklisted releases
        releases = self._filter_blacklisted(media_item.releases or [])
        if not releases:
            logger.warning(
                "All releases for media item %s are blacklisted, no alternatives available",
                media_item.guid,
            )
            return None

        # Platform-scoped acquisition: when the player asked for a specific
        # platform (e.g. N64), only download a release for THAT platform so a
        # multi-platform title (N64 ROM vs 3DS remake vs PC port) doesn't grab
        # the wrong one — which our retro container couldn't even run.
        if platform:
            releases = self._filter_by_platform(releases, platform)
            if not releases:
                logger.warning(
                    "No %s release for media item %s", platform, media_item.guid
                )
                return None

        # Resolve user preferences and codec settings
        scoring_params = await self._resolve_scoring_params(media_item, user_guid)

        # Select best release
        best_release = await MediaService(self.db).select_best_release(
            media_item,
            releases,
            user_preferences,
            **scoring_params,
        )

        if not best_release:
            logger.warning("No suitable release found for media item %s", media_item.guid)
            return None

        # Final upgrade guard: never replace an existing file unless the
        # chosen release is a genuine profile-allowed improvement.
        if upgrade:
            from pyrate.services import upgrade_interfaces as ui

            if not await ui.is_upgrade_wanted(
                self.db, media_item, best_release
            ):
                logger.info(
                    "Best release for %s is not an upgrade, skipping",
                    media_item.guid,
                )
                return None

        # Get download link
        best_link = await self._get_best_link(best_release)
        if not best_link:
            logger.warning(
                "Best release has no download links for media item %s",
                media_item.guid,
            )
            return None

        # Get appropriate downloader (depends on link type, not media type —
        # a movie may have nzb or magnet links and they go to different services)
        downloader = await self._get_downloader(media_item, best_link)
        if not downloader:
            return None

        # Create and dispatch download
        download = await self._create_download(
            media_item, best_release, best_link, downloader, user_guid,
            is_upgrade=upgrade, replace_media_file_guid=replace_media_file_guid,
        )

        return {
            "download_guid": str(download.guid),
            "title": best_release.title,
            "media_item_guid": media_item_guid,
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _load_media_item(self, media_item_guid: str) -> MediaItem | None:
        result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.guid == media_item_guid)
            .options(
                selectinload(MediaItem.releases).selectinload(MediaRelease.links),
            )
        )
        return result.scalar_one_or_none()

    async def _is_eligible(
        self, media_item: MediaItem, *, upgrade: bool = False
    ) -> bool:
        """Check if media item is eligible for download.

        Normally an item with an existing file (or an in-progress download)
        is skipped. For ``upgrade=True`` an existing file is *expected* and
        the file-exists check is bypassed (the completion handler swaps the
        old file for the new one); the in-progress check still applies so we
        never double-dispatch.
        """
        if not upgrade:
            # Check if already has a file
            files_result = await self.db.execute(
                select(MediaFile).where(
                    MediaFile.media_item_guid == media_item.guid
                )
            )
            if files_result.first() is not None:
                logger.info(
                    "Media item %s already has a file, skipping", media_item.guid
                )
                return False

        # Check if download already in progress
        downloads_result = await self.db.execute(
            select(Download)
            .join(
                MediaReleaseLink,
                Download.media_release_link_guid == MediaReleaseLink.guid,
            )
            .join(
                MediaRelease,
                MediaReleaseLink.media_release_guid == MediaRelease.guid,
            )
            .where(MediaRelease.media_item_guid == media_item.guid)
            .where(Download.status.notin_(DownloadStatus.ACTIVE_EXCLUSIONS))
        )
        if downloads_result.first() is not None:
            logger.info("Download already in progress for media item %s", media_item.guid)
            return False

        # Global cap on concurrent upgrade downloads so enabling upgrades on
        # a large library can't storm the downloaders.
        if upgrade:
            try:
                cap = int(
                    await SettingsService(self.db).get(
                        "automation.max_concurrent_upgrade_downloads", 3
                    )
                    or 3
                )
            except Exception:
                cap = 3
            active_upgrades = await self.db.execute(
                select(func.count())
                .select_from(Download)
                .where(Download.is_upgrade.is_(True))
                .where(Download.status.notin_(DownloadStatus.ACTIVE_EXCLUSIONS))
            )
            if (active_upgrades.scalar() or 0) >= cap:
                logger.info(
                    "Upgrade concurrency cap (%d) reached, deferring %s",
                    cap, media_item.guid,
                )
                return False

        return True

    def _filter_by_platform(
        self, releases: list[MediaRelease], platform: str
    ) -> list[MediaRelease]:
        """Keep only releases for ``platform``.

        Prefer releases explicitly tagged with the platform (e.g. "…-N64-ROM");
        if none are tagged, fall back to untagged releases. A release tagged for
        a DIFFERENT known platform (3DS remake, GameCube, PC port) is always
        excluded so we never acquire something the chosen runtime can't run.
        """
        from pyrate.services.game_platforms import platform_from_release_title

        tagged = [
            r for r in releases
            if platform_from_release_title(getattr(r, "title", "")) == platform
        ]
        if tagged:
            return tagged
        return [
            r for r in releases
            if platform_from_release_title(getattr(r, "title", "")) in (None, platform)
        ]

    def _filter_blacklisted(self, releases: list[MediaRelease]) -> list[MediaRelease]:
        """Filter out blacklisted releases."""
        total_before = len(releases)
        filtered = [r for r in releases if r.blacklisted_reason is None]

        if len(filtered) < total_before:
            logger.info(
                "Filtered out %s blacklisted releases, %s remaining",
                total_before - len(filtered),
                len(filtered),
            )

        return filtered

    async def _resolve_scoring_params(
        self, media_item: MediaItem, user_guid: str | None
    ) -> dict[str, Any]:
        """Load user language preference, codec settings, and library config for scoring."""
        resolved_user_languages: list[str] | None = None
        resolved_supported_video_codecs: list[str] = []
        resolved_supported_audio_codecs: list[str] = []
        resolved_codec_match_bonus: int = 0
        resolved_codec_mismatch_penalty: int = 0

        if user_guid:
            try:
                user_result = await self.db.execute(
                    select(User).where(User.guid == user_guid)
                )
                user_obj = user_result.scalar_one_or_none()
                if user_obj:
                    resolved_user_languages = user_obj.audio_languages
                    qp = user_obj.quality_preferences or {}
                    resolved_supported_video_codecs = qp.get(
                        "supported_video_codecs", []
                    )
                    resolved_supported_audio_codecs = qp.get(
                        "supported_audio_codecs", []
                    )
                    resolved_codec_match_bonus = qp.get("codec_match_bonus", 0)
                    resolved_codec_mismatch_penalty = qp.get(
                        "codec_mismatch_penalty", 0
                    )
            except Exception as e:
                logger.warning("Could not load user language for scoring: %s", e)

        # Load library allowed_languages
        resolved_allowed_languages: list[str] = []
        settings_service = SettingsService(self.db)
        try:
            media_type_str = (
                media_item.media_type.value
                if hasattr(media_item.media_type, "value")
                else str(media_item.media_type)
            ).lower()
            raw_allowed = await settings_service.get(
                f"plugin.{media_type_str}.allowed_languages", []
            )
            if isinstance(raw_allowed, list):
                resolved_allowed_languages = raw_allowed
        except Exception as e:
            logger.warning("Could not load allowed_languages for scoring: %s", e)

        # Check if admin enabled codec-aware downloads
        try:
            prefer_compatible = await settings_service.get(
                "transcoding.prefer_compatible_codecs", False
            )
            if not prefer_compatible:
                resolved_supported_video_codecs = []
                resolved_supported_audio_codecs = []
                resolved_codec_match_bonus = 0
                resolved_codec_mismatch_penalty = 0
        except Exception as e:
            logger.warning("Could not load prefer_compatible_codecs setting: %s", e)

        return {
            "user_languages": resolved_user_languages,
            "allowed_languages": resolved_allowed_languages or None,
            "supported_video_codecs": resolved_supported_video_codecs or None,
            "supported_audio_codecs": resolved_supported_audio_codecs or None,
            "codec_match_bonus": resolved_codec_match_bonus,
            "codec_mismatch_penalty": resolved_codec_mismatch_penalty,
        }

    async def _get_best_link(self, release: MediaRelease) -> MediaReleaseLink | None:
        """Get the first download link for a release."""
        links_result = await self.db.execute(
            select(MediaReleaseLink).where(
                MediaReleaseLink.media_release_guid == release.guid
            )
        )
        links = links_result.scalars().all()
        return links[0] if links else None

    # Link types are produced by indexer/metadata plugins; keep this map close
    # to where it's consumed so a new downloader plugin only needs one edit.
    # Keys are MediaReleaseLink.link_type, values are downloader.type strings
    # (case-insensitive). First match wins; allow a manual override list per
    # link type for future flexibility.
    _LINK_TYPE_TO_DOWNLOADER_TYPES: dict[str, tuple[str, ...]] = {
        "nzb": ("usenet_downloader", "sabnzbd"),
        "magnet": ("torrent_downloader", "deluge"),
        "torrent": ("torrent_downloader", "deluge"),
        "spotify": ("spotdl",),
    }

    async def _get_downloader(
        self, media_item: MediaItem, link: MediaReleaseLink
    ) -> Any | None:
        """Pick the downloader that can actually process this link.

        Selection is driven by the *link type*, not the media type. A movie
        with an ``nzb`` link must go to a usenet downloader even if the user
        also has a spotdl configured, otherwise the job sits pending forever
        because spotdl can't process nzb URLs (we hit this in production).
        """
        downloaders = await DownloaderService(self.db).get_all()
        if not downloaders:
            logger.warning("No downloaders configured")
            return None

        link_type = (link.link_type or "").lower()
        compatible_types = self._LINK_TYPE_TO_DOWNLOADER_TYPES.get(link_type)
        if not compatible_types:
            logger.warning(
                "No downloader mapping for link_type=%r (link guid=%s); "
                "media_type=%s — extend _LINK_TYPE_TO_DOWNLOADER_TYPES",
                link_type, link.guid, media_item.media_type,
            )
            return None

        for desired in compatible_types:
            for d in downloaders:
                if (d.type or "").lower() == desired:
                    logger.info(
                        "Selected downloader type=%s label=%s for link_type=%s",
                        d.type, d.label, link_type,
                    )
                    return d

        logger.warning(
            "No configured downloader matches link_type=%r (need one of %s); "
            "configured types: %s",
            link_type,
            list(compatible_types),
            [d.type for d in downloaders],
        )
        return None

    async def _create_download(
        self,
        media_item: MediaItem,
        best_release: MediaRelease,
        best_link: MediaReleaseLink,
        downloader: Any,
        user_guid: str | None,
        *,
        is_upgrade: bool = False,
        replace_media_file_guid: str | None = None,
    ) -> Download:
        """Create the Download record, commit, and dispatch the download task."""
        replaces_guid: uuid.UUID | None = None
        if replace_media_file_guid:
            try:
                replaces_guid = uuid.UUID(str(replace_media_file_guid))
            except (ValueError, TypeError):
                replaces_guid = None
        download = Download(
            guid=uuid.uuid4(),
            downloader_id=downloader.guid,
            external_id=None,
            title=best_release.title,
            type=media_item.media_type.value,
            status="pending",
            media_release_link_guid=best_link.guid,
            user_guid=uuid.UUID(user_guid) if user_guid else None,
            is_upgrade=is_upgrade,
            replaces_media_file_guid=replaces_guid,
        )
        self.db.add(download)
        await self.db.commit()

        logger.info(
            "Created download for media item %s: %s",
            media_item.title,
            best_release.title,
        )

        # Dispatch to appropriate download task
        await self._dispatch_download(media_item, best_link, user_guid)

        return download

    @staticmethod
    async def _dispatch_download(
        media_item: MediaItem,
        best_link: MediaReleaseLink,
        user_guid: str | None,
    ) -> None:
        """Start the download by dispatching to the appropriate task."""
        # Import here to avoid circular imports (worker imports this service)
        from pyrate.worker import add_download, add_music_download, add_show_download

        if media_item.media_type in (MediaType.SONGS, MediaType.ALBUMS):
            await add_music_download.kiq(str(best_link.guid), user_guid)
        elif media_item.media_type == MediaType.SHOWS:
            await add_show_download.kiq(str(best_link.guid), user_guid)
        else:
            await add_download.kiq(str(best_link.guid), user_guid)

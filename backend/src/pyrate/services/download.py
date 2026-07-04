"""
Download Service

This service handles download operations including adding downloads
to downloader clients, managing download status, and handling completed downloads.
"""

import asyncio
import logging
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.downloaders.deluge import Deluge
from pyrate.downloaders.sabnzbd import Sabnzbd
from pyrate.libraries import get_library_type_for_media_item_type, get_plugin_instance
from pyrate.models.downloader import Downloader
from pyrate.models.downloads import Download, DownloadStatus
from pyrate.models.media import (
    MediaFile,
    MediaItem,
    MediaRelease,
    MediaReleaseLink,
)
from pyrate.services.download_status import download_phase
from pyrate.services.observability import (
    record_download_retry_event,
    record_download_transition,
)

logger = logging.getLogger(__name__)


# Errors caused by our infrastructure (full disk, dead network, NNTP timeouts,
# downloader container down, etc.) say nothing about whether the release itself
# is good. Blacklisting on these cripples future auto-download attempts —
# the release stays excluded long after the underlying problem is fixed.
# Match conservatively: substring search on the lowercased reason. Anything
# matched here marks the *link* attempt as failed but lets the release stay
# selectable; everything else gets the legacy "release is bad" treatment.
_TRANSIENT_ERROR_FRAGMENTS: tuple[str, ...] = (
    "no space left on device",
    "disk full",
    "enospc",
    # Local filesystem / mount failures. A remote-backed download dir (e.g. an
    # rclone/FUSE mount) surfaces a FULL disk as a generic EIO ("I/O error
    # (os error 5)") rather than ENOSPC, so ENOSPC alone missed it and every
    # grab blacklisted its release. These are infra faults, never a bad release.
    "i/o error",
    "input/output error",
    "os error 5",
    "cannot create dest dir",
    "cannot create temp dir",
    "write error",
    "read-only file system",
    "os error 28",  # ENOSPC surfaced as a raw errno by some backends
    "connection refused",
    "connection reset",
    "connection timed out",
    "network is unreachable",
    "temporary failure in name resolution",
    "broken pipe",
    "read timeout",
    "operation timed out",
    "503 service unavailable",
    "502 bad gateway",
    "504 gateway timeout",
)


def _is_transient_error(reason: str | None) -> bool:
    """Return True when *reason* indicates an infra problem, not a bad release."""
    if not reason:
        return False
    lowered = reason.lower()
    return any(fragment in lowered for fragment in _TRANSIENT_ERROR_FRAGMENTS)


class DownloadService:
    """Service for managing downloads."""

    def __init__(self, db: AsyncSession):
        """Initialize the download service.

        Args:
            db: Database session
        """
        self.db = db

    @staticmethod
    def _build_display_title(download: Download) -> dict:
        """Build display title and media metadata for a download.

        Traverses the release link -> release -> media item -> parent hierarchy
        to construct a human-readable display title (e.g. "Show - S01E03 - Episode Title").

        Args:
            download: Download with eagerly loaded relationships

        Returns:
            Dict with keys: display_title, media_item_guid, media_title,
            show_title, season_number, episode_number
        """
        display_title = download.title
        media_item_guid = None
        media_title = None
        show_title = None
        season_number = None
        episode_number = None

        if download.media_release_link:
            try:
                release_link = download.media_release_link
                if release_link.release and release_link.release.media_item:
                    media_item = release_link.release.media_item
                    media_item_guid = str(media_item.guid)
                    media_title = media_item.title

                    # Check if this is an episode: has parent (season) which has parent (show)
                    season = media_item.parent
                    if season and season.parent:
                        show = season.parent
                        show_title = show.title
                        season_number = season.sequence_number
                        episode_number = media_item.sequence_number
                        season_str = str(season_number or 0).zfill(2)
                        episode_str = str(episode_number or 0).zfill(2)
                        display_title = f"{show_title} - S{season_str}E{episode_str} - {media_title}"
                    else:
                        display_title = media_title
            except Exception as e:
                logger.warning("Failed to resolve download display title: %s", e)

        return {
            "display_title": display_title,
            "media_item_guid": media_item_guid,
            "media_title": media_title,
            "show_title": show_title,
            "season_number": season_number,
            "episode_number": episode_number,
        }

    async def list_downloads(
        self, user_guid: uuid.UUID | None = None
    ) -> list[dict]:
        """List all downloads with resolved media information.

        Args:
            user_guid: Optional filter by user GUID

        Returns:
            List of dicts ready for DownloadResponse construction
        """
        query = select(Download)
        if user_guid:
            query = query.where(Download.user_guid == user_guid)
        result = await self.db.execute(
            query
            .options(
                selectinload(Download.media_release_link)
                .selectinload(MediaReleaseLink.release)
                .selectinload(MediaRelease.media_item)
                .selectinload(MediaItem.parent)  # season
                .selectinload(MediaItem.parent),  # show (grandparent)
                selectinload(Download.started_by),
                selectinload(Download.downloader),
            )
            .order_by(Download.created_at.desc())
        )
        downloads = result.scalars().all()

        response = []
        for download in downloads:
            meta = self._build_display_title(download)
            response.append(
                {
                    "guid": str(download.guid),
                    "title": download.title,
                    "display_title": meta["display_title"],
                    "type": download.type,
                    "status": download.status,
                    "status_phase": download_phase(download.status),
                    "status_detail": download.error_reason,
                    "progress": download.progress,
                    "speed_bps": download.speed_bps,
                    "media_item_guid": meta["media_item_guid"],
                    "media_title": meta["media_title"],
                    "show_title": meta["show_title"],
                    "season_number": meta["season_number"],
                    "episode_number": meta["episode_number"],
                    "downloader_name": download.downloader.label if download.downloader else None,
                    "downloader_type": download.downloader.type if download.downloader else None,
                    "user_guid": str(download.user_guid) if download.user_guid else None,
                    "started_by_name": (
                        f"{download.started_by.first_name} {download.started_by.last_name}".strip()
                        if download.started_by
                        else None
                    ),
                    "created_at": download.created_at,
                    "error_reason": download.error_reason,
                }
            )

        return response

    async def delete(self, download_id: uuid.UUID) -> Download | None:
        """Delete a download by ID and cancel it on the downloader.

        Removing the row alone leaves the job running on the downloader
        (eating bandwidth + a Newshosting connection slot). Best-effort
        DELETE on the downloader's job endpoint first; we still drop the
        row even if the cancel call fails so a stale or unreachable
        downloader can't trap the entry forever.

        Args:
            download_id: GUID of the download to delete

        Returns:
            The deleted Download if found, None otherwise
        """
        download = await self.db.get(Download, download_id)
        if not download:
            return None

        if download.external_id and download.downloader_id:
            downloader = await self.db.get(Downloader, download.downloader_id)
            if downloader is not None:
                client = None
                try:
                    client = self.get_downloader_client(downloader)
                    await client.remove(download.external_id)
                    logger.info(
                        "Cancelled download %s (%s) on %s",
                        download.title, download.external_id, downloader.label,
                    )
                except Exception as exc:
                    # Already-gone job, network glitch, or unknown
                    # downloader type — log and continue with the local
                    # delete so the user isn't blocked.
                    logger.warning(
                        "Could not cancel %s on downloader %s: %s",
                        download.external_id, downloader.label, exc,
                    )
                finally:
                    if client is not None:
                        await client.close()

        await self.db.delete(download)
        await self.db.commit()
        return download

    async def _set_paused(
        self, download_id: uuid.UUID, paused: bool
    ) -> Download | None:
        """Pause or resume a download on its downloader.

        The downloader is the source of truth for run state; the local
        ``status`` is reconciled by the regular poll, but we set it eagerly
        so the UI reflects the action immediately.
        """
        download = await self.db.get(Download, download_id)
        if not download:
            return None
        if not (download.external_id and download.downloader_id):
            return download

        downloader = await self.db.get(Downloader, download.downloader_id)
        if downloader is not None:
            client = None
            try:
                client = self.get_downloader_client(downloader)
                if paused:
                    await client.pause_download(download.external_id)
                else:
                    await client.resume_job(download.external_id)
            except Exception as exc:
                logger.warning(
                    "Could not %s %s on downloader %s: %s",
                    "pause" if paused else "resume",
                    download.external_id,
                    downloader.label,
                    exc,
                )
                raise
            finally:
                if client is not None:
                    await client.close()

        download.status = DownloadStatus.QUEUED
        if not paused:
            download.speed_bps = 0
        self.db.add(download)
        await self.db.commit()
        return download

    async def pause(self, download_id: uuid.UUID) -> Download | None:
        return await self._set_paused(download_id, True)

    async def resume(self, download_id: uuid.UUID) -> Download | None:
        return await self._set_paused(download_id, False)

    def get_downloader_client(self, downloader: Downloader) -> Sabnzbd | Deluge:
        """Factory method to create the appropriate downloader client.

        Args:
            downloader: Downloader model instance

        Returns:
            Instance of the appropriate downloader client (Sabnzbd or Deluge)
        """
        # Delegate to DownloaderService
        from pyrate.services.downloader import DownloaderService

        return DownloaderService.get_client(downloader)

    async def extract_external_id_from_response(
        self, downloader: Downloader, status: dict
    ) -> str | None:
        """Extract external ID from downloader response based on downloader type.

        Args:
            downloader: The downloader instance
            status: Response from the downloader's add_by_url method

        Returns:
            External ID string if successful, None otherwise
        """
        downloader_type = downloader.type.lower()

        if downloader_type == "deluge":
            external_id = status.get("torrent_hash")
            if not external_id:
                logger.error(
                    "Failed to get torrent hash from Deluge response: %s", status
                )
                return None
        elif downloader_type in ("spotdl", "torrent_downloader", "usenet_downloader"):
            external_id = status.get("job_id")
            if not external_id:
                logger.error(
                    "Failed to get job_id from %s response: %s", downloader_type, status
                )
                return None
        else:  # sabnzbd or default
            nzo_ids = status.get("nzo_ids", [])
            if not nzo_ids:
                logger.error("Failed to get nzo_ids from SABnzbd response: %s", status)
                return None
            external_id = nzo_ids[0]

        return external_id

    async def add_media_download(
        self,
        release_link_guid: str,
        downloaders: list[Downloader],
        media_type: str,
        user_guid: uuid.UUID | None = None,
    ) -> Download | None:
        """Add a media download to the first available downloader.

        Unified method for all media types (movies, shows, games, etc.).

        Args:
            release_link_guid: GUID of the MediaReleaseLink
            downloaders: List of available downloaders
            media_type: Type of media ("movie", "show", "game", etc.)

        Returns:
            The created Download object if successful, None otherwise
        """
        # Fetch release link with relationships
        result = await self.db.execute(
            select(MediaReleaseLink)
            .where(MediaReleaseLink.guid == release_link_guid)
            .options(
                selectinload(MediaReleaseLink.release).selectinload(
                    MediaRelease.media_item
                )
            )
        )
        release_link = result.scalars().first()
        if not release_link:
            logger.error("Release link with GUID %s not found.", release_link_guid)
            return None

        media_item = release_link.release.media_item

        # Short-circuit any task retry that would otherwise create a second
        # download row for an already-active job.
        active_download = await self.db.execute(
            select(Download)
            .where(Download.media_release_link_guid == release_link_guid)
            .where(
                Download.status.in_(
                    (
                        DownloadStatus.QUEUED,
                        DownloadStatus.DOWNLOADING,
                        DownloadStatus.COMPLETED,
                    )
                )
            )
            .limit(1)
        )
        already_active = active_download.scalars().first()
        if already_active:
            logger.info(
                "Download for release_link %s already %s, skipping duplicate add",
                release_link_guid, already_active.status,
            )
            return already_active

        existing_download = await self.db.execute(
            select(Download)
            .where(Download.media_release_link_guid == release_link_guid)
            .where(Download.status == DownloadStatus.PENDING)
        )
        existing_download = existing_download.scalars().first()

        # Filter downloaders by media type:
        # Music (spotify links) must use spotdl, everything else uses non-spotdl
        if media_type == "music":
            compatible = [d for d in downloaders if d.type.lower() == "spotdl"]
        else:
            compatible = [d for d in downloaders if d.type.lower() != "spotdl"]

        if not compatible:
            # Fallback to all downloaders if no type-specific ones found
            logger.warning(
                "No %s-compatible downloader found, trying all downloaders",
                media_type,
            )
            compatible = downloaders

        # Try each compatible downloader until one succeeds
        for downloader in compatible:
            client = self.get_downloader_client(downloader)
            try:
                status = await client.add_by_url(release_link.link)
            except Exception as exc:
                logger.warning(
                    "Downloader %s failed to accept %s: %s",
                    downloader.guid, media_item.title, exc,
                )
                continue
            finally:
                await client.close()
            external_id = await self.extract_external_id_from_response(
                downloader, status
            )

            if not external_id:
                continue

            if existing_download:
                # Update existing pending download
                existing_download.external_id = external_id
                old_status = existing_download.status
                existing_download.status = DownloadStatus.QUEUED
                existing_download.downloader_id = downloader.guid
                await self.db.commit()
                record_download_transition(old_status, existing_download.status, "add_media_download")
                logger.info("Updated existing download for %s", media_item.title)
                return existing_download
            else:
                # Create new download
                download = Download(
                    downloader_id=downloader.guid,
                    external_id=external_id,
                    # Derive the type from the media item (authoritative) rather
                    # than the caller's hint — the generic `add_download` task
                    # hardcodes "movie", which mistyped game/other downloads.
                    title=media_item.title,
                    type=getattr(media_item.media_type, "value", media_type),
                    status=DownloadStatus.QUEUED,
                    media_release_link_guid=release_link_guid,
                    user_guid=user_guid,
                )
                self.db.add(download)
                await self.db.commit()
                await self.db.refresh(download)
                record_download_transition(None, download.status, "add_media_download")
                logger.info(
                    "Added %s download to %s: %s", media_type, downloader.guid, status
                )
                return download

        logger.error(
            "Failed to add %s download for release link %s", media_type, release_link_guid
        )
        return None

    async def add_music_download(
        self,
        release_guid: str,
        downloaders: list[Downloader],
        user_guid: uuid.UUID | None = None,
    ) -> Download | None:
        """Add a music download to the first available spotdl downloader.

        Args:
            release_guid: GUID of the MediaReleaseLink
            downloaders: List of available downloaders
            user_guid: Optional GUID of the user who started the download

        Returns:
            The created or updated Download object if successful, None otherwise
        """
        # Filter to spotdl downloaders only
        spotdl_downloaders = [d for d in downloaders if d.type.lower() == "spotdl"]
        if not spotdl_downloaders:
            logger.error("No spotdl downloader configured for music downloads")
            return None
        return await self.add_media_download(
            release_guid, spotdl_downloaders, "music", user_guid
        )

    async def update_downloads_from_client(
        self, downloader: Downloader
    ) -> dict[str, int]:
        """Update download statuses from downloader client.

        Args:
            downloader: The downloader to refresh

        Returns:
            Dictionary with statistics: {'updated': count, 'completed': count, 'failed': count}
        """
        client = self.get_downloader_client(downloader)
        try:
            status = await client.get_downloads()
        finally:
            await client.close()

        # Batch fetch all downloads by external IDs
        external_ids = [item["external_id"] for item in status]
        if external_ids:
            result = await self.db.execute(
                select(Download).where(Download.external_id.in_(external_ids))
            )
            downloads_by_external_id = {
                download.external_id: download for download in result.scalars().all()
            }
        else:
            downloads_by_external_id = {}

        updated_count = 0
        completed_count = 0
        failed_count = 0

        # Update download statuses
        for item in status:
            download = downloads_by_external_id.get(item["external_id"])
            if download and download.status not in DownloadStatus.TERMINAL:
                old_status = download.status
                old_progress = download.progress
                old_speed = download.speed_bps

                download.status = item["status"]
                download.progress = float(item.get("progress", 0.0))
                download.speed_bps = int(item.get("speed_bps", 0) or 0)

                # Only commit if something actually changed
                if (
                    download.status != old_status
                    or download.progress != old_progress
                    or download.speed_bps != old_speed
                ):
                    self.db.add(download)
                    updated_count += 1

                    if download.status != old_status:
                        record_download_transition(old_status, download.status, "poll")
                        logger.info(
                            "Updated download %s %s status to %s",
                            download.title, download.external_id, item['status']
                        )
                    elif download.progress != old_progress:
                        logger.info(
                            "Updated download %s %s progress to %s%%",
                            download.title, download.external_id, download.progress
                        )

                if download.status == DownloadStatus.COMPLETED:
                    completed_count += 1
                elif download.status == DownloadStatus.FAILED:
                    failed_count += 1

        await self.db.commit()

        return {"updated": updated_count, "completed": completed_count, "failed": failed_count}

    VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".mpg", ".mpeg"}
    AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma"}
    EBOOK_EXTENSIONS = {".epub", ".pdf", ".mobi", ".azw", ".azw3", ".cbr", ".cbz", ".djvu"}
    AUDIOBOOK_EXTENSIONS = {".m4b", ".mp3", ".m4a", ".aac", ".ogg", ".opus"}

    def is_valid_video_file(self, file_path: Path) -> bool:
        """Check if a file is a valid video file.

        Args:
            file_path: Path to the file

        Returns:
            True if valid video file, False otherwise
        """
        if not file_path.is_file():
            return False

        if file_path.suffix.lower() not in self.VIDEO_EXTENSIONS:
            return False

        if "sample" in file_path.name.lower():
            return False

        return True

    def is_valid_audio_file(self, file_path: Path) -> bool:
        """Check if a file is a valid audio file."""
        if not file_path.is_file():
            return False
        return file_path.suffix.lower() in self.AUDIO_EXTENSIONS

    def is_valid_book_file(self, file_path: Path) -> bool:
        """Check if a file is a valid ebook or audiobook file."""
        if not file_path.is_file():
            return False
        return file_path.suffix.lower() in (
            self.EBOOK_EXTENSIONS | self.AUDIOBOOK_EXTENSIONS
        )

    def is_valid_media_file(self, file_path: Path, media_type: str) -> bool:
        """Check if a file is valid for the given media type."""
        library_type = get_library_type_for_media_item_type(media_type)
        if library_type == "MUSIC":
            return self.is_valid_audio_file(file_path)
        if library_type == "BOOKS":
            return self.is_valid_book_file(file_path)
        if library_type == "GAMES":
            return self.is_valid_game_file(file_path)
        return self.is_valid_video_file(file_path)

    @staticmethod
    def is_valid_game_file(file_path: Path) -> bool:
        """A ROM/game file (console ROM, disc image, PC installer/archive).

        Console ROMs aren't videos, so the default video check wrongly rejected
        them (\"No valid media files found\"). RetroArch also loads zipped ROMs,
        so archives count too.
        """
        from pyrate.services.game_platforms import ROM_EXTENSIONS

        game_exts = ROM_EXTENSIONS | {".iso", ".exe", ".msi", ".rar", ".7z", ".zip"}
        return file_path.suffix.lower() in game_exts

    @staticmethod
    def _title_tokens(text: str) -> set[str]:
        """Lowercased alphanumeric tokens of length >= 3 from a release-style
        name. The trailing "-GROUP" release tag is stripped first — otherwise
        two unrelated releases that happen to share a release group (x265-FuN)
        would appear to "match"."""
        from pyrate.parsers.release_parser import ReleaseParser

        cleaned = ReleaseParser.RELEASE_GROUP_PATTERN.sub("", Path(text).stem)
        return {
            t
            for t in re.split(r"[^A-Za-z0-9]+", cleaned.lower())
            if len(t) >= 3 and not t.isdigit()
        }

    def _detect_content_mismatch(
        self, download_title: str, file_name: str, library_type: str,
    ) -> str | None:
        """Return a reason string if the file clearly belongs to a different
        release than the one we asked to download; None otherwise.

        Catches rclone cross-directory leaks: a Chicago Med download that
        somehow yields a Daredevil episode, an American Pie download that
        yields Daredevil, etc. Uses a simple token-overlap check + S##E##
        parity for shows.
        """
        from pyrate.parsers.release_parser import ReleaseParser

        if library_type == "SHOWS":
            dl = ReleaseParser.parse_show_release(download_title)
            f = ReleaseParser.parse_show_release(file_name)
            if (
                dl.season is not None
                and f.season is not None
                and (dl.season, dl.episode) != (f.season, f.episode)
            ):
                return (
                    f"S{dl.season:02d}E{dl.episode or 0:02d} expected, "
                    f"got '{file_name}' (S{f.season:02d}E{f.episode or 0:02d})"
                )

        # Token overlap: at least one alphabetic token of length >= 3 from the
        # release title must appear in the file name. "Chicago.Med...x265-FuN"
        # and "Daredevil.Born.Again...x265-FuN" still share "x265" / "FuN",
        # so drop the quality/codec/release-group boilerplate first.
        boilerplate = {
            "ac3", "dts", "web", "webrip", "bluray", "brrip", "bdrip", "hdtv",
            "dvd", "dvdrip", "720p", "1080p", "2160p", "480p", "4320p",
            "german", "english", "multi", "dual", "sub", "subbed",
            "x264", "x265", "h264", "h265", "hevc", "avc", "av1", "xvid",
            "dl", "rip", "web-dl", "remux", "sdr", "hdr", "dv", "ddp",
            "ac3d", "mkv", "mp4", "avi",
        }
        dl_tokens = self._title_tokens(download_title) - boilerplate
        file_tokens = self._title_tokens(file_name) - boilerplate
        if dl_tokens and file_tokens and not (dl_tokens & file_tokens):
            return (
                f"No overlapping title tokens between '{download_title}' and "
                f"'{file_name}'"
            )
        return None

    async def get_by_external_id(self, external_id: str) -> Download | None:
        """Get a download by its external ID.

        Args:
            external_id: The external ID from the downloader

        Returns:
            Download object if found, None otherwise
        """
        result = await self.db.execute(
            select(Download).where(Download.external_id == external_id)
        )
        return result.scalar_one_or_none()

    async def mark_as_imported(self, download: Download) -> None:
        """Mark a download as imported.

        Args:
            download: The download to mark
        """
        old_status = download.status
        download.status = DownloadStatus.IMPORTED
        self.db.add(download)
        await self.db.commit()
        record_download_transition(old_status, download.status, "import")

    async def mark_as_failed(self, download: Download, reason: str = None) -> None:
        """Mark a download as failed.

        Args:
            download: The download to mark
            reason: Optional failure reason
        """
        old_status = download.status
        download.status = DownloadStatus.FAILED
        download.error_reason = reason
        if reason:
            logger.error("Download %s failed: %s", download.external_id, reason)
        self.db.add(download)
        await self.db.commit()
        record_download_transition(old_status, download.status, "failure")

    async def blacklist_download(
        self,
        download: Download,
        reason: str | None = None,
        retriable: bool | None = None,
    ) -> bool:
        """Blacklist the release associated with a failed download.

        Sets `blacklisted_reason` on the MediaRelease so that it is
        excluded from future automatic selection.

        Args:
            download: The failed download
            reason: Human-readable failure reason
            retriable: Authoritative infra-vs-release classification from the
                downloader. When ``True`` the failure was the downloader's/
                infrastructure's fault (disk IO, network) and the release is
                NOT blacklisted. When ``None`` (older downloaders that don't
                report it) we fall back to matching the reason text.

        Returns:
            True if the release was successfully blacklisted.
        """
        try:
            await self.db.refresh(download, attribute_names=["media_release_link"])
            if not download.media_release_link:
                logger.warning(
                    "Cannot blacklist download %s: no release link", download.external_id
                )
                return False

            await self.db.refresh(
                download.media_release_link, attribute_names=["release"]
            )
            release = download.media_release_link.release
            if not release:
                logger.warning(
                    "Cannot blacklist download %s: no release", download.external_id
                )
                return False

            if release.blacklisted_reason:
                logger.info("Release '%s' is already blacklisted", release.title)
                return True

            # Prefer the downloader's structured classification; fall back to
            # matching the free-text reason only when it isn't reported.
            is_transient = (
                retriable if retriable is not None else _is_transient_error(reason)
            )
            if is_transient:
                # Infra problem (disk full, network down, ...). Don't poison the
                # release pool — the next auto-download attempt should be free
                # to retry this release once the infra is healthy again.
                logger.warning(
                    "Skipping blacklist for release '%s' (media %s) — transient error: %s",
                    release.title, release.media_item_guid, reason,
                )
                return False

            release.blacklisted_reason = reason or "Unknown failure"
            self.db.add(release)
            await self.db.commit()
            logger.info(
                "Blacklisted release '%s' for media item %s: %s",
                release.title, release.media_item_guid, release.blacklisted_reason
            )
            return True
        except Exception as e:
            logger.error("Failed to blacklist release for download %s: %s", download.external_id, e)
            return False

    async def try_alternative_link(
        self, download: Download, error_msg: str, retriable: bool | None = None
    ) -> MediaReleaseLink | None:
        """Try an alternative download link for the same release.

        When a download fails (e.g. missing Usenet articles), another indexer
        may have the same release.  This method marks the failed link, finds
        an untried link for the same release, and queues a new download.

        ``retriable`` is the downloader's structured infra-vs-release verdict
        (see :meth:`blacklist_download`); when ``None`` we fall back to matching
        the ``error_msg`` text.

        Returns the alternative link if one was found and queued, else None.
        """
        try:
            await self.db.refresh(download, attribute_names=["media_release_link"])
            failed_link = download.media_release_link
            if not failed_link:
                return None

            await self.db.refresh(failed_link, attribute_names=["release"])
            release = failed_link.release
            if not release:
                return None

            # Mark the failed link so we don't retry it — unless this was an
            # infra hiccup (full disk, network), in which case keep the link
            # selectable so the release can be retried after recovery.
            is_transient = (
                retriable if retriable is not None else _is_transient_error(error_msg)
            )
            if is_transient:
                logger.info(
                    "Not blacklisting link %s of release '%s' — transient error: %s",
                    failed_link.guid, release.title, error_msg,
                )
                record_download_retry_event("transient_link_retry_allowed")
            else:
                failed_link.blacklisted_reason = error_msg
                self.db.add(failed_link)

            # Find alternative links for the same release
            result = await self.db.execute(
                select(MediaReleaseLink)
                .where(MediaReleaseLink.media_release_guid == release.guid)
                .where(MediaReleaseLink.guid != failed_link.guid)
                .where(MediaReleaseLink.blacklisted_reason.is_(None))
            )
            alt_link = result.scalars().first()
            if not alt_link:
                return None

            # Get the downloader to queue the alternative
            downloader = None
            if download.downloader_id:
                dl_result = await self.db.execute(
                    select(Downloader).where(Downloader.guid == download.downloader_id)
                )
                downloader = dl_result.scalar_one_or_none()

            if not downloader:
                return None

            client = self.get_downloader_client(downloader)
            try:
                status = await client.add_by_url(alt_link.link)
            finally:
                await client.close()
            external_id = await self.extract_external_id_from_response(downloader, status)
            if not external_id:
                return None

            # Create a new download for the alternative link
            new_download = Download(
                downloader_id=downloader.guid,
                external_id=external_id,
                title=download.title,
                type=download.type,
                status=DownloadStatus.QUEUED,
                media_release_link_guid=alt_link.guid,
                user_guid=download.user_guid,
            )
            self.db.add(new_download)
            await self.db.commit()
            record_download_retry_event("alternative_link_queued")
            record_download_transition(None, new_download.status, "alternative_link")

            logger.info(
                "Retrying release '%s' with alternative link %s",
                release.title, alt_link.guid,
            )
            return alt_link

        except Exception as e:
            logger.error("Failed to try alternative link: %s", e)
            return None

    async def get_media_item_guid_for_download(self, download: Download) -> uuid.UUID | None:
        """Resolve the media_item_guid that a download belongs to.

        Navigates Download -> MediaReleaseLink -> MediaRelease -> media_item_guid.

        Returns:
            The media item GUID or None.
        """
        try:
            await self.db.refresh(download, attribute_names=["media_release_link"])
            if not download.media_release_link:
                return None
            await self.db.refresh(
                download.media_release_link, attribute_names=["release"]
            )
            if not download.media_release_link.release:
                return None
            return download.media_release_link.release.media_item_guid
        except Exception:
            return None

    async def handle_failed_download(
        self, result: dict, external_id: str
    ) -> dict | None:
        """Extract retry information from a failed/blacklisted download result.

        Checks if the result indicates a blacklisted release and recovers the
        ``media_item_guid`` and ``user_guid`` needed to queue an automatic
        retry with the next best release.

        Args:
            result: The result dict from a completed-download or refresh
                handler.  Must contain ``"blacklisted": True`` and
                ``"media_item_guid"`` to be actionable.
            external_id: The downloader's external ID for the download.

        Returns:
            A dict with ``media_item_guid`` (str) and ``user_guid``
            (str | None) if a retry should be queued, or ``None`` otherwise.
        """
        if not result.get("blacklisted") or not result.get("media_item_guid"):
            return None

        media_item_guid = result["media_item_guid"]
        download = await self.get_by_external_id(external_id)
        user_guid = (
            str(download.user_guid) if download and download.user_guid else None
        )

        logger.info(
            "Release blacklisted for media item %s, preparing retry info",
            media_item_guid,
        )
        record_download_retry_event("next_release_retry_prepared")
        return {"media_item_guid": media_item_guid, "user_guid": user_guid}

    async def handle_completed_download(
        self,
        external_id: str,
        path: str,
        expected_files: list[str] | None = None,
    ) -> dict:
        """Handle a completed download by its external ID.

        This method moves the downloaded files to the library, probes them for
        metadata, and creates the appropriate file records.

        Args:
            external_id: External ID of the download from the downloader
            path: Path to the downloaded files
            expected_files: Basenames the downloader actually produced. When
                provided, only files in this list are considered for import —
                this is the authoritative whitelist against rclone cross-dir
                leaks.

        Returns:
            dict: Result with success status and file info
        """
        # Already imported at top

        download = await self.get_by_external_id(external_id)

        if not download:
            logger.error("Download with external ID %s not found.", external_id)
            return {"success": False, "error": "Download not found"}

        # Idempotency: if a previous webhook/retry already imported this
        # download (status IMPORTED or FAILED), short-circuit before touching
        # the filesystem or creating duplicate MediaFile rows.
        if download.status == DownloadStatus.IMPORTED:
            logger.info(
                "Download %s already imported, skipping duplicate completion",
                external_id,
            )
            return {"success": True, "files_imported": 0, "already_imported": True}
        if download.status == DownloadStatus.FAILED:
            logger.info(
                "Download %s already marked failed, skipping",
                external_id,
            )
            return {"success": False, "error": "Download already failed"}

        downloader = await self.db.get(Downloader, download.downloader_id)
        if not downloader:
            logger.error("Downloader with ID %s not found.", download.downloader_id)
            return {"success": False, "error": "Downloader not found"}

        folder = Path(path)

        # Retry folder.exists() a few times: the usenet downloader runs on a
        # remote host and its /downloads dir is rclone-sftp-mounted with a
        # ~30s dir cache. The webhook-triggered TaskIQ handler races ahead of
        # the cache, so the freshly-finished directory may not be visible yet.
        for attempt in range(6):
            if await asyncio.to_thread(folder.exists):
                break
            await asyncio.sleep(2 ** min(attempt, 3))
        else:
            logger.error(
                "Download path does not exist: %s for download %s", path, external_id
            )
            await self.mark_as_failed(download, f"Path does not exist: {path}")
            await self.blacklist_download(download, f"Path does not exist: {path}")
            media_item_guid = await self.get_media_item_guid_for_download(download)
            return {
                "success": False,
                "error": "Path does not exist",
                "blacklisted": True,
                "media_item_guid": str(media_item_guid) if media_item_guid else None,
            }

        # Resolve the relationship chain: Download -> MediaReleaseLink -> Release -> MediaItem
        await self.db.refresh(download, attribute_names=["media_release_link"])
        if not download.media_release_link:
            logger.error(
                "Media release link not found for download %s", external_id
            )
            return {"success": False, "error": "Media release link not found"}

        await self.db.refresh(
            download.media_release_link, attribute_names=["release"]
        )
        release = download.media_release_link.release
        if not release:
            logger.error(
                "Release not found for download %s", external_id
            )
            return {"success": False, "error": "Release not found"}

        await self.db.refresh(release, attribute_names=["media_item"])
        media_item = release.media_item
        if not media_item:
            logger.error(
                "Media item not found for download %s", external_id
            )
            return {"success": False, "error": "Media item not found"}

        await self.db.refresh(media_item, attribute_names=["external_ids"])

        if await asyncio.to_thread(folder.is_file):
            files = [folder]
        else:
            # Authoritative whitelist: the downloader tells us which files it
            # actually produced for this job (list of basenames). Anything
            # outside that list is an rclone cross-directory leak and must be
            # ignored.  Retry a few times while the rclone VFS settles.
            whitelist = {Path(n).name for n in (expected_files or []) if n}
            files = []

            def _scan_media_files() -> list[Path]:
                try:
                    return [
                        f
                        for f in folder.iterdir()
                        if f.is_file()
                        and self.is_valid_media_file(f, media_item.media_type)
                    ]
                except FileNotFoundError:
                    return []

            for attempt in range(6):
                entries = await asyncio.to_thread(_scan_media_files)

                if whitelist:
                    entries = [f for f in entries if f.name in whitelist]
                if entries:
                    files = entries
                    break
                await asyncio.sleep(2 ** min(attempt, 3))

            if not files and whitelist:
                logger.error(
                    "Download %s: none of the expected files %s are visible at %s",
                    external_id, sorted(whitelist), path,
                )

        # For single-item downloads (episodes, movies), pick only the largest
        # file.  Downloads often contain extra files from unrelated releases
        # that would otherwise be imported under the wrong media item.
        library_type = get_library_type_for_media_item_type(media_item.media_type)
        if library_type in ("SHOWS", "MOVIES") and len(files) > 1:
            sizes = await asyncio.to_thread(
                lambda: {f: f.stat().st_size for f in files}
            )
            best = max(files, key=lambda f: sizes[f])
            logger.info(
                "Download %s: selected largest file %s (%d bytes) out of %d candidates",
                download.external_id, best.name, sizes[best], len(files),
            )
            files = [best]

        if not files:
            logger.error("No valid media files found in %s", path)
            await self.mark_as_failed(download, "No valid media files found")
            await self.blacklist_download(download, "No valid media files found")
            return {
                "success": False,
                "error": "No valid media files",
                "blacklisted": True,
                "media_item_guid": str(media_item.guid),
            }

        # Content guard: ensure the file we're about to import actually matches
        # the release/download we asked for. When the rclone mount misbehaves
        # (cross-directory listings) the picked file can be a completely
        # different show/movie — this flips "Chicago Med S10E06" to play a
        # Daredevil episode, etc. Reject before plugin import; don't blacklist
        # the release (the release itself is fine, the mount handed back the
        # wrong bytes). The caller can retry.
        if library_type in ("SHOWS", "MOVIES") and download.title:
            mismatch_reason = self._detect_content_mismatch(
                download.title, files[0].name, library_type,
            )
            if mismatch_reason:
                logger.error(
                    "Rejecting import for download %s: %s",
                    download.external_id, mismatch_reason,
                )
                await self.mark_as_failed(download, mismatch_reason)
                return {
                    "success": False,
                    "error": "Content mismatch",
                    "blacklisted": False,
                    "media_item_guid": str(media_item.guid),
                }

        # Get the appropriate plugin based on media type.
        # media_type may be a sub-type (e.g. "SONGS"), so resolve to the
        # library type ("MUSIC") when a direct lookup fails.
        plugin = get_plugin_instance(media_item.media_type)
        if not plugin:
            library_type = get_library_type_for_media_item_type(media_item.media_type)
            if library_type:
                plugin = get_plugin_instance(library_type)
        if not plugin:
            logger.error(
                "No plugin found for media type '%s'", media_item.media_type
            )
            return {
                "success": False,
                "error": f"No plugin for media type: {media_item.media_type}",
            }

        release_metadata = release.release_metadata

        download_context = {
            "download": download,
            "media_item": media_item,
            "release_metadata": release_metadata,
        }

        result = await plugin.handle_completed_download(
            download_context=download_context,
            files=files,
            db=self.db,
        )

        if result.get("success"):
            await self.mark_as_imported(download)
            result["media_item_guid"] = str(media_item.guid)
            result["media_type"] = str(media_item.media_type.value if hasattr(media_item.media_type, "value") else media_item.media_type)
            # Keep the remote job: its files back the media_file record. The
            # retention task removes them (and the job) once eligible.
            logger.info("Marked download %s as completed.", external_id)
            if download.is_upgrade and download.replaces_media_file_guid:
                try:
                    swapped = await self._apply_upgrade_swap(
                        download, media_item, release
                    )
                    result["upgrade_swapped"] = swapped
                except Exception as exc:
                    # Swap failure must not lose the new file; keep both,
                    # the duplicate cleanup is profile-aware and skips
                    # monitored items so nothing is clobbered.
                    logger.error(
                        "Upgrade swap failed for %s (keeping both files): %s",
                        media_item.guid, exc,
                    )
        elif download.is_upgrade:
            # Failed upgrade: keep the existing file untouched and do NOT
            # blacklist (the release isn't proven bad for first-acquire).
            error_msg = result.get("error", "Import failed")
            await self.mark_as_failed(download, error_msg)
            logger.info(
                "Upgrade import failed for %s; keeping current file",
                media_item.guid,
            )
            result["upgrade_failed"] = True
            result["media_item_guid"] = str(media_item.guid)
        else:
            # Import failed — blacklist the release and signal for retry
            error_msg = result.get("error", "Import failed")
            await self.mark_as_failed(download, error_msg)
            await self.blacklist_download(download, error_msg)
            media_item_guid = await self.get_media_item_guid_for_download(download)
            result["blacklisted"] = True
            result["media_item_guid"] = str(media_item_guid) if media_item_guid else None

        return result

    async def _apply_upgrade_swap(
        self,
        download: Download,
        media_item: MediaItem,
        release: MediaRelease,
    ) -> bool:
        """Atomically replace the old file with the freshly-imported one.

        Ordering guarantees no "unavailable" gap: the plugin already
        created + committed the new MediaFile before we touch the old one,
        so a reader between the two always sees at least one file. If no
        new file materialised we keep the old one and bail (no data loss).
        """
        old_guid = download.replaces_media_file_guid
        old_mf = await self.db.get(MediaFile, old_guid)

        # The new file = newest MediaFile for this item that isn't the old.
        res = await self.db.execute(
            select(MediaFile)
            .where(MediaFile.media_item_guid == media_item.guid)
            .where(MediaFile.guid != old_guid)
            .order_by(
                MediaFile.imported_at.is_(None).asc(),
                MediaFile.imported_at.desc(),
                MediaFile.created_at.desc(),
            )
        )
        new_mf = res.scalars().first()
        if new_mf is None:
            logger.error(
                "Upgrade import produced no new MediaFile for %s; "
                "keeping old file",
                media_item.guid,
            )
            return False

        # Persist quality linkage on the new file (S1).
        from pyrate.services import upgrade_interfaces as ui

        await ui.link_media_file_to_release(
            self.db, new_mf, release, media_item.media_type
        )

        # Remove only the old file (its specific path), never the new one
        # and never the MediaItem. Skip deletion when the plugin imported
        # the upgrade in-place to the same path — deleting that path would
        # destroy the new content (cleanup_media_file deletes every row +
        # disk file matching the path).
        if (
            old_mf is not None
            and old_mf.guid != new_mf.guid
            and old_mf.file_path != new_mf.file_path
        ):
            from pyrate.services.media import MediaService

            await MediaService(self.db).cleanup_media_file(
                media_item.guid,
                file_path=old_mf.file_path,
                delete_media_item=False,
            )
        await self.db.commit()
        logger.info(
            "Upgrade swap complete for %s: new file %s replaced %s",
            media_item.guid, new_mf.guid, old_guid,
        )
        return True

    # ------------------------------------------------------------------
    # Webhook handlers
    # ------------------------------------------------------------------

    async def get_download_by_external_id(self, external_id: str) -> Download | None:
        """Find a download by its external ID (e.g. spotdl job ID)."""
        result = await self.db.execute(
            select(Download).where(Download.external_id == external_id)
        )
        return result.scalars().first()

    async def handle_spotdl_webhook(self, payload: dict) -> dict:
        """Process a spotdl webhook notification.

        Args:
            payload: The webhook payload from spotdl containing job status.

        Returns:
            dict with processing result.
        """
        from pyrate.downloaders.spotdl import Spotdl

        job_id = payload.get("id")
        status = payload.get("status")

        download = await self.get_download_by_external_id(job_id)
        if not download:
            logger.warning("spotdl webhook for unknown job: %s", job_id)
            return {"ignored": True, "reason": "unknown_job"}

        if status == "done":
            download.status = DownloadStatus.COMPLETED
            download.progress = 100.0
            await self.db.commit()

            # Remap path from spotdl container to backend mount
            raw_path = payload.get("path", "")
            mapped_path = Spotdl._map_path(raw_path)

            logger.info(
                "spotdl webhook: job %s completed, path=%s → %s",
                job_id, raw_path, mapped_path,
            )

            # Trigger file import
            from pyrate.worker import handle_completed_download

            await handle_completed_download.kiq(job_id, mapped_path)

            return {"processed": True, "action": "import_queued", "path": mapped_path}

        elif status == "failed":
            error_msg = payload.get("error", "Download failed")
            download.status = DownloadStatus.FAILED
            await self.db.commit()

            logger.warning("spotdl webhook: job %s failed: %s", job_id, error_msg)

            # Blacklist and trigger retry
            await self.blacklist_download(download, error_msg)
            media_item_guid = await self.get_media_item_guid_for_download(download)

            return {
                "processed": True,
                "action": "failed_blacklisted",
                "error": error_msg,
                "media_item_guid": str(media_item_guid) if media_item_guid else None,
            }

        return {"ignored": True, "reason": f"unhandled_status_{status}"}

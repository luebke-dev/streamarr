import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from streamarr.services import trickplay
from streamarr.services.download_status import download_phase

# ---------------------------------------------------------------------------
# Backwards-compatible re-exports.
#
# The codec/container *decision* logic now lives canonically in
# ``streamarr.services.playback_decision`` and the transcode/probe *lifecycle*
# helpers in ``streamarr.services.transcode_lifecycle``. They are re-exported here
# so existing importers of ``streamarr.services.play`` keep working unchanged.
# ---------------------------------------------------------------------------
from streamarr.services.playback_decision import (  # noqa: F401  (re-export)
    LOSSLESS_AUDIO_CODECS,
    LOSSY_AUDIO_BITRATE_CAP,
    LOSSY_FALLBACK_CODEC,
    QUALITY_TO_RESOLUTION,
    RESOLUTION_ORDER,
    AudioQualityRestrictionResult,
    CodecNegotiationResult,
    QualityRestrictionResult,
    TranscodingDisallowedError,
    apply_audio_quality_restrictions,
    apply_quality_restrictions,
    build_stream_info,
    extract_source_info,
    is_direct_playable,
    negotiate_codecs,
)
from streamarr.services.transcode_lifecycle import (  # noqa: F401  (re-export)
    _get_base_library_path,
    _probe_video_with_computing_service,
    _structure_probe_data,
    get_active_transcode_container,
    probe_video_full,
    probe_video_metadata,
    start_transcode_container,
    start_trickplay_container,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes for structured returns
# ---------------------------------------------------------------------------

@dataclass
class PlayAction:
    """Result of resolving what action to take for a play request."""
    status: str  # "ready", "downloading", "searching", "no-release"
    message: str
    # Only when status == "ready"
    file: object | None = None
    file_path: str | None = None
    probe_data: dict | None = None
    # Only when status == "downloading"
    download_progress: float | None = None
    download_status: str | None = None
    download_phase: str | None = None
    download_status_detail: str | None = None


# ---------------------------------------------------------------------------
# Concurrent transcode capacity check
# ---------------------------------------------------------------------------

async def check_transcode_capacity(db: AsyncSession) -> bool:
    """Check if the server has capacity for another transcode session.

    Args:
        db: Database session

    Returns:
        True if capacity is available, False if the limit has been reached.
    """
    from streamarr.services.system_settings import SystemSettingsService
    from streamarr.services.transcoding_session import get_transcoding_session_service

    settings_service = SystemSettingsService(db)
    transcoding_settings = await settings_service.get_transcoding_settings()
    max_concurrent = transcoding_settings.get("max_concurrent_transcodes", 0)

    if max_concurrent > 0:
        session_service = get_transcoding_session_service()
        active_sessions = await session_service.get_all_sessions(active_only=True)
        if len(active_sessions) >= max_concurrent:
            return False

    return True


# ---------------------------------------------------------------------------
# Play action resolution (extracted from api/v1/play.py)
# ---------------------------------------------------------------------------

async def resolve_play_action(
    db: AsyncSession,
    media_item,
    media_id: UUID,
    user_guid: UUID | None = None,
    media_source_id: UUID | None = None,
) -> PlayAction:
    """Determine the play action for a media item.

    Checks (in order):
    1. File exists on disk → status='ready'
    2. Download in progress → status='downloading'
    3. Releases with links → triggers auto-download, status='downloading'
    4. Releases without links → triggers search, status='searching'
    5. No releases → triggers search, status='searching'
    """
    from streamarr.models.downloads import Download, DownloadStatus
    from streamarr.models.media import MediaFile, MediaRelease, MediaReleaseLink
    from streamarr.worker import auto_download_media_item, search_media_item_releases

    # 1. Check if file exists
    file_query = select(MediaFile).where(MediaFile.media_item_guid == media_id)
    if media_source_id is not None:
        file_query = file_query.where(MediaFile.guid == media_source_id)
    result = await db.execute(file_query)
    file = result.scalars().first()

    if file:
        file_path = Path(file.file_path)
        # Retry briefly if file was just imported (rename may still be in progress)
        exists = await asyncio.to_thread(file_path.exists)
        if not exists:
            for _ in range(3):
                await asyncio.sleep(1)
                exists = await asyncio.to_thread(file_path.exists)
                if exists:
                    break
        if exists:
            # Parse probe data
            probe_data = None
            if file.probe_data:
                try:
                    probe_data = json.loads(file.probe_data)
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning("Failed to parse probe data: %s", e)

            # Refuse to start playback before the probe has produced real data.
            # Without it ffmpeg would launch with no codec/duration and the UI
            # would show unknown runtime. Queue a re-probe and tell the
            # frontend to wait.
            has_streams = bool(
                probe_data
                and (
                    probe_data.get("video_streams")
                    or probe_data.get("audio_streams")
                    or probe_data.get("streams")
                )
            )
            if not has_streams:
                try:
                    from streamarr.worker import probe_media_file
                    await probe_media_file.kiq(str(file.guid))
                except Exception as e:
                    logger.warning("Failed to queue re-probe for %s: %s", file.guid, e)
                # Reuse the existing "downloading + importing" frontend state:
                # it shows a spinner and polls, which is what we want while
                # the re-probe finishes in the background.
                return PlayAction(
                    status="downloading",
                    message="Probe pending",
                    download_progress=100.0,
                    download_status="importing",
                    download_phase="importing",
                )

            return PlayAction(
                status="ready",
                message="File found, ready to stream",
                file=file,
                file_path=file.file_path,
                probe_data=probe_data,
            )

    # 2. Check if download in progress
    downloads_result = await db.execute(
        select(Download)
        .join(MediaReleaseLink, Download.media_release_link_guid == MediaReleaseLink.guid)
        .join(MediaRelease, MediaReleaseLink.media_release_guid == MediaRelease.guid)
        .where(MediaRelease.media_item_guid == media_id)
        .where(Download.status.notin_(DownloadStatus.TERMINAL))
    )
    existing_download = downloads_result.scalars().first()

    if existing_download:
        if existing_download.status == DownloadStatus.COMPLETED:
            return PlayAction(
                status="downloading",
                message="Download complete, importing...",
                download_progress=100.0,
                download_status="importing",
                download_phase="importing",
            )
        return PlayAction(
            status="downloading",
            message=f"Download in progress: {existing_download.status}",
            download_progress=existing_download.progress or 0.0,
            download_status=existing_download.status,
            download_phase=download_phase(existing_download.status),
            download_status_detail=existing_download.error_reason,
        )

    # 3. Check for existing releases with download links
    releases_result = await db.execute(
        select(MediaRelease)
        .where(MediaRelease.media_item_guid == media_id)
        .options(selectinload(MediaRelease.links))
        .order_by(MediaRelease.score.desc())
    )
    releases = releases_result.scalars().all()

    releases_with_links = [r for r in releases if r.links]

    # Resolve permissions once so the limit checks below can consult them
    # without three separate queries.
    perms = None
    if user_guid:
        from streamarr.services.permission import PermissionService
        perms = await PermissionService(db).resolve_user_permissions(user_guid)

    if releases_with_links:
        # Enforce on-demand download rate limit (user-initiated fetch) and
        # the indexer-downloads cap. The indexer cap covers downloads of
        # already-indexed releases; on_demand_fetch covers the play-driven
        # auto-fetch behaviour. Both must allow the action.
        if user_guid and perms is not None:
            from streamarr.services.rate_limiter import check_and_record
            allowed = await check_and_record(
                user_guid, "on_demand_fetch",
                perms.on_demand_fetch_limit,
                perms.on_demand_fetch_period_minutes,
            )
            if not allowed:
                return PlayAction(
                    status="error",
                    message="On-demand download rate limit reached. Please wait.",
                )
            allowed = await check_and_record(
                user_guid, "indexer_downloads",
                perms.indexer_downloads_limit,
                perms.indexer_downloads_period_minutes,
            )
            if not allowed:
                return PlayAction(
                    status="error",
                    message="Release download limit reached. Please wait.",
                )

        logger.info(
            "Smart Play: Found %s releases with links for %s, starting auto-download",
            len(releases_with_links), media_item.title,
        )
        await auto_download_media_item.kiq(str(media_id), None, str(user_guid) if user_guid else None)
        return PlayAction(
            status="downloading",
            message="Preparing download...",
            download_progress=0.0,
            download_status="preparing",
            download_phase="preparing",
        )

    # Both remaining branches kick off a fresh indexer search — gate them
    # together by indexer_api_requests_limit.
    if user_guid and perms is not None:
        from streamarr.services.rate_limiter import check_and_record
        allowed = await check_and_record(
            user_guid, "indexer_api_requests",
            perms.indexer_api_requests_limit,
            perms.indexer_api_requests_period_minutes,
        )
        if not allowed:
            return PlayAction(
                status="error",
                message="Indexer search rate limit reached. Please wait.",
            )

    if releases:
        logger.info(
            "Smart Play: Found %s releases but none have download links, starting search",
            len(releases),
        )
        await search_media_item_releases.kiq(str(media_id), str(user_guid) if user_guid else None)
        return PlayAction(
            status="searching",
            message=f"Searching releases for {media_item.title}...",
            download_status="searching",
            download_phase="searching",
        )

    # 5. No releases at all
    logger.info("Smart Play: No releases found for %s, starting search", media_item.title)
    await search_media_item_releases.kiq(str(media_id), str(user_guid) if user_guid else None)
    return PlayAction(
        status="searching",
        message=f"Searching releases for {media_item.title}...",
        download_status="searching",
        download_phase="searching",
    )


# ---------------------------------------------------------------------------
# Prefetch next episode (extracted from api/v1/play.py)
# ---------------------------------------------------------------------------

async def prefetch_next_episode(
    db: AsyncSession,
    current_episode_id: UUID,
    user_guid: UUID | None = None,
) -> None:
    """Find and prefetch the next episode for automatic download.

    1. Finds the next episode in the same season
    2. Checks if prefetch downloads are enabled
    3. Checks if the episode already has a file or download in progress
    4. Triggers search and download for the next episode
    """
    from streamarr.models.downloads import Download, DownloadStatus
    from streamarr.models.media import (
        MediaFile,
        MediaItem,
        MediaRelease,
        MediaReleaseLink,
        MediaType,
    )
    from streamarr.services.media import MediaService
    from streamarr.services.system_settings import SystemSettingsService
    from streamarr.worker import auto_download_media_item, search_media_item_releases

    try:
        unified_service = MediaService(db)

        current_episode = await unified_service.get_by_id(current_episode_id)
        if not current_episode or current_episode.media_type != MediaType.SHOWS:
            return

        if not current_episode.parent_guid:
            return

        season = await unified_service.get_by_id(current_episode.parent_guid)
        if not season or season.media_type != MediaType.SHOWS:
            return

        # Check if prefetch downloads are enabled
        settings_service = SystemSettingsService(db)
        show_settings = await settings_service.get_library_settings("shows")
        if not show_settings.get("enable_prefetch_downloads", False):
            logger.info("Prefetch downloads disabled for shows, skipping")
            return

        # Find next episode in same season
        next_episode = (
            await db.execute(
                select(MediaItem)
                .where(MediaItem.parent_guid == season.guid)
                .where(MediaItem.sequence_number == current_episode.sequence_number + 1)
                .where(MediaItem.media_type == MediaType.SHOWS)
            )
        ).scalars().first()

        # If no next episode, try next season
        if not next_episode:
            logger.info("No next episode in S%02d, checking next season...", season.sequence_number)
            show = await unified_service.get_by_id(season.parent_guid)
            if not show:
                return

            next_season = (
                await db.execute(
                    select(MediaItem)
                    .where(MediaItem.parent_guid == show.guid)
                    .where(MediaItem.sequence_number == season.sequence_number + 1)
                    .where(MediaItem.media_type == MediaType.SHOWS)
                )
            ).scalars().first()

            if not next_season:
                logger.info("No next season after S%02d", season.sequence_number)
                return

            next_episode = (
                await db.execute(
                    select(MediaItem)
                    .where(MediaItem.parent_guid == next_season.guid)
                    .where(MediaItem.sequence_number == 1)
                    .where(MediaItem.media_type == MediaType.SHOWS)
                )
            ).scalars().first()

            if not next_episode:
                logger.info("Next season S%02d has no episodes", next_season.sequence_number)
                return
            logger.info(
                "Found next episode: S%02dE%02d",
                next_season.sequence_number, next_episode.sequence_number,
            )

        # Check if next episode already has a file
        existing_file = (
            await db.execute(
                select(MediaFile).where(MediaFile.media_item_guid == next_episode.guid)
            )
        ).scalars().first()

        if existing_file and await asyncio.to_thread(
            Path(existing_file.file_path).exists
        ):
            logger.info("Next episode already has a file, skipping prefetch")
            return

        # Check if download already in progress
        existing_download = (
            await db.execute(
                select(Download)
                .join(MediaReleaseLink, Download.media_release_link_guid == MediaReleaseLink.guid)
                .join(MediaRelease, MediaReleaseLink.media_release_guid == MediaRelease.guid)
                .where(MediaRelease.media_item_guid == next_episode.guid)
                .where(Download.status.notin_(DownloadStatus.ACTIVE_EXCLUSIONS))
            )
        ).scalars().first()

        if existing_download:
            logger.info("Next episode already has a download in progress: %s", existing_download.status)
            return

        # Check if releases exist
        existing_releases = (
            await db.execute(
                select(MediaRelease).where(MediaRelease.media_item_guid == next_episode.guid)
            )
        ).scalars().all()

        logger.info("Prefetching next episode: %s", next_episode.title)

        if not existing_releases:
            logger.info("No releases found, searching first...")
            await search_media_item_releases.kiq(str(next_episode.guid), str(user_guid) if user_guid else None)
            await asyncio.sleep(2)

        await auto_download_media_item.kiq(str(next_episode.guid), None, str(user_guid) if user_guid else None)

    except Exception as e:
        logger.error("Error prefetching next episode: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Stream selection (audio/subtitle language matching)
# ---------------------------------------------------------------------------

def _match_language(stream_lang: str, preferred: str) -> bool:
    """Match a stream language tag against a user preference.

    Handles the mismatch between ISO 639-1 codes stored in user preferences
    (e.g. 'de', 'en', 'ja') and ISO 639-2 codes used by ffprobe/MKV files
    (e.g. 'ger'/'deu', 'eng', 'jpn').
    """
    if not stream_lang or not preferred:
        return False

    stream_lang = stream_lang.lower()
    preferred = preferred.lower()

    # Direct match or prefix match (e.g. 'de' matches 'deu', 'en' matches 'eng')
    if stream_lang.startswith(preferred) or preferred.startswith(stream_lang):
        return True

    # ISO 639-1 <-> ISO 639-2 mapping for common languages
    # Maps both bibliographic (B) and terminological (T) codes
    _ISO_MAP: dict[str, set[str]] = {
        "de": {"ger", "deu"},
        "en": {"eng"},
        "fr": {"fre", "fra"},
        "es": {"spa"},
        "it": {"ita"},
        "ja": {"jpn"},
        "ko": {"kor"},
        "zh": {"zho", "chi"},
        "pt": {"por"},
        "ru": {"rus"},
        "pl": {"pol"},
        "nl": {"nld", "dut"},
        "sv": {"swe"},
        "no": {"nor", "nob", "nno"},
        "da": {"dan"},
        "fi": {"fin"},
        "cs": {"ces", "cze"},
        "hu": {"hun"},
        "tr": {"tur"},
        "ar": {"ara"},
        "hi": {"hin"},
        "th": {"tha"},
        "uk": {"ukr"},
        "el": {"ell", "gre"},
        "he": {"heb"},
        "ro": {"ron", "rum"},
    }

    # Check if preferred (ISO 639-1) maps to stream_lang (ISO 639-2)
    if preferred in _ISO_MAP and stream_lang in _ISO_MAP[preferred]:
        return True

    # Check reverse: stream_lang might be ISO 639-1 and preferred ISO 639-2
    for iso1, iso2_set in _ISO_MAP.items():
        if stream_lang == iso1 and preferred in iso2_set:
            return True
        if preferred == iso1 and stream_lang in iso2_set:
            return True

    return False


def select_streams_for_user(
    probe_data: dict,
    preferred_audio_languages: list[str] | None = None,
    preferred_subtitle_language: str | None = None,
) -> dict:
    """
    Select the best audio and subtitle streams based on user language preferences.

    Args:
        probe_data: The probe_data dict from probe_video_full()
        preferred_audio_languages: Ordered list of preferred audio languages (e.g., ['de', 'en', 'ja']).
                                   The first matching language wins.
        preferred_subtitle_language: User's preferred subtitle language (None = disabled)

    Returns:
        Dict with selected stream indices: {audio_stream: int, subtitle_stream: int | None}
    """
    result = {
        "audio_stream": 0,  # Default to first audio stream
        "subtitle_stream": None,
    }

    if not probe_data:
        return result

    audio_streams = probe_data.get("audio_streams", [])
    subtitle_streams = probe_data.get("subtitle_streams", [])

    # Select audio stream
    # NOTE: We return the *relative* index within audio_streams (0-based),
    # because ffmpeg's -map 0:a:N uses relative audio stream indices,
    # not the absolute stream index from probe data.
    if audio_streams:
        matched = False
        if preferred_audio_languages:
            for pref_lang in preferred_audio_languages:
                for i, stream in enumerate(audio_streams):
                    lang = stream.get("language", "")
                    if _match_language(lang, pref_lang):
                        result["audio_stream"] = i
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                # No match for any preferred language, use default stream if marked
                for i, stream in enumerate(audio_streams):
                    if stream.get("default"):
                        result["audio_stream"] = i
                        break

    # Select subtitle stream (relative index within subtitle_streams)
    if preferred_subtitle_language and subtitle_streams:
        for i, stream in enumerate(subtitle_streams):
            lang = stream.get("language", "")
            if _match_language(lang, preferred_subtitle_language):
                if not stream.get("forced"):
                    result["subtitle_stream"] = i
                    break
                elif result["subtitle_stream"] is None:
                    result["subtitle_stream"] = i

    return result


async def report_stream_problem(
    db: AsyncSession,
    media_item_guid: uuid.UUID,
    reason: str,
    details: str | None,
    user_guid: uuid.UUID,
) -> dict:
    """Handle a user-reported stream problem by blacklisting releases and re-queuing download."""
    from streamarr.models.media import (
        AvailabilityStatus,
        MediaFile,
        MediaItem,
        MediaRelease,
    )
    from streamarr.worker import auto_download_media_item

    result = await db.execute(
        select(MediaItem).where(MediaItem.guid == media_item_guid)
    )
    media_item = result.scalars().first()
    if not media_item:
        raise ValueError(f"MediaItem {media_item_guid} not found")

    # Blacklist all non-blacklisted releases for this media item
    blacklist_reason = f"User report: {reason}" + (f" - {details}" if details else "")
    releases_result = await db.execute(
        select(MediaRelease).where(
            MediaRelease.media_item_guid == media_item_guid,
            MediaRelease.blacklisted_reason.is_(None),
        )
    )
    releases = releases_result.scalars().all()
    for release in releases:
        release.blacklisted_reason = blacklist_reason

    # Delete media files (DB records and physical files)
    files_result = await db.execute(
        select(MediaFile).where(MediaFile.media_item_guid == media_item_guid)
    )
    for media_file in files_result.scalars().all():
        if media_file.file_path:
            try:
                await asyncio.to_thread(os.remove, media_file.file_path)
            except FileNotFoundError:
                logger.warning("File already missing: %s", media_file.file_path)
            except OSError as e:
                logger.error("Failed to delete file %s: %s", media_file.file_path, e)
            # Drop the cached sprites even when the file was already gone —
            # otherwise they would outlive the media they describe.
            trickplay.purge(media_file.file_path)
        await db.delete(media_file)

    # Reset availability
    media_item.availability_status = AvailabilityStatus.UNKNOWN
    await db.commit()

    # Queue re-download
    await auto_download_media_item.kiq(str(media_item_guid), None, str(user_guid))

    return {
        "status": "reported",
        "releases_blacklisted": len(releases),
        "new_download_queued": True,
    }

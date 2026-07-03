import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.services.computing import ComputingService
from pyrate.services.download_status import download_phase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Quality / resolution constants (used by apply_quality_restrictions and others)
# ---------------------------------------------------------------------------

QUALITY_TO_RESOLUTION: dict[str, str] = {
    "sd": "480p",
    "hd": "720p",
    "fhd": "1080p",
    "uhd": "4k",
}

RESOLUTION_ORDER: dict[str, int] = {
    "480p": 1,
    "720p": 2,
    "1080p": 3,
    "4k": 4,
}

# Audio codecs that retain the original samples bit-for-bit. ``copy`` of any
# of these counts as lossless playback. Anything else (aac/opus/mp3/vorbis/
# ac3/eac3/...) is lossy.
LOSSLESS_AUDIO_CODECS: set[str] = {
    "flac", "alac", "ape", "wav", "wavpack", "dsd", "dsf", "tta",
    "pcm", "pcm_s16le", "pcm_s24le", "pcm_f32le",
}

# Hard cap on audio bitrate when the user is restricted to lossy quality.
# 320 kbps AAC is the established "transparent lossy" reference point.
LOSSY_AUDIO_BITRATE_CAP = "320k"

# Fallback lossy codec when forcing a re-encode away from a lossless source.
LOSSY_FALLBACK_CODEC = "aac"


# ---------------------------------------------------------------------------
# Data classes for structured returns
# ---------------------------------------------------------------------------

@dataclass
class CodecNegotiationResult:
    """Result of codec negotiation between client capabilities and source file."""
    video_codec: str
    audio_codec: str
    resolution: str | None
    transcode_reasons: list[str] = field(default_factory=list)


@dataclass
class QualityRestrictionResult:
    """Result of applying quality restrictions based on user permissions."""
    client_max_resolution: str | None
    video_permitted: bool
    denial_reason: str | None = None


@dataclass
class AudioQualityRestrictionResult:
    """Result of applying audio-quality permission restrictions."""
    audio_codec: str | None
    audio_bitrate: str | None
    audio_permitted: bool
    denial_reason: str | None = None


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
# Quality restrictions (permission-based quality capping)
# ---------------------------------------------------------------------------

def apply_quality_restrictions(
    max_video_quality: str | None,
    client_max_resolution: str | None,
    transcoding_max_resolution: str | None = None,
) -> QualityRestrictionResult:
    """Apply permission-based quality restrictions to determine effective max resolution.

    Caps resolution based on the user's max_video_quality permission and the
    server-wide ``transcoding.max_resolution`` system setting, choosing the
    most restrictive of all three constraints.

    Args:
        max_video_quality: User's max video quality permission (e.g. "sd", "hd", "fhd", "uhd").
                           None means no video access permitted.
        client_max_resolution: Client-requested max resolution (e.g. "480p", "720p", "1080p", "4k").
        transcoding_max_resolution: Server-wide hard cap from system settings
            (same labels as client_max_resolution). Optional.

    Returns:
        QualityRestrictionResult with the effective client_max_resolution and whether video is permitted.
    """
    if not max_video_quality:
        return QualityRestrictionResult(
            client_max_resolution=client_max_resolution,
            video_permitted=False,
            denial_reason="Video playback not permitted",
        )

    permission_max_res = QUALITY_TO_RESOLUTION.get(max_video_quality)
    if not permission_max_res:
        permission_max_res = None

    # Pick the strictest constraint (lowest rank wins).
    candidates: list[str] = []
    if permission_max_res:
        candidates.append(permission_max_res)
    if transcoding_max_resolution and transcoding_max_resolution in RESOLUTION_ORDER:
        candidates.append(transcoding_max_resolution)
    if client_max_resolution and client_max_resolution in RESOLUTION_ORDER:
        candidates.append(client_max_resolution)

    if not candidates:
        return QualityRestrictionResult(
            client_max_resolution=client_max_resolution,
            video_permitted=True,
        )

    effective = min(candidates, key=lambda r: RESOLUTION_ORDER.get(r, 4))

    return QualityRestrictionResult(
        client_max_resolution=effective,
        video_permitted=True,
    )


def _bitrate_to_kbps(bitrate: str | None) -> int | None:
    """Parse '320k' / '256000' style bitrate strings to integer kbps."""
    if not bitrate:
        return None
    s = str(bitrate).strip().lower()
    try:
        if s.endswith("k"):
            return int(float(s[:-1]))
        if s.endswith("m"):
            return int(float(s[:-1]) * 1000)
        # plain bps
        return max(1, int(float(s)) // 1000)
    except (ValueError, TypeError):
        return None


def apply_audio_quality_restrictions(
    *,
    max_audio_quality: str | None,
    requested_audio_codec: str | None,
    source_audio_codec: str | None,
    requested_audio_bitrate: str | None,
) -> AudioQualityRestrictionResult:
    """Cap audio codec/bitrate per the user's ``max_audio_quality`` permission.

    Rules:
    - ``None``: audio playback denied (deliberately blank permission).
    - ``"lossless"``: no caps — caller's choices pass through.
    - ``"lossy"``: bitrate capped at 320 kbps and ``copy`` of a lossless
      source is rewritten to the AAC fallback so the original lossless
      stream never leaves the server.
    """
    if not max_audio_quality:
        return AudioQualityRestrictionResult(
            audio_codec=requested_audio_codec,
            audio_bitrate=requested_audio_bitrate,
            audio_permitted=False,
            denial_reason="Audio playback not permitted",
        )

    if max_audio_quality == "lossless":
        return AudioQualityRestrictionResult(
            audio_codec=requested_audio_codec,
            audio_bitrate=requested_audio_bitrate,
            audio_permitted=True,
        )

    # lossy: clamp bitrate, refuse copy of lossless source.
    capped_bitrate = requested_audio_bitrate
    cap_kbps = _bitrate_to_kbps(LOSSY_AUDIO_BITRATE_CAP)
    req_kbps = _bitrate_to_kbps(requested_audio_bitrate)
    if cap_kbps and (req_kbps is None or req_kbps > cap_kbps):
        capped_bitrate = LOSSY_AUDIO_BITRATE_CAP

    capped_codec = requested_audio_codec
    src = (source_audio_codec or "").lower()
    if src in LOSSLESS_AUDIO_CODECS and (
        requested_audio_codec in (None, "copy")
        or (requested_audio_codec or "").lower() in LOSSLESS_AUDIO_CODECS
    ):
        capped_codec = LOSSY_FALLBACK_CODEC

    return AudioQualityRestrictionResult(
        audio_codec=capped_codec,
        audio_bitrate=capped_bitrate,
        audio_permitted=True,
    )


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
    from pyrate.services.system_settings import SystemSettingsService
    from pyrate.services.transcoding_session import get_transcoding_session_service

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
# Codec negotiation (extracted from api/v1/play.py)
# ---------------------------------------------------------------------------


class TranscodingDisallowedError(Exception):
    """Raised when a requested codec/option is forbidden by transcoding settings."""


def is_direct_playable(
    source_info: dict,
    supported_video_codecs: str | None,
    supported_audio_codecs: str | None,
) -> bool:
    """Return True iff the source can be served without re-encoding.

    Used to decide whether playback may proceed when ``transcoding.enabled``
    is false on the server.
    """
    src_v = (source_info.get("video_codec") or "").lower()
    src_a = (source_info.get("audio_codec") or "").lower()

    # Audio-only file: only need audio codec match.
    if not src_v:
        if not supported_audio_codecs:
            return False
        client_a = {c.strip().lower() for c in supported_audio_codecs.split(",")}
        return src_a in client_a

    if not supported_video_codecs or not supported_audio_codecs:
        return False
    client_v = {c.strip().lower() for c in supported_video_codecs.split(",")}
    client_a = {c.strip().lower() for c in supported_audio_codecs.split(",")}

    # Map source codec aliases to client-codec labels.
    src_v_mapped = {"hevc": "h265", "h265": "h265", "h264": "h264", "avc": "h264",
                    "vp9": "vp9", "av1": "av1"}.get(src_v, src_v)
    return src_v_mapped in client_v and src_a in client_a


def negotiate_codecs(
    source_info: dict,
    probe_data: dict | None,
    file,
    supported_video_codecs: str | None,
    supported_audio_codecs: str | None,
    client_max_resolution: str | None,
    requested_video_codec: str = "h264",
    requested_audio_codec: str = "aac",
    requested_resolution: str | None = None,
    transcoding_settings: dict | None = None,
) -> CodecNegotiationResult:
    """Negotiate effective codecs based on client capabilities and source file.

    Args:
        source_info: Dict from extract_source_info() with video_codec, audio_codec, etc.
        probe_data: Parsed probe data dict (may be None)
        file: MediaFile object
        supported_video_codecs: Comma-separated client video codecs (e.g. "h264,h265")
        supported_audio_codecs: Comma-separated client audio codecs (e.g. "aac,opus")
        client_max_resolution: Client max resolution ("4k", "1080p", "720p", "480p")
        requested_video_codec: Default video codec from query param
        requested_audio_codec: Default audio codec from query param
        requested_resolution: Explicitly requested resolution

    Returns:
        CodecNegotiationResult with effective codecs and resolution
    """
    # Hard-reject if the explicitly requested codec is not in the admin's
    # allow-list. ``copy`` is always allowed because it doesn't actually run
    # the named encoder. ``None`` means audio-only / unspecified.
    if transcoding_settings:
        allowed_v = transcoding_settings.get("allowed_video_codecs") or []
        allowed_a = transcoding_settings.get("allowed_audio_codecs") or []
        if (
            requested_video_codec
            and requested_video_codec not in ("copy", None)
            and allowed_v
            and requested_video_codec not in allowed_v
        ):
            raise TranscodingDisallowedError(
                f"Video codec '{requested_video_codec}' is not allowed by the "
                f"server. Allowed: {', '.join(allowed_v)}"
            )
        if (
            requested_audio_codec
            and requested_audio_codec not in ("copy", None)
            and allowed_a
            and requested_audio_codec not in allowed_a
        ):
            raise TranscodingDisallowedError(
                f"Audio codec '{requested_audio_codec}' is not allowed by the "
                f"server. Allowed: {', '.join(allowed_a)}"
            )

    effective_video_codec = requested_video_codec
    effective_audio_codec = requested_audio_codec
    effective_resolution = requested_resolution

    source_video_codec = source_info.get("video_codec")
    if source_video_codec:
        source_video_codec = source_video_codec.lower()

    logger.info(
        "Codec negotiation - Client video codecs: %s, Source codec: %s, File codec: %s",
        supported_video_codecs, source_video_codec, file.codec,
    )

    # --- Audio-only: skip video negotiation entirely ---
    if not source_video_codec:
        effective_video_codec = None
        effective_resolution = None
        logger.info("Audio-only file detected, skipping video codec negotiation")

        # Still negotiate audio
        if probe_data and supported_audio_codecs:
            client_audio_codecs = [c.strip().lower() for c in supported_audio_codecs.split(",")]
            source_audio_codec = source_info.get("audio_codec")
            if source_audio_codec:
                source_audio_codec = source_audio_codec.lower()
            audio_codec_map = {
                "aac": "aac", "mp3": "mp3", "opus": "opus", "flac": "flac",
                "vorbis": "aac", "ogg": "aac",
            }
            mapped_audio = audio_codec_map.get(source_audio_codec)
            if mapped_audio and mapped_audio in client_audio_codecs:
                effective_audio_codec = mapped_audio
            elif "aac" in client_audio_codecs:
                effective_audio_codec = "aac"
            else:
                effective_audio_codec = requested_audio_codec

        logger.info(
            "Final codec selection: video=None (audio-only), audio=%s, resolution=None",
            effective_audio_codec,
        )
        return CodecNegotiationResult(
            video_codec=None,
            audio_codec=effective_audio_codec,
            resolution=None,
        )

    # --- Video codec negotiation ---
    if supported_video_codecs:
        client_video_codecs = [c.strip().lower() for c in supported_video_codecs.split(",")]

        codec_priority = ["hevc", "h265", "h264", "vp9", "av1"]
        source_to_client_map = {
            "hevc": "h265", "h265": "h265", "h264": "h264",
            "avc": "h264", "vp9": "vp9", "av1": "av1",
        }

        source_mapped = source_to_client_map.get(source_video_codec)

        if source_mapped and source_mapped in client_video_codecs:
            can_copy = True

            if client_max_resolution:
                source_height = source_info.get("height") or (file.height if file else None)
                resolution_heights = {"4k": 2160, "1080p": 1080, "720p": 720, "480p": 480}
                max_height = resolution_heights.get(client_max_resolution, 9999)

                if source_height and source_height > max_height:
                    can_copy = False
                    resolution_map = {
                        "4k": "3840x2160", "1080p": "1920x1080",
                        "720p": "1280x720", "480p": "854x480",
                    }
                    effective_resolution = resolution_map.get(client_max_resolution, requested_resolution)

            if can_copy:
                effective_video_codec = "copy"
                logger.info("Smart codec selection: Using copy for %s", source_video_codec)
            else:
                effective_video_codec = source_mapped
                logger.info("Smart codec selection: Using %s (need resolution change)", source_mapped)
        else:
            for codec in codec_priority:
                mapped = source_to_client_map.get(codec, codec)
                if mapped in client_video_codecs:
                    effective_video_codec = mapped
                    logger.info("Smart codec selection: Transcoding from %s to %s", source_video_codec, mapped)
                    break
            else:
                effective_video_codec = "h264"
                logger.info("Smart codec selection: Fallback to h264")

    # --- Audio codec negotiation ---
    if probe_data and supported_audio_codecs:
        client_audio_codecs = [c.strip().lower() for c in supported_audio_codecs.split(",")]

        source_audio_codec = source_info.get("audio_codec")
        if source_audio_codec:
            source_audio_codec = source_audio_codec.lower()

        audio_codec_map = {
            "aac": "aac", "mp3": "mp3", "opus": "opus", "flac": "flac",
            "ac3": "aac", "eac3": "aac", "dts": "aac", "truehd": "aac",
        }

        mapped_audio = audio_codec_map.get(source_audio_codec)
        if mapped_audio and mapped_audio in client_audio_codecs:
            if source_audio_codec in ["aac", "mp3", "opus", "flac"]:
                effective_audio_codec = "copy"
                logger.info("Smart audio codec: Using copy for %s", source_audio_codec)
            else:
                effective_audio_codec = mapped_audio
                logger.info("Smart audio codec: Transcoding %s to %s", source_audio_codec, mapped_audio)
        elif "aac" in client_audio_codecs:
            effective_audio_codec = "aac"
        else:
            effective_audio_codec = requested_audio_codec

    # --- Resolution limit from client capabilities ---
    if client_max_resolution and not effective_resolution and effective_video_codec != "copy":
        resolution_map = {
            "4k": None, "1080p": "1920x1080", "720p": "1280x720", "480p": "854x480",
        }
        effective_resolution = resolution_map.get(client_max_resolution, requested_resolution)

    logger.info(
        "Final codec selection: video=%s, audio=%s, resolution=%s",
        effective_video_codec, effective_audio_codec, effective_resolution,
    )

    return CodecNegotiationResult(
        video_codec=effective_video_codec,
        audio_codec=effective_audio_codec,
        resolution=effective_resolution,
    )


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
    from pyrate.models.downloads import Download, DownloadStatus
    from pyrate.models.media import MediaFile, MediaRelease, MediaReleaseLink
    from pyrate.worker import auto_download_media_item, search_media_item_releases

    # 1. Check if file exists
    file_query = select(MediaFile).where(MediaFile.media_item_guid == media_id)
    if media_source_id is not None:
        file_query = file_query.where(MediaFile.guid == media_source_id)
    result = await db.execute(file_query)
    file = result.scalars().first()

    if file:
        file_path = Path(file.file_path)
        # Retry briefly if file was just imported (rename may still be in progress)
        if not file_path.exists():
            import asyncio
            for _ in range(3):
                await asyncio.sleep(1)
                if file_path.exists():
                    break
        if file_path.exists():
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
                    from pyrate.worker import probe_media_file
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
        from pyrate.services.permission import PermissionService
        perms = await PermissionService(db).resolve_user_permissions(user_guid)

    if releases_with_links:
        # Enforce on-demand download rate limit (user-initiated fetch) and
        # the indexer-downloads cap. The indexer cap covers downloads of
        # already-indexed releases; on_demand_fetch covers the play-driven
        # auto-fetch behaviour. Both must allow the action.
        if user_guid and perms is not None:
            from pyrate.services.rate_limiter import check_and_record
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
        from pyrate.services.rate_limiter import check_and_record
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
    import asyncio

    from pyrate.models.downloads import Download, DownloadStatus
    from pyrate.models.media import (
        MediaFile,
        MediaItem,
        MediaRelease,
        MediaReleaseLink,
        MediaType,
    )
    from pyrate.services.media import MediaService
    from pyrate.services.system_settings import SystemSettingsService
    from pyrate.worker import auto_download_media_item, search_media_item_releases

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

        if existing_file and Path(existing_file.file_path).exists():
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


async def _get_base_library_path(db: AsyncSession) -> str:
    """Get the base library path from settings or use default."""
    from pyrate.services.settings import SettingsService

    settings_service = SettingsService(db)
    # Try to get from settings, fallback to environment default
    base_path = await settings_service.get("library.base_path", "/data")
    return base_path


async def probe_video_full(file_path: str, db: AsyncSession) -> dict | None:
    """
    Probe video file and extract complete stream information using ffprobe.
    Uses ComputingService to run ffprobe via Docker or Kubernetes provider.
    Returns a dict with all streams (video, audio, subtitle) including language metadata.
    This data is stored in the database for stream selection during playback.

    Args:
        file_path: Path to the video file to probe
        db: Database session (required)

    Returns:
        Dictionary with video, audio, and subtitle stream information
    """
    return await _probe_video_with_computing_service(file_path, db)


async def _probe_video_with_computing_service(
    file_path: str, db: AsyncSession
) -> dict | None:
    """Probe video using ComputingService (delegates to the shared helper)."""
    try:
        logger.info("Probing video file with ComputingService: %s", file_path)
        async with ComputingService(db) as computing_service:
            probe_data = await computing_service.probe_media_file(file_path)
        if not probe_data:
            return None
        return _structure_probe_data(probe_data, file_path)
    except Exception as e:
        logger.error("Error probing video %s with ComputingService: %s", file_path, e)
        return None


def _structure_probe_data(probe_data: dict, file_path: str) -> dict:
    """Structure FFprobe output data for easier access.

    Delegates to the canonical :func:`pyrate.libraries.base.structure_probe_data`
    utility and logs the result.
    """
    from pyrate.libraries.base import structure_probe_data

    structured_data = structure_probe_data(probe_data)

    logger.info(
        "Probed %s: %s video, %s audio, %s subtitle streams",
        file_path, len(structured_data['video_streams']), len(structured_data['audio_streams']), len(structured_data['subtitle_streams']),
    )

    return structured_data


def extract_source_info(probe_data: dict | None, file=None) -> dict:
    """Extract source codec info from probe data.

    Primarily expects the canonical structured format with
    ``video_streams`` / ``audio_streams`` arrays (as produced by
    :func:`pyrate.libraries.base.structure_probe_data`).

    For backwards compatibility with data written before the format was
    unified, it also handles:
    - Raw ffprobe JSON with a ``streams`` array
    - Legacy flat dicts with ``video_codec``, ``audio_codec``, etc.

    Args:
        probe_data: Parsed probe data dict
        file: Optional MediaFile for fallback values (codec, width, height)

    Returns:
        Dict with keys: video_codec, audio_codec, bit_depth, width, height
    """
    info = {
        "video_codec": None,
        "audio_codec": None,
        "bit_depth": 8,
        "width": file.width if file else 0,
        "height": file.height if file else 0,
    }

    if not probe_data:
        if file:
            info["video_codec"] = file.codec
        return info

    # Primary: Structured format (video_streams / audio_streams arrays)
    video_streams = probe_data.get("video_streams", [])
    audio_streams = probe_data.get("audio_streams", [])
    if video_streams or audio_streams:
        if video_streams:
            vs = video_streams[0]
            info["video_codec"] = vs.get("codec_name")
            pix_fmt = vs.get("pix_fmt", "")
            if "10" in pix_fmt or "p010" in pix_fmt.lower():
                info["bit_depth"] = 10
            elif "12" in pix_fmt:
                info["bit_depth"] = 12
            info["width"] = vs.get("width", info["width"])
            info["height"] = vs.get("height", info["height"])
        if audio_streams:
            info["audio_codec"] = audio_streams[0].get("codec_name")
    else:
        # Legacy fallback: Raw ffprobe JSON with 'streams' array
        streams = probe_data.get("streams", [])
        if streams:
            for stream in streams:
                if stream.get("codec_type") == "video" and not info["video_codec"]:
                    info["video_codec"] = stream.get("codec_name")
                    pix_fmt = stream.get("pix_fmt", "")
                    if "10" in pix_fmt or "p010" in pix_fmt.lower():
                        info["bit_depth"] = 10
                    elif "12" in pix_fmt:
                        info["bit_depth"] = 12
                    info["width"] = stream.get("width", info["width"])
                    info["height"] = stream.get("height", info["height"])
                elif stream.get("codec_type") == "audio" and not info["audio_codec"]:
                    info["audio_codec"] = stream.get("codec_name")
        else:
            # Legacy fallback: Flat dict from old probe_media_file()
            info["video_codec"] = probe_data.get("video_codec")
            audio = probe_data.get("audio_codec")
            if audio:
                info["audio_codec"] = audio.lower()
            info["width"] = probe_data.get("width", info["width"])
            info["height"] = probe_data.get("height", info["height"])
            # HDR implies 10-bit
            if probe_data.get("hdr_format"):
                info["bit_depth"] = 10

    # Fallback to file.codec for video — only if the file has video dimensions
    if not info["video_codec"] and file and file.width and file.height:
        info["video_codec"] = file.codec

    return info


def build_stream_info(
    file,
    probe_data: dict | None,
    effective_video_codec: str,
    effective_audio_codec: str,
    effective_resolution: str | None,
    video_codec: str,
    audio_codec: str,
    supported_video_codecs: str | None,
    supported_audio_codecs: str | None,
    client_max_resolution: str | None,
) -> dict:
    """Build stream info dict for admin debug panel.

    Args:
        file: MediaFile object
        probe_data: Parsed probe data dict
        effective_video_codec: The codec actually used for transcoding
        effective_audio_codec: The audio codec actually used
        effective_resolution: The resolution actually used
        video_codec: Originally requested video codec
        audio_codec: Originally requested audio codec
        supported_video_codecs: Client's supported video codecs (comma-separated)
        supported_audio_codecs: Client's supported audio codecs (comma-separated)
        client_max_resolution: Client's max resolution capability

    Returns:
        Dict with source_file, transcoding, transcoding_reasons, client_capabilities
    """
    from pathlib import Path

    src = extract_source_info(probe_data, file)
    source_video_codec = src["video_codec"]
    source_audio_codec = src["audio_codec"]
    source_bit_depth = src["bit_depth"]
    source_width = src["width"] or 0
    source_height = src["height"] or 0

    # Determine transcoding reasons
    transcoding_reasons = []

    if effective_video_codec != "copy":
        reason_added = False
        if source_video_codec and supported_video_codecs:
            client_codecs = [
                c.strip().lower() for c in supported_video_codecs.split(",")
            ]
            # Map source codec to client codec name
            codec_map = {"hevc": "h265", "avc": "h264"}
            mapped_source = codec_map.get(source_video_codec, source_video_codec)
            if mapped_source not in client_codecs:
                transcoding_reasons.append(
                    f"Client does not support {source_video_codec}"
                )
                reason_added = True
        if source_bit_depth > 8:
            transcoding_reasons.append(f"{source_bit_depth}-bit → 8-bit conversion")
            reason_added = True
        if effective_resolution:
            transcoding_reasons.append(f"Resolution: {effective_resolution}")
            reason_added = True
        # Fallback: always show what's being transcoded
        if not reason_added:
            src_name = source_video_codec or "unknown"
            transcoding_reasons.append(f"Video: {src_name} → {effective_video_codec}")

    if effective_audio_codec != "copy":
        if source_audio_codec and source_audio_codec in [
            "ac3",
            "eac3",
            "dts",
            "truehd",
        ]:
            transcoding_reasons.append(
                f"Audio: {source_audio_codec} → {effective_audio_codec}"
            )
        elif source_audio_codec:
            transcoding_reasons.append(
                f"Audio: {source_audio_codec} → {effective_audio_codec}"
            )
        else:
            transcoding_reasons.append(f"Audio transcoding → {effective_audio_codec}")

    # Detect hardware acceleration (from config or environment)
    hw_accel = None
    try:
        from pyrate.services.computing import detect_hardware_acceleration

        hw_config = detect_hardware_acceleration()
        if hw_config:
            hw_accel = hw_config.get("type", "").upper() or None
    except Exception as e:
        logger.debug("Could not read hardware acceleration config: %s", e)

    return {
        "source_file": {
            "file_guid": str(file.guid) if getattr(file, "guid", None) else None,
            "file_name": Path(file.file_path).name if file.file_path else "Unknown",
            "file_size": file.file_size,
            "duration": file.duration,
            "video_codec": source_video_codec or "unknown",
            "audio_codec": source_audio_codec or "unknown",
            "width": source_width,
            "height": source_height,
            "bit_depth": source_bit_depth,
        },
        "transcoding": {
            "video_codec": effective_video_codec,
            "audio_codec": effective_audio_codec,
            "resolution": effective_resolution,
            "hw_accel": hw_accel,
            "requested_video_codec": video_codec,
            "requested_audio_codec": audio_codec,
        },
        "transcoding_reasons": transcoding_reasons,
        "client_capabilities": {
            "supported_video_codecs": supported_video_codecs,
            "supported_audio_codecs": supported_audio_codecs,
            "max_resolution": client_max_resolution,
        },
    }


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


async def get_active_transcode_container(
    content_id: str,
    db: AsyncSession | None = None,
) -> str | None:
    """
    Check if there's an active FFmpeg compute task transcoding for this content.
    Returns the Docker container ID when available, otherwise the provider task ID.
    """
    try:
        async with ComputingService(db) as computing_service:
            tasks = await computing_service.list_tasks(
                labels={"content_id": str(content_id)}
            )
        for task in tasks:
            if task.get("status") not in {"pending", "running"}:
                continue
            return task.get("container_id") or task.get("task_id")
        return None
    except Exception as e:
        logging.error("Error checking for active transcode task: %s", e)
        return None


async def probe_video_metadata(file_path: str, db: AsyncSession | None = None) -> dict:
    """
    Probe video file and extract metadata using ffprobe via Docker container.
    Returns a dict with duration, size, width, height, codec, and bitrate.

    Args:
        file_path: Path to the video file to probe
        db: Optional database session. If provided, uses ComputingService.
    """
    metadata = {
        "duration": None,
        "file_size": None,
        "width": None,
        "height": None,
        "codec": None,
        "bitrate": None,
    }

    try:
        # Use probe_video_full which uses ComputingService if db is provided
        probe_data = await probe_video_full(file_path, db=db)

        if not probe_data:
            return metadata

        # Extract format info
        fmt = probe_data.get("format", {})
        if fmt:
            duration = fmt.get("duration")
            metadata["duration"] = float(duration) if duration else None

            size = fmt.get("size")
            metadata["file_size"] = int(size) if size else None

            bit_rate = fmt.get("bit_rate")
            metadata["bitrate"] = int(int(bit_rate) / 1000) if bit_rate else None

        # Extract video stream info
        video_streams = probe_data.get("video_streams", [])
        if video_streams:
            video = video_streams[0]
            metadata["width"] = video.get("width")
            metadata["height"] = video.get("height")
            metadata["codec"] = video.get("codec_name")

        return metadata

    except Exception as e:
        logger.error("Error probing video metadata: %s", e)
        return metadata


async def start_trickplay_container(
    input_path: str,
    session_id: str,
) -> str | None:
    """
    Start trickplay sprite generation for a streaming session.

    Launches a Docker container that generates sprite sheet thumbnails
    from the source video. Runs as fire-and-forget — failures are logged
    but don't affect playback.

    Uses its own DB session to avoid concurrent session conflicts when
    called via asyncio.create_task.

    Args:
        input_path: Path to the source video file
        session_id: The streaming session ID

    Returns:
        Task ID or None if failed
    """
    try:
        from pyrate.database import sessionmanager

        async with sessionmanager.session() as db:
            base_path = await _get_base_library_path(db)

            async with ComputingService(db) as computing_service:
                return await computing_service.start_trickplay_generation(
                    input_path=input_path,
                    session_id=session_id,
                    library_path=base_path,
                )
    except Exception as e:
        logger.warning("Failed to start trickplay generation for session %s: %s", session_id, e)
        return None


async def start_transcode_container(
    db: AsyncSession,
    input_path: str,
    rel_output: str,
    segment_pattern: str,
    hls_time: int = 6,
    session_id: str | None = None,
    video_codec: str | None = "h264",
    audio_codec: str = "aac",
    video_bitrate: str | None = None,
    audio_bitrate: str = "128k",
    start_position: float | None = None,
    resolution: str | None = None,
    # Stream selection parameters
    audio_stream_index: int | None = None,
    subtitle_stream_index: int | None = None,
    burn_subtitles: bool = False,
    # Session tracking parameters
    user_guid: str | None = None,
    user_name: str | None = None,
    content_type: str = "episode",
    content_id: str | None = None,
    content_title: str | None = None,
    audio_only: bool = False,
) -> str:
    """
    Start a new FFmpeg transcoding session with customizable options.

    Automatically chooses between Docker and Kubernetes based on configuration
    and runtime environment.

    Args:
        db: Database session
        input_path: Path to the input video file
        rel_output: Path to the output playlist file
        segment_pattern: Pattern for segment filenames
        hls_time: Duration of each HLS segment in seconds
        session_id: Optional session ID for this transcode (defaults to UUID)
        video_codec: Video codec to use ('h264', 'h265', 'vp9', 'copy')
        audio_codec: Audio codec to use ('aac', 'opus', 'mp3', 'copy')
        video_bitrate: Target video bitrate (e.g., '2000k', '5000k', None for CRF mode)
        audio_bitrate: Target audio bitrate (e.g., '128k', '192k', '320k')
        start_position: Start position in seconds for seek transcoding
        resolution: Target resolution (e.g., '1920x1080', '1280x720', '854x480', None for original)
        audio_stream_index: Index of the audio stream to use (from probe_data)
        subtitle_stream_index: Index of the subtitle stream to burn (from probe_data)
        burn_subtitles: Whether to burn subtitles into the video
        user_guid: GUID of the user starting the transcode
        user_name: Username of the user starting the transcode
        content_type: Type of content ('movie', 'episode', 'music')
        content_id: GUID of the content being transcoded
        content_title: Title of the content being transcoded

    Returns:
        The transcoding session ID
    """
    if session_id is None:
        session_id = str(uuid.uuid4())

    logger.info("Input Path: %s", input_path)
    logger.info("Transcode Session ID: %s", session_id)
    logger.info(
        "Options: video=%s, audio=%s, vbr=%s, abr=%s, start=%s, res=%s",
        video_codec, audio_codec, video_bitrate, audio_bitrate, start_position, resolution,
    )
    logger.info(
        "Stream selection: audio_stream=%s, subtitle_stream=%s, burn_subtitles=%s",
        audio_stream_index, subtitle_stream_index, burn_subtitles,
    )

    # Use the computing service to start transcoding
    from pyrate.services.computing import ComputingService

    # Get base library path from settings
    base_path = await _get_base_library_path(db)

    logger.info("Starting transcoding through computing service")

    # Use context manager to ensure proper cleanup
    async with ComputingService(db) as computing_service:
        return await computing_service.start_transcoding(
            input_path=input_path,
            rel_output=rel_output,
            segment_pattern=segment_pattern,
            hls_time=hls_time,
            session_id=session_id,
            video_codec=video_codec,
            audio_codec=audio_codec,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            start_position=start_position,
            resolution=resolution,
            audio_stream_index=audio_stream_index,
            subtitle_stream_index=subtitle_stream_index,
            burn_subtitles=burn_subtitles,
            user_guid=user_guid,
            user_name=user_name,
            content_type=content_type,
            content_id=content_id,
            content_title=content_title,
            library_path=base_path,
            audio_only=audio_only,
        )


async def report_stream_problem(
    db: AsyncSession,
    media_item_guid: uuid.UUID,
    reason: str,
    details: str | None,
    user_guid: uuid.UUID,
) -> dict:
    """Handle a user-reported stream problem by blacklisting releases and re-queuing download."""
    from pyrate.models.media import (
        AvailabilityStatus,
        MediaFile,
        MediaItem,
        MediaRelease,
    )
    from pyrate.worker import auto_download_media_item

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
                os.remove(media_file.file_path)
            except FileNotFoundError:
                logger.warning("File already missing: %s", media_file.file_path)
            except OSError as e:
                logger.error("Failed to delete file %s: %s", media_file.file_path, e)
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

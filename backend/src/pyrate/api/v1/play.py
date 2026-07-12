"""
Unified Play/Streaming API

Media-type-agnostic streaming and playback for all content types:
- Movies
- TV Episodes
- Music
- Game videos (cutscenes, trailers)

Replaces type-specific play endpoints (/movies/{id}/play, /shows/{id}/play, etc.)
"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from pyrate.api.dependencies import (
    CurrentSuperuser,
    CurrentUser,
    DatabaseSession,
    UserPermissionsDep,
)
from pyrate.api.rate_limit import rate_limit
from pyrate.api.v1.playback_params import PlaybackInfoQuery, PlayMediaQuery
from pyrate.models.device import Device
from pyrate.models.media import MediaItem
from pyrate.services.media_access import (
    require_media_mutation_access,
    require_media_play_access,
)
from pyrate.services.playback_info import PlaybackInfoService
from pyrate.services.playback_session import (
    PlayMediaRequest,
    PlaybackSessionService,
    SeekMediaRequest,
)
from pyrate.services.play import report_stream_problem as report_stream_problem_service
from pyrate.services.settings import SettingsService
from pyrate.services.song_identification import SongIdentificationService

router = APIRouter()

# Abuse-sensitive playback endpoints: identify-song triggers audio extraction
# plus an external Shazam lookup, and report-problem mutates shared library
# state and re-queues downloads. Rate-limit both per client.
_identify_song_rate_limit = rate_limit(
    max_calls=10, window_seconds=60, scope="identify_song"
)
_report_problem_rate_limit = rate_limit(
    max_calls=5, window_seconds=300, scope="report_problem"
)


async def _require_playable_media_item(
    db: DatabaseSession,
    media_id: UUID,
    current_user,
    permissions,
) -> MediaItem:
    """Load a media item and enforce library/parental play access.

    Mirrors the object-level authz other media read/play endpoints apply so a
    user cannot act on items in libraries they cannot access (or that are
    hidden by the parental gate).
    """
    media_item = await db.get(MediaItem, media_id)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")
    require_media_play_access(current_user, permissions, media_item)
    return media_item


_PLAYBACK_PROFILES: dict[str, dict] = {
    "browser": {
        "supported_video_codecs": ["h264", "vp9", "av1"],
        "supported_audio_codecs": ["aac", "mp3", "opus", "vorbis"],
        "supported_containers": ["mp4", "webm", "ogg", "mp3", "m4a"],
        "max_resolution": "4k",
        "supports_direct_play": True,
        "supports_direct_stream": True,
        "supports_transcoding": True,
    },
    "chromecast": {
        "supported_video_codecs": ["h264", "vp8", "vp9", "hevc"],
        "supported_audio_codecs": ["aac", "mp3", "opus", "flac", "ac3", "eac3"],
        "supported_containers": ["mp4", "webm", "mkv", "mp3", "flac"],
        "max_resolution": "4k",
        "supports_direct_play": True,
        "supports_direct_stream": True,
        "supports_transcoding": True,
    },
    "dlna_generic": {
        "supported_video_codecs": ["h264", "mpeg2"],
        "supported_audio_codecs": ["aac", "mp3", "ac3"],
        "supported_containers": ["mp4", "mpegts", "ts", "mp3"],
        "max_resolution": "1080p",
        "supports_direct_play": True,
        "supports_direct_stream": True,
        "supports_transcoding": True,
    },
}


class PlaybackProfile(BaseModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    type: str = Field(default="custom", max_length=50)
    supported_video_codecs: list[str] = Field(default_factory=list)
    supported_audio_codecs: list[str] = Field(default_factory=list)
    supported_containers: list[str] = Field(default_factory=list)
    max_resolution: str | None = Field(default=None, max_length=20)
    max_bitrate: int | None = Field(default=None, ge=1)
    supports_direct_play: bool = True
    supports_direct_stream: bool = True
    supports_transcoding: bool = True
    built_in: bool = False


class PlaybackProfilesUpdate(BaseModel):
    profiles: list[PlaybackProfile] = Field(default_factory=list, max_length=100)


def _builtin_playback_profiles() -> list[PlaybackProfile]:
    return [
        PlaybackProfile(
            id=profile_id,
            name=profile_id.replace("_", " ").title(),
            type="builtin",
            built_in=True,
            **capabilities,
        )
        for profile_id, capabilities in _PLAYBACK_PROFILES.items()
    ]


async def _load_custom_playback_profiles(db: DatabaseSession) -> list[PlaybackProfile]:
    raw_profiles = await SettingsService(db).get("playback.profiles", [])
    if not isinstance(raw_profiles, list):
        return []
    profiles: list[PlaybackProfile] = []
    for raw in raw_profiles:
        if not isinstance(raw, dict):
            continue
        try:
            profile = PlaybackProfile(**raw)
        except (TypeError, ValueError, ValidationError):
            continue
        profile.built_in = False
        profiles.append(profile)
    return profiles


async def _load_playback_profiles(db: DatabaseSession) -> list[PlaybackProfile]:
    custom_by_id = {
        profile.id.lower(): profile
        for profile in await _load_custom_playback_profiles(db)
    }
    profiles = _builtin_playback_profiles()
    profiles.extend(
        profile
        for profile in sorted(custom_by_id.values(), key=lambda item: item.name.lower())
        if profile.id.lower() not in _PLAYBACK_PROFILES
    )
    return profiles


def _ensure_unique_profile_ids(profiles: list[PlaybackProfile]) -> None:
    seen: set[str] = set()
    for profile in profiles:
        profile_id = profile.id.lower()
        if profile_id in _PLAYBACK_PROFILES:
            raise HTTPException(
                status_code=422,
                detail=f"Playback profile '{profile.id}' is built in",
            )
        if profile_id in seen:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate playback profile id '{profile.id}'",
            )
        seen.add(profile_id)


async def _resolve_playback_capabilities(
    db: DatabaseSession,
    current_user,
    profile_id: str | None,
    device_guid: UUID | None,
) -> tuple[dict, Device | None, str | None]:
    custom_profiles = await _load_custom_playback_profiles(db)
    capabilities = _profile_capabilities(profile_id, custom_profiles)
    device = None
    effective_profile_id = profile_id
    if device_guid:
        result = await db.execute(
            select(Device).where(
                Device.guid == device_guid,
                Device.user_id == current_user.guid,
            )
        )
        device = result.scalars().first()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        device_info = device.device_info or {}
        raw_capabilities = device_info.get("capabilities")
        if isinstance(raw_capabilities, dict):
            effective_profile_id = (
                profile_id
                or raw_capabilities.get("profile_id")
                or raw_capabilities.get("playback_profile")
            )
            capabilities = {
                **_profile_capabilities(effective_profile_id, custom_profiles),
                **raw_capabilities,
            }
        elif not profile_id:
            effective_profile_id = None
    return capabilities, device, effective_profile_id


def _profile_capabilities(
    profile_id: str | None,
    custom_profiles: list[PlaybackProfile] | None = None,
) -> dict:
    if not profile_id:
        return {}
    normalized_id = profile_id.strip().lower()
    if normalized_id in _PLAYBACK_PROFILES:
        return dict(_PLAYBACK_PROFILES[normalized_id])
    for profile in custom_profiles or []:
        if profile.id.lower() == normalized_id:
            return profile.model_dump(exclude={"id", "name", "type", "built_in"})
    return {}


# ==================== Smart Play ====================


@router.get("/profiles", response_model=list[PlaybackProfile])
async def list_playback_profiles(
    db: DatabaseSession,
    current_user: CurrentUser,  # noqa: ARG001
):
    """List built-in and configured playback capability profiles."""
    return await _load_playback_profiles(db)


@router.put("/profiles", response_model=list[PlaybackProfile])
async def update_playback_profiles(
    update: PlaybackProfilesUpdate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    """Replace configured custom playback capability profiles."""
    _ensure_unique_profile_ids(update.profiles)
    profiles = sorted(update.profiles, key=lambda item: item.name.lower())
    await SettingsService(db).set(
        "playback.profiles",
        [
            profile.model_dump(
                mode="json",
                exclude_none=True,
                exclude={"built_in"},
            )
            for profile in profiles
        ],
    )
    return await _load_playback_profiles(db)


@router.get("/{media_id}/playback-info")
async def get_playback_info(
    media_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    params: PlaybackInfoQuery = Depends(),
):
    """Return media-source playback decisions without starting a stream."""
    return await PlaybackInfoService(
        db,
        capability_resolver=_resolve_playback_capabilities,
    ).get_playback_info(
        media_id=media_id,
        current_user=current_user,
        permissions=permissions,
        params=params,
    )


@router.post("/{media_id}")
async def play_media(
    media_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    params: PlayMediaQuery = Depends(),
):
    """Smart Play endpoint."""
    return await PlaybackSessionService(
        db,
        capability_resolver=_resolve_playback_capabilities,
    ).play_media(
        media_id=media_id,
        current_user=current_user,
        permissions=permissions,
        request=PlayMediaRequest(**params.impl_kwargs()),
    )


# ==================== Seek (Resume from Position) ====================


@router.post("/{media_id}/seek")
async def seek_media(
    media_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    position: float = Query(..., description="Position to seek to in seconds"),
    old_session_id: str | None = Query(
        None, description="Previous session ID to terminate"
    ),
    video_codec: str = Query("h264", description="Video codec: h264, h265, vp9, copy"),
    audio_codec: str = Query("aac", description="Audio codec: aac, opus, mp3, copy"),
    video_bitrate: str | None = Query(None, description="Video bitrate"),
    audio_bitrate: str = Query("128k", description="Audio bitrate"),
    resolution: str | None = Query(None, description="Target resolution"),
    audio_track: int | None = Query(
        None,
        description="Audio stream index (0-based among audio streams) to use. Overrides automatic language-based selection.",
    ),
    requested_subtitle_stream_index: int | None = Query(
        None,
        alias="subtitle_stream_index",
        ge=0,
        description="Subtitle stream index to use. Overrides automatic language-based selection.",
    ),
    device_guid: UUID | None = Query(
        None, description="Registered device whose playback capabilities should be used"
    ),
    profile_id: str | None = Query(
        None,
        description="Playback profile id, such as browser, chromecast, dlna_generic, or a custom profile",
    ),
    media_source_id: UUID | None = Query(
        None, description="Specific media source/file GUID to seek within"
    ),
):
    """
    Seek to a specific position in the media.

    Creates a new transcoding session starting from the specified position.
    Optionally terminates the old session to free resources.
    Optionally selects a specific audio track by index.

    Works for all media types with video content.
    """
    return await PlaybackSessionService(
        db,
        capability_resolver=_resolve_playback_capabilities,
    ).seek_media(
        media_id=media_id,
        current_user=current_user,
        permissions=permissions,
        request=SeekMediaRequest(
            position=position,
            old_session_id=old_session_id,
            video_codec=video_codec,
            audio_codec=audio_codec,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            resolution=resolution,
            audio_track=audio_track,
            requested_subtitle_stream_index=requested_subtitle_stream_index,
            device_guid=device_guid,
            profile_id=profile_id,
            media_source_id=media_source_id,
        ),
    )


@router.post(
    "/{media_id}/identify-song",
    dependencies=[Depends(_identify_song_rate_limit)],
)
async def identify_song(
    media_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    position: float = Query(0, description="Current playback position in seconds"),
):
    """
    Identify the song playing at the given position using Shazam.

    Extracts a 15-second audio segment centered on the given position,
    then uses ShazamIO to identify the song.
    """
    await _require_playable_media_item(db, media_id, current_user, permissions)
    return await SongIdentificationService(db).identify_song(media_id, position)


class StreamProblemReport(BaseModel):
    reason: Literal[
        "wrong_content", "wrong_language", "bad_quality",
        "bad_audio", "broken_file", "other"
    ]
    details: str | None = None


@router.post(
    "/{media_id}/report-problem",
    dependencies=[Depends(_report_problem_rate_limit)],
)
async def report_problem(
    media_id: UUID,
    report: StreamProblemReport,
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
):
    """Report a stream problem. Blacklists releases and queues a new download.

    This is a destructive, library-wide operation: it blacklists every release
    for the item and physically deletes its source files from disk and the
    database, then re-queues a download. Because that mutates shared library
    state for all users, it is restricted to administrators rather than being
    triggerable by any single user report.
    """
    media_item = await _require_playable_media_item(
        db, media_id, current_user, permissions
    )
    require_media_mutation_access(current_user, media_item)
    try:
        result = await report_stream_problem_service(
            db=db,
            media_item_guid=media_id,
            reason=report.reason,
            details=report.details,
            user_guid=current_user.guid,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

"""Playback session orchestration shared by play endpoints."""

from __future__ import annotations

import asyncio
import logging
import uuid as uuid_module
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from redis.exceptions import RedisError
from sqlalchemy import select

from streamarr.database import sessionmanager
from streamarr.models.device import Device
from streamarr.models.media import MediaFile, MediaType
from streamarr.schemas.play_token import PlayTokenCreate, PlayTokenRead
from streamarr.services.media import MediaService
from streamarr.services.media_access import require_media_play_access
from streamarr.services.media_marker import MediaMarkerService
from streamarr.services.play import (
    apply_audio_quality_restrictions,
    apply_quality_restrictions,
    build_stream_info,
    check_transcode_capacity,
    extract_source_info,
    is_direct_playable,
    prefetch_next_episode,
    resolve_play_action,
    select_streams_for_user,
    start_transcode_container,
    start_trickplay_container,
)
from streamarr.services.play_token import get_play_token_service
from streamarr.services.playback_decision import (
    PlaybackClientContext,
    PlaybackDecisionError,
    PlaybackDecisionService,
    PlaybackSourceDecision,
    direct_file_play_container,
    parse_probe_data,
)
from streamarr.services.rate_limiter import _get_redis, check_and_record
from streamarr.services.system_settings import SystemSettingsService
from streamarr.services.transcoding_session import get_transcoding_session_service

logger = logging.getLogger(__name__)

_TRANSCODE_LOCK_TTL_SECONDS = 10
_MIN_TRANSCODE_TAIL_SECONDS = 10.0
_background_tasks: set[asyncio.Task] = set()

_HLS_TS_COPY_VIDEO_CODECS = {"h264", "avc", "avc1"}
_HLS_TS_COPY_AUDIO_CODECS = {"aac", "mp3"}


@dataclass(frozen=True)
class PlayMediaRequest:
    video_codec: str
    audio_codec: str
    video_bitrate: str | None
    audio_bitrate: str | None
    start_position: float | None
    resolution: str | None
    supported_video_codecs: str | None
    supported_audio_codecs: str | None
    supported_containers: str | None
    client_max_resolution: str | None
    client_max_bitrate: int | None
    device_guid: UUID | None
    profile_id: str | None
    media_source_id: UUID | None
    audio_track: int | None
    requested_subtitle_stream_index: int | None


@dataclass(frozen=True)
class SeekMediaRequest:
    position: float
    old_session_id: str | None
    video_codec: str
    audio_codec: str
    video_bitrate: str | None
    audio_bitrate: str | None
    resolution: str | None
    audio_track: int | None
    requested_subtitle_stream_index: int | None
    device_guid: UUID | None
    profile_id: str | None
    media_source_id: UUID | None


@dataclass(frozen=True)
class PlaybackContext:
    transcoding_settings: dict
    client_context: PlaybackClientContext
    device: Device | None
    profile_id: str | None
    video_bitrate: str | None
    audio_bitrate: str | None


@dataclass(frozen=True)
class StreamSelection:
    audio_stream_index: int | None
    subtitle_stream_index: int | None
    burn_subtitles: bool


@dataclass(frozen=True)
class StreamSessionRequest:
    current_user: object
    permissions: object
    media_item: object
    media_id: UUID
    content_type: str
    file: MediaFile
    decision: PlaybackSourceDecision
    video_codec: str
    audio_codec: str
    video_bitrate: str | None
    audio_bitrate: str | None
    needs_transcode: bool
    start_position: float | None
    client_context: PlaybackClientContext
    profile_id: str | None
    device: Device | None
    audio_track: int | None
    requested_subtitle_stream_index: int | None


async def _acquire_transcode_lock(user_guid: str, media_id: str) -> bool:
    lock_key = f"streamarr:transcode_lock:{user_guid}:{media_id}"
    try:
        redis = await _get_redis()
        acquired = await redis.set(lock_key, "1", nx=True, ex=_TRANSCODE_LOCK_TTL_SECONDS)
        return bool(acquired)
    except RedisError as exc:
        logger.warning("Transcode lock acquire failed (allowing anyway): %s", exc)
        return True


async def _release_transcode_lock(user_guid: str, media_id: str) -> None:
    lock_key = f"streamarr:transcode_lock:{user_guid}:{media_id}"
    try:
        redis = await _get_redis()
        await redis.delete(lock_key)
    except RedisError as exc:
        logger.debug("Transcode lock release failed: %s", exc)


async def _prefetch_next_episode(
    current_episode_id: UUID,
    user_guid: UUID | None = None,
) -> None:
    async with sessionmanager.session() as db:
        await prefetch_next_episode(db, current_episode_id, user_guid=user_guid)


def _supervise_background_task(
    coro,
    *,
    name: str,
    user_guid: str | None = None,
) -> asyncio.Task:
    async def _runner():
        try:
            await coro
        except Exception:
            logger.exception("Background task %s failed (user=%s)", name, user_guid)

    task = asyncio.create_task(_runner(), name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def content_type_for_media_type(media_type: MediaType) -> str:
    return {
        MediaType.MOVIES: "movie",
        MediaType.SHOWS: "episode",
        MediaType.SONGS: "music",
        MediaType.GAMES: "game",
    }.get(media_type, "media")


def _play_action_payload(action) -> dict:
    result = {"status": action.status, "message": action.message}
    if action.download_progress is not None:
        result["download_progress"] = action.download_progress
    if action.download_status is not None:
        result["download_status"] = action.download_status
    if action.download_phase is not None:
        result["download_phase"] = action.download_phase
    if action.download_status_detail is not None:
        result["download_status_detail"] = action.download_status_detail
    return result


def _effective_transcode_bitrates(
    transcoding_settings: dict,
    video_bitrate: str | None,
    audio_bitrate: str | None,
) -> tuple[str | None, str | None]:
    if not video_bitrate:
        video_bitrate = transcoding_settings.get("default_video_bitrate") or video_bitrate
    if not audio_bitrate or audio_bitrate == "128k":
        audio_bitrate = transcoding_settings.get("default_audio_bitrate") or audio_bitrate
    return video_bitrate, audio_bitrate


def _normalize_transcode_start_position(
    file: MediaFile,
    requested_position: float | None,
) -> float | None:
    if requested_position is None:
        return None

    try:
        start_position = float(requested_position)
    except (TypeError, ValueError):
        return 0

    if start_position <= 0:
        return 0

    duration = float(file.duration or 0)
    if duration <= 0:
        return start_position

    if start_position >= duration:
        logger.info(
            "Resetting transcode start %.3fs to 0 because it is beyond media duration %.3fs",
            start_position,
            duration,
        )
        return 0

    max_start = max(0.0, duration - _MIN_TRANSCODE_TAIL_SECONDS)
    if start_position > max_start:
        logger.info(
            "Clamping transcode start %.3fs to %.3fs for media duration %.3fs",
            start_position,
            max_start,
            duration,
        )
        return max_start

    return start_position


def _enforce_hls_ts_compatibility(decision: PlaybackSourceDecision) -> None:
    """Avoid codecs that browsers cannot consume from MPEG-TS HLS segments.

    Codec capability detection only says that a browser can decode a codec; it
    does not mean that HLS.js can demux that codec from MPEG-TS. Directly copied
    AV1/VP9 video and Opus/FLAC audio therefore produce a valid playlist that no
    supported browser can play. Direct-file playback is unaffected.
    """
    if decision.can_direct_file_play or decision.codec_result is None:
        return

    source_video = str(decision.source_info.get("video_codec") or "").lower()
    source_audio = str(decision.source_info.get("audio_codec") or "").lower()
    changed = False

    if (
        decision.codec_result.video_codec == "copy"
        and source_video not in _HLS_TS_COPY_VIDEO_CODECS
    ):
        decision.codec_result.video_codec = "h264"
        decision.effective_video_codec = "h264"
        decision.transcode_reasons.append(
            f"Video: {source_video or 'unknown'} -> h264 for HLS MPEG-TS"
        )
        changed = True

    if (
        decision.codec_result.audio_codec == "copy"
        and source_audio not in _HLS_TS_COPY_AUDIO_CODECS
    ):
        decision.codec_result.audio_codec = "aac"
        decision.effective_audio_codec = "aac"
        decision.transcode_reasons.append(
            f"Audio: {source_audio or 'unknown'} -> aac for HLS MPEG-TS"
        )
        changed = True

    if changed:
        decision.needs_transcode = True
        decision.can_direct_stream = False
        decision.can_transcode = True
        decision.playback_method = "transcode"


async def _enforce_playback_rate_limit(current_user, permissions) -> None:
    if permissions is None:
        return
    allowed = await check_and_record(
        current_user.guid,
        "playback",
        permissions.playback_limit,
        permissions.playback_period_minutes,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Playback rate limit reached. Please wait.",
        )


async def _load_media_markers(db, media_id: UUID) -> dict:
    markers = await MediaMarkerService(db).get_effective_markers(media_id)
    return markers.model_dump()


def _select_playback_streams(
    *,
    probe_data: dict | None,
    current_user,
    audio_track: int | None,
    requested_subtitle_stream_index: int | None,
) -> StreamSelection:
    audio_stream_index = None
    subtitle_stream_index = requested_subtitle_stream_index
    burn_subtitles = requested_subtitle_stream_index is not None

    if audio_track is not None:
        audio_stream_index = audio_track
        preferred_audio_languages = None
    else:
        preferred_audio_languages = current_user.audio_languages

    if probe_data:
        try:
            streams = select_streams_for_user(
                probe_data,
                preferred_audio_languages=preferred_audio_languages,
                preferred_subtitle_language=current_user.subtitle_language,
            )
            if audio_track is None:
                audio_stream_index = streams.get("audio_stream")
            if requested_subtitle_stream_index is None:
                subtitle_stream_index = streams.get("subtitle_stream")
            burn_subtitles = subtitle_stream_index is not None
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Failed to parse probe data for stream selection: %s", exc)

    return StreamSelection(
        audio_stream_index=audio_stream_index,
        subtitle_stream_index=subtitle_stream_index,
        burn_subtitles=burn_subtitles,
    )


async def _enforce_concurrent_stream_limit(current_user, permissions) -> None:
    max_streams = permissions.max_concurrent_streams if permissions else 0
    if max_streams <= 0:
        return

    try:
        session_service = get_transcoding_session_service()
        user_sessions = await session_service.get_user_sessions(str(current_user.guid))
        active_user_streams = len([session for session in user_sessions if session.is_active])
        if max_streams > 0 and active_user_streams >= max_streams:
            logger.warning(
                "User %s exceeded concurrent stream limit (%d/%d)",
                current_user.guid,
                active_user_streams,
                max_streams,
            )
            raise HTTPException(
                status_code=429,
                detail=f"Maximum concurrent streams reached ({max_streams}). Stop another stream first.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Could not check concurrent streams: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Could not verify concurrent stream limit. Please try again.",
        ) from exc


class PlaybackSessionService:
    def __init__(self, db, capability_resolver) -> None:
        self.db = db
        self.capability_resolver = capability_resolver

    async def play_media(
        self,
        *,
        media_id: UUID,
        current_user,
        permissions,
        request: PlayMediaRequest,
    ) -> dict:
        media_item = await self._load_media_item(media_id, current_user, permissions)
        content_type = content_type_for_media_type(media_item.media_type)
        await self._ensure_media_source_exists(media_id, request.media_source_id)

        action = await resolve_play_action(
            self.db,
            media_item,
            media_id,
            user_guid=current_user.guid,
            media_source_id=request.media_source_id,
        )
        if action.status != "ready":
            return _play_action_payload(action)

        file = action.file
        if media_item.media_type == MediaType.BOOKS:
            return await self._direct_book_response(current_user, content_type, media_id, file)
        if media_item.media_type == MediaType.SONGS:
            return await self._direct_audio_response(current_user, content_type, media_id, file)

        return await self._stream_playback_response(
            media_item=media_item,
            media_id=media_id,
            current_user=current_user,
            permissions=permissions,
            content_type=content_type,
            file=file,
            request=request,
        )

    async def _stream_playback_response(
        self,
        *,
        media_item,
        media_id: UUID,
        current_user,
        permissions,
        content_type: str,
        file: MediaFile,
        request: PlayMediaRequest,
    ) -> dict:
        request = replace(
            request,
            start_position=_normalize_transcode_start_position(
                file,
                request.start_position,
            ),
        )
        context = await self._playback_context(current_user, request)
        decision = self._playback_decision(
            media_item=media_item,
            file=file,
            permissions=permissions,
            request=request,
            context=context,
        )
        _enforce_hls_ts_compatibility(decision)
        needs_transcode = await self._effective_transcode_requirement(
            media_id=media_id,
            request=request,
            context=context,
            decision=decision,
        )
        if self._can_direct_file_play(decision, context, needs_transcode, request):
            return await self._direct_file_play_response(
                current_user=current_user,
                permissions=permissions,
                media_id=media_id,
                content_type=content_type,
                decision=decision,
                request=request,
                context=context,
            )
        needs_transcode = self._enforce_stream_policy(
            request=request,
            context=context,
            decision=decision,
            needs_transcode=needs_transcode,
        )
        return await self._start_stream_session_response(
            StreamSessionRequest(
                current_user=current_user,
                permissions=permissions,
                media_item=media_item,
                media_id=media_id,
                content_type=content_type,
                file=file,
                decision=decision,
                video_codec=request.video_codec,
                audio_codec=decision.effective_audio_codec,
                video_bitrate=context.video_bitrate,
                audio_bitrate=decision.effective_audio_bitrate or context.audio_bitrate,
                needs_transcode=needs_transcode,
                start_position=request.start_position,
                client_context=context.client_context,
                profile_id=context.profile_id,
                device=context.device,
                audio_track=request.audio_track,
                requested_subtitle_stream_index=request.requested_subtitle_stream_index,
            )
        )

    async def seek_media(
        self,
        *,
        media_id: UUID,
        current_user,
        permissions,
        request: SeekMediaRequest,
    ) -> PlayTokenRead:
        media_item, file = await self._load_seek_media(media_id, current_user, permissions, request)
        request = replace(
            request,
            position=_normalize_transcode_start_position(file, request.position) or 0,
        )
        content_type = content_type_for_media_type(media_item.media_type)
        context = await self._seek_context(current_user, request)
        video_bitrate, audio_bitrate = _effective_transcode_bitrates(
            context.transcoding_settings,
            request.video_bitrate,
            request.audio_bitrate,
        )
        resolution, audio_codec, audio_bitrate = self._apply_seek_quality_restrictions(
            file=file,
            permissions=permissions,
            request=request,
            transcoding_settings=context.transcoding_settings,
            audio_bitrate=audio_bitrate,
        )
        request = replace(request, resolution=resolution, audio_codec=audio_codec)
        needs_transcode = await self._enforce_seek_policy(media_id, request, context)

        await _enforce_playback_rate_limit(current_user, permissions)
        await _enforce_concurrent_stream_limit(current_user, permissions)
        await self._terminate_old_session(request.old_session_id)
        selection = _select_playback_streams(
            probe_data=parse_probe_data(file.probe_data),
            current_user=current_user,
            audio_track=request.audio_track,
            requested_subtitle_stream_index=request.requested_subtitle_stream_index,
        )
        play_token, session_id = await self._start_seek_session(
            media_item=media_item,
            media_id=media_id,
            content_type=content_type,
            file=file,
            current_user=current_user,
            request=request,
            selection=selection,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
        )
        return self._seek_token_response(
            play_token=play_token,
            session_id=session_id,
            file=file,
            request=request,
            context=context,
            needs_transcode=needs_transcode,
            selection=selection,
        )

    async def _load_media_item(self, media_id: UUID, current_user, permissions):
        media_item = await MediaService(self.db).get_by_id(media_id)
        if not media_item:
            raise HTTPException(status_code=404, detail="Media not found")
        require_media_play_access(current_user, permissions, media_item)
        return media_item

    async def _ensure_media_source_exists(
        self,
        media_id: UUID,
        media_source_id: UUID | None,
    ) -> None:
        if media_source_id is None:
            return
        result = await self.db.execute(
            select(MediaFile).where(
                MediaFile.media_item_guid == media_id,
                MediaFile.guid == media_source_id,
            )
        )
        if not result.scalars().first():
            raise HTTPException(status_code=404, detail="Media source not found")

    async def _direct_book_response(
        self,
        current_user,
        content_type: str,
        media_id: UUID,
        file: MediaFile,
    ) -> dict:
        play_token = await self._create_direct_play_token(
            current_user=current_user,
            content_type=content_type,
            media_id=media_id,
            file=file,
        )
        ext = file.file_path.rsplit(".", 1)[-1].lower() if file.file_path else ""
        return {
            "status": "ready",
            "token": play_token.token,
            "session_id": None,
            "media_source_id": str(file.guid),
            "book_only": True,
            "book_format": ext,
            "file_name": file.file_path.rsplit("/", 1)[-1] if file.file_path else "",
            "message": "Ready to read",
        }

    async def _direct_audio_response(
        self,
        current_user,
        content_type: str,
        media_id: UUID,
        file: MediaFile,
    ) -> dict:
        play_token = await self._create_direct_play_token(
            current_user=current_user,
            content_type=content_type,
            media_id=media_id,
            file=file,
        )
        return {
            "status": "ready",
            "token": play_token.token,
            "session_id": None,
            "media_source_id": str(file.guid),
            "duration": file.duration or 0,
            "start_position": 0,
            "width": 0,
            "height": 0,
            "audio_only": True,
            "message": "Ready to play",
            "markers": await _load_media_markers(self.db, media_id),
        }

    async def _create_direct_play_token(
        self,
        *,
        current_user,
        content_type: str,
        media_id: UUID,
        file: MediaFile,
    ):
        return await get_play_token_service().create_token(
            PlayTokenCreate(
                user_guid=current_user.guid,
                content_type=content_type,
                content_id=media_id,
                file_path=file.file_path,
            )
        )

    async def _playback_context(
        self,
        current_user,
        request: PlayMediaRequest,
    ) -> PlaybackContext:
        transcoding_settings = await SystemSettingsService(self.db).get_transcoding_settings()
        capabilities, device, profile_id = await self.capability_resolver(
            self.db,
            current_user,
            request.profile_id,
            request.device_guid,
        )
        decision_service = PlaybackDecisionService()
        client_context = decision_service.client_context(
            capabilities=capabilities,
            supported_video_codecs=request.supported_video_codecs,
            supported_audio_codecs=request.supported_audio_codecs,
            supported_containers=request.supported_containers,
            client_max_resolution=request.client_max_resolution,
            client_max_bitrate=request.client_max_bitrate,
        )
        video_bitrate, audio_bitrate = _effective_transcode_bitrates(
            transcoding_settings,
            request.video_bitrate,
            request.audio_bitrate,
        )
        return PlaybackContext(
            transcoding_settings=transcoding_settings,
            client_context=client_context,
            device=device,
            profile_id=profile_id,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
        )

    def _playback_decision(
        self,
        *,
        media_item,
        file: MediaFile,
        permissions,
        request: PlayMediaRequest,
        context: PlaybackContext,
    ) -> PlaybackSourceDecision:
        try:
            decision = PlaybackDecisionService().decide_source(
                media_item=media_item,
                media_file=file,
                permissions=permissions,
                context=context.client_context,
                transcoding_settings=context.transcoding_settings,
                requested_video_codec=request.video_codec,
                requested_audio_codec=request.audio_codec,
                requested_audio_bitrate=context.audio_bitrate,
                requested_resolution=request.resolution,
                start_position=request.start_position,
                raise_on_transcoding_disallowed=True,
            )
        except PlaybackDecisionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        if decision.codec_result is None:
            raise HTTPException(status_code=422, detail="No supported playback method")
        return decision

    async def _effective_transcode_requirement(
        self,
        *,
        media_id: UUID,
        request: PlayMediaRequest,
        context: PlaybackContext,
        decision: PlaybackSourceDecision,
    ) -> bool:
        needs_transcode = decision.needs_transcode
        if not needs_transcode:
            return False
        quarantine_reason = await get_transcoding_session_service().is_quarantined(
            str(media_id)
        )
        if not quarantine_reason:
            return True
        if is_direct_playable(
            decision.source_info,
            context.client_context.supported_video_codecs,
            context.client_context.supported_audio_codecs,
        ):
            decision.codec_result.video_codec = (
                "copy" if decision.source_info.get("video_codec") else None
            )
            decision.codec_result.audio_codec = "copy"
            decision.codec_result.resolution = None
            return False
        raise HTTPException(
            status_code=503,
            detail=(
                "Transcoding for this title is temporarily blocked "
                f"({quarantine_reason}). Please try again in a few minutes."
            ),
        )

    @staticmethod
    def _can_direct_file_play(
        decision: PlaybackSourceDecision,
        context: PlaybackContext,
        needs_transcode: bool,
        request: PlayMediaRequest,
    ) -> bool:
        return (
            not needs_transcode
            and context.client_context.supports_direct_play
            and direct_file_play_container(decision.file, context.client_context.capabilities)
            and not decision.client_bitrate_exceeded
            and request.start_position in (None, 0)
        )

    async def _direct_file_play_response(
        self,
        *,
        current_user,
        permissions,
        media_id: UUID,
        content_type: str,
        decision: PlaybackSourceDecision,
        request: PlayMediaRequest,
        context: PlaybackContext,
    ) -> dict:
        await _enforce_playback_rate_limit(current_user, permissions)
        play_token = await self._create_direct_play_token(
            current_user=current_user,
            content_type=content_type,
            media_id=media_id,
            file=decision.file,
        )
        return {
            "status": "ready",
            "token": play_token.token,
            "session_id": None,
            "media_source_id": str(decision.file.guid),
            "profile_id": context.profile_id,
            "device_guid": str(context.device.guid) if context.device else None,
            "device_id": context.device.device_id if context.device else None,
            "playback_method": "direct_play",
            "direct_play": True,
            "direct_file_url": f"/api/stream/file?token={play_token.token}",
            "duration": decision.file.duration or 0,
            "start_position": 0,
            "width": decision.file.width or 1920,
            "height": decision.file.height or 1080,
            "audio_only": False,
            "audio_track": request.audio_track,
            "subtitle_stream_index": request.requested_subtitle_stream_index,
            "message": "Ready to play directly",
            "stream_info": decision.stream_info,
            "markers": await _load_media_markers(self.db, media_id),
        }

    @staticmethod
    def _enforce_stream_policy(
        *,
        request: PlayMediaRequest,
        context: PlaybackContext,
        decision: PlaybackSourceDecision,
        needs_transcode: bool,
    ) -> bool:
        client_context = context.client_context
        direct_stream_requested = not needs_transcode
        if direct_stream_requested and not context.transcoding_settings.get("enabled", False):
            raise HTTPException(
                status_code=422,
                detail=(
                    "This file requires direct stream remuxing which is disabled by "
                    "the administrator."
                ),
            )
        if direct_stream_requested and not client_context.supports_direct_stream:
            if not client_context.supports_transcoding:
                raise HTTPException(
                    status_code=422,
                    detail="This device does not support direct stream or transcoding.",
                )
            decision.codec_result.video_codec = (
                request.video_codec if decision.source_info.get("video_codec") else None
            )
            decision.codec_result.audio_codec = decision.effective_audio_codec
            needs_transcode = True
        if needs_transcode and not client_context.supports_transcoding:
            raise HTTPException(status_code=422, detail="This device does not support transcoding.")
        return needs_transcode

    async def _start_stream_session_response(
        self,
        request: StreamSessionRequest,
    ) -> dict:
        selection = _select_playback_streams(
            probe_data=request.decision.probe_data,
            current_user=request.current_user,
            audio_track=request.audio_track,
            requested_subtitle_stream_index=request.requested_subtitle_stream_index,
        )
        session_id = str(uuid_module.uuid4())
        lock_acquired = await _acquire_transcode_lock(
            str(request.current_user.guid),
            str(request.media_id),
        )
        if not lock_acquired:
            raise HTTPException(
                status_code=409,
                detail="Transcoding already starting for this media. Please wait.",
            )
        try:
            return await self._locked_stream_session_response(
                request=request,
                session_id=session_id,
                selection=selection,
            )
        finally:
            await _release_transcode_lock(
                str(request.current_user.guid),
                str(request.media_id),
            )

    async def _locked_stream_session_response(
        self,
        *,
        request: StreamSessionRequest,
        session_id: str,
        selection: StreamSelection,
    ) -> dict:
        await _enforce_playback_rate_limit(request.current_user, request.permissions)
        await _enforce_concurrent_stream_limit(request.current_user, request.permissions)
        await self._ensure_transcode_capacity()
        await get_transcoding_session_service().terminate_active_content_sessions(
            str(request.media_id),
            user_guid=str(request.current_user.guid),
            exclude_session_id=session_id,
        )
        play_token = await self._create_stream_play_token(request, session_id)
        await self._start_transcode_session(request, session_id, selection)
        self._start_playback_background_tasks(request, session_id)
        return await self._stream_session_payload(
            request=request,
            play_token=play_token,
            session_id=session_id,
            selection=selection,
        )

    async def _ensure_transcode_capacity(self) -> None:
        if not await check_transcode_capacity(self.db):
            raise HTTPException(
                status_code=503,
                detail="Server transcoding capacity reached. Please try again later.",
            )

    async def _create_stream_play_token(
        self,
        request: StreamSessionRequest,
        session_id: str,
    ):
        token_service = get_play_token_service()
        play_token = await token_service.create_token(
            PlayTokenCreate(
                user_guid=request.current_user.guid,
                content_type=request.content_type,
                content_id=request.media_id,
                file_path=request.file.file_path,
            )
        )
        await token_service.update_session_id(play_token.token, session_id)
        return play_token

    async def _start_transcode_session(
        self,
        request: StreamSessionRequest,
        session_id: str,
        selection: StreamSelection,
    ) -> None:
        await start_transcode_container(
            db=self.db,
            input_path=request.file.file_path,
            rel_output=f"/temp/{session_id}.m3u8",
            segment_pattern=f"/temp/{session_id}_%03d.ts",
            session_id=session_id,
            start_position=request.start_position or 0,
            video_codec=request.decision.codec_result.video_codec,
            audio_codec=request.decision.codec_result.audio_codec,
            video_bitrate=request.video_bitrate,
            audio_bitrate=request.audio_bitrate,
            resolution=request.decision.codec_result.resolution,
            audio_stream_index=selection.audio_stream_index,
            burn_subtitles=selection.burn_subtitles,
            subtitle_stream_index=selection.subtitle_stream_index,
            user_guid=str(request.current_user.guid),
            user_name=request.current_user.preferred_username or request.current_user.email,
            content_type=request.content_type,
            content_id=str(request.media_id),
            content_title=request.media_item.title,
            audio_only=request.decision.audio_only,
        )

    @staticmethod
    def _start_playback_background_tasks(
        request: StreamSessionRequest,
        session_id: str,
    ) -> None:
        if not request.decision.audio_only:
            _supervise_background_task(
                start_trickplay_container(request.file.file_path, session_id),
                name="start_trickplay_container",
                user_guid=str(request.current_user.guid),
            )
        if request.media_item.media_type == MediaType.SHOWS:
            _supervise_background_task(
                _prefetch_next_episode(
                    request.media_id,
                    user_guid=request.current_user.guid,
                ),
                name="prefetch_next_episode",
                user_guid=str(request.current_user.guid),
            )

    async def _stream_session_payload(
        self,
        *,
        request: StreamSessionRequest,
        play_token,
        session_id: str,
        selection: StreamSelection,
    ) -> dict:
        file = request.file
        return {
            "status": "ready",
            "token": play_token.token,
            "session_id": session_id,
            "media_source_id": str(file.guid),
            "profile_id": request.profile_id,
            "device_guid": str(request.device.guid) if request.device else None,
            "device_id": request.device.device_id if request.device else None,
            "playback_method": "transcode" if request.needs_transcode else "direct_stream",
            "direct_stream": not request.needs_transcode,
            "duration": file.duration or 0,
            "start_position": request.start_position or 0,
            "width": file.width or (0 if request.decision.audio_only else 1920),
            "height": file.height or (0 if request.decision.audio_only else 1080),
            "audio_only": request.decision.audio_only,
            "audio_track": selection.audio_stream_index,
            "subtitle_stream_index": selection.subtitle_stream_index,
            "message": "Ready to play",
            "stream_info": self._stream_info(request),
            "markers": await _load_media_markers(self.db, request.media_id),
        }

    @staticmethod
    def _stream_info(request: StreamSessionRequest) -> dict:
        return build_stream_info(
            file=request.file,
            probe_data=request.decision.probe_data,
            effective_video_codec=request.decision.codec_result.video_codec,
            effective_audio_codec=request.decision.codec_result.audio_codec,
            effective_resolution=request.decision.codec_result.resolution,
            video_codec=request.video_codec,
            audio_codec=request.audio_codec,
            supported_video_codecs=request.client_context.supported_video_codecs,
            supported_audio_codecs=request.client_context.supported_audio_codecs,
            client_max_resolution=request.client_context.client_max_resolution,
        )

    async def _load_seek_media(
        self,
        media_id: UUID,
        current_user,
        permissions,
        request: SeekMediaRequest,
    ) -> tuple[object, MediaFile]:
        media_item = await self._load_media_item(media_id, current_user, permissions)
        file_query = select(MediaFile).where(MediaFile.media_item_guid == media_id)
        if request.media_source_id is not None:
            file_query = file_query.where(MediaFile.guid == request.media_source_id)
        result = await self.db.execute(file_query)
        file = result.scalars().first()
        if not file:
            if request.media_source_id is not None:
                raise HTTPException(status_code=404, detail="Media source not found")
            raise HTTPException(status_code=404, detail="No file found for this media")
        if not Path(file.file_path).exists():
            raise HTTPException(status_code=404, detail="File not found on disk")
        return media_item, file

    async def _seek_context(
        self,
        current_user,
        request: SeekMediaRequest,
    ) -> PlaybackContext:
        transcoding_settings = await SystemSettingsService(self.db).get_transcoding_settings()
        capabilities, device, profile_id = await self.capability_resolver(
            self.db,
            current_user,
            request.profile_id,
            request.device_guid,
        )
        client_context = PlaybackDecisionService().client_context(
            capabilities=capabilities,
            supported_video_codecs=None,
            supported_audio_codecs=None,
            supported_containers=None,
            client_max_resolution=None,
            client_max_bitrate=None,
        )
        return PlaybackContext(
            transcoding_settings=transcoding_settings,
            client_context=client_context,
            device=device,
            profile_id=profile_id,
            video_bitrate=request.video_bitrate,
            audio_bitrate=request.audio_bitrate,
        )

    @staticmethod
    def _apply_seek_quality_restrictions(
        *,
        file: MediaFile,
        permissions,
        request: SeekMediaRequest,
        transcoding_settings: dict,
        audio_bitrate: str | None,
    ) -> tuple[str | None, str, str | None]:
        if permissions is None:
            return request.resolution, request.audio_codec, audio_bitrate
        source_info = extract_source_info(parse_probe_data(file.probe_data), file)
        quality_result = apply_quality_restrictions(
            max_video_quality=permissions.max_video_quality,
            client_max_resolution=request.resolution,
            transcoding_max_resolution=transcoding_settings.get("max_resolution"),
        )
        if not quality_result.video_permitted and source_info.get("video_codec"):
            raise HTTPException(status_code=403, detail=quality_result.denial_reason)
        audio_quality_result = apply_audio_quality_restrictions(
            max_audio_quality=permissions.max_audio_quality,
            requested_audio_codec=request.audio_codec,
            source_audio_codec=source_info.get("audio_codec"),
            requested_audio_bitrate=audio_bitrate,
        )
        if not audio_quality_result.audio_permitted:
            raise HTTPException(status_code=403, detail=audio_quality_result.denial_reason)
        resolution = quality_result.client_max_resolution if request.resolution else None
        return resolution, audio_quality_result.audio_codec, audio_quality_result.audio_bitrate

    async def _enforce_seek_policy(
        self,
        media_id: UUID,
        request: SeekMediaRequest,
        context: PlaybackContext,
    ) -> bool:
        if not context.transcoding_settings.get("enabled", False):
            raise HTTPException(
                status_code=422,
                detail="Transcoding is disabled by the administrator; seek requires it.",
            )
        await self._enforce_seek_quarantine(media_id)
        self._enforce_allowed_seek_codecs(request, context.transcoding_settings)
        needs_transcode = (
            request.video_codec not in ("copy", None)
            or request.audio_codec not in ("copy", None)
            or request.resolution is not None
        )
        client_context = context.client_context
        if needs_transcode and not client_context.supports_transcoding:
            raise HTTPException(status_code=422, detail="This device does not support transcoding.")
        if not needs_transcode and not client_context.supports_direct_stream:
            raise HTTPException(status_code=422, detail="This device does not support direct stream.")
        return needs_transcode

    @staticmethod
    async def _enforce_seek_quarantine(media_id: UUID) -> None:
        quarantine_reason = await get_transcoding_session_service().is_quarantined(
            str(media_id)
        )
        if quarantine_reason:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Transcoding for this title is temporarily blocked "
                    f"({quarantine_reason}). Please try again in a few minutes."
                ),
            )

    @staticmethod
    def _enforce_allowed_seek_codecs(
        request: SeekMediaRequest,
        transcoding_settings: dict,
    ) -> None:
        allowed_video = transcoding_settings.get("allowed_video_codecs") or []
        allowed_audio = transcoding_settings.get("allowed_audio_codecs") or []
        if (
            request.video_codec not in ("copy", None)
            and allowed_video
            and request.video_codec not in allowed_video
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Video codec '{request.video_codec}' is not allowed by the server.",
            )
        if (
            request.audio_codec not in ("copy", None)
            and allowed_audio
            and request.audio_codec not in allowed_audio
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Audio codec '{request.audio_codec}' is not allowed by the server.",
            )

    @staticmethod
    async def _terminate_old_session(old_session_id: str | None) -> None:
        if not old_session_id:
            return
        try:
            await get_transcoding_session_service().terminate_session(old_session_id)
            logger.info("Terminated old transcoding session: %s", old_session_id)
        except Exception as exc:
            logger.debug(
                "Old session %s cleanup failed or not found: %s",
                old_session_id,
                exc,
            )

    async def _start_seek_session(
        self,
        *,
        media_item,
        media_id: UUID,
        content_type: str,
        file: MediaFile,
        current_user,
        request: SeekMediaRequest,
        selection: StreamSelection,
        video_bitrate: str | None,
        audio_bitrate: str | None,
    ):
        play_token = await self._create_direct_play_token(
            current_user=current_user,
            content_type=content_type,
            media_id=media_id,
            file=file,
        )
        session_id = str(uuid_module.uuid4())
        await self._ensure_transcode_capacity()
        await start_transcode_container(
            db=self.db,
            input_path=file.file_path,
            rel_output=f"/temp/{session_id}.m3u8",
            segment_pattern=f"/temp/{session_id}_%03d.ts",
            session_id=session_id,
            video_codec=request.video_codec,
            audio_codec=request.audio_codec,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            start_position=request.position,
            resolution=request.resolution,
            audio_stream_index=selection.audio_stream_index,
            subtitle_stream_index=selection.subtitle_stream_index,
            burn_subtitles=selection.burn_subtitles,
            user_guid=str(current_user.guid) if current_user else None,
            user_name=self._user_display_name(current_user),
            content_type=content_type,
            content_id=str(media_id),
            content_title=media_item.title,
            audio_only=not file.width,
        )
        await get_play_token_service().update_session_id(play_token.token, session_id)
        return play_token, session_id

    @staticmethod
    def _user_display_name(current_user) -> str | None:
        if not current_user:
            return None
        return current_user.preferred_username or current_user.email

    @staticmethod
    def _seek_token_response(
        *,
        play_token,
        session_id: str,
        file: MediaFile,
        request: SeekMediaRequest,
        context: PlaybackContext,
        needs_transcode: bool,
        selection: StreamSelection,
    ) -> PlayTokenRead:
        return PlayTokenRead.from_token(
            play_token,
            session_id=session_id,
            duration=file.duration,
            start_position=request.position,
            width=file.width,
            height=file.height,
            codec=file.codec,
            is_low_quality=False,
            availability="streamable",
            audio_track=selection.audio_stream_index,
            subtitle_stream_index=selection.subtitle_stream_index,
            media_source_id=str(file.guid),
            profile_id=context.profile_id,
            device_guid=str(context.device.guid) if context.device else None,
            playback_method="transcode" if needs_transcode else "direct_stream",
            direct_stream=not needs_transcode,
        )

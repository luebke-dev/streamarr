"""Playback source decision helpers shared by playback endpoints."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from pyrate.models.media import MediaFile, MediaItem, MediaType
from pyrate.services.play import (
    CodecNegotiationResult,
    TranscodingDisallowedError,
    apply_audio_quality_restrictions,
    apply_quality_restrictions,
    build_stream_info,
    extract_source_info,
    is_direct_playable,
    negotiate_codecs,
)


class PlaybackDecisionError(Exception):
    """Raised when playback decision rules reject a source."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class PlaybackClientContext:
    capabilities: dict
    supported_video_codecs: str | None
    supported_audio_codecs: str | None
    supported_containers: str | None
    client_max_resolution: str | None
    max_bitrate: int | None
    supports_direct_play: bool
    supports_direct_stream: bool
    supports_transcoding: bool

    def response_payload(self, profile_id: str | None) -> dict[str, Any]:
        return {
            "profile_id": profile_id,
            "supported_video_codecs": self.supported_video_codecs,
            "supported_audio_codecs": self.supported_audio_codecs,
            "supported_containers": capability_values(
                self.capabilities.get("supported_containers")
            ),
            "max_resolution": self.client_max_resolution,
            "max_bitrate": self.max_bitrate,
            "supports_direct_play": self.supports_direct_play,
            "supports_direct_stream": self.supports_direct_stream,
            "supports_transcoding": self.supports_transcoding,
        }


@dataclass
class PlaybackSourceDecision:
    file: MediaFile
    probe_data: dict | None
    source_info: dict
    audio_only: bool
    codec_result: CodecNegotiationResult | None
    stream_info: dict | None
    needs_transcode: bool
    client_bitrate_exceeded: bool
    can_direct_file_play: bool
    can_direct_play: bool
    can_direct_stream: bool
    can_transcode: bool
    playback_method: str
    direct_reasons: list[str]
    direct_stream_reasons: list[str]
    transcode_reasons: list[str]
    effective_video_codec: str | None
    effective_audio_codec: str | None
    effective_audio_bitrate: str | None
    effective_resolution: str | None

    def media_source_payload(
        self,
        *,
        media_id: UUID,
        profile_id: str | None,
        device_guid: UUID | None,
        supported_containers: str | None,
        max_bitrate: int | None,
    ) -> dict[str, Any]:
        file_name = self.file.file_name
        if not file_name and self.file.file_path:
            file_name = Path(self.file.file_path).name

        return {
            "id": str(self.file.guid),
            "file_guid": str(self.file.guid),
            "file_name": file_name,
            "container": source_container(self.file),
            "path": self.file.file_path,
            "size": self.file.file_size,
            "duration": self.file.duration,
            "width": self.file.width or self.source_info.get("width"),
            "height": self.file.height or self.source_info.get("height"),
            "bitrate": self.file.bitrate,
            "quality": self.file.quality,
            "audio_only": self.audio_only,
            "source_info": self.source_info,
            "playback_method": self.playback_method,
            "can_direct_play": self.can_direct_play,
            "can_direct_stream": self.can_direct_stream,
            "can_transcode": self.can_transcode,
            "direct_play_url": (
                f"/api/media/{media_id}/files/{self.file.guid}/download"
                if self.can_direct_play
                else None
            ),
            "direct_stream_url": (
                play_url(
                    media_id,
                    self.file.guid,
                    profile_id=profile_id,
                    device_guid=str(device_guid) if device_guid else None,
                    supported_containers=supported_containers,
                    client_max_bitrate=str(max_bitrate) if max_bitrate else None,
                    video_codec="copy",
                    audio_codec="copy",
                )
                if self.can_direct_stream
                else None
            ),
            "transcode_url": (
                play_url(
                    media_id,
                    self.file.guid,
                    profile_id=profile_id,
                    device_guid=str(device_guid) if device_guid else None,
                    supported_containers=supported_containers,
                    client_max_bitrate=str(max_bitrate) if max_bitrate else None,
                )
                if self.can_transcode
                else None
            ),
            "direct_play_reasons": self.direct_reasons,
            "direct_stream_reasons": self.direct_stream_reasons,
            "transcode_reasons": self.transcode_reasons,
            "stream_info": self.stream_info,
        }


def parse_probe_data(raw_probe_data: str | dict | None) -> dict | None:
    if not raw_probe_data:
        return None
    if isinstance(raw_probe_data, dict):
        return raw_probe_data
    try:
        return json.loads(raw_probe_data)
    except (TypeError, json.JSONDecodeError):
        return None


def csv_or_capability(
    explicit: str | None,
    capabilities: dict,
    key: str,
) -> str | None:
    if explicit:
        return explicit
    raw = capabilities.get(key)
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        values = [str(value).strip() for value in raw if str(value).strip()]
        return ",".join(values) if values else None
    return None


def int_or_capability(
    explicit: int | None,
    capabilities: dict,
    key: str,
) -> int | None:
    if explicit is not None:
        return explicit
    raw = capabilities.get(key)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def capability_values(raw: str | list | tuple | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = raw.split(",")
    else:
        values = raw
    return [str(value).strip() for value in values if str(value).strip()]


def source_container(media_file: MediaFile) -> str | None:
    container = (media_file.format or "").strip().lower()
    if container:
        return container.lstrip(".")
    if media_file.file_name and "." in media_file.file_name:
        return media_file.file_name.rsplit(".", 1)[-1].lower()
    if media_file.file_path and "." in media_file.file_path:
        return media_file.file_path.rsplit(".", 1)[-1].lower()
    return None


def supports_container(media_file: MediaFile, capabilities: dict) -> bool:
    containers = capabilities.get("supported_containers")
    if not containers:
        return True
    source = source_container(media_file)
    if not source:
        return False
    container_values = containers.split(",") if isinstance(containers, str) else containers
    return source in {
        str(container).strip().lower().lstrip(".")
        for container in container_values
        if str(container).strip()
    }


def browser_direct_play_container(media_file: MediaFile) -> bool:
    return (source_container(media_file) or "").lower() in {
        "mp4",
        "m4v",
        "mov",
        "webm",
        "ogg",
        "ogv",
    }


def direct_file_play_container(media_file: MediaFile, capabilities: dict) -> bool:
    if capabilities.get("supported_containers"):
        return supports_container(media_file, capabilities)
    return browser_direct_play_container(media_file)


def play_url(media_id: UUID, media_source_id: UUID, **params: str) -> str:
    query_params = {
        "media_source_id": str(media_source_id),
        **{key: value for key, value in params.items() if value is not None},
    }
    query = "&".join(f"{key}={value}" for key, value in query_params.items())
    return f"/api/play/{media_id}?{query}"


def needs_transcode(codec_result: CodecNegotiationResult | None) -> bool:
    if codec_result is None:
        return True
    return (
        codec_result.video_codec not in (None, "copy")
        or codec_result.audio_codec not in (None, "copy")
        or codec_result.resolution is not None
    )


class PlaybackDecisionService:
    """Build direct-play/direct-stream/transcode decisions for media files."""

    @staticmethod
    def client_context(
        *,
        capabilities: dict,
        supported_video_codecs: str | None,
        supported_audio_codecs: str | None,
        supported_containers: str | None,
        client_max_resolution: str | None,
        client_max_bitrate: int | None,
    ) -> PlaybackClientContext:
        supported_video_codecs = csv_or_capability(
            supported_video_codecs, capabilities, "supported_video_codecs"
        )
        supported_audio_codecs = csv_or_capability(
            supported_audio_codecs, capabilities, "supported_audio_codecs"
        )
        supported_containers = csv_or_capability(
            supported_containers, capabilities, "supported_containers"
        )
        if supported_containers:
            capabilities = {**capabilities, "supported_containers": supported_containers}
        client_max_resolution = (
            client_max_resolution or capabilities.get("max_resolution") or None
        )
        max_bitrate = int_or_capability(
            client_max_bitrate, capabilities, "max_bitrate"
        )

        return PlaybackClientContext(
            capabilities=capabilities,
            supported_video_codecs=supported_video_codecs,
            supported_audio_codecs=supported_audio_codecs,
            supported_containers=supported_containers,
            client_max_resolution=client_max_resolution,
            max_bitrate=max_bitrate,
            supports_direct_play=capabilities.get("supports_direct_play", True) is not False,
            supports_direct_stream=capabilities.get("supports_direct_stream", True) is not False,
            supports_transcoding=capabilities.get("supports_transcoding", True) is not False,
        )

    def decide_source(
        self,
        *,
        media_item: MediaItem,
        media_file: MediaFile,
        permissions,
        context: PlaybackClientContext,
        transcoding_settings: dict,
        requested_video_codec: str,
        requested_audio_codec: str,
        requested_audio_bitrate: str | None,
        requested_resolution: str | None,
        start_position: float | None = None,
        raise_on_transcoding_disallowed: bool = False,
    ) -> PlaybackSourceDecision:
        probe_data = parse_probe_data(media_file.probe_data)
        source_info = extract_source_info(probe_data, media_file)
        audio_only = media_item.media_type == MediaType.SONGS or not source_info.get(
            "video_codec"
        )

        quality_result = apply_quality_restrictions(
            max_video_quality=permissions.max_video_quality,
            client_max_resolution=context.client_max_resolution,
            transcoding_max_resolution=transcoding_settings.get("max_resolution"),
        )
        if not quality_result.video_permitted and source_info.get("video_codec"):
            raise PlaybackDecisionError(403, quality_result.denial_reason)

        audio_quality_result = apply_audio_quality_restrictions(
            max_audio_quality=permissions.max_audio_quality,
            requested_audio_codec=requested_audio_codec,
            source_audio_codec=source_info.get("audio_codec"),
            requested_audio_bitrate=requested_audio_bitrate,
        )
        if not audio_quality_result.audio_permitted:
            raise PlaybackDecisionError(403, audio_quality_result.denial_reason)

        effective_audio_codec = audio_quality_result.audio_codec
        effective_audio_bitrate = audio_quality_result.audio_bitrate
        effective_client_max_resolution = quality_result.client_max_resolution

        direct_reasons: list[str] = []
        direct_stream_reasons: list[str] = []
        codec_compatible = is_direct_playable(
            source_info,
            context.supported_video_codecs,
            context.supported_audio_codecs,
        )
        if not codec_compatible:
            direct_reasons.append("client codec support does not match source")
            direct_stream_reasons.append("client codec support does not match source")
        if not supports_container(media_file, context.capabilities):
            direct_reasons.append("client container support does not match source")

        client_bitrate_exceeded = bool(
            context.max_bitrate
            and media_file.bitrate
            and media_file.bitrate > context.max_bitrate
        )
        if client_bitrate_exceeded:
            direct_reasons.append("source bitrate exceeds client maximum")
            direct_stream_reasons.append("source bitrate exceeds client maximum")

        can_direct_play = context.supports_direct_play and not direct_reasons
        if not context.supports_direct_play:
            direct_reasons.append("device does not support direct play")

        codec_result: CodecNegotiationResult | None
        transcode_reasons: list[str]
        stream_info: dict | None
        try:
            codec_result = negotiate_codecs(
                source_info=source_info,
                probe_data=probe_data,
                file=media_file,
                supported_video_codecs=context.supported_video_codecs,
                supported_audio_codecs=context.supported_audio_codecs,
                client_max_resolution=effective_client_max_resolution,
                requested_video_codec=requested_video_codec,
                requested_audio_codec=effective_audio_codec,
                requested_resolution=requested_resolution,
                transcoding_settings=transcoding_settings,
            )
            transcode_reasons = list(codec_result.transcode_reasons)
        except TranscodingDisallowedError as exc:
            if not raise_on_transcoding_disallowed:
                codec_result = None
                transcode_reasons = [str(exc)]
            elif (
                context.supports_direct_play
                and is_direct_playable(
                    source_info,
                    context.supported_video_codecs,
                    context.supported_audio_codecs,
                )
                and direct_file_play_container(media_file, context.capabilities)
                and not client_bitrate_exceeded
                and start_position in (None, 0)
            ):
                codec_result = CodecNegotiationResult(
                    video_codec="copy" if source_info.get("video_codec") else None,
                    audio_codec="copy",
                    resolution=None,
                )
                transcode_reasons = []
            else:
                raise PlaybackDecisionError(403, str(exc)) from exc

        should_transcode = needs_transcode(codec_result)
        if client_bitrate_exceeded and codec_result is not None and not should_transcode:
            if not context.supports_transcoding:
                raise PlaybackDecisionError(
                    422,
                    (
                        "Source bitrate exceeds the client maximum and this device "
                        "does not support transcoding."
                    ),
                )
            codec_result.video_codec = (
                requested_video_codec if source_info.get("video_codec") else None
            )
            codec_result.audio_codec = effective_audio_codec
            codec_result.resolution = requested_resolution
            should_transcode = True

        if not context.supports_direct_stream:
            direct_stream_reasons.append("device does not support direct stream")
        if can_direct_play:
            direct_stream_reasons.append("direct play is available")
        if not bool(transcoding_settings.get("enabled", False)):
            direct_stream_reasons.append("server transcoding is disabled")

        can_direct_stream = (
            context.supports_direct_stream
            and codec_compatible
            and not direct_stream_reasons
            and not can_direct_play
            and bool(transcoding_settings.get("enabled", False))
        )

        can_transcode = (
            context.supports_transcoding
            and bool(transcoding_settings.get("enabled", False))
            and codec_result is not None
            and (should_transcode or not can_direct_play)
        )
        if not context.supports_transcoding:
            transcode_reasons.append("device does not support transcoding")
        if not transcoding_settings.get("enabled", False):
            transcode_reasons.append("server transcoding is disabled")

        if (
            raise_on_transcoding_disallowed
            and should_transcode
            and not context.supports_transcoding
        ):
            raise PlaybackDecisionError(
                422,
                "This device does not support transcoding.",
            )

        if (
            raise_on_transcoding_disallowed
            and should_transcode
            and not transcoding_settings.get("enabled", False)
        ):
            if is_direct_playable(
                source_info,
                context.supported_video_codecs,
                context.supported_audio_codecs,
            ):
                codec_result.video_codec = (
                    "copy" if source_info.get("video_codec") else None
                )
                codec_result.audio_codec = "copy"
                codec_result.resolution = None
                should_transcode = False
            else:
                raise PlaybackDecisionError(
                    422,
                    (
                        "This file requires transcoding which is disabled by the "
                        "administrator. Try a client that supports the source codecs."
                    ),
                )

        can_direct_file_play = (
            not should_transcode
            and context.supports_direct_play
            and direct_file_play_container(media_file, context.capabilities)
            and not client_bitrate_exceeded
            and start_position in (None, 0)
        )

        if codec_result is not None:
            stream_info = build_stream_info(
                file=media_file,
                probe_data=probe_data,
                effective_video_codec=codec_result.video_codec,
                effective_audio_codec=codec_result.audio_codec,
                effective_resolution=codec_result.resolution,
                video_codec=requested_video_codec,
                audio_codec=effective_audio_codec,
                supported_video_codecs=context.supported_video_codecs,
                supported_audio_codecs=context.supported_audio_codecs,
                client_max_resolution=effective_client_max_resolution,
            )
        else:
            stream_info = None

        playback_method = (
            "direct_play"
            if can_direct_play
            else "direct_stream"
            if can_direct_stream
            else "transcode"
            if can_transcode
            else "unsupported"
        )

        return PlaybackSourceDecision(
            file=media_file,
            probe_data=probe_data,
            source_info=source_info,
            audio_only=audio_only,
            codec_result=codec_result,
            stream_info=stream_info,
            needs_transcode=should_transcode,
            client_bitrate_exceeded=client_bitrate_exceeded,
            can_direct_file_play=can_direct_file_play,
            can_direct_play=can_direct_play,
            can_direct_stream=can_direct_stream,
            can_transcode=can_transcode,
            playback_method=playback_method,
            direct_reasons=direct_reasons,
            direct_stream_reasons=direct_stream_reasons,
            transcode_reasons=transcode_reasons,
            effective_video_codec=codec_result.video_codec if codec_result else None,
            effective_audio_codec=effective_audio_codec,
            effective_audio_bitrate=effective_audio_bitrate,
            effective_resolution=codec_result.resolution if codec_result else None,
        )

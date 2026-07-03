"""Playback source decision helpers shared by playback endpoints."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from pyrate.models.media import MediaFile, MediaItem, MediaType

logger = logging.getLogger(__name__)


# ===========================================================================
# Canonical codec/container decision logic.
#
# This is the single source of truth for codec negotiation and quality
# restriction decisions. ``pyrate.services.play`` re-exports these names for
# backwards compatibility.
# ===========================================================================

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


class TranscodingDisallowedError(Exception):
    """Raised when a requested codec/option is forbidden by transcoding settings."""


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
# Codec negotiation
# ---------------------------------------------------------------------------

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

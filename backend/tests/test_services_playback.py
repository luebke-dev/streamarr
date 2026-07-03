"""Tests for playback/computing services: play, computing, transcoding_session (gaps), websocket (gaps), redis_event."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
import pytest_asyncio

from pyrate.schemas.transcoding import TranscodingSession, TranscodingSessionCreate
from pyrate.services.play import (
    CodecNegotiationResult,
    PlayAction,
    build_stream_info,
    extract_source_info,
    get_active_transcode_container,
    negotiate_codecs,
    probe_video_full,
    probe_video_metadata,
    select_streams_for_user,
    start_transcode_container,
    _get_base_library_path,
    _probe_video_with_computing_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(**overrides):
    """Create a mock MediaFile object."""
    defaults = {
        "codec": "h264",
        "width": 1920,
        "height": 1080,
        "file_path": "/library/movies/test.mkv",
        "file_size": 5_000_000_000,
        "duration": 7200.0,
        "probe_data": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_ws() -> AsyncMock:
    """Create a mock FastAPI WebSocket."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


# ===========================================================================
# 1. play.py – negotiate_codecs
# ===========================================================================

class TestNegotiateCodecs:
    """Test codec negotiation between client capabilities and source file."""

    def test_audio_only_file_skips_video(self):
        """Audio-only source sets video_codec=None and resolution=None."""
        source_info = {"video_codec": None, "audio_codec": "mp3"}
        file = _make_file(codec=None, width=0, height=0)

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"audio_streams": [{"codec_name": "mp3"}]},
            file=file,
            supported_video_codecs="h264,h265",
            supported_audio_codecs="aac,mp3",
            client_max_resolution=None,
        )

        assert result.video_codec is None
        assert result.resolution is None
        assert result.audio_codec == "mp3"

    def test_audio_only_mapped_audio(self):
        """Audio-only file with vorbis maps to aac when client supports it."""
        source_info = {"video_codec": None, "audio_codec": "vorbis"}
        file = _make_file(codec=None, width=0, height=0)

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"audio_streams": [{"codec_name": "vorbis"}]},
            file=file,
            supported_video_codecs=None,
            supported_audio_codecs="aac,opus",
            client_max_resolution=None,
        )

        assert result.video_codec is None
        assert result.audio_codec == "aac"

    def test_audio_only_no_client_audio_list(self):
        """Audio-only file with no supported_audio_codecs falls back to defaults."""
        source_info = {"video_codec": None, "audio_codec": "mp3"}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data=None,
            file=file,
            supported_video_codecs=None,
            supported_audio_codecs=None,
            client_max_resolution=None,
        )

        assert result.video_codec is None
        assert result.audio_codec == "aac"  # default

    def test_audio_only_fallback_to_requested(self):
        """Audio-only with unsupported source audio falls back to requested."""
        source_info = {"video_codec": None, "audio_codec": "unknown_codec"}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"audio_streams": [{"codec_name": "unknown_codec"}]},
            file=file,
            supported_video_codecs=None,
            supported_audio_codecs="opus",
            client_max_resolution=None,
            requested_audio_codec="opus",
        )

        # "unknown_codec" is not in audio_codec_map, so mapped_audio is None
        # "aac" is not in client_audio_codecs ["opus"],
        # so fall back to requested_audio_codec
        assert result.audio_codec == "opus"

    def test_source_h264_client_supports_copy(self):
        """When client supports source codec, use copy."""
        source_info = {"video_codec": "h264", "audio_codec": "aac", "height": 1080}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "h264"}]},
            file=file,
            supported_video_codecs="h264,h265",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        assert result.video_codec == "copy"

    def test_source_hevc_mapped_to_h265_copy(self):
        """HEVC source maps to h265 and copies when client supports it."""
        source_info = {"video_codec": "hevc", "audio_codec": "aac", "height": 1080}
        file = _make_file(codec="hevc")

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "hevc"}]},
            file=file,
            supported_video_codecs="h264,h265",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        assert result.video_codec == "copy"

    def test_source_exceeds_client_max_resolution(self):
        """4K source with 1080p client triggers transcode, not copy."""
        source_info = {"video_codec": "h264", "audio_codec": "aac", "height": 2160}
        file = _make_file(height=2160)

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "h264"}]},
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution="1080p",
        )

        assert result.video_codec == "h264"
        assert result.resolution == "1920x1080"

    def test_source_codec_not_supported_transcodes(self):
        """Unsupported source codec triggers transcode to best available."""
        source_info = {"video_codec": "vp9", "audio_codec": "opus", "height": 1080}
        file = _make_file(codec="vp9")

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "vp9"}]},
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        # vp9 not in client codecs, priority fallback: first match in client codecs
        assert result.video_codec == "h264"

    def test_fallback_h264_when_no_match(self):
        """Falls back to h264 when no codec matches client."""
        source_info = {"video_codec": "mpeg2", "audio_codec": "ac3", "height": 480}
        file = _make_file(codec="mpeg2")

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "mpeg2"}]},
            file=file,
            supported_video_codecs="wmv",  # nothing in priority matches
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        assert result.video_codec == "h264"

    def test_audio_copy_when_source_is_aac(self):
        """AAC source audio uses copy when client supports aac."""
        source_info = {"video_codec": "h264", "audio_codec": "aac", "height": 1080}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"audio_streams": [{"codec_name": "aac"}]},
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs="aac,opus",
            client_max_resolution=None,
        )

        assert result.audio_codec == "copy"

    def test_audio_transcode_ac3_to_aac(self):
        """AC3 audio transcodes to aac."""
        source_info = {"video_codec": "h264", "audio_codec": "ac3", "height": 1080}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"audio_streams": [{"codec_name": "ac3"}]},
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        assert result.audio_codec == "aac"

    def test_audio_fallback_to_requested(self):
        """Unknown audio codec with no aac support uses requested."""
        source_info = {"video_codec": "h264", "audio_codec": "unknown", "height": 1080}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"audio_streams": [{"codec_name": "unknown"}]},
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs="opus",
            client_max_resolution=None,
            requested_audio_codec="opus",
        )

        assert result.audio_codec == "opus"

    def test_no_supported_video_codecs_uses_defaults(self):
        """When no supported_video_codecs, use requested defaults."""
        source_info = {"video_codec": "h264", "audio_codec": "aac", "height": 1080}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data=None,
            file=file,
            supported_video_codecs=None,
            supported_audio_codecs=None,
            client_max_resolution=None,
            requested_video_codec="h265",
        )

        assert result.video_codec == "h265"

    def test_resolution_limit_applied_when_not_copy(self):
        """Client max resolution applies when video is not copy."""
        source_info = {"video_codec": "vp9", "audio_codec": "aac", "height": 1080}
        file = _make_file(codec="vp9")

        result = negotiate_codecs(
            source_info=source_info,
            probe_data=None,
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs=None,
            client_max_resolution="720p",
        )

        assert result.resolution == "1280x720"

    def test_resolution_4k_is_none(self):
        """Client max resolution 4k means no downscale."""
        source_info = {"video_codec": "vp9", "audio_codec": "aac", "height": 1080}
        file = _make_file(codec="vp9")

        result = negotiate_codecs(
            source_info=source_info,
            probe_data=None,
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs=None,
            client_max_resolution="4k",
        )

        assert result.resolution is None

    def test_copy_skips_resolution_limit(self):
        """When video is copy (source fits in client max), resolution limit is not applied."""
        source_info = {"video_codec": "h264", "audio_codec": "aac", "height": 720}
        file = _make_file(height=720)

        result = negotiate_codecs(
            source_info=source_info,
            probe_data=None,
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs=None,
            client_max_resolution="720p",
        )

        # Source 720p fits in 720p max, so copy is used; no resolution applied
        assert result.video_codec == "copy"
        assert result.resolution is None

    def test_source_height_from_file_when_not_in_source_info(self):
        """Uses file.height when source_info height is missing for resolution check."""
        source_info = {"video_codec": "h264", "audio_codec": "aac"}
        file = _make_file(height=2160)

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "h264"}]},
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs=None,
            client_max_resolution="1080p",
        )

        assert result.video_codec == "h264"
        assert result.resolution == "1920x1080"


# ===========================================================================
# 1b. play.py – extract_source_info
# ===========================================================================

class TestExtractSourceInfo:
    def test_no_probe_data_no_file(self):
        info = extract_source_info(None, file=None)
        assert info["video_codec"] is None
        assert info["width"] == 0

    def test_no_probe_data_with_file(self):
        file = _make_file(codec="hevc", width=3840, height=2160)
        info = extract_source_info(None, file=file)
        assert info["video_codec"] == "hevc"
        assert info["width"] == 3840

    def test_structured_format_video_and_audio(self):
        probe = {
            "video_streams": [
                {"codec_name": "h264", "pix_fmt": "yuv420p", "width": 1920, "height": 1080}
            ],
            "audio_streams": [{"codec_name": "aac"}],
        }
        info = extract_source_info(probe)
        assert info["video_codec"] == "h264"
        assert info["audio_codec"] == "aac"
        assert info["bit_depth"] == 8
        assert info["width"] == 1920

    def test_10bit_detection_from_pix_fmt(self):
        probe = {
            "video_streams": [
                {"codec_name": "hevc", "pix_fmt": "yuv420p10le", "width": 3840, "height": 2160}
            ],
            "audio_streams": [],
        }
        info = extract_source_info(probe)
        assert info["bit_depth"] == 10

    def test_12bit_detection(self):
        probe = {
            "video_streams": [
                {"codec_name": "hevc", "pix_fmt": "yuv420p12le", "width": 3840, "height": 2160}
            ],
            "audio_streams": [],
        }
        info = extract_source_info(probe)
        assert info["bit_depth"] == 12

    def test_p010_format_detection(self):
        probe = {
            "video_streams": [
                {"codec_name": "hevc", "pix_fmt": "p010le", "width": 3840, "height": 2160}
            ],
            "audio_streams": [],
        }
        info = extract_source_info(probe)
        assert info["bit_depth"] == 10

    def test_legacy_raw_ffprobe_streams(self):
        """Fallback to raw ffprobe JSON with streams array."""
        probe = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "width": 1280, "height": 720},
                {"codec_type": "audio", "codec_name": "aac"},
            ]
        }
        info = extract_source_info(probe)
        assert info["video_codec"] == "h264"
        assert info["audio_codec"] == "aac"
        assert info["width"] == 1280

    def test_legacy_flat_dict(self):
        """Fallback to flat dict from old probe."""
        probe = {"video_codec": "hevc", "audio_codec": "DTS", "width": 1920, "height": 1080}
        info = extract_source_info(probe)
        assert info["video_codec"] == "hevc"
        assert info["audio_codec"] == "dts"

    def test_legacy_flat_dict_hdr_implies_10bit(self):
        probe = {"video_codec": "hevc", "hdr_format": "HDR10", "width": 3840, "height": 2160}
        info = extract_source_info(probe)
        assert info["bit_depth"] == 10

    def test_audio_only_no_video_streams(self):
        probe = {
            "video_streams": [],
            "audio_streams": [{"codec_name": "mp3"}],
        }
        info = extract_source_info(probe)
        assert info["video_codec"] is None
        assert info["audio_codec"] == "mp3"

    def test_video_codec_fallback_to_file(self):
        """Falls back to file.codec when probe has no video streams and file has dimensions."""
        probe = {"video_streams": [], "audio_streams": []}
        file = _make_file(codec="h264", width=1920, height=1080)
        info = extract_source_info(probe, file=file)
        assert info["video_codec"] == "h264"

    def test_no_video_fallback_when_file_has_no_dimensions(self):
        """Does not fall back to file.codec when file has no width/height."""
        probe = {"video_streams": [], "audio_streams": []}
        file = _make_file(codec="h264", width=0, height=0)
        info = extract_source_info(probe, file=file)
        assert info["video_codec"] is None


# ===========================================================================
# 1c. play.py – build_stream_info
# ===========================================================================

class TestBuildStreamInfo:
    @patch("pyrate.services.computing.detect_hardware_acceleration", return_value={"type": "qsv"})
    def test_basic_build(self, _mock_hw):
        file = _make_file()
        result = build_stream_info(
            file=file,
            probe_data={
                "video_streams": [{"codec_name": "h264", "pix_fmt": "yuv420p", "width": 1920, "height": 1080}],
                "audio_streams": [{"codec_name": "aac"}],
            },
            effective_video_codec="h264",
            effective_audio_codec="aac",
            effective_resolution=None,
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        assert result["source_file"]["video_codec"] == "h264"
        assert result["transcoding"]["video_codec"] == "h264"
        assert result["transcoding"]["hw_accel"] == "QSV"
        assert result["client_capabilities"]["supported_video_codecs"] == "h264"

    @patch("pyrate.services.computing.detect_hardware_acceleration", return_value={"type": ""})
    def test_hw_accel_empty_type(self, _mock_hw):
        file = _make_file()
        result = build_stream_info(
            file=file,
            probe_data=None,
            effective_video_codec="copy",
            effective_audio_codec="copy",
            effective_resolution=None,
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs=None,
            supported_audio_codecs=None,
            client_max_resolution=None,
        )

        assert result["transcoding"]["hw_accel"] is None

    @patch("pyrate.services.computing.detect_hardware_acceleration", side_effect=ImportError)
    def test_hw_accel_exception(self, _mock_hw):
        file = _make_file()
        result = build_stream_info(
            file=file,
            probe_data=None,
            effective_video_codec="copy",
            effective_audio_codec="copy",
            effective_resolution=None,
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs=None,
            supported_audio_codecs=None,
            client_max_resolution=None,
        )

        assert result["transcoding"]["hw_accel"] is None

    @patch("pyrate.services.computing.detect_hardware_acceleration", return_value={"type": ""})
    def test_transcoding_reasons_codec_unsupported(self, _mock_hw):
        file = _make_file(codec="hevc")
        result = build_stream_info(
            file=file,
            probe_data={
                "video_streams": [{"codec_name": "hevc", "pix_fmt": "yuv420p", "width": 1920, "height": 1080}],
                "audio_streams": [{"codec_name": "ac3"}],
            },
            effective_video_codec="h264",
            effective_audio_codec="aac",
            effective_resolution="1280x720",
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution="720p",
        )

        reasons = result["transcoding_reasons"]
        assert any("hevc" in r for r in reasons)
        assert any("720" in r for r in reasons)
        assert any("ac3" in r for r in reasons)

    @patch("pyrate.services.computing.detect_hardware_acceleration", return_value={"type": ""})
    def test_transcoding_reasons_10bit(self, _mock_hw):
        file = _make_file()
        result = build_stream_info(
            file=file,
            probe_data={
                "video_streams": [{"codec_name": "hevc", "pix_fmt": "yuv420p10le", "width": 3840, "height": 2160}],
                "audio_streams": [{"codec_name": "aac"}],
            },
            effective_video_codec="h264",
            effective_audio_codec="copy",
            effective_resolution=None,
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        reasons = result["transcoding_reasons"]
        assert any("10-bit" in r for r in reasons)

    @patch("pyrate.services.computing.detect_hardware_acceleration", return_value={"type": ""})
    def test_transcoding_reasons_audio_no_source(self, _mock_hw):
        """Audio transcoding reason when source_audio_codec is None."""
        file = _make_file()
        result = build_stream_info(
            file=file,
            probe_data=None,
            effective_video_codec="copy",
            effective_audio_codec="aac",
            effective_resolution=None,
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs=None,
            supported_audio_codecs=None,
            client_max_resolution=None,
        )

        reasons = result["transcoding_reasons"]
        assert any("Audio transcoding" in r for r in reasons)

    @patch("pyrate.services.computing.detect_hardware_acceleration", return_value={"type": ""})
    def test_transcoding_reasons_fallback_video(self, _mock_hw):
        """Video transcoding reason fallback when no specific reason applies."""
        file = _make_file()
        result = build_stream_info(
            file=file,
            probe_data={
                "video_streams": [{"codec_name": "h264", "pix_fmt": "yuv420p", "width": 1920, "height": 1080}],
                "audio_streams": [{"codec_name": "aac"}],
            },
            effective_video_codec="h264",
            effective_audio_codec="copy",
            effective_resolution=None,
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs="h264,h265",  # client supports h264 so no "unsupported" reason
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        reasons = result["transcoding_reasons"]
        # Should have fallback "Video: h264 -> h264"
        assert any("Video:" in r for r in reasons)


# ===========================================================================
# 1d. play.py – select_streams_for_user
# ===========================================================================

class TestSelectStreamsForUser:
    def test_no_probe_data(self):
        result = select_streams_for_user(None)
        assert result["audio_stream"] == 0
        assert result["subtitle_stream"] is None

    def test_preferred_audio_found(self):
        probe = {
            "audio_streams": [
                {"index": 0, "language": "eng"},
                {"index": 1, "language": "deu"},
            ],
            "subtitle_streams": [],
        }
        result = select_streams_for_user(probe, preferred_audio_languages=["de"])
        assert result["audio_stream"] == 1

    def test_audio_default_fallback(self):
        """Uses default stream when no language match."""
        probe = {
            "audio_streams": [
                {"index": 0, "language": "jpn"},
                {"index": 1, "language": "eng", "default": True},
            ],
            "subtitle_streams": [],
        }
        result = select_streams_for_user(probe, preferred_audio_languages=["de"])
        assert result["audio_stream"] == 1

    def test_audio_no_match_no_default(self):
        """Stays at index 0 when no match and no default."""
        probe = {
            "audio_streams": [
                {"index": 0, "language": "jpn"},
                {"index": 1, "language": "eng"},
            ],
            "subtitle_streams": [],
        }
        result = select_streams_for_user(probe, preferred_audio_languages=["de"])
        assert result["audio_stream"] == 0

    def test_subtitle_selection_non_forced(self):
        probe = {
            "audio_streams": [{"index": 0, "language": "eng"}],
            "subtitle_streams": [
                {"index": 0, "language": "deu", "forced": True},
                {"index": 1, "language": "deu", "forced": False},
            ],
        }
        result = select_streams_for_user(
            probe, preferred_subtitle_language="de"
        )
        assert result["subtitle_stream"] == 1

    def test_subtitle_forced_only_option(self):
        """If only forced subtitle matches, use it."""
        probe = {
            "audio_streams": [{"index": 0, "language": "eng"}],
            "subtitle_streams": [
                {"index": 0, "language": "deu", "forced": True},
            ],
        }
        result = select_streams_for_user(
            probe, preferred_subtitle_language="de"
        )
        assert result["subtitle_stream"] == 0

    def test_no_subtitle_when_not_requested(self):
        probe = {
            "audio_streams": [{"index": 0, "language": "eng"}],
            "subtitle_streams": [
                {"index": 0, "language": "eng"},
            ],
        }
        result = select_streams_for_user(probe, preferred_subtitle_language=None)
        assert result["subtitle_stream"] is None

    def test_empty_audio_streams(self):
        probe = {"audio_streams": [], "subtitle_streams": []}
        result = select_streams_for_user(probe, preferred_audio_languages=["en"])
        assert result["audio_stream"] == 0


# ===========================================================================
# 1e. play.py – get_active_transcode_container
# ===========================================================================

class TestGetActiveTranscodeContainer:
    @pytest.mark.asyncio
    async def test_finds_matching_task(self):
        content_id = "abc-123"
        mock_computing = AsyncMock()
        mock_computing.list_tasks = AsyncMock(
            return_value=[
                {
                    "task_id": "task-xyz",
                    "container_id": "container-xyz",
                    "status": "running",
                    "labels": {"content_id": content_id},
                }
            ]
        )
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.play.ComputingService", return_value=mock_computing):
            result = await get_active_transcode_container(content_id)

        assert result == "container-xyz"
        mock_computing.list_tasks.assert_awaited_once_with(
            labels={"content_id": content_id}
        )

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        mock_computing = AsyncMock()
        mock_computing.list_tasks = AsyncMock(return_value=[])
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.play.ComputingService", return_value=mock_computing):
            result = await get_active_transcode_container("nonexistent-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        with patch(
            "pyrate.services.play.ComputingService",
            side_effect=Exception("provider not available"),
        ):
            result = await get_active_transcode_container("any-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_skips_inactive_tasks(self):
        mock_computing = AsyncMock()
        mock_computing.list_tasks = AsyncMock(
            return_value=[
                {
                    "task_id": "task-xyz",
                    "container_id": "container-xyz",
                    "status": "completed",
                    "labels": {"content_id": "abc-123"},
                }
            ]
        )
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.play.ComputingService", return_value=mock_computing):
            result = await get_active_transcode_container("abc-123")

        assert result is None


# ===========================================================================
# 1f. play.py – probe_video_full / _probe_video_with_computing_service
# ===========================================================================

class TestProbeVideoFull:
    @pytest.mark.asyncio
    async def test_probe_completed_successfully(self):
        mock_computing = AsyncMock()
        mock_computing.probe_media_file = AsyncMock(return_value={
            "streams": [{"codec_type": "video", "codec_name": "h264"}],
            "format": {"duration": "120.0"},
        })
        mock_computing.start_task.return_value = "task-123"
        mock_computing.get_task_status.return_value = "completed"
        mock_computing.get_task_logs.return_value = json.dumps({
            "streams": [{"codec_type": "video", "codec_name": "h264"}],
            "format": {"duration": "120.0"},
        })
        mock_computing.delete_task = AsyncMock()
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)

        mock_settings = AsyncMock()
        mock_settings.get.return_value = "/data"

        with patch("pyrate.services.play.ComputingService", return_value=mock_computing), \
             patch("pyrate.services.settings.SettingsService", return_value=mock_settings), \
             patch("pyrate.services.play._structure_probe_data", return_value={"video_streams": []}) as mock_struct:
            result = await probe_video_full("/library/movies/test.mkv", db=AsyncMock())

        assert result is not None
        mock_struct.assert_called_once()

    @pytest.mark.asyncio
    async def test_probe_task_failed(self):
        mock_computing = AsyncMock()
        mock_computing.probe_media_file = AsyncMock(return_value=None)
        mock_computing.start_task.return_value = "task-123"
        mock_computing.get_task_status.return_value = "failed"
        mock_computing.get_task_logs.return_value = "Error: file not found"
        mock_computing.delete_task = AsyncMock()
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)

        mock_settings = AsyncMock()
        mock_settings.get.return_value = "/data"

        with patch("pyrate.services.play.ComputingService", return_value=mock_computing), \
             patch("pyrate.services.settings.SettingsService", return_value=mock_settings):
            result = await probe_video_full("/library/movies/test.mkv", db=AsyncMock())

        assert result is None

    @pytest.mark.asyncio
    async def test_probe_empty_output(self):
        mock_computing = AsyncMock()
        mock_computing.probe_media_file = AsyncMock(return_value=None)
        mock_computing.start_task.return_value = "task-123"
        mock_computing.get_task_status.return_value = "completed"
        mock_computing.get_task_logs.return_value = "   "
        mock_computing.delete_task = AsyncMock()
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)

        mock_settings = AsyncMock()
        mock_settings.get.return_value = "/data"

        with patch("pyrate.services.play.ComputingService", return_value=mock_computing), \
             patch("pyrate.services.settings.SettingsService", return_value=mock_settings):
            result = await probe_video_full("/library/movies/test.mkv", db=AsyncMock())

        assert result is None

    @pytest.mark.asyncio
    async def test_probe_exception_returns_none(self):
        with patch("pyrate.services.play.ComputingService", side_effect=Exception("fail")), \
             patch("pyrate.services.settings.SettingsService", return_value=AsyncMock(get=AsyncMock(return_value="/data"))):
            result = await _probe_video_with_computing_service("/test.mkv", db=AsyncMock())

        assert result is None


# ===========================================================================
# 1g. play.py – probe_video_metadata
# ===========================================================================

class TestProbeVideoMetadata:
    @pytest.mark.asyncio
    async def test_returns_metadata(self):
        probe_data = {
            "format": {"duration": "120.5", "size": "5000000", "bit_rate": "5000000"},
            "video_streams": [{"codec_name": "h264", "width": 1920, "height": 1080}],
        }

        with patch("pyrate.services.play.probe_video_full", new_callable=AsyncMock, return_value=probe_data):
            result = await probe_video_metadata("/test.mkv", db=AsyncMock())

        assert result["duration"] == 120.5
        assert result["file_size"] == 5000000
        assert result["bitrate"] == 5000
        assert result["width"] == 1920
        assert result["codec"] == "h264"

    @pytest.mark.asyncio
    async def test_returns_defaults_when_probe_fails(self):
        with patch("pyrate.services.play.probe_video_full", new_callable=AsyncMock, return_value=None):
            result = await probe_video_metadata("/test.mkv", db=AsyncMock())

        assert result["duration"] is None
        assert result["width"] is None

    @pytest.mark.asyncio
    async def test_returns_defaults_on_exception(self):
        with patch("pyrate.services.play.probe_video_full", new_callable=AsyncMock, side_effect=Exception("fail")):
            result = await probe_video_metadata("/test.mkv", db=AsyncMock())

        assert result["duration"] is None


# ===========================================================================
# 1h. play.py – _get_base_library_path
# ===========================================================================

class TestGetBaseLibraryPath:
    @pytest.mark.asyncio
    async def test_returns_configured_path(self):
        mock_settings = AsyncMock()
        mock_settings.get.return_value = "/mnt/media"

        with patch("pyrate.services.settings.SettingsService", return_value=mock_settings):
            result = await _get_base_library_path(db=AsyncMock())

        assert result == "/mnt/media"


# ===========================================================================
# 1i. play.py – start_transcode_container
# ===========================================================================

class TestStartTranscodeContainer:
    @pytest.mark.asyncio
    async def test_delegates_to_computing_service(self):
        mock_computing = AsyncMock()
        mock_computing.start_transcoding.return_value = "task-456"
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)

        mock_settings = AsyncMock()
        mock_settings.get.return_value = "/data"

        with patch("pyrate.services.computing.ComputingService", return_value=mock_computing), \
             patch("pyrate.services.settings.SettingsService", return_value=mock_settings):
            result = await start_transcode_container(
                db=AsyncMock(),
                input_path="/library/movies/test.mkv",
                rel_output="/temp/stream.m3u8",
                segment_pattern="/temp/seg_%03d.ts",
                session_id="sess-1",
            )

        assert result == "task-456"
        mock_computing.start_transcoding.assert_awaited_once()
        kwargs = mock_computing.start_transcoding.call_args.kwargs
        assert kwargs["input_path"] == "/library/movies/test.mkv"
        assert kwargs["session_id"] == "sess-1"

    @pytest.mark.asyncio
    async def test_generates_session_id_if_none(self):
        mock_computing = AsyncMock()
        mock_computing.start_transcoding.return_value = "task-789"
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)

        mock_settings = AsyncMock()
        mock_settings.get.return_value = "/data"

        with patch("pyrate.services.computing.ComputingService", return_value=mock_computing), \
             patch("pyrate.services.settings.SettingsService", return_value=mock_settings):
            await start_transcode_container(
                db=AsyncMock(),
                input_path="/test.mkv",
                rel_output="/out.m3u8",
                segment_pattern="/seg_%03d.ts",
                session_id=None,
            )

        kwargs = mock_computing.start_transcoding.call_args.kwargs
        # session_id should be a valid UUID string
        uuid.UUID(kwargs["session_id"])


# ===========================================================================
# 2. computing.py – detect_hardware_acceleration
# ===========================================================================

class TestDetectHardwareAcceleration:
    def test_disabled_via_env(self):
        from pyrate.services.computing import detect_hardware_acceleration

        with patch.dict("os.environ", {"ENABLE_HARDWARE_ACCEL": "false"}):
            result = detect_hardware_acceleration()

        assert result["type"] is None
        assert result["devices"] == []
        assert result["encoder_suffix"] == ""

    def test_no_dri_devices(self):
        from pyrate.services.computing import detect_hardware_acceleration

        with patch.dict("os.environ", {"ENABLE_HARDWARE_ACCEL": "true"}), \
             patch("os.path.exists", return_value=False):
            result = detect_hardware_acceleration()

        assert result["type"] is None
        assert result["devices"] == []

    def test_intel_gpu_detected(self):
        from pyrate.services.computing import detect_hardware_acceleration

        def mock_exists(path):
            return path in ("/dev/dri", "/dev/dri/renderD128", "/dev/dri/card0")

        with patch.dict("os.environ", {"ENABLE_HARDWARE_ACCEL": "true"}), \
             patch("os.path.exists", side_effect=mock_exists):
            result = detect_hardware_acceleration()

        assert result["type"] == "qsv"
        assert "/dev/dri/renderD128" in result["devices"]
        assert "/dev/dri/card0" in result["devices"]
        assert result["encoder_suffix"] == "_qsv"

    def test_only_renderD128(self):
        from pyrate.services.computing import detect_hardware_acceleration

        def mock_exists(path):
            return path in ("/dev/dri", "/dev/dri/renderD128")

        with patch.dict("os.environ", {"ENABLE_HARDWARE_ACCEL": "true"}), \
             patch("os.path.exists", side_effect=mock_exists):
            result = detect_hardware_acceleration()

        assert result["type"] == "qsv"
        assert result["devices"] == ["/dev/dri/renderD128"]


# ===========================================================================
# 2b. computing.py – ComputingService
# ===========================================================================

class TestComputingService:
    @pytest.mark.asyncio
    async def test_context_manager(self):
        from pyrate.services.computing import ComputingService

        db = AsyncMock()
        svc = ComputingService(db)
        mock_provider = AsyncMock()
        svc._provider = mock_provider

        async with svc:
            pass

        # After __aexit__, close() sets _provider to None
        mock_provider.close.assert_awaited_once()
        assert svc._provider is None

    @pytest.mark.asyncio
    async def test_close_without_provider(self):
        from pyrate.services.computing import ComputingService

        db = AsyncMock()
        svc = ComputingService(db)
        await svc.close()  # should not raise

    @pytest.mark.asyncio
    async def test_close_with_error(self):
        from pyrate.services.computing import ComputingService

        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = AsyncMock()
        svc._provider.close.side_effect = Exception("close error")
        svc._provider_domain = "test.provider"

        await svc.close()  # should not raise
        assert svc._provider is None

    @pytest.mark.asyncio
    async def test_get_provider_cached(self):
        from pyrate.services.computing import ComputingService

        db = AsyncMock()
        svc = ComputingService(db)
        mock_provider = MagicMock()
        svc._provider = mock_provider

        result = await svc.get_provider()
        assert result is mock_provider

    @pytest.mark.asyncio
    async def test_get_provider_loads_docker(self):
        from pyrate.services.computing import ComputingService

        db = AsyncMock()
        svc = ComputingService(db)

        mock_instance = AsyncMock()

        with patch("pyrate.services.computing.get_computing_provider_domain", return_value="docker"), \
             patch("pyrate.services.computing.DockerComputingProvider", return_value=mock_instance):
            provider = await svc.get_provider()

        assert provider is mock_instance
        mock_instance.setup.assert_awaited_once()


# ===========================================================================
# 2c. computing.py – ComputingService task delegation
# ===========================================================================

class TestComputingServiceTasks:
    @pytest.mark.asyncio
    async def test_start_task(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        mock_provider.start_task.return_value = "task-1"

        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        result = await svc.start_task(image="test:latest", command=["echo"])
        assert result == "task-1"

    @pytest.mark.asyncio
    async def test_get_task_status(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        mock_provider.get_task_status.return_value = "running"

        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        result = await svc.get_task_status("task-1")
        assert result == "running"

    @pytest.mark.asyncio
    async def test_get_task_logs(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        mock_provider.get_task_logs.return_value = "log output"

        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        result = await svc.get_task_logs("task-1")
        assert result == "log output"

    @pytest.mark.asyncio
    async def test_stop_task(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        await svc.stop_task("task-1", force=True)
        mock_provider.stop_task.assert_awaited_once_with("task-1", force=True)

    @pytest.mark.asyncio
    async def test_delete_task(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        await svc.delete_task("task-1")
        mock_provider.delete_task.assert_awaited_once_with("task-1")

    @pytest.mark.asyncio
    async def test_list_tasks(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        mock_provider.list_tasks.return_value = [{"id": "task-1"}]

        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        result = await svc.list_tasks(labels={"key": "val"})
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_tasks_by_label(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        mock_provider.list_tasks.return_value = [{"id": "task-1"}]

        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        result = await svc.get_tasks_by_label("session_id", "sess-1")
        assert len(result) == 1
        mock_provider.list_tasks.assert_awaited_once_with(labels={"session_id": "sess-1"})

    @pytest.mark.asyncio
    async def test_terminate_task_success(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        result = await svc.terminate_task("task-1")
        assert result is True
        mock_provider.stop_task.assert_awaited_once_with("task-1", force=True)
        mock_provider.delete_task.assert_awaited_once_with("task-1")

    @pytest.mark.asyncio
    async def test_terminate_task_failure(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        mock_provider.stop_task.side_effect = Exception("fail")

        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        result = await svc.terminate_task("task-1")
        assert result is False


# ===========================================================================
# 2d. computing.py – start_ffmpeg_task / start_ffprobe_task
# ===========================================================================

class TestComputingServiceFFmpegTasks:
    @pytest.mark.asyncio
    async def test_start_ffmpeg_task(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        mock_provider.start_task.return_value = "ffmpeg-task-1"

        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        result = await svc.start_ffmpeg_task(
            input_file="/input.mkv",
            output_file="/output.mp4",
            ffmpeg_args=["-c:v", "libx264"],
        )

        assert result == "ffmpeg-task-1"
        call_kwargs = mock_provider.start_task.call_args.kwargs
        assert call_kwargs["command"] == ["ffmpeg", "-i", "/input.mkv", "-c:v", "libx264", "/output.mp4"]
        assert call_kwargs["labels"]["pyrate.task_type"] == "transcode"

    @pytest.mark.asyncio
    async def test_start_ffmpeg_task_with_gpu(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        mock_provider.start_task.return_value = "gpu-task-1"

        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        await svc.start_ffmpeg_task(
            input_file="/input.mkv",
            output_file="/output.mp4",
            ffmpeg_args=["-c:v", "h264_qsv"],
            gpu_enabled=True,
        )

        call_kwargs = mock_provider.start_task.call_args.kwargs
        assert call_kwargs["gpu_limit"] == 1

    @pytest.mark.asyncio
    async def test_start_ffprobe_task(self):
        from pyrate.services.computing import ComputingService

        mock_provider = AsyncMock()
        mock_provider.start_task.return_value = "probe-task-1"

        db = AsyncMock()
        svc = ComputingService(db)
        svc._provider = mock_provider

        result = await svc.start_ffprobe_task(input_file="/video.mkv")

        assert result == "probe-task-1"
        call_kwargs = mock_provider.start_task.call_args.kwargs
        assert "ffprobe" in call_kwargs["command"]
        assert "/video.mkv" in call_kwargs["command"]
        assert call_kwargs["labels"]["pyrate.task_type"] == "probe"


# ===========================================================================
# 2e. computing.py – _build_ffmpeg_command
# ===========================================================================

class TestBuildFfmpegCommand:
    def _make_service(self):
        from pyrate.services.computing import ComputingService
        return ComputingService(db=AsyncMock())

    def _default_kwargs(self, **overrides):
        defaults = {
            "input_path": "/input.mkv",
            "rel_output": "/output/stream.m3u8",
            "segment_pattern": "/output/seg_%03d.ts",
            "hls_time": 6,
            "video_codec": "h264",
            "audio_codec": "aac",
            "video_bitrate": None,
            "audio_bitrate": "128k",
            "start_position": None,
            "resolution": None,
            "audio_stream_index": None,
            "subtitle_stream_index": None,
            "burn_subtitles": False,
            "hw_accel": None,
            "thread_count": 0,
            "audio_only": False,
        }
        defaults.update(overrides)
        return defaults

    def test_h264_software_crf(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs())

        assert "-c:v" in cmd
        idx = cmd.index("-c:v")
        assert cmd[idx + 1] == "libx264"
        assert "-crf" in cmd
        assert "-c:a" in cmd
        aidx = cmd.index("-c:a")
        assert cmd[aidx + 1] == "aac"
        assert "-f" in cmd
        assert "hls" in cmd

    def test_h264_with_bitrate(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(video_bitrate="4000k"))

        assert "-b:v" in cmd
        assert "4000k" in cmd
        assert "-maxrate" in cmd
        assert "-bufsize" in cmd
        assert "-crf" not in cmd

    def test_h265_software(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(video_codec="h265"))

        idx = cmd.index("-c:v")
        assert cmd[idx + 1] == "libx265"
        assert "-tag:v" in cmd
        tag_idx = cmd.index("-tag:v")
        assert cmd[tag_idx + 1] == "hvc1"

    def test_h265_with_qsv(self):
        svc = self._make_service()
        hw_accel = {"type": "qsv", "devices": ["/dev/dri/renderD128"], "encoder_suffix": "_qsv"}
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(video_codec="h265", hw_accel=hw_accel))

        assert "hevc_qsv" in cmd
        assert "-init_hw_device" in cmd

    def test_vp9_software(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(video_codec="vp9"))

        idx = cmd.index("-c:v")
        assert cmd[idx + 1] == "libvpx-vp9"

    def test_av1_software(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(video_codec="av1"))

        idx = cmd.index("-c:v")
        assert cmd[idx + 1] == "libsvtav1"

    def test_av1_with_qsv(self):
        svc = self._make_service()
        hw_accel = {"type": "qsv", "devices": [], "encoder_suffix": "_qsv"}
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(video_codec="av1", hw_accel=hw_accel))

        assert "av1_qsv" in cmd

    def test_copy_video(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(video_codec="copy"))

        idx = cmd.index("-c:v")
        assert cmd[idx + 1] == "copy"
        assert "-tag:v" in cmd

    def test_copy_audio(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(audio_codec="copy"))

        aidx = cmd.index("-c:a")
        assert cmd[aidx + 1] == "copy"

    def test_opus_audio(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(audio_codec="opus"))

        aidx = cmd.index("-c:a")
        assert cmd[aidx + 1] == "libopus"

    def test_mp3_audio(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(audio_codec="mp3"))

        aidx = cmd.index("-c:a")
        assert cmd[aidx + 1] == "libmp3lame"

    def test_start_position(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(start_position=120.5))

        assert "-ss" in cmd
        ss_idx = cmd.index("-ss")
        assert cmd[ss_idx + 1] == "120.5"
        # -ss must be before -i for fast seeking
        i_idx = cmd.index("-i")
        assert ss_idx < i_idx

    def test_resolution_scaling(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(resolution="1280x720"))

        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        assert "1280" in cmd[vf_idx + 1]
        assert "720" in cmd[vf_idx + 1]

    def test_audio_stream_selection(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(audio_stream_index=2))

        assert "0:a:2" in cmd

    def test_burn_subtitles(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(
            subtitle_stream_index=1,
            burn_subtitles=True,
        ))

        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        assert "subtitles" in cmd[vf_idx + 1]
        assert "si=1" in cmd[vf_idx + 1]

    def test_burn_subtitles_with_qsv(self):
        svc = self._make_service()
        hw_accel = {"type": "qsv", "devices": [], "encoder_suffix": "_qsv"}
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(
            subtitle_stream_index=0,
            burn_subtitles=True,
            hw_accel=hw_accel,
        ))

        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        vf_value = cmd[vf_idx + 1]
        assert "subtitles" in vf_value
        assert "hwupload" in vf_value

    def test_thread_count(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(thread_count=4))

        assert "-threads" in cmd
        t_idx = cmd.index("-threads")
        assert cmd[t_idx + 1] == "4"

    def test_audio_only(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(audio_only=True))

        assert "-vn" in cmd
        # Should not have video codec
        assert "-c:v" not in cmd
        # Should map audio
        assert "0:a:0" in cmd

    def test_audio_only_with_stream_index(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(
            audio_only=True,
            audio_stream_index=3,
        ))

        assert "0:a:3" in cmd
        assert "-vn" in cmd

    def test_qsv_resolution_scaling(self):
        svc = self._make_service()
        hw_accel = {"type": "qsv", "devices": [], "encoder_suffix": "_qsv"}
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(
            resolution="1920x1080",
            hw_accel=hw_accel,
        ))

        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        vf_value = cmd[vf_idx + 1]
        assert "scale=1920:1080" in vf_value
        assert "format=nv12" in vf_value
        assert "hwupload" in vf_value

    def test_vaapi_hw_accel(self):
        svc = self._make_service()
        hw_accel = {"type": "vaapi", "devices": ["/dev/dri/renderD128"], "encoder_suffix": ""}
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(hw_accel=hw_accel))

        assert "-hwaccel" in cmd
        assert "vaapi" in cmd

    def test_hls_output_settings(self):
        svc = self._make_service()
        cmd = svc._build_ffmpeg_command(**self._default_kwargs(hls_time=10))

        assert "-f" in cmd
        f_idx = cmd.index("-f")
        assert cmd[f_idx + 1] == "hls"
        assert "-hls_time" in cmd
        ht_idx = cmd.index("-hls_time")
        assert cmd[ht_idx + 1] == "10"
        assert "/output/stream.m3u8" in cmd


# ===========================================================================
# 3. transcoding_session.py – gaps not covered by existing tests
# ===========================================================================

class TestTranscodingSessionTerminateWithContainer:
    """Test terminate_session with Docker container cleanup (not in existing tests)."""

    @pytest_asyncio.fixture
    async def service(self):
        from pyrate.services.transcoding_session import TranscodingSessionService
        svc = TranscodingSessionService()
        svc._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        return svc

    def _create_session_data(self, session_id="sess_001", container_id=None):
        return TranscodingSessionCreate(
            session_id=session_id,
            user_guid=uuid.uuid4(),
            user_name="Test User",
            content_type="movie",
            content_id=uuid.uuid4(),
            content_title="Test Movie",
            video_codec="h264",
            audio_codec="aac",
            container_id=container_id,
        )

    @pytest.mark.asyncio
    async def test_terminate_with_container_stop_and_delete(self, service):
        """Terminate session with container_id triggers Docker stop+delete."""
        data = self._create_session_data(container_id="container-abc")
        await service.create_session(data)

        mock_container = AsyncMock()
        mock_docker = AsyncMock()
        mock_docker.containers.get.return_value = mock_container
        mock_docker.containers.list.return_value = []
        mock_docker.__aenter__ = AsyncMock(return_value=mock_docker)
        mock_docker.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.transcoding_session.Docker", return_value=mock_docker):
            result = await service.terminate_session("sess_001")

        assert result["success"] is True
        assert result["container_stopped"] is True
        mock_container.stop.assert_awaited_once()
        mock_container.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_terminate_container_error_still_succeeds(self, service):
        """Terminate succeeds even if Docker container stop fails."""
        data = self._create_session_data(container_id="container-abc")
        await service.create_session(data)

        mock_docker = AsyncMock()
        mock_docker.containers.get.side_effect = Exception("container not found")
        mock_docker.containers.list.return_value = []
        mock_docker.__aenter__ = AsyncMock(return_value=mock_docker)
        mock_docker.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.transcoding_session.Docker", return_value=mock_docker):
            result = await service.terminate_session("sess_001")

        assert result["success"] is True
        assert "container_error" in result

    @pytest.mark.asyncio
    async def test_terminate_finds_container_by_label(self, service):
        """Terminate finds container by session_id label."""
        data = self._create_session_data(container_id="container-abc")
        await service.create_session(data)

        # First Docker call (get by ID) succeeds
        mock_container_by_id = AsyncMock()
        # Second Docker call (list) finds container by label
        mock_container_by_label = AsyncMock()
        mock_container_by_label.show.return_value = {
            "Config": {"Labels": {"transcode.session_id": "sess_001"}}
        }

        mock_docker_1 = AsyncMock()
        mock_docker_1.containers.get.return_value = mock_container_by_id
        mock_docker_1.__aenter__ = AsyncMock(return_value=mock_docker_1)
        mock_docker_1.__aexit__ = AsyncMock(return_value=False)

        mock_docker_2 = AsyncMock()
        mock_docker_2.containers.list.return_value = [mock_container_by_label]
        mock_docker_2.__aenter__ = AsyncMock(return_value=mock_docker_2)
        mock_docker_2.__aexit__ = AsyncMock(return_value=False)

        call_count = 0
        def make_docker():
            nonlocal call_count
            call_count += 1
            return mock_docker_1 if call_count == 1 else mock_docker_2

        with patch("pyrate.services.transcoding_session.Docker", side_effect=make_docker):
            result = await service.terminate_session("sess_001")

        assert result["success"] is True
        mock_container_by_label.stop.assert_awaited_once()
        mock_container_by_label.delete.assert_awaited_once()


class TestTranscodingSessionCleanupStale:
    """Test cleanup_stale_sessions (not in existing tests)."""

    @pytest_asyncio.fixture
    async def service(self):
        from pyrate.services.transcoding_session import TranscodingSessionService
        svc = TranscodingSessionService()
        svc._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        return svc

    @pytest.mark.asyncio
    async def test_cleanup_removes_stale_sessions(self, service):
        """Sessions with stopped containers and old last_accessed_at are cleaned."""
        data = TranscodingSessionCreate(
            session_id="stale-sess",
            user_guid=uuid.uuid4(),
            user_name="User",
            content_type="movie",
            content_id=uuid.uuid4(),
            content_title="Movie",
            video_codec="h264",
            audio_codec="aac",
            container_id="old-container",
        )
        session = await service.create_session(data)

        # Manually age the session's last_accessed_at
        r = await service._get_redis()
        session_key = service._get_session_key("stale-sess")
        session_data = json.loads(await r.get(session_key))
        session_data["last_accessed_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await r.set(session_key, json.dumps(session_data), ex=7200)

        # Mock Docker with no running containers
        mock_docker = AsyncMock()
        mock_docker.containers.list.return_value = []
        mock_docker.__aenter__ = AsyncMock(return_value=mock_docker)
        mock_docker.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.transcoding_session.Docker", return_value=mock_docker):
            cleaned = await service.cleanup_stale_sessions()

        assert cleaned == 1
        assert await service.get_session("stale-sess") is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_recently_accessed(self, service):
        """Sessions accessed recently are kept even if container stopped."""
        data = TranscodingSessionCreate(
            session_id="recent-sess",
            user_guid=uuid.uuid4(),
            user_name="User",
            content_type="movie",
            content_id=uuid.uuid4(),
            content_title="Movie",
            video_codec="h264",
            audio_codec="aac",
            container_id="container-1",
        )
        await service.create_session(data)

        # Mock Docker with no running containers
        mock_docker = AsyncMock()
        mock_docker.containers.list.return_value = []
        mock_docker.__aenter__ = AsyncMock(return_value=mock_docker)
        mock_docker.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.transcoding_session.Docker", return_value=mock_docker):
            cleaned = await service.cleanup_stale_sessions()

        assert cleaned == 0
        assert await service.get_session("recent-sess") is not None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_running_containers(self, service):
        """Sessions with running containers are kept."""
        data = TranscodingSessionCreate(
            session_id="running-sess",
            user_guid=uuid.uuid4(),
            user_name="User",
            content_type="movie",
            content_id=uuid.uuid4(),
            content_title="Movie",
            video_codec="h264",
            audio_codec="aac",
            container_id="running-container",
        )
        session = await service.create_session(data)

        # Age the session
        r = await service._get_redis()
        session_key = service._get_session_key("running-sess")
        session_data = json.loads(await r.get(session_key))
        session_data["last_accessed_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await r.set(session_key, json.dumps(session_data), ex=7200)

        # Mock Docker with the container running
        mock_container = AsyncMock()
        mock_container.show.return_value = {
            "Id": "running-container",
            "Config": {"Labels": {}},
        }
        mock_docker = AsyncMock()
        mock_docker.containers.list.return_value = [mock_container]
        mock_docker.__aenter__ = AsyncMock(return_value=mock_docker)
        mock_docker.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.transcoding_session.Docker", return_value=mock_docker):
            cleaned = await service.cleanup_stale_sessions()

        assert cleaned == 0

    @pytest.mark.asyncio
    async def test_cleanup_keeps_session_by_label(self, service):
        """Sessions with containers matched by label are kept."""
        data = TranscodingSessionCreate(
            session_id="label-sess",
            user_guid=uuid.uuid4(),
            user_name="User",
            content_type="movie",
            content_id=uuid.uuid4(),
            content_title="Movie",
            video_codec="h264",
            audio_codec="aac",
            container_id="different-id",
        )
        await service.create_session(data)

        # Age the session
        r = await service._get_redis()
        session_key = service._get_session_key("label-sess")
        session_data = json.loads(await r.get(session_key))
        session_data["last_accessed_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await r.set(session_key, json.dumps(session_data), ex=7200)

        # Container has session_id in labels
        mock_container = AsyncMock()
        mock_container.show.return_value = {
            "Id": "some-other-id",
            "Config": {"Labels": {"transcode.session_id": "label-sess"}},
        }
        mock_docker = AsyncMock()
        mock_docker.containers.list.return_value = [mock_container]
        mock_docker.__aenter__ = AsyncMock(return_value=mock_docker)
        mock_docker.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.transcoding_session.Docker", return_value=mock_docker):
            cleaned = await service.cleanup_stale_sessions()

        assert cleaned == 0

    @pytest.mark.asyncio
    async def test_cleanup_skips_inactive_sessions(self, service):
        """Inactive sessions are not cleaned up (already stopped)."""
        data = TranscodingSessionCreate(
            session_id="inactive-sess",
            user_guid=uuid.uuid4(),
            user_name="User",
            content_type="movie",
            content_id=uuid.uuid4(),
            content_title="Movie",
            video_codec="h264",
            audio_codec="aac",
        )
        await service.create_session(data)
        await service.mark_failed("inactive-sess")

        mock_docker = AsyncMock()
        mock_docker.containers.list.return_value = []
        mock_docker.__aenter__ = AsyncMock(return_value=mock_docker)
        mock_docker.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.transcoding_session.Docker", return_value=mock_docker):
            cleaned = await service.cleanup_stale_sessions()

        assert cleaned == 0


class TestGetSessionsResponse:
    """Test get_sessions_response (not in existing tests)."""

    @pytest_asyncio.fixture
    async def service(self):
        from pyrate.services.transcoding_session import TranscodingSessionService
        svc = TranscodingSessionService()
        svc._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        return svc

    @pytest.mark.asyncio
    async def test_get_sessions_response_with_cleanup(self, service):
        data = TranscodingSessionCreate(
            session_id="sess-1",
            user_guid=uuid.uuid4(),
            user_name="User",
            content_type="movie",
            content_id=uuid.uuid4(),
            content_title="Movie",
            video_codec="h264",
            audio_codec="aac",
        )
        await service.create_session(data)

        # Mock cleanup to return 0
        with patch.object(service, "cleanup_stale_sessions", new_callable=AsyncMock, return_value=0):
            response = await service.get_sessions_response()

        assert response.total == 1
        assert response.active_count == 1
        assert len(response.sessions) == 1

    @pytest.mark.asyncio
    async def test_get_sessions_response_active_only(self, service):
        data1 = TranscodingSessionCreate(
            session_id="sess-1",
            user_guid=uuid.uuid4(),
            user_name="User",
            content_type="movie",
            content_id=uuid.uuid4(),
            video_codec="h264",
            audio_codec="aac",
        )
        data2 = TranscodingSessionCreate(
            session_id="sess-2",
            user_guid=uuid.uuid4(),
            user_name="User",
            content_type="movie",
            content_id=uuid.uuid4(),
            video_codec="h264",
            audio_codec="aac",
        )
        await service.create_session(data1)
        await service.create_session(data2)
        await service.mark_failed("sess-2")

        with patch.object(service, "cleanup_stale_sessions", new_callable=AsyncMock, return_value=0):
            response = await service.get_sessions_response(active_only=True)

        assert response.total == 1
        assert response.active_count == 1

    @pytest.mark.asyncio
    async def test_get_sessions_response_cleanup_failure(self, service):
        """get_sessions_response handles cleanup failure gracefully."""
        data = TranscodingSessionCreate(
            session_id="sess-1",
            user_guid=uuid.uuid4(),
            user_name="User",
            content_type="movie",
            content_id=uuid.uuid4(),
            video_codec="h264",
            audio_codec="aac",
        )
        await service.create_session(data)

        with patch.object(service, "cleanup_stale_sessions", new_callable=AsyncMock, side_effect=Exception("fail")):
            response = await service.get_sessions_response()

        assert response.total == 1

    @pytest.mark.asyncio
    async def test_get_sessions_response_no_auto_cleanup(self, service):
        """get_sessions_response skips cleanup when auto_cleanup=False."""
        data = TranscodingSessionCreate(
            session_id="sess-1",
            user_guid=uuid.uuid4(),
            user_name="User",
            content_type="movie",
            content_id=uuid.uuid4(),
            video_codec="h264",
            audio_codec="aac",
        )
        await service.create_session(data)

        with patch.object(service, "cleanup_stale_sessions", new_callable=AsyncMock) as mock_cleanup:
            response = await service.get_sessions_response(auto_cleanup=False)

        mock_cleanup.assert_not_awaited()
        assert response.total == 1


# ===========================================================================
# 4. websocket.py – gaps not covered by existing tests
# ===========================================================================

class TestWebSocketRemoteControl:
    """Test _handle_remote_control (missing from existing tests)."""

    @pytest.mark.asyncio
    async def test_remote_control_success(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws_sender = _make_ws()
            ws_target = _make_ws()

            conn_sender = await mgr.connect(ws_sender, user_id="u1", device_id="sender-dev")
            conn_target = await mgr.connect(ws_target, user_id="u1", device_id="target-dev")

            await mgr.handle_message(conn_sender, {
                "action": "remote_control",
                "target_device_id": "target-dev",
                "command": "play",
                "payload": {"media_guid": "movie-1"},
            })

            # Target should have received remote_control event
            target_calls = ws_target.send_json.call_args_list
            rc_found = any(
                c[0][0].get("event") == "remote_control"
                for c in target_calls
            )
            assert rc_found

            # Sender should have received ack
            sender_calls = ws_sender.send_json.call_args_list
            ack_found = any(
                c[0][0].get("event") == "remote_control_ack"
                for c in sender_calls
            )
            assert ack_found

            await mgr.disconnect(conn_sender)
            await mgr.disconnect(conn_target)

    @pytest.mark.asyncio
    async def test_remote_control_missing_target(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1", device_id="d1")

            await mgr.handle_message(conn, {
                "action": "remote_control",
                "command": "play",
            })

            calls = ws.send_json.call_args_list
            error_found = any(c[0][0].get("event") == "error" for c in calls)
            assert error_found

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_remote_control_missing_command(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1", device_id="d1")

            await mgr.handle_message(conn, {
                "action": "remote_control",
                "target_device_id": "d2",
            })

            calls = ws.send_json.call_args_list
            error_found = any(c[0][0].get("event") == "error" for c in calls)
            assert error_found

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_remote_control_invalid_command(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1", device_id="d1")

            await mgr.handle_message(conn, {
                "action": "remote_control",
                "target_device_id": "d2",
                "command": "invalid_cmd",
            })

            calls = ws.send_json.call_args_list
            error_found = any(c[0][0].get("event") == "error" for c in calls)
            assert error_found

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_remote_control_target_not_found(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1", device_id="d1")

            await mgr.handle_message(conn, {
                "action": "remote_control",
                "target_device_id": "nonexistent-device",
                "command": "pause",
            })

            calls = ws.send_json.call_args_list
            err_found = any(c[0][0].get("event") == "remote_control_error" for c in calls)
            assert err_found

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_remote_control_target_send_failure(self):
        """When target send fails, sender gets remote_control_error."""
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            from pyrate.services.websocket import WebSocketManager

            mgr = WebSocketManager()
            ws_sender = _make_ws()
            ws_target = _make_ws()

            conn_sender = await mgr.connect(ws_sender, user_id="u1", device_id="sender")
            conn_target = await mgr.connect(ws_target, user_id="u1", device_id="target")

            # Make target's websocket fail on send
            ws_target.send_json.side_effect = RuntimeError("connection closed")

            await mgr.handle_message(conn_sender, {
                "action": "remote_control",
                "target_device_id": "target",
                "command": "seek",
                "payload": {"position": 120},
            })

            sender_calls = ws_sender.send_json.call_args_list
            err_found = any(c[0][0].get("event") == "remote_control_error" for c in sender_calls)
            assert err_found

            await mgr.disconnect(conn_sender)
            await mgr.disconnect(conn_target)


class TestWebSocketWatchParty:
    """Test watch party sync/member update handlers (missing from existing tests)."""

    @pytest.mark.asyncio
    async def test_watch_party_sync(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_svc.publish = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.handle_message(conn, {
                "action": "party_sync",
                "party_id": "party-1",
                "current_time": 123.45,
                "is_playing": True,
                "playback_rate": 1.0,
            })

            mock_svc.publish.assert_awaited_once()
            call_kwargs = mock_svc.publish.call_args.kwargs
            assert call_kwargs["channel"] == "party:party-1"
            assert call_kwargs["event"] == "party_sync"
            assert call_kwargs["data"]["current_time"] == 123.45

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_watch_party_sync_missing_fields(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.handle_message(conn, {
                "action": "party_sync",
                "party_id": "party-1",
                # missing current_time and is_playing
            })

            calls = ws.send_json.call_args_list
            error_found = any(c[0][0].get("event") == "error" for c in calls)
            assert error_found

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_watch_party_member_update(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_svc.publish = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.handle_message(conn, {
                "action": "party_member_update",
                "party_id": "party-1",
                "last_position": 42.0,
                "is_connected": True,
            })

            mock_svc.publish.assert_awaited_once()
            call_kwargs = mock_svc.publish.call_args.kwargs
            assert call_kwargs["channel"] == "party:party-1"
            assert call_kwargs["event"] == "party_member_update"
            assert call_kwargs["data"]["last_position"] == 42.0

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_watch_party_member_update_missing_party_id(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.handle_message(conn, {
                "action": "party_member_update",
            })

            calls = ws.send_json.call_args_list
            error_found = any(c[0][0].get("event") == "error" for c in calls)
            assert error_found

            await mgr.disconnect(conn)


class TestWebSocketUnsubscribeMessage:
    """Test unsubscribe via handle_message (missing from existing tests)."""

    @pytest.mark.asyncio
    async def test_unsubscribe_via_message(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.handle_message(conn, {
                "action": "subscribe",
                "resource_type": "episode",
                "resource_id": "ep-1",
            })
            assert "episode:ep-1" in conn.subscriptions

            await mgr.handle_message(conn, {
                "action": "unsubscribe",
                "resource_type": "episode",
                "resource_id": "ep-1",
            })
            assert "episode:ep-1" not in conn.subscriptions

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_unsubscribe_missing_fields(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.handle_message(conn, {
                "action": "unsubscribe",
            })

            calls = ws.send_json.call_args_list
            error_found = any(c[0][0].get("event") == "error" for c in calls)
            assert error_found

            await mgr.disconnect(conn)


# ===========================================================================
# 5. redis_event.py – subscribe/unsubscribe/_start_subscriber/_subscriber_loop/stop
# ===========================================================================

from pyrate.services.websocket import WebSocketConnection, WebSocketManager


class TestRedisEventServiceSubscribe:
    def _make_mocks(self):
        """Create properly configured redis and pubsub mocks.

        r.pubsub() is a sync call, so mock_redis must be MagicMock.
        subscribe/unsubscribe/get_message/close are async, so use AsyncMock.
        get_message must yield control (sleep) so the subscriber loop can be
        cancelled cleanly — otherwise the tight loop starves asyncio.
        """
        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()

        async def _slow_get_message(**kwargs):
            await asyncio.sleep(0.05)
            return None

        mock_pubsub.get_message = _slow_get_message
        mock_pubsub.close = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.close = AsyncMock()

        return mock_redis, mock_pubsub

    @pytest.mark.asyncio
    async def test_subscribe_creates_pubsub_and_starts_loop(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        mock_redis, mock_pubsub = self._make_mocks()
        svc._redis = mock_redis

        handler = AsyncMock()

        await svc.subscribe("test:channel", handler)

        assert svc._running is True
        assert "pyrate:events:test:channel" in svc._handlers
        assert handler in svc._handlers["pyrate:events:test:channel"]
        mock_pubsub.subscribe.assert_awaited_once_with("pyrate:events:test:channel")

        # Clean up
        await svc.stop()

    @pytest.mark.asyncio
    async def test_subscribe_second_handler_same_channel(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        mock_redis, mock_pubsub = self._make_mocks()
        svc._redis = mock_redis

        handler1 = AsyncMock()
        handler2 = AsyncMock()

        await svc.subscribe("test:ch", handler1)
        await svc.subscribe("test:ch", handler2)

        # Only one Redis subscribe call per channel
        assert mock_pubsub.subscribe.await_count == 1
        assert len(svc._handlers["pyrate:events:test:ch"]) == 2

        await svc.stop()

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        mock_redis, mock_pubsub = self._make_mocks()
        svc._redis = mock_redis

        handler = AsyncMock()
        await svc.subscribe("test:ch", handler)
        await svc.unsubscribe("test:ch", handler)

        assert "pyrate:events:test:ch" not in svc._handlers
        mock_pubsub.unsubscribe.assert_awaited_once_with("pyrate:events:test:ch")

        await svc.stop()

    @pytest.mark.asyncio
    async def test_unsubscribe_keeps_other_handlers(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        mock_redis, mock_pubsub = self._make_mocks()
        svc._redis = mock_redis

        handler1 = AsyncMock()
        handler2 = AsyncMock()
        await svc.subscribe("test:ch", handler1)
        await svc.subscribe("test:ch", handler2)

        await svc.unsubscribe("test:ch", handler1)

        assert "pyrate:events:test:ch" in svc._handlers
        assert handler2 in svc._handlers["pyrate:events:test:ch"]
        # Should NOT unsubscribe from Redis since handler2 still listening
        mock_pubsub.unsubscribe.assert_not_awaited()

        await svc.stop()

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_handler(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        mock_redis, mock_pubsub = self._make_mocks()
        svc._redis = mock_redis

        handler1 = AsyncMock()
        handler2 = AsyncMock()
        await svc.subscribe("test:ch", handler1)

        # Unsubscribing a handler that was never subscribed should not raise
        await svc.unsubscribe("test:ch", handler2)

        assert handler1 in svc._handlers["pyrate:events:test:ch"]

        await svc.stop()


class TestRedisEventServiceSubscriberLoop:
    def _make_mocks(self):
        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.close = AsyncMock()

        return mock_redis, mock_pubsub

    @pytest.mark.asyncio
    async def test_subscriber_loop_dispatches_messages(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        mock_redis, mock_pubsub = self._make_mocks()
        svc._redis = mock_redis

        handler = AsyncMock()
        channel = "pyrate:events:test:ch"

        # Simulate message then None to break after one iteration
        call_count = 0

        async def fake_get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "type": "message",
                    "channel": channel,
                    "data": json.dumps({"event": "test", "data": {"x": 1}}),
                }
            # Stop the loop
            svc._running = False
            return None

        mock_pubsub.get_message = fake_get_message

        await svc.subscribe("test:ch", handler)

        # Let the loop run briefly
        await asyncio.sleep(0.2)

        handler.assert_awaited_once()
        call_data = handler.call_args[0][0]
        assert call_data["event"] == "test"
        assert call_data["data"] == {"x": 1}

        await svc.stop()

    @pytest.mark.asyncio
    async def test_subscriber_loop_handles_invalid_json(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        mock_redis, mock_pubsub = self._make_mocks()
        svc._redis = mock_redis

        handler = AsyncMock()
        channel = "pyrate:events:test:ch"

        call_count = 0

        async def fake_get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "type": "message",
                    "channel": channel,
                    "data": "not valid json{{{",
                }
            svc._running = False
            return None

        mock_pubsub.get_message = fake_get_message

        await svc.subscribe("test:ch", handler)
        await asyncio.sleep(0.2)

        # Handler should not have been called
        handler.assert_not_awaited()

        await svc.stop()

    @pytest.mark.asyncio
    async def test_subscriber_loop_skips_non_message_types(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        mock_redis, mock_pubsub = self._make_mocks()
        svc._redis = mock_redis

        handler = AsyncMock()

        call_count = 0

        async def fake_get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "subscribe", "channel": "ch", "data": "1"}
            svc._running = False
            return None

        mock_pubsub.get_message = fake_get_message

        await svc.subscribe("test:ch", handler)
        await asyncio.sleep(0.2)

        handler.assert_not_awaited()

        await svc.stop()

    @pytest.mark.asyncio
    async def test_subscriber_loop_handler_error_continues(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        mock_redis, mock_pubsub = self._make_mocks()
        svc._redis = mock_redis

        handler = AsyncMock(side_effect=ValueError("handler error"))
        channel = "pyrate:events:test:ch"

        call_count = 0

        async def fake_get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "type": "message",
                    "channel": channel,
                    "data": json.dumps({"event": "test", "data": {}}),
                }
            svc._running = False
            return None

        mock_pubsub.get_message = fake_get_message

        await svc.subscribe("test:ch", handler)
        await asyncio.sleep(0.2)

        # Should have called handler despite error
        handler.assert_awaited_once()

        await svc.stop()


class TestRedisEventServiceStop:
    @pytest.mark.asyncio
    async def test_stop_cleans_up(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()
        mock_pubsub.get_message = AsyncMock(return_value=None)

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.close = AsyncMock()
        svc._redis = mock_redis

        handler = AsyncMock()
        await svc.subscribe("ch", handler)

        await svc.stop()

        assert svc._running is False
        assert svc._subscriber_task is None
        assert svc._pubsub is None
        assert svc._redis is None
        mock_pubsub.close.assert_awaited_once()
        mock_redis.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        await svc.stop()  # should not raise
        assert svc._running is False


class TestRedisEventServicePublish:
    @pytest.mark.asyncio
    async def test_publish(self):
        from pyrate.services.redis_event import RedisEventService

        svc = RedisEventService()
        mock_redis = AsyncMock()
        mock_redis.publish.return_value = 2
        svc._redis = mock_redis

        count = await svc.publish("test:ch", "my_event", {"key": "val"})

        assert count == 2
        mock_redis.publish.assert_awaited_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "pyrate:events:test:ch"
        payload = json.loads(call_args[0][1])
        assert payload["event"] == "my_event"
        assert payload["data"] == {"key": "val"}

"""Tests for playback services: computing, play/transcode, codec negotiation, stream selection."""

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from streamarr.schemas.search import SearchRequest, SearchType
from streamarr.services.search import SearchService, IMPORT_LOCK_PREFIX, IMPORT_LOCK_TTL_SECONDS


def _make_file(**overrides):
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

class TestAcquireImportLock:
    """Test _acquire_import_lock."""

    @pytest.mark.asyncio
    async def test_lock_acquired(self):
        db = MagicMock()
        svc = SearchService(db)
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        svc._redis = mock_redis
        result = await svc._acquire_import_lock("MOVIES", 12345)
        assert result is True
        mock_redis.set.assert_called_once_with(
            f"{IMPORT_LOCK_PREFIX}MOVIES:12345", "1", nx=True, ex=IMPORT_LOCK_TTL_SECONDS
        )

    @pytest.mark.asyncio
    async def test_lock_already_exists(self):
        db = MagicMock()
        svc = SearchService(db)
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)
        svc._redis = mock_redis
        result = await svc._acquire_import_lock("MOVIES", 12345)
        assert result is False


# ============================================================================
# computing.py — detect_hardware_acceleration
# ============================================================================


class TestDetectHardwareAcceleration:
    """Test detect_hardware_acceleration."""

    def test_hw_accel_disabled(self):
        from streamarr.services.computing import detect_hardware_acceleration
        with patch.dict(os.environ, {"ENABLE_HARDWARE_ACCEL": "false"}):
            result = detect_hardware_acceleration()
            assert result["type"] is None
            assert result["devices"] == []
            assert result["encoder_suffix"] == ""

    def test_hw_accel_with_dri_devices(self):
        from streamarr.services.computing import detect_hardware_acceleration
        with (
            patch.dict(os.environ, {"ENABLE_HARDWARE_ACCEL": "true"}, clear=False),
            patch("os.path.exists") as mock_exists,
        ):
            mock_exists.side_effect = lambda p: p in ("/dev/dri", "/dev/dri/renderD128", "/dev/dri/card0")
            result = detect_hardware_acceleration()
            assert result["type"] == "qsv"
            assert "/dev/dri/renderD128" in result["devices"]
            assert "/dev/dri/card0" in result["devices"]
            assert result["encoder_suffix"] == "_qsv"

    def test_hw_accel_no_devices(self):
        from streamarr.services.computing import detect_hardware_acceleration
        with (
            patch.dict(os.environ, {"ENABLE_HARDWARE_ACCEL": "true"}, clear=False),
            patch("os.path.exists", return_value=False),
        ):
            result = detect_hardware_acceleration()
            assert result["type"] is None
            assert result["devices"] == []


# ============================================================================
# computing.py — ComputingService extras
# ============================================================================


class TestComputingServiceExtras:
    """Test ComputingService methods not covered elsewhere."""

    @pytest.mark.asyncio
    async def test_close_with_error(self):
        from streamarr.services.computing import ComputingService
        db = MagicMock()
        svc = ComputingService(db)
        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock(side_effect=Exception("close error"))
        svc._provider = mock_provider
        svc._provider_domain = "test"
        await svc.close()
        assert svc._provider is None
        assert svc._provider_domain is None

    @pytest.mark.asyncio
    async def test_terminate_task_success(self):
        from streamarr.services.computing import ComputingService
        db = MagicMock()
        svc = ComputingService(db)
        mock_provider = AsyncMock()
        svc._provider = mock_provider
        result = await svc.terminate_task("task-1")
        assert result is True
        mock_provider.stop_task.assert_called_once_with("task-1", force=True)
        mock_provider.delete_task.assert_called_once_with("task-1")

    @pytest.mark.asyncio
    async def test_terminate_task_failure(self):
        from streamarr.services.computing import ComputingService
        db = MagicMock()
        svc = ComputingService(db)
        mock_provider = AsyncMock()
        mock_provider.stop_task = AsyncMock(side_effect=Exception("fail"))
        svc._provider = mock_provider
        result = await svc.terminate_task("task-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_tasks_by_label(self):
        from streamarr.services.computing import ComputingService
        db = MagicMock()
        svc = ComputingService(db)
        mock_provider = AsyncMock()
        mock_provider.list_tasks = AsyncMock(return_value=[{"id": "t1", "labels": {"key": "val"}}])
        svc._provider = mock_provider
        result = await svc.get_tasks_by_label("key", "val")
        mock_provider.list_tasks.assert_called_once_with(labels={"key": "val"})
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_context_manager(self):
        from streamarr.services.computing import ComputingService
        db = MagicMock()
        async with ComputingService(db) as svc:
            assert svc is not None

    def test_build_ffmpeg_command_audio_only(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=2,
            subtitle_stream_index=None,
            burn_subtitles=False,
            audio_only=True,
        )
        assert "-vn" in cmd
        assert "0:a:2" in cmd
        # Should not contain video codec
        assert "-c:v" not in cmd

    def test_build_ffmpeg_command_audio_only_default_stream(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
            audio_only=True,
        )
        assert "-vn" in cmd
        assert "0:a:0" in cmd

    def test_build_ffmpeg_command_vp9(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="vp9",
            audio_codec="aac",
            video_bitrate="2000k",
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "libvpx-vp9" in cmd
        assert "-b:v" in cmd

    def test_build_ffmpeg_command_vp9_no_bitrate(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="vp9",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "-crf" in cmd
        assert "31" in cmd

    def test_build_ffmpeg_command_av1(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="av1",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "libsvtav1" in cmd

    def test_build_ffmpeg_command_av1_with_bitrate(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="av1",
            audio_codec="aac",
            video_bitrate="3000k",
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "-b:v" in cmd
        assert "3000k" in cmd

    def test_build_ffmpeg_command_mp3_audio(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="mp3",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "libmp3lame" in cmd

    def test_build_ffmpeg_command_copy_audio(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="copy",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )
        ca_idx = cmd.index("-c:a")
        assert cmd[ca_idx + 1] == "copy"

    def test_build_ffmpeg_command_thread_count(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
            thread_count=4,
        )
        assert "-threads" in cmd
        assert "4" in cmd

    def test_build_ffmpeg_command_h265_no_bitrate(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h265",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "-crf" in cmd
        assert "28" in cmd

    def test_build_ffmpeg_command_hevc_alias(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="hevc",
            audio_codec="aac",
            video_bitrate="4000k",
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "libx265" in cmd

    def test_build_ffmpeg_command_h264_no_bitrate(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "-crf" in cmd
        assert "23" in cmd

    def test_build_ffmpeg_command_negative_subtitle_index(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=-1,
            burn_subtitles=True,
        )
        # Negative subtitle index should be ignored, no subtitles filter
        assert "subtitles" not in " ".join(cmd)

    def test_build_ffmpeg_command_qsv_with_resolution(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        hw_accel = {"type": "qsv", "devices": ["/dev/dri/renderD128"], "encoder_suffix": "_qsv"}
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution="1920x1080",
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
            hw_accel=hw_accel,
        )
        assert "h264_qsv" in cmd
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        vf_val = cmd[vf_idx + 1]
        assert "scale=1920:1080" in vf_val
        assert "hwupload" in vf_val

    def test_build_ffmpeg_command_qsv_with_subtitles(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        hw_accel = {"type": "qsv", "devices": ["/dev/dri/renderD128"], "encoder_suffix": "_qsv"}
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=1,
            burn_subtitles=True,
            hw_accel=hw_accel,
        )
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        vf_val = cmd[vf_idx + 1]
        assert "subtitles" in vf_val
        assert "hwupload" in vf_val

    def test_build_ffmpeg_command_vaapi(self):
        from streamarr.services.computing import ComputingService
        svc = ComputingService.__new__(ComputingService)
        hw_accel = {"type": "vaapi", "devices": ["/dev/dri/renderD128"], "encoder_suffix": ""}
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
            hw_accel=hw_accel,
        )
        assert "-hwaccel" in cmd
        assert "vaapi" in cmd


# ============================================================================
# play.py — extract_source_info edge cases
# ============================================================================


class TestExtractSourceInfoEdgeCases:
    """Test extract_source_info uncovered paths."""

    def test_legacy_flat_dict(self):
        from streamarr.services.play import extract_source_info
        probe_data = {
            "video_codec": "h264",
            "audio_codec": "AAC",
            "width": 1920,
            "height": 1080,
        }
        info = extract_source_info(probe_data, file=None)
        assert info["video_codec"] == "h264"
        assert info["audio_codec"] == "aac"
        assert info["width"] == 1920

    def test_legacy_flat_dict_with_hdr(self):
        from streamarr.services.play import extract_source_info
        probe_data = {
            "video_codec": "hevc",
            "hdr_format": "HDR10",
        }
        info = extract_source_info(probe_data, file=None)
        assert info["bit_depth"] == 10

    def test_raw_streams_array(self):
        from streamarr.services.play import extract_source_info
        probe_data = {
            "streams": [
                {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le", "width": 3840, "height": 2160},
                {"codec_type": "audio", "codec_name": "eac3"},
            ]
        }
        info = extract_source_info(probe_data, file=None)
        assert info["video_codec"] == "hevc"
        assert info["audio_codec"] == "eac3"
        assert info["bit_depth"] == 10
        assert info["width"] == 3840

    def test_raw_streams_12bit(self):
        from streamarr.services.play import extract_source_info
        probe_data = {
            "streams": [
                {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p12le"},
            ]
        }
        info = extract_source_info(probe_data, file=None)
        assert info["bit_depth"] == 12

    def test_no_probe_data_with_file(self):
        from streamarr.services.play import extract_source_info
        f = _make_file(codec="hevc")
        info = extract_source_info(None, file=f)
        assert info["video_codec"] == "hevc"

    def test_no_probe_data_no_file(self):
        from streamarr.services.play import extract_source_info
        info = extract_source_info(None, file=None)
        assert info["video_codec"] is None

    def test_structured_format_audio_only(self):
        from streamarr.services.play import extract_source_info
        probe_data = {
            "video_streams": [],
            "audio_streams": [{"codec_name": "flac"}],
        }
        info = extract_source_info(probe_data, file=None)
        assert info["video_codec"] is None
        assert info["audio_codec"] == "flac"

    def test_structured_format_with_p010_pix_fmt(self):
        from streamarr.services.play import extract_source_info
        probe_data = {
            "video_streams": [{"codec_name": "hevc", "pix_fmt": "p010le", "width": 3840, "height": 2160}],
            "audio_streams": [],
        }
        info = extract_source_info(probe_data, file=None)
        assert info["bit_depth"] == 10

    def test_fallback_to_file_codec(self):
        from streamarr.services.play import extract_source_info
        # Empty streams arrays -> falls back to file.codec
        probe_data = {
            "video_streams": [],
            "audio_streams": [],
            "streams": [],
        }
        f = _make_file(codec="h264", width=1920, height=1080)
        info = extract_source_info(probe_data, file=f)
        assert info["video_codec"] == "h264"


# ============================================================================
# play.py — build_stream_info
# ============================================================================


class TestBuildStreamInfo:
    """Test build_stream_info uncovered paths."""

    def test_audio_only_transcoding_reason(self):
        from streamarr.services.play import build_stream_info
        f = _make_file()
        probe = {"video_streams": [{"codec_name": "h264", "width": 1920, "height": 1080, "pix_fmt": "yuv420p"}], "audio_streams": [{"codec_name": "dts"}]}
        with patch("streamarr.services.computing.detect_hardware_acceleration", return_value={"type": None}):
            result = build_stream_info(
                file=f, probe_data=probe,
                effective_video_codec="copy",
                effective_audio_codec="aac",
                effective_resolution=None,
                video_codec="h264", audio_codec="aac",
                supported_video_codecs="h264,h265",
                supported_audio_codecs="aac",
                client_max_resolution=None,
            )
        # When video is "copy", no video reason but audio dts->aac should be a reason
        assert any("dts" in r for r in result["transcoding_reasons"])

    def test_no_source_audio_codec_reason(self):
        from streamarr.services.play import build_stream_info
        f = _make_file()
        probe = {"video_streams": [{"codec_name": "h264", "width": 1920, "height": 1080, "pix_fmt": "yuv420p"}], "audio_streams": []}
        with patch("streamarr.services.computing.detect_hardware_acceleration", return_value={"type": None}):
            result = build_stream_info(
                file=f, probe_data=probe,
                effective_video_codec="copy",
                effective_audio_codec="aac",
                effective_resolution=None,
                video_codec="h264", audio_codec="aac",
                supported_video_codecs="h264",
                supported_audio_codecs="aac",
                client_max_resolution=None,
            )
        assert any("Audio transcoding" in r for r in result["transcoding_reasons"])

    def test_video_transcode_fallback_reason(self):
        from streamarr.services.play import build_stream_info
        f = _make_file()
        probe = {"video_streams": [{"codec_name": "h264", "width": 1920, "height": 1080, "pix_fmt": "yuv420p"}], "audio_streams": [{"codec_name": "aac"}]}
        with patch("streamarr.services.computing.detect_hardware_acceleration", return_value={"type": None}):
            result = build_stream_info(
                file=f, probe_data=probe,
                effective_video_codec="h264",
                effective_audio_codec="copy",
                effective_resolution=None,
                video_codec="h264", audio_codec="aac",
                supported_video_codecs="h264",
                supported_audio_codecs="aac",
                client_max_resolution=None,
            )
        # Client supports h264, source is h264, so fallback reason should appear
        assert any("h264" in r for r in result["transcoding_reasons"])

    def test_hw_accel_detection_exception(self):
        from streamarr.services.play import build_stream_info
        f = _make_file()
        probe = {"video_streams": [{"codec_name": "h264", "width": 1920, "height": 1080, "pix_fmt": "yuv420p"}], "audio_streams": [{"codec_name": "aac"}]}
        with patch("streamarr.services.computing.detect_hardware_acceleration", side_effect=Exception("err")):
            result = build_stream_info(
                file=f, probe_data=probe,
                effective_video_codec="copy",
                effective_audio_codec="copy",
                effective_resolution=None,
                video_codec="h264", audio_codec="aac",
                supported_video_codecs="h264",
                supported_audio_codecs="aac",
                client_max_resolution=None,
            )
        assert result["transcoding"]["hw_accel"] is None


# ============================================================================
# play.py — _match_language
# ============================================================================


class TestMatchLanguage:
    """Test _match_language."""

    def test_direct_match(self):
        from streamarr.services.play import _match_language
        assert _match_language("en", "en") is True

    def test_prefix_match(self):
        from streamarr.services.play import _match_language
        assert _match_language("eng", "en") is True

    def test_iso_map_match(self):
        from streamarr.services.play import _match_language
        assert _match_language("ger", "de") is True
        assert _match_language("deu", "de") is True
        assert _match_language("jpn", "ja") is True

    def test_reverse_iso_map(self):
        from streamarr.services.play import _match_language
        assert _match_language("de", "ger") is True

    def test_no_match(self):
        from streamarr.services.play import _match_language
        assert _match_language("spa", "de") is False

    def test_empty_strings(self):
        from streamarr.services.play import _match_language
        assert _match_language("", "en") is False
        assert _match_language("en", "") is False
        assert _match_language(None, "en") is False


# ============================================================================
# play.py — select_streams_for_user
# ============================================================================


class TestSelectStreamsForUser:
    """Test select_streams_for_user."""

    def test_no_probe_data(self):
        from streamarr.services.play import select_streams_for_user
        result = select_streams_for_user(None)
        assert result["audio_stream"] == 0
        assert result["subtitle_stream"] is None

    def test_preferred_audio_found(self):
        from streamarr.services.play import select_streams_for_user
        probe = {
            "audio_streams": [
                {"language": "eng", "default": True},
                {"language": "deu", "default": False},
            ],
            "subtitle_streams": [],
        }
        result = select_streams_for_user(probe, preferred_audio_languages=["de"])
        assert result["audio_stream"] == 1

    def test_preferred_audio_not_found_uses_default(self):
        from streamarr.services.play import select_streams_for_user
        probe = {
            "audio_streams": [
                {"language": "eng", "default": False},
                {"language": "fre", "default": True},
            ],
            "subtitle_streams": [],
        }
        result = select_streams_for_user(probe, preferred_audio_languages=["ja"])
        assert result["audio_stream"] == 1  # default stream

    def test_subtitle_selection(self):
        from streamarr.services.play import select_streams_for_user
        probe = {
            "audio_streams": [{"language": "eng"}],
            "subtitle_streams": [
                {"language": "eng", "forced": False},
                {"language": "deu", "forced": False},
            ],
        }
        result = select_streams_for_user(probe, preferred_subtitle_language="de")
        assert result["subtitle_stream"] == 1

    def test_subtitle_forced_fallback(self):
        from streamarr.services.play import select_streams_for_user
        probe = {
            "audio_streams": [{"language": "eng"}],
            "subtitle_streams": [
                {"language": "deu", "forced": True},
            ],
        }
        result = select_streams_for_user(probe, preferred_subtitle_language="de")
        # forced subtitle selected as fallback
        assert result["subtitle_stream"] == 0

    def test_no_subtitle_preference(self):
        from streamarr.services.play import select_streams_for_user
        probe = {
            "audio_streams": [{"language": "eng"}],
            "subtitle_streams": [
                {"language": "deu", "forced": False},
            ],
        }
        result = select_streams_for_user(probe, preferred_subtitle_language=None)
        assert result["subtitle_stream"] is None


# ============================================================================
# play.py — negotiate_codecs edge cases
# ============================================================================


class TestNegotiateCodecsExtraCases:
    """Test negotiate_codecs extra uncovered paths."""

    def test_audio_only_file(self):
        from streamarr.services.play import negotiate_codecs
        source_info = {"video_codec": None, "audio_codec": "flac"}
        probe = {"audio_streams": [{"codec_name": "flac"}]}
        f = _make_file(codec=None, width=0, height=0)
        result = negotiate_codecs(
            source_info=source_info, probe_data=probe, file=f,
            supported_video_codecs="h264", supported_audio_codecs="aac,flac",
            client_max_resolution=None,
        )
        assert result.video_codec is None
        assert result.resolution is None
        assert result.audio_codec == "flac"

    def test_audio_only_no_supported_audio(self):
        from streamarr.services.play import negotiate_codecs
        source_info = {"video_codec": None, "audio_codec": "opus"}
        f = _make_file(codec=None, width=0, height=0)
        result = negotiate_codecs(
            source_info=source_info, probe_data=None, file=f,
            supported_video_codecs=None, supported_audio_codecs=None,
            client_max_resolution=None,
        )
        assert result.video_codec is None

    def test_resolution_limit_not_copy(self):
        from streamarr.services.play import negotiate_codecs
        source_info = {"video_codec": "h264", "audio_codec": "aac", "height": 720}
        f = _make_file()
        result = negotiate_codecs(
            source_info=source_info, probe_data={"audio_streams": []}, file=f,
            supported_video_codecs=None, supported_audio_codecs=None,
            client_max_resolution="720p",
        )
        assert result.resolution == "1280x720"

    def test_source_needs_resolution_downscale(self):
        from streamarr.services.play import negotiate_codecs
        source_info = {"video_codec": "h264", "audio_codec": "aac", "height": 2160}
        f = _make_file(height=2160)
        result = negotiate_codecs(
            source_info=source_info, probe_data={"audio_streams": []}, file=f,
            supported_video_codecs="h264", supported_audio_codecs="aac",
            client_max_resolution="1080p",
        )
        assert result.video_codec == "h264"  # can't copy because resolution change
        assert result.resolution == "1920x1080"

    def test_codec_priority_fallback(self):
        from streamarr.services.play import negotiate_codecs
        source_info = {"video_codec": "mpeg2", "audio_codec": "aac", "height": 1080}
        f = _make_file()
        result = negotiate_codecs(
            source_info=source_info, probe_data={"audio_streams": []}, file=f,
            supported_video_codecs="vp9", supported_audio_codecs="aac",
            client_max_resolution=None,
        )
        assert result.video_codec == "vp9"

    def test_audio_copy_for_native_codec(self):
        from streamarr.services.play import negotiate_codecs
        source_info = {"video_codec": "h264", "audio_codec": "aac", "height": 1080}
        f = _make_file()
        result = negotiate_codecs(
            source_info=source_info, probe_data={"audio_streams": [{"codec_name": "aac"}]}, file=f,
            supported_video_codecs="h264", supported_audio_codecs="aac",
            client_max_resolution=None,
        )
        assert result.audio_codec == "copy"

    def test_audio_transcode_surround(self):
        from streamarr.services.play import negotiate_codecs
        source_info = {"video_codec": "h264", "audio_codec": "dts", "height": 1080}
        f = _make_file()
        result = negotiate_codecs(
            source_info=source_info, probe_data={"audio_streams": [{"codec_name": "dts"}]}, file=f,
            supported_video_codecs="h264", supported_audio_codecs="aac",
            client_max_resolution=None,
        )
        assert result.audio_codec == "aac"


# ============================================================================
# download.py — DownloadService edge cases
# ============================================================================


class TestDownloadServiceHelpers:
    """Test DownloadService helper methods."""

    def test_is_valid_video_file_sample(self, tmp_path):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        sample = tmp_path / "Sample.mkv"
        sample.touch()
        assert svc.is_valid_video_file(sample) is False

    def test_is_valid_video_file_wrong_ext(self, tmp_path):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        f = tmp_path / "file.txt"
        f.touch()
        assert svc.is_valid_video_file(f) is False

    def test_is_valid_video_file_not_exists(self):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        assert svc.is_valid_video_file(Path("/nonexistent/file.mkv")) is False

    def test_is_valid_video_file_valid(self, tmp_path):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        f = tmp_path / "movie.mkv"
        f.touch()
        assert svc.is_valid_video_file(f) is True

    def test_is_valid_audio_file(self, tmp_path):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        f = tmp_path / "song.mp3"
        f.touch()
        assert svc.is_valid_audio_file(f) is True

    def test_is_valid_audio_file_not_audio(self, tmp_path):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        f = tmp_path / "file.mkv"
        f.touch()
        assert svc.is_valid_audio_file(f) is False

    def test_is_valid_media_file_music(self, tmp_path):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        f = tmp_path / "song.mp3"
        f.touch()
        with patch("streamarr.services.download.get_library_type_for_media_item_type", return_value="MUSIC"):
            assert svc.is_valid_media_file(f, "SONGS") is True

    def test_is_valid_media_file_video(self, tmp_path):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        f = tmp_path / "movie.mkv"
        f.touch()
        with patch("streamarr.services.download.get_library_type_for_media_item_type", return_value="MOVIES"):
            assert svc.is_valid_media_file(f, "MOVIES") is True

    @pytest.mark.asyncio
    async def test_extract_external_id_deluge(self):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        downloader = MagicMock()
        downloader.type = "Deluge"
        result = await svc.extract_external_id_from_response(downloader, {"torrent_hash": "abc123"})
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_extract_external_id_deluge_missing(self):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        downloader = MagicMock()
        downloader.type = "Deluge"
        result = await svc.extract_external_id_from_response(downloader, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_external_id_spotdl(self):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        downloader = MagicMock()
        downloader.type = "SpotDL"
        result = await svc.extract_external_id_from_response(downloader, {"job_id": "job123"})
        assert result == "job123"

    @pytest.mark.asyncio
    async def test_extract_external_id_spotdl_missing(self):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        downloader = MagicMock()
        downloader.type = "SpotDL"
        result = await svc.extract_external_id_from_response(downloader, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_external_id_sabnzbd(self):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        downloader = MagicMock()
        downloader.type = "SABnzbd"
        result = await svc.extract_external_id_from_response(downloader, {"nzo_ids": ["nzo_abc"]})
        assert result == "nzo_abc"

    @pytest.mark.asyncio
    async def test_extract_external_id_sabnzbd_empty(self):
        from streamarr.services.download import DownloadService
        db = MagicMock()
        svc = DownloadService(db)
        downloader = MagicMock()
        downloader.type = "SABnzbd"
        result = await svc.extract_external_id_from_response(downloader, {"nzo_ids": []})
        assert result is None


# ============================================================================
# media.py — MediaService extra coverage
# ============================================================================


class TestMediaServiceStaticHelpers:
    """Test MediaService static helpers."""

    def test_is_valid_video_file_valid(self, tmp_path):
        from streamarr.services.media import MediaService
        f = tmp_path / "movie.mp4"
        f.touch()
        assert MediaService.is_valid_video_file(f) is True

    def test_is_valid_video_file_sample(self, tmp_path):
        from streamarr.services.media import MediaService
        f = tmp_path / "sample.mkv"
        f.touch()
        assert MediaService.is_valid_video_file(f) is False

    def test_is_valid_video_file_wrong_ext(self, tmp_path):
        from streamarr.services.media import MediaService
        f = tmp_path / "readme.txt"
        f.touch()
        assert MediaService.is_valid_video_file(f) is False

    def test_nav_response(self):
        from streamarr.services.media import MediaService
        item = MagicMock()
        item.guid = uuid.uuid4()
        item.title = "Test"
        item.sequence_number = 3
        result = MediaService._nav_response(item, parent_seq=2)
        assert result["guid"] == str(item.guid)
        assert result["title"] == "Test"
        assert result["sequence_number"] == 3
        assert result["season_number"] == 2


class TestMediaServiceCleanup:
    """Test cleanup helper methods."""

    def test_cleanup_empty_dirs(self, tmp_path):
        from streamarr.services.media import MediaService
        db = MagicMock()
        svc = MediaService(db)
        # Create nested empty dirs
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        svc._cleanup_empty_dirs(nested, stop_at=str(tmp_path))
        # Dirs should be cleaned up
        assert not (tmp_path / "a" / "b" / "c").exists()

    def test_cleanup_empty_dirs_not_empty(self, tmp_path):
        from streamarr.services.media import MediaService
        db = MagicMock()
        svc = MediaService(db)
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "file.txt").touch()
        svc._cleanup_empty_dirs(nested, stop_at=str(tmp_path))
        # Should not be deleted because it has a file
        assert nested.exists()


# ============================================================================
# library.py — LibraryService edge cases
# ============================================================================


class TestLibraryServiceGetPlugin:
    """Test LibraryService.get_plugin."""

    def test_get_plugin_not_found(self):
        from streamarr.services.library import LibraryService
        db = MagicMock()
        with patch("streamarr.services.library.get_registered_plugins", return_value={}):
            svc = LibraryService(db)
            assert svc.get_plugin("NONEXISTENT") is None

    def test_get_plugin_found(self):
        from streamarr.services.library import LibraryService
        db = MagicMock()
        mock_cls = MagicMock()
        with patch("streamarr.services.library.get_registered_plugins", return_value={"MOVIES": mock_cls}):
            svc = LibraryService(db)
            result = svc.get_plugin("MOVIES")
            mock_cls.assert_called_once_with()

    def test_get_plugin_with_config(self):
        from streamarr.services.library import LibraryService
        db = MagicMock()
        mock_cls = MagicMock()
        with patch("streamarr.services.library.get_registered_plugins", return_value={"MOVIES": mock_cls}):
            svc = LibraryService(db)
            result = svc.get_plugin("MOVIES", config={"key": "val"})
            mock_cls.assert_called_once_with()


# ============================================================================
# SearchService — enrich_with_library_status
# ============================================================================


class TestEnrichWithLibraryStatus:
    """Test enrich_with_library_status (uses DB mock)."""

    @pytest.mark.asyncio
    async def test_enriches_movie_hit(self):
        db = AsyncMock()
        mock_result = MagicMock()
        test_guid = uuid.uuid4()
        mock_result.all.return_value = [("tmdb", "12345", test_guid)]
        db.execute = AsyncMock(return_value=mock_result)

        svc = SearchService(db)
        hits = [{"type": SearchType.MOVIES, "tmdb_id": 12345, "in_library": False}]
        result = await svc.enrich_with_library_status(hits)
        assert result[0]["in_library"] is True
        assert result[0]["id"] == str(test_guid)

    @pytest.mark.asyncio
    async def test_no_external_id_skipped(self):
        db = AsyncMock()
        svc = SearchService(db)
        hits = [{"type": SearchType.MOVIES, "tmdb_id": None, "in_library": False}]
        result = await svc.enrich_with_library_status(hits)
        assert result[0]["in_library"] is False

    @pytest.mark.asyncio
    async def test_game_hit(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        svc = SearchService(db)
        hits = [{"type": SearchType.GAMES, "igdb_id": 999, "in_library": False}]
        result = await svc.enrich_with_library_status(hits)
        assert result[0]["in_library"] is False

    @pytest.mark.asyncio
    async def test_music_artist_hit(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        svc = SearchService(db)
        hits = [{"type": SearchType.MUSIC, "spotify_id": "s1", "music_type": "artist", "in_library": False}]
        result = await svc.enrich_with_library_status(hits)
        assert result[0]["in_library"] is False

    @pytest.mark.asyncio
    async def test_music_track_hit(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        svc = SearchService(db)
        hits = [{"type": SearchType.MUSIC, "spotify_id": "s1", "music_type": "track", "in_library": False}]
        result = await svc.enrich_with_library_status(hits)
        assert result[0]["in_library"] is False

    @pytest.mark.asyncio
    async def test_db_exception_handled(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB error"))
        svc = SearchService(db)
        hits = [{"type": SearchType.MOVIES, "tmdb_id": 123, "in_library": False}]
        result = await svc.enrich_with_library_status(hits)
        # Should not raise, just skip
        assert result[0]["in_library"] is False


# ============================================================================
# SearchService — _queue_imports
# ============================================================================


class TestQueueImports:
    """Test _queue_imports."""

    @pytest.mark.asyncio
    async def test_import_error_handled_gracefully(self):
        """When worker imports fail, should log and not crash."""
        db = AsyncMock()
        svc = SearchService(db)
        svc._active_library_types = {"MOVIES"}
        svc._redis = AsyncMock()
        svc._redis.set = AsyncMock(return_value=True)

        with patch("streamarr.services.search.select") as mock_select:
            # Mock DB to say item doesn't exist
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            db.execute = AsyncMock(return_value=mock_result)

            # The import will fail because worker module doesn't exist in test
            hits = [{"type": SearchType.MOVIES, "tmdb_id": 999}]
            # Should not raise
            await svc._queue_imports(hits, SearchType.MOVIES)

    @pytest.mark.asyncio
    async def test_skip_no_external_id(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._active_library_types = {"MOVIES"}

        hits = [{"type": SearchType.MOVIES, "tmdb_id": None}]
        await svc._queue_imports(hits, SearchType.MOVIES)
        # Nothing should happen, no error

    @pytest.mark.asyncio
    async def test_skip_inactive_library_type(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._active_library_types = {"SHOWS"}  # No MOVIES

        hits = [{"type": SearchType.MOVIES, "tmdb_id": 123}]
        await svc._queue_imports(hits, SearchType.MOVIES)
        # Should skip without error

    @pytest.mark.asyncio
    async def test_queue_game_import(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._active_library_types = {"GAMES"}
        svc._redis = AsyncMock()
        svc._redis.set = AsyncMock(return_value=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        hits = [{"type": SearchType.GAMES, "igdb_id": 555}]
        # Should not raise even if worker import fails
        await svc._queue_imports(hits, SearchType.GAMES)

    @pytest.mark.asyncio
    async def test_queue_music_artist_import(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._active_library_types = {"MUSIC"}
        svc._redis = AsyncMock()
        svc._redis.set = AsyncMock(return_value=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        hits = [{"type": SearchType.MUSIC, "spotify_id": "art1", "music_type": "artist"}]
        await svc._queue_imports(hits, SearchType.MUSIC)

    @pytest.mark.asyncio
    async def test_queue_music_track_import(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._active_library_types = {"MUSIC"}
        svc._redis = AsyncMock()
        svc._redis.set = AsyncMock(return_value=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        hits = [{"type": SearchType.MUSIC, "spotify_id": "track1", "album_spotify_id": "album1", "music_type": "track"}]
        await svc._queue_imports(hits, SearchType.MUSIC)

    @pytest.mark.asyncio
    async def test_queue_music_album_import(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._active_library_types = {"MUSIC"}
        svc._redis = AsyncMock()
        svc._redis.set = AsyncMock(return_value=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        hits = [{"type": SearchType.MUSIC, "spotify_id": "al1", "music_type": "album"}]
        await svc._queue_imports(hits, SearchType.MUSIC)

    @pytest.mark.asyncio
    async def test_queue_show_import(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._active_library_types = {"SHOWS"}
        svc._redis = AsyncMock()
        svc._redis.set = AsyncMock(return_value=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        hits = [{"type": SearchType.SHOWS, "tmdb_id": 777}]
        await svc._queue_imports(hits, SearchType.SHOWS)

    @pytest.mark.asyncio
    async def test_queue_existing_item_skipped(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._active_library_types = {"MOVIES"}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = uuid.uuid4()  # Item exists
        db.execute = AsyncMock(return_value=mock_result)

        hits = [{"type": SearchType.MOVIES, "tmdb_id": 123}]
        await svc._queue_imports(hits, SearchType.MOVIES)

    @pytest.mark.asyncio
    async def test_queue_lock_not_acquired_skipped(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._active_library_types = {"MOVIES"}
        svc._redis = AsyncMock()
        svc._redis.set = AsyncMock(return_value=None)  # Lock already exists

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        hits = [{"type": SearchType.MOVIES, "tmdb_id": 456}]
        await svc._queue_imports(hits, SearchType.MOVIES)


# ============================================================================
# SearchService — get_or_import_item
# ============================================================================


class TestGetOrImportItem:
    """Test get_or_import_item."""

    @pytest.mark.asyncio
    async def test_no_external_id(self):
        db = AsyncMock()
        svc = SearchService(db)
        result = await svc.get_or_import_item(media_type_str="MOVIES")
        assert result is None

    @pytest.mark.asyncio
    async def test_already_exists_movie(self):
        db = AsyncMock()
        svc = SearchService(db)
        test_guid = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.first.return_value = (test_guid,)
        db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_or_import_item(tmdb_id=123, media_type_str="MOVIES")
        assert result["guid"] == str(test_guid)
        assert result["library_guid"] is None

    @pytest.mark.asyncio
    async def test_already_exists_show(self):
        db = AsyncMock()
        svc = SearchService(db)
        test_guid = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.first.return_value = (test_guid, None)
        db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_or_import_item(tmdb_id=456, media_type_str="SHOWS")
        assert result["guid"] == str(test_guid)
        assert result["library_guid"] is None

    @pytest.mark.asyncio
    async def test_already_exists_game(self):
        db = AsyncMock()
        svc = SearchService(db)
        test_guid = uuid.uuid4()
        test_lib = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.first.return_value = (test_guid, test_lib)
        db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_or_import_item(igdb_id=789, media_type_str="GAMES")
        assert result["guid"] == str(test_guid)

    @pytest.mark.asyncio
    async def test_already_exists_music(self):
        db = AsyncMock()
        svc = SearchService(db)
        test_guid = uuid.uuid4()
        test_lib = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.first.return_value = (test_guid, test_lib)
        db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_or_import_item(spotify_id="sp1", media_type_str="MUSIC")
        assert result["guid"] == str(test_guid)

    @pytest.mark.asyncio
    async def test_already_exists_artist(self):
        db = AsyncMock()
        svc = SearchService(db)
        test_guid = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.first.return_value = (test_guid, None)
        db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_or_import_item(spotify_id="art1", media_type_str="ARTISTS")
        assert result is not None

    @pytest.mark.asyncio
    async def test_already_exists_songs(self):
        db = AsyncMock()
        svc = SearchService(db)
        test_guid = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.first.return_value = (test_guid, None)
        db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_or_import_item(spotify_id="song1", media_type_str="SONGS")
        assert result is not None

    @pytest.mark.asyncio
    async def test_no_active_library(self):
        db = AsyncMock()
        svc = SearchService(db)
        # First call: item not found, second call: no library
        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(tmdb_id=999, media_type_str="MOVIES")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_game_no_igdb_client(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_igdb_credentials = AsyncMock(return_value=(None, None))

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(igdb_id=100, media_type_str="GAMES")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_game_no_details(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_igdb_credentials = AsyncMock(return_value=("id", "secret"))
        mock_igdb = AsyncMock()
        mock_igdb.get_game_details = AsyncMock(return_value=None)
        svc._igdb = mock_igdb

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(igdb_id=100, media_type_str="GAMES")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_album_no_spotify_client(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_spotify_credentials = AsyncMock(return_value=(None, None))

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(spotify_id="sp1", media_type_str="MUSIC")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_album_no_details(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_spotify = AsyncMock()
        mock_spotify.get_album_details = AsyncMock(return_value=None)
        svc._spotify = mock_spotify

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(spotify_id="sp1", media_type_str="MUSIC")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_artist_no_spotify_client(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_spotify_credentials = AsyncMock(return_value=(None, None))

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(spotify_id="art1", media_type_str="ARTISTS")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_artist_no_details(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_spotify = AsyncMock()
        mock_spotify.get_artist_details = AsyncMock(return_value=None)
        svc._spotify = mock_spotify

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(spotify_id="art1", media_type_str="ARTISTS")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_song_no_spotify_client(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_spotify_credentials = AsyncMock(return_value=(None, None))

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(spotify_id="song1", media_type_str="SONGS")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_song_no_track_details(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_spotify = AsyncMock()
        mock_spotify.get_track_details = AsyncMock(return_value=None)
        svc._spotify = mock_spotify

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(spotify_id="song1", media_type_str="SONGS")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_song_no_album_id(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_spotify = AsyncMock()
        mock_spotify.get_track_details = AsyncMock(return_value={"album": {}})
        svc._spotify = mock_spotify

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(spotify_id="song1", media_type_str="SONGS")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_movie_no_tmdb_client(self):
        db = AsyncMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_tmdb_api_key = AsyncMock(return_value=None)

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(tmdb_id=999, media_type_str="MOVIES")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_movie_no_details(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_tmdb = AsyncMock()
        mock_tmdb.get_movie_details = AsyncMock(return_value=None)
        svc._tmdb = mock_tmdb

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(tmdb_id=999, media_type_str="MOVIES")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_show_no_details(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_tmdb = AsyncMock()
        mock_tmdb.get_show_details = AsyncMock(return_value=None)
        svc._tmdb = mock_tmdb

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(tmdb_id=888, media_type_str="SHOWS")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_movie_success(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_tmdb = AsyncMock()
        mock_tmdb.get_movie_details = AsyncMock(return_value={
            "title": "Test Movie",
            "original_title": "Test Original",
            "overview": "Description",
            "release_date": "2024-01-01",
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
            "original_language": "en",
            "external_ids": {"imdb_id": "tt1234567"},
            "genres": [{"name": "Action"}, {"name": "Drama"}],
        })
        svc._tmdb = mock_tmdb

        lib_guid = uuid.uuid4()
        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = lib_guid
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        with patch("streamarr.services.search.MediaService") as MockMediaService:
            mock_media_svc = AsyncMock()
            mock_item = MagicMock()
            mock_item.guid = uuid.uuid4()
            mock_media_svc.create_media_item = AsyncMock(return_value=mock_item)
            mock_media_svc.add_external_id = AsyncMock()
            mock_media_svc.set_genres = AsyncMock()
            MockMediaService.return_value = mock_media_svc

            result = await svc.get_or_import_item(tmdb_id=100, media_type_str="MOVIES")
            assert result is not None
            assert result["guid"] == str(mock_item.guid)
            # Check that imdb external ID was added
            assert mock_media_svc.add_external_id.call_count >= 2  # tmdb + imdb

    @pytest.mark.asyncio
    async def test_import_show_success(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_tmdb = AsyncMock()
        mock_tmdb.get_show_details = AsyncMock(return_value={
            "name": "Test Show",
            "original_name": "Original Show",
            "overview": "Show desc",
            "first_air_date": "2023-06-01",
            "poster_path": "/show.jpg",
            "backdrop_path": None,
            "original_language": "en",
            "external_ids": {"tvdb_id": 9999, "imdb_id": "tt7654321"},
            "genres": [{"name": "Comedy"}],
        })
        svc._tmdb = mock_tmdb

        lib_guid = uuid.uuid4()
        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = lib_guid
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        with (
            patch("streamarr.services.search.MediaService") as MockMediaService,
            patch(
                "streamarr.services.search.SearchService._queue_show_import",
                new_callable=AsyncMock,
            ),
        ):
            mock_media_svc = AsyncMock()
            mock_item = MagicMock()
            mock_item.guid = uuid.uuid4()
            mock_media_svc.create_media_item = AsyncMock(return_value=mock_item)
            mock_media_svc.add_external_id = AsyncMock()
            mock_media_svc.set_genres = AsyncMock()
            MockMediaService.return_value = mock_media_svc

            result = await svc.get_or_import_item(tmdb_id=200, media_type_str="SHOWS")
            assert result is not None
            # tmdb + tvdb + imdb = 3
            assert mock_media_svc.add_external_id.call_count >= 3

    @pytest.mark.asyncio
    async def test_import_game_success(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_igdb = AsyncMock()
        mock_igdb.get_game_details = AsyncMock(return_value={
            "name": "Test Game",
            "summary": "Game desc",
            "first_release_date": 1609459200,
            "cover": {"image_id": "abc"},
            "genres": [{"name": "Action"}],
        })
        svc._igdb = mock_igdb

        lib_guid = uuid.uuid4()
        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = lib_guid
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        with patch("streamarr.services.search.MediaService") as MockMediaService:
            mock_media_svc = AsyncMock()
            mock_item = MagicMock()
            mock_item.guid = uuid.uuid4()
            mock_media_svc.create_media_item = AsyncMock(return_value=mock_item)
            mock_media_svc.add_external_id = AsyncMock()
            mock_media_svc.set_genres = AsyncMock()
            MockMediaService.return_value = mock_media_svc

            result = await svc.get_or_import_item(igdb_id=300, media_type_str="GAMES")
            assert result is not None

    @pytest.mark.asyncio
    async def test_import_album_success(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_spotify = AsyncMock()
        mock_spotify.get_album_details = AsyncMock(return_value={
            "name": "Test Album",
            "release_date": "2023",
            "images": [{"url": "https://img.spotify.com/album.jpg"}],
            "artists": [{"name": "Artist", "id": "art1"}],
            "genres": [],
        })
        mock_spotify.get_artist_details = AsyncMock(return_value={
            "genres": ["pop", "rock"],
        })
        svc._spotify = mock_spotify

        lib_guid = uuid.uuid4()
        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = lib_guid
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        with patch("streamarr.services.search.MediaService") as MockMediaService:
            mock_media_svc = AsyncMock()
            mock_item = MagicMock()
            mock_item.guid = uuid.uuid4()
            mock_media_svc.create_media_item = AsyncMock(return_value=mock_item)
            mock_media_svc.add_external_id = AsyncMock()
            mock_media_svc.set_genres = AsyncMock()
            MockMediaService.return_value = mock_media_svc

            result = await svc.get_or_import_item(spotify_id="al1", media_type_str="MUSIC")
            assert result is not None

    @pytest.mark.asyncio
    async def test_import_album_date_formats(self):
        """Test Spotify date parsing for YYYY-MM and YYYY-MM-DD."""
        db = AsyncMock()
        svc = SearchService(db)

        for date_str in ("2023-06", "2023-06-15"):
            mock_spotify = AsyncMock()
            mock_spotify.get_album_details = AsyncMock(return_value={
                "name": "Album",
                "release_date": date_str,
                "images": [],
                "artists": [],
                "genres": ["pop"],
            })
            svc._spotify = mock_spotify

            lib_guid = uuid.uuid4()
            mock_result1 = MagicMock()
            mock_result1.first.return_value = None
            mock_result2 = MagicMock()
            mock_result2.scalar_one_or_none.return_value = lib_guid
            db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

            with patch("streamarr.services.search.MediaService") as MockMediaService:
                mock_media_svc = AsyncMock()
                mock_item = MagicMock()
                mock_item.guid = uuid.uuid4()
                mock_media_svc.create_media_item = AsyncMock(return_value=mock_item)
                mock_media_svc.add_external_id = AsyncMock()
                mock_media_svc.set_genres = AsyncMock()
                MockMediaService.return_value = mock_media_svc

                result = await svc.get_or_import_item(spotify_id="al2", media_type_str="MUSIC")
                assert result is not None

    @pytest.mark.asyncio
    async def test_import_artist_success_with_album_queue(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_spotify = AsyncMock()
        mock_spotify.get_artist_details = AsyncMock(return_value={
            "name": "Famous Artist",
            "images": [{"url": "https://img.spotify.com/artist.jpg"}],
            "genres": ["rock"],
        })
        mock_spotify.get_artist_albums = AsyncMock(return_value=[
            {"id": "al1"}, {"id": "al2"},
        ])
        svc._spotify = mock_spotify

        lib_guid = uuid.uuid4()
        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = lib_guid
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        with (
            patch("streamarr.services.search.MediaService") as MockMediaService,
            patch("streamarr.services.search.SearchService._get_spotify_client", new_callable=AsyncMock, return_value=mock_spotify),
        ):
            mock_media_svc = AsyncMock()
            mock_item = MagicMock()
            mock_item.guid = uuid.uuid4()
            mock_media_svc.create_media_item = AsyncMock(return_value=mock_item)
            mock_media_svc.add_external_id = AsyncMock()
            mock_media_svc.set_genres = AsyncMock()
            MockMediaService.return_value = mock_media_svc

            # The album import queuing will fail (no worker) but should not crash
            result = await svc.get_or_import_item(spotify_id="art1", media_type_str="ARTISTS")
            assert result is not None

    @pytest.mark.asyncio
    async def test_import_exception_rolls_back(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_tmdb = AsyncMock()
        mock_tmdb.get_movie_details = AsyncMock(side_effect=Exception("API down"))
        svc._tmdb = mock_tmdb

        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        result = await svc.get_or_import_item(tmdb_id=999, media_type_str="MOVIES")
        assert result is None
        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_import_movie_invalid_date(self):
        db = AsyncMock()
        svc = SearchService(db)
        mock_tmdb = AsyncMock()
        mock_tmdb.get_movie_details = AsyncMock(return_value={
            "title": "Movie",
            "release_date": "invalid-date",
            "external_ids": {},
            "genres": [],
        })
        svc._tmdb = mock_tmdb

        lib_guid = uuid.uuid4()
        mock_result1 = MagicMock()
        mock_result1.first.return_value = None
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = lib_guid
        db.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

        with patch("streamarr.services.search.MediaService") as MockMediaService:
            mock_media_svc = AsyncMock()
            mock_item = MagicMock()
            mock_item.guid = uuid.uuid4()
            mock_media_svc.create_media_item = AsyncMock(return_value=mock_item)
            mock_media_svc.add_external_id = AsyncMock()
            mock_media_svc.set_genres = AsyncMock()
            MockMediaService.return_value = mock_media_svc

            result = await svc.get_or_import_item(tmdb_id=100, media_type_str="MOVIES")
            assert result is not None  # Should succeed despite invalid date

"""Tests for ComputingService – covers uncovered lines (146, 453-632)."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.services.computing import ComputingService, detect_hardware_acceleration


# ---------------------------------------------------------------------------
# detect_hardware_acceleration
# ---------------------------------------------------------------------------


class TestDetectHardwareAcceleration:
    def test_hw_accel_disabled(self):
        """ENABLE_HARDWARE_ACCEL=false returns empty result."""
        with patch.dict(os.environ, {"ENABLE_HARDWARE_ACCEL": "false"}):
            result = detect_hardware_acceleration()
        assert result["type"] is None
        assert result["devices"] == []
        assert result["encoder_suffix"] == ""

    def test_no_dri_devices(self):
        """No /dev/dri returns empty result."""
        with patch.dict(os.environ, {"ENABLE_HARDWARE_ACCEL": "true"}), \
             patch("os.path.exists", return_value=False):
            result = detect_hardware_acceleration()
        assert result["type"] is None

    def test_intel_gpu_detected(self):
        """Intel GPU devices detected returns qsv."""
        def mock_exists(path):
            return path in ("/dev/dri", "/dev/dri/renderD128", "/dev/dri/card0")

        with patch.dict(os.environ, {"ENABLE_HARDWARE_ACCEL": "true"}), \
             patch("os.path.exists", side_effect=mock_exists):
            result = detect_hardware_acceleration()
        assert result["type"] == "qsv"
        assert "/dev/dri/renderD128" in result["devices"]
        assert result["encoder_suffix"] == "_qsv"


# ---------------------------------------------------------------------------
# ComputingService: get_provider (line 146)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ComputingService: start_transcoding (lines 453-632)
# ---------------------------------------------------------------------------


class TestStartTranscoding:
    @pytest.mark.asyncio
    async def test_start_transcoding_basic(self, db_session: AsyncSession):
        """start_transcoding builds command and starts task."""
        service = ComputingService(db_session)

        mock_provider = AsyncMock()
        mock_provider.start_task = AsyncMock(return_value="task-abc-123")
        service._provider = mock_provider
        service._provider_domain = "test"

        mock_settings_svc = MagicMock()
        mock_settings_svc.get_transcoding_settings = AsyncMock(return_value={
            "ffmpeg_image": "lscr.io/linuxserver/ffmpeg:latest",
            "hardware_acceleration": False,
            "thread_count": 0,
            "hls_segment_duration": 6,
        })

        mock_session_svc = MagicMock()
        mock_session_svc.create_session = AsyncMock()

        with patch("pyrate.services.system_settings.SystemSettingsService", return_value=mock_settings_svc), \
             patch("pyrate.services.transcoding_session.get_transcoding_session_service", return_value=mock_session_svc), \
             patch("os.path.exists", return_value=False), \
             patch("os.makedirs"), \
             patch("os.chmod"):
            task_id = await service.start_transcoding(
                input_path="/library/movies/test.mkv",
                rel_output="/temp/session.m3u8",
                segment_pattern="/temp/session_%03d.ts",
                hls_time=6,
                session_id="session-123",
                video_codec="h264",
                audio_codec="aac",
                video_bitrate="4000k",
                audio_bitrate="128k",
                start_position=None,
                resolution=None,
                audio_stream_index=None,
                subtitle_stream_index=None,
                burn_subtitles=False,
                user_guid=str(uuid.uuid4()),
                user_name="testuser",
                content_type="movie",
                content_id=str(uuid.uuid4()),
                content_title="Test Movie",
                library_path="/library",
            )

        assert task_id == "task-abc-123"
        mock_provider.start_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_transcoding_with_hw_accel(self, db_session: AsyncSession):
        """start_transcoding with hardware acceleration enabled."""
        service = ComputingService(db_session)

        mock_provider = AsyncMock()
        mock_provider.start_task = AsyncMock(return_value="task-hw-456")
        service._provider = mock_provider
        service._provider_domain = "test"

        mock_settings_svc = MagicMock()
        mock_settings_svc.get_transcoding_settings = AsyncMock(return_value={
            "ffmpeg_image": "lscr.io/linuxserver/ffmpeg:latest",
            "hardware_acceleration": True,
            "hardware_acceleration_device": "/dev/dri/renderD128",
            "thread_count": 4,
            "hls_segment_duration": 6,
        })

        mock_session_svc = MagicMock()
        mock_session_svc.create_session = AsyncMock()

        with patch("pyrate.services.system_settings.SystemSettingsService", return_value=mock_settings_svc), \
             patch("pyrate.services.transcoding_session.get_transcoding_session_service", return_value=mock_session_svc), \
             patch("pyrate.services.computing.detect_hardware_acceleration", return_value={
                 "type": "qsv",
                 "devices": ["/dev/dri/renderD128"],
                 "encoder_suffix": "_qsv",
             }), \
             patch("os.path.exists", return_value=False), \
             patch("os.makedirs"), \
             patch("os.chmod"):
            task_id = await service.start_transcoding(
                input_path="/library/movies/test.mkv",
                rel_output="/temp/session.m3u8",
                segment_pattern="/temp/session_%03d.ts",
                hls_time=6,
                session_id="session-456",
                video_codec="h264",
                audio_codec="aac",
                video_bitrate="4000k",
                audio_bitrate="128k",
                start_position=10.0,
                resolution="1920x1080",
                audio_stream_index=1,
                subtitle_stream_index=0,
                burn_subtitles=True,
                user_guid=str(uuid.uuid4()),
                user_name="testuser",
                content_type="movie",
                content_id=str(uuid.uuid4()),
                content_title="Test Movie",
                library_path="/library",
            )

        assert task_id == "task-hw-456"

    @pytest.mark.asyncio
    async def test_start_transcoding_in_docker(self, db_session: AsyncSession):
        """start_transcoding running inside Docker uses host paths."""
        service = ComputingService(db_session)

        mock_provider = AsyncMock()
        mock_provider.start_task = AsyncMock(return_value="task-docker-789")
        service._provider = mock_provider
        service._provider_domain = "test"

        mock_settings_svc = MagicMock()
        mock_settings_svc.get_transcoding_settings = AsyncMock(return_value={
            "ffmpeg_image": "lscr.io/linuxserver/ffmpeg:latest",
            "hardware_acceleration": False,
            "thread_count": 0,
            "hls_segment_duration": 6,
        })

        mock_session_svc = MagicMock()
        mock_session_svc.create_session = AsyncMock()

        def mock_exists(path):
            return path == "/.dockerenv"

        with patch("pyrate.services.system_settings.SystemSettingsService", return_value=mock_settings_svc), \
             patch("pyrate.services.transcoding_session.get_transcoding_session_service", return_value=mock_session_svc), \
             patch("os.path.exists", side_effect=mock_exists), \
             patch("os.makedirs"), \
             patch("os.chmod"), \
             patch.dict(os.environ, {"PROJECT_ROOT": "/root/pyrate.media/data/"}):
            task_id = await service.start_transcoding(
                input_path="/library/movies/test.mkv",
                rel_output="/temp/session.m3u8",
                segment_pattern="/temp/session_%03d.ts",
                hls_time=6,
                session_id="session-789",
                video_codec="h264",
                audio_codec="aac",
                video_bitrate=None,
                audio_bitrate="128k",
                start_position=None,
                resolution=None,
                audio_stream_index=None,
                subtitle_stream_index=None,
                burn_subtitles=False,
                user_guid=None,
                user_name=None,
                content_type="movie",
                content_id=None,
                content_title=None,
                library_path="/library",
            )

        assert task_id == "task-docker-789"

    @pytest.mark.asyncio
    async def test_start_transcoding_redis_failure(self, db_session: AsyncSession):
        """start_transcoding continues even if Redis session storage fails."""
        service = ComputingService(db_session)

        mock_provider = AsyncMock()
        mock_provider.start_task = AsyncMock(return_value="task-redis-fail")
        service._provider = mock_provider
        service._provider_domain = "test"

        mock_settings_svc = MagicMock()
        mock_settings_svc.get_transcoding_settings = AsyncMock(return_value={
            "ffmpeg_image": "lscr.io/linuxserver/ffmpeg:latest",
            "hardware_acceleration": False,
            "thread_count": 0,
            "hls_segment_duration": 6,
        })

        mock_session_svc = MagicMock()
        mock_session_svc.create_session = AsyncMock(side_effect=Exception("Redis down"))

        with patch("pyrate.services.system_settings.SystemSettingsService", return_value=mock_settings_svc), \
             patch("pyrate.services.transcoding_session.get_transcoding_session_service", return_value=mock_session_svc), \
             patch("os.path.exists", return_value=False), \
             patch("os.makedirs"), \
             patch("os.chmod"):
            task_id = await service.start_transcoding(
                input_path="/library/movies/test.mkv",
                rel_output="/temp/session.m3u8",
                segment_pattern="/temp/session_%03d.ts",
                hls_time=6,
                session_id="session-redis",
                video_codec="h264",
                audio_codec="aac",
                video_bitrate=None,
                audio_bitrate="128k",
                start_position=None,
                resolution=None,
                audio_stream_index=None,
                subtitle_stream_index=None,
                burn_subtitles=False,
                user_guid=None,
                user_name=None,
                content_type="movie",
                content_id=None,
                content_title=None,
                library_path="/library",
            )

        assert task_id == "task-redis-fail"

    @pytest.mark.asyncio
    async def test_start_transcoding_audio_only(self, db_session: AsyncSession):
        """start_transcoding with audio_only=True."""
        service = ComputingService(db_session)

        mock_provider = AsyncMock()
        mock_provider.start_task = AsyncMock(return_value="task-audio-only")
        service._provider = mock_provider
        service._provider_domain = "test"

        mock_settings_svc = MagicMock()
        mock_settings_svc.get_transcoding_settings = AsyncMock(return_value={
            "ffmpeg_image": "lscr.io/linuxserver/ffmpeg:latest",
            "hardware_acceleration": False,
            "thread_count": 0,
            "hls_segment_duration": 6,
        })

        mock_session_svc = MagicMock()
        mock_session_svc.create_session = AsyncMock()

        with patch("pyrate.services.system_settings.SystemSettingsService", return_value=mock_settings_svc), \
             patch("pyrate.services.transcoding_session.get_transcoding_session_service", return_value=mock_session_svc), \
             patch("os.path.exists", return_value=False), \
             patch("os.makedirs"), \
             patch("os.chmod"):
            task_id = await service.start_transcoding(
                input_path="/library/music/track.flac",
                rel_output="/temp/session.m3u8",
                segment_pattern="/temp/session_%03d.ts",
                hls_time=6,
                session_id="session-audio",
                video_codec="h264",
                audio_codec="aac",
                video_bitrate=None,
                audio_bitrate="128k",
                start_position=None,
                resolution=None,
                audio_stream_index=0,
                subtitle_stream_index=None,
                burn_subtitles=False,
                user_guid=None,
                user_name=None,
                content_type="music",
                content_id=None,
                content_title=None,
                library_path="/library",
                audio_only=True,
            )

        assert task_id == "task-audio-only"


# ---------------------------------------------------------------------------
# _build_ffmpeg_command: various codec branches
# ---------------------------------------------------------------------------


class TestBuildFfmpegCommand:
    def _make_service(self, db_session):
        return ComputingService(db_session)

    def test_build_h265_software(self, db_session: AsyncSession):
        """h265 without hw_accel uses libx265."""
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.mkv", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="h265", audio_codec="aac",
            video_bitrate="4000k", audio_bitrate="128k",
            start_position=None, resolution=None,
            audio_stream_index=None, subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "libx265" in cmd

    def test_build_vp9(self, db_session: AsyncSession):
        """vp9 uses libvpx-vp9."""
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.mkv", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="vp9", audio_codec="aac",
            video_bitrate=None, audio_bitrate="128k",
            start_position=None, resolution=None,
            audio_stream_index=None, subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "libvpx-vp9" in cmd

    def test_build_av1_software(self, db_session: AsyncSession):
        """av1 without hw_accel uses libsvtav1."""
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.mkv", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="av1", audio_codec="aac",
            video_bitrate=None, audio_bitrate="128k",
            start_position=None, resolution=None,
            audio_stream_index=None, subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "libsvtav1" in cmd

    def test_build_opus_audio(self, db_session: AsyncSession):
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.mkv", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="h264", audio_codec="opus",
            video_bitrate=None, audio_bitrate="128k",
            start_position=None, resolution=None,
            audio_stream_index=None, subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "libopus" in cmd

    def test_build_mp3_audio(self, db_session: AsyncSession):
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.mkv", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="h264", audio_codec="mp3",
            video_bitrate=None, audio_bitrate="128k",
            start_position=None, resolution=None,
            audio_stream_index=None, subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "libmp3lame" in cmd

    def test_build_copy_codec(self, db_session: AsyncSession):
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.mkv", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="copy", audio_codec="copy",
            video_bitrate=None, audio_bitrate="128k",
            start_position=None, resolution=None,
            audio_stream_index=None, subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "copy" in cmd

    def test_build_with_start_position(self, db_session: AsyncSession):
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.mkv", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="h264", audio_codec="aac",
            video_bitrate=None, audio_bitrate="128k",
            start_position=30.0, resolution=None,
            audio_stream_index=None, subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "-ss" in cmd

    def test_build_with_resolution(self, db_session: AsyncSession):
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.mkv", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="h264", audio_codec="aac",
            video_bitrate=None, audio_bitrate="128k",
            start_position=None, resolution="1280x720",
            audio_stream_index=None, subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "-vf" in cmd

    def test_build_subtitle_burn(self, db_session: AsyncSession):
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.mkv", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="h264", audio_codec="aac",
            video_bitrate=None, audio_bitrate="128k",
            start_position=None, resolution=None,
            audio_stream_index=None, subtitle_stream_index=0,
            burn_subtitles=True,
        )
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        assert "subtitles" in cmd[vf_idx + 1]

    def test_build_with_thread_count(self, db_session: AsyncSession):
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.mkv", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="h264", audio_codec="aac",
            video_bitrate=None, audio_bitrate="128k",
            start_position=None, resolution=None,
            audio_stream_index=None, subtitle_stream_index=None,
            burn_subtitles=False, thread_count=4,
        )
        assert "-threads" in cmd

    def test_invalid_audio_stream_index(self, db_session: AsyncSession):
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.mkv", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="h264", audio_codec="aac",
            video_bitrate=None, audio_bitrate="128k",
            start_position=None, resolution=None,
            audio_stream_index=-1, subtitle_stream_index=None,
            burn_subtitles=False,
        )
        assert "0:a:0" in cmd

    def test_build_audio_only(self, db_session: AsyncSession):
        """audio_only=True produces -vn and maps audio."""
        svc = self._make_service(db_session)
        cmd = svc._build_ffmpeg_command(
            input_path="/input.flac", rel_output="/output.m3u8",
            segment_pattern="/seg_%03d.ts", hls_time=6,
            video_codec="h264", audio_codec="aac",
            video_bitrate=None, audio_bitrate="128k",
            start_position=None, resolution=None,
            audio_stream_index=None, subtitle_stream_index=None,
            burn_subtitles=False, audio_only=True,
        )
        assert "-vn" in cmd
        assert "0:a:0" in cmd


# ---------------------------------------------------------------------------
# Static utility methods
# ---------------------------------------------------------------------------


class TestComputingServiceStaticMethods:
    def test_parse_bitrate_valid(self):
        assert ComputingService._parse_bitrate("128k") == 128

    def test_parse_bitrate_empty(self):
        assert ComputingService._parse_bitrate("") == 0
        assert ComputingService._parse_bitrate(None) == 0

    def test_parse_bitrate_invalid(self):
        assert ComputingService._parse_bitrate("abc") == 0

    def test_parse_resolution_valid(self):
        assert ComputingService._parse_resolution("1920x1080") == (1920, 1080)

    def test_parse_resolution_none(self):
        assert ComputingService._parse_resolution(None) is None
        assert ComputingService._parse_resolution("") is None

    def test_parse_resolution_no_x(self):
        assert ComputingService._parse_resolution("1920") is None

    def test_parse_resolution_out_of_bounds(self):
        assert ComputingService._parse_resolution("50x50") is None

    def test_parse_resolution_invalid(self):
        assert ComputingService._parse_resolution("abcxdef") is None

    def test_escape_ffmpeg_path(self):
        assert "\\:" in ComputingService._escape_ffmpeg_path("/path:with:colons")

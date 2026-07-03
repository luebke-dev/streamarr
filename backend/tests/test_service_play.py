"""Tests for play service – covers uncovered lines."""

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.services.play import (
    CodecNegotiationResult,
    PlayAction,
    _match_language,
    _structure_probe_data,
    build_stream_info,
    extract_source_info,
    negotiate_codecs,
    prefetch_next_episode,
    resolve_play_action,
    select_streams_for_user,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(**overrides):
    defaults = dict(
        codec="h264",
        width=1920,
        height=1080,
        file_path="/library/movies/test.mkv",
        file_size=5000000,
        duration=7200,
    )
    defaults.update(overrides)
    f = MagicMock()
    for k, v in defaults.items():
        setattr(f, k, v)
    return f


# ---------------------------------------------------------------------------
# negotiate_codecs: audio-only path (line 108 – no source_video_codec)
# ---------------------------------------------------------------------------


class TestNegotiateCodecsAudioOnly:
    def test_audio_only_returns_none_video(self):
        """Audio-only file sets video_codec=None, resolution=None."""
        source_info = {"video_codec": None, "audio_codec": "aac"}
        file = _make_file(codec=None, width=0, height=0)

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"audio_streams": [{"codec_name": "aac"}]},
            file=file,
            supported_video_codecs=None,
            supported_audio_codecs="aac,opus",
            client_max_resolution=None,
        )

        assert result.video_codec is None
        assert result.resolution is None
        assert result.audio_codec in ("aac", "copy")

    def test_audio_only_aac_fallback(self):
        """Audio-only with unknown codec falls back to aac if client supports it."""
        source_info = {"video_codec": None, "audio_codec": "pcm_s16le"}
        file = _make_file(codec=None, width=0, height=0)

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"audio_streams": [{"codec_name": "pcm"}]},
            file=file,
            supported_video_codecs=None,
            supported_audio_codecs="aac,opus",
            client_max_resolution=None,
        )

        assert result.video_codec is None
        assert result.audio_codec == "aac"

    def test_audio_only_requested_fallback(self):
        """Audio-only with no aac support falls back to requested_audio_codec."""
        source_info = {"video_codec": None, "audio_codec": "pcm_s16le"}
        file = _make_file(codec=None, width=0, height=0)

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"audio_streams": [{"codec_name": "pcm"}]},
            file=file,
            supported_video_codecs=None,
            supported_audio_codecs="opus",  # no aac
            client_max_resolution=None,
            requested_audio_codec="mp3",
        )

        assert result.audio_codec == "mp3"


# ---------------------------------------------------------------------------
# negotiate_codecs: resolution downscale prevents copy (lines 247-250)
# ---------------------------------------------------------------------------


class TestNegotiateCodecsResolutionDownscale:
    def test_resolution_downscale_prevents_copy(self):
        """When source exceeds client max resolution, copy is not used."""
        source_info = {"video_codec": "h264", "audio_codec": "aac", "height": 2160}
        file = _make_file(height=2160)

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "h264"}]},
            file=file,
            supported_video_codecs="h264,h265",
            supported_audio_codecs="aac",
            client_max_resolution="1080p",
        )

        assert result.video_codec != "copy"
        assert result.resolution == "1920x1080"


# ---------------------------------------------------------------------------
# negotiate_codecs: codec priority fallback (lines 271-278)
# ---------------------------------------------------------------------------


class TestNegotiateCodecsFallback:
    def test_unsupported_source_codec_triggers_priority_fallback(self):
        """When source codec isn't supported, first priority match is used."""
        source_info = {"video_codec": "mpeg2", "audio_codec": "aac", "height": 1080}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "mpeg2"}]},
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        assert result.video_codec == "h264"

    def test_no_matching_codec_falls_back_to_h264(self):
        """When no priority codec matches client, fallback to h264."""
        source_info = {"video_codec": "mpeg2", "audio_codec": "aac", "height": 1080}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "mpeg2"}]},
            file=file,
            supported_video_codecs="theora",  # not in priority list
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        # Falls through all codecs, h264 is the fallback
        assert result.video_codec == "h264"


# ---------------------------------------------------------------------------
# negotiate_codecs: resolution limit without copy (lines 297-302)
# ---------------------------------------------------------------------------


class TestNegotiateCodecsResolutionLimit:
    def test_resolution_limit_applied_when_not_copy(self):
        """client_max_resolution applies when codec is not copy."""
        source_info = {"video_codec": "mpeg2", "audio_codec": "aac"}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "mpeg2"}]},
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution="720p",
        )

        assert result.resolution == "1280x720"

    def test_resolution_limit_4k_returns_none(self):
        """client_max_resolution='4k' returns None (no downscale)."""
        source_info = {"video_codec": "mpeg2", "audio_codec": "aac"}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "mpeg2"}]},
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution="4k",
        )

        assert result.resolution is None


# ---------------------------------------------------------------------------
# negotiate_codecs: audio codec copy path (lines 310-315)
# ---------------------------------------------------------------------------


class TestNegotiateCodecsAudioCopy:
    def test_audio_copy_for_supported_passthrough(self):
        """Copy is used for passthrough-eligible audio codecs."""
        source_info = {"video_codec": "h264", "audio_codec": "aac", "height": 1080}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "h264"}], "audio_streams": [{"codec_name": "aac"}]},
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        assert result.audio_codec == "copy"

    def test_audio_transcode_for_lossy_surround(self):
        """Surround codecs (ac3, dts) are transcoded, not copied."""
        source_info = {"video_codec": "h264", "audio_codec": "ac3", "height": 1080}
        file = _make_file()

        result = negotiate_codecs(
            source_info=source_info,
            probe_data={"video_streams": [{"codec_name": "h264"}], "audio_streams": [{"codec_name": "ac3"}]},
            file=file,
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )

        assert result.audio_codec == "aac"


# ---------------------------------------------------------------------------
# resolve_play_action (lines 345-464)
# ---------------------------------------------------------------------------


class TestResolvePlayAction:
    @pytest.mark.asyncio
    async def test_resolve_play_action_downloading_completed(self, db_session: AsyncSession):
        """When existing download status is Completed, returns importing status."""
        media_id = uuid.uuid4()
        media_item = MagicMock()
        media_item.title = "Test Movie"

        mock_download = MagicMock()
        mock_download.status = "Completed"
        mock_download.progress = 100.0

        file_result = MagicMock()
        file_result.scalars.return_value.first.return_value = None

        download_result = MagicMock()
        download_result.scalars.return_value.first.return_value = mock_download

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return file_result
            elif call_count == 2:
                return download_result

        mock_worker = MagicMock()
        mock_worker.auto_download_media_item = MagicMock()
        mock_worker.auto_download_media_item.kiq = AsyncMock()
        mock_worker.search_media_item_releases = MagicMock()
        mock_worker.search_media_item_releases.kiq = AsyncMock()

        with patch.object(db_session, "execute", side_effect=mock_execute), \
             patch.dict("sys.modules", {"pyrate.worker": mock_worker}):
            result = await resolve_play_action(db_session, media_item, media_id)

        assert result.status == "downloading"
        assert result.download_progress == 100.0
        assert result.download_status == "importing"

    @pytest.mark.asyncio
    async def test_resolve_play_action_downloading_in_progress(self, db_session: AsyncSession):
        """When existing download in progress, returns downloading status."""
        media_id = uuid.uuid4()
        media_item = MagicMock()
        media_item.title = "Test Movie"

        mock_download = MagicMock()
        mock_download.status = "Downloading"
        mock_download.progress = 45.5

        file_result = MagicMock()
        file_result.scalars.return_value.first.return_value = None

        download_result = MagicMock()
        download_result.scalars.return_value.first.return_value = mock_download

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return file_result
            return download_result

        mock_worker = MagicMock()
        mock_worker.auto_download_media_item = MagicMock()
        mock_worker.auto_download_media_item.kiq = AsyncMock()
        mock_worker.search_media_item_releases = MagicMock()
        mock_worker.search_media_item_releases.kiq = AsyncMock()

        with patch.object(db_session, "execute", side_effect=mock_execute), \
             patch.dict("sys.modules", {"pyrate.worker": mock_worker}):
            result = await resolve_play_action(db_session, media_item, media_id)

        assert result.status == "downloading"
        assert result.download_progress == 45.5

    @pytest.mark.asyncio
    async def test_resolve_play_action_releases_with_links(self, db_session: AsyncSession):
        """Releases with links triggers auto-download."""
        media_id = uuid.uuid4()
        media_item = MagicMock()
        media_item.title = "Test Movie"

        mock_release = MagicMock()
        mock_release.links = [MagicMock()]

        file_result = MagicMock()
        file_result.scalars.return_value.first.return_value = None

        download_result = MagicMock()
        download_result.scalars.return_value.first.return_value = None

        releases_result = MagicMock()
        releases_result.scalars.return_value.all.return_value = [mock_release]

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return file_result
            elif call_count == 2:
                return download_result
            return releases_result

        mock_worker = MagicMock()
        mock_worker.auto_download_media_item = MagicMock()
        mock_worker.auto_download_media_item.kiq = AsyncMock()
        mock_worker.search_media_item_releases = MagicMock()
        mock_worker.search_media_item_releases.kiq = AsyncMock()

        with patch.object(db_session, "execute", side_effect=mock_execute), \
             patch.dict("sys.modules", {"pyrate.worker": mock_worker}):
            result = await resolve_play_action(db_session, media_item, media_id, user_guid=uuid.uuid4())

        assert result.status == "downloading"
        assert result.download_status == "preparing"

    @pytest.mark.asyncio
    async def test_resolve_play_action_releases_without_links(self, db_session: AsyncSession):
        """Releases without links triggers search."""
        media_id = uuid.uuid4()
        media_item = MagicMock()
        media_item.title = "Test Movie"

        mock_release = MagicMock()
        mock_release.links = []

        file_result = MagicMock()
        file_result.scalars.return_value.first.return_value = None

        download_result = MagicMock()
        download_result.scalars.return_value.first.return_value = None

        releases_result = MagicMock()
        releases_result.scalars.return_value.all.return_value = [mock_release]

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return file_result
            elif call_count == 2:
                return download_result
            return releases_result

        mock_worker = MagicMock()
        mock_worker.auto_download_media_item = MagicMock()
        mock_worker.auto_download_media_item.kiq = AsyncMock()
        mock_worker.search_media_item_releases = MagicMock()
        mock_worker.search_media_item_releases.kiq = AsyncMock()

        with patch.object(db_session, "execute", side_effect=mock_execute), \
             patch.dict("sys.modules", {"pyrate.worker": mock_worker}):
            result = await resolve_play_action(db_session, media_item, media_id)

        assert result.status == "searching"

    @pytest.mark.asyncio
    async def test_resolve_play_action_no_releases(self, db_session: AsyncSession):
        """No releases at all triggers search."""
        media_id = uuid.uuid4()
        media_item = MagicMock()
        media_item.title = "Test Movie"

        file_result = MagicMock()
        file_result.scalars.return_value.first.return_value = None

        download_result = MagicMock()
        download_result.scalars.return_value.first.return_value = None

        releases_result = MagicMock()
        releases_result.scalars.return_value.all.return_value = []

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return file_result
            elif call_count == 2:
                return download_result
            return releases_result

        mock_worker = MagicMock()
        mock_worker.auto_download_media_item = MagicMock()
        mock_worker.auto_download_media_item.kiq = AsyncMock()
        mock_worker.search_media_item_releases = MagicMock()
        mock_worker.search_media_item_releases.kiq = AsyncMock()

        with patch.object(db_session, "execute", side_effect=mock_execute), \
             patch.dict("sys.modules", {"pyrate.worker": mock_worker}):
            result = await resolve_play_action(db_session, media_item, media_id)

        assert result.status == "searching"


# ---------------------------------------------------------------------------
# _probe_video_with_computing_service (lines 580-594, 597-598, 610-619)
# ---------------------------------------------------------------------------


class TestProbeVideoWithComputingService:
    @pytest.mark.asyncio
    async def test_probe_timeout(self, db_session: AsyncSession):
        """Probe times out after max_wait."""
        from pyrate.services.play import _probe_video_with_computing_service
        import asyncio

        mock_computing = MagicMock()
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)
        mock_computing.start_task = AsyncMock(return_value="task-123")
        mock_computing.get_task_status = AsyncMock(return_value="running")
        mock_computing.stop_task = AsyncMock()
        mock_computing.delete_task = AsyncMock()

        with patch("pyrate.services.transcode_lifecycle._get_base_library_path", new_callable=AsyncMock, return_value="/data"), \
             patch("pyrate.services.transcode_lifecycle.ComputingService", return_value=mock_computing), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _probe_video_with_computing_service("/library/movies/test.mkv", db_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_probe_failed_task(self, db_session: AsyncSession):
        """Probe returns None when task fails."""
        from pyrate.services.play import _probe_video_with_computing_service

        mock_computing = MagicMock()
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)
        mock_computing.start_task = AsyncMock(return_value="task-123")
        mock_computing.get_task_status = AsyncMock(return_value="failed")
        mock_computing.get_task_logs = AsyncMock(return_value="error: file not found")
        mock_computing.delete_task = AsyncMock()

        with patch("pyrate.services.transcode_lifecycle._get_base_library_path", new_callable=AsyncMock, return_value="/data"), \
             patch("pyrate.services.transcode_lifecycle.ComputingService", return_value=mock_computing):
            result = await _probe_video_with_computing_service("/library/movies/test.mkv", db_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_probe_json_decode_error(self, db_session: AsyncSession):
        """Probe returns None on JSON decode error (line 597-598)."""
        from pyrate.services.play import _probe_video_with_computing_service

        mock_computing = MagicMock()
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)
        mock_computing.start_task = AsyncMock(return_value="task-123")
        mock_computing.get_task_status = AsyncMock(return_value="completed")
        mock_computing.get_task_logs = AsyncMock(return_value="not valid json{{{")
        mock_computing.delete_task = AsyncMock()

        with patch("pyrate.services.transcode_lifecycle._get_base_library_path", new_callable=AsyncMock, return_value="/data"), \
             patch("pyrate.services.transcode_lifecycle.ComputingService", return_value=mock_computing):
            result = await _probe_video_with_computing_service("/library/movies/test.mkv", db_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_probe_empty_output(self, db_session: AsyncSession):
        """Probe returns None when output is empty."""
        from pyrate.services.play import _probe_video_with_computing_service

        mock_computing = MagicMock()
        mock_computing.__aenter__ = AsyncMock(return_value=mock_computing)
        mock_computing.__aexit__ = AsyncMock(return_value=False)
        mock_computing.start_task = AsyncMock(return_value="task-123")
        mock_computing.get_task_status = AsyncMock(return_value="completed")
        mock_computing.get_task_logs = AsyncMock(return_value="   ")
        mock_computing.delete_task = AsyncMock()

        with patch("pyrate.services.transcode_lifecycle._get_base_library_path", new_callable=AsyncMock, return_value="/data"), \
             patch("pyrate.services.transcode_lifecycle.ComputingService", return_value=mock_computing):
            result = await _probe_video_with_computing_service("/library/movies/test.mkv", db_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_probe_general_exception(self, db_session: AsyncSession):
        """Probe returns None on general exception (line 600)."""
        from pyrate.services.play import _probe_video_with_computing_service

        with patch("pyrate.services.transcode_lifecycle._get_base_library_path", new_callable=AsyncMock, side_effect=Exception("boom")):
            result = await _probe_video_with_computing_service("/library/movies/test.mkv", db_session)

        assert result is None


# ---------------------------------------------------------------------------
# _structure_probe_data (lines 610-619)
# ---------------------------------------------------------------------------


class TestStructureProbeData:
    def test_structure_probe_data_delegates(self):
        """_structure_probe_data delegates to plugins.base.structure_probe_data."""
        mock_structured = {
            "video_streams": [{"codec_name": "h264"}],
            "audio_streams": [{"codec_name": "aac"}],
            "subtitle_streams": [],
        }

        with patch("pyrate.libraries.base.structure_probe_data", return_value=mock_structured):
            result = _structure_probe_data({"streams": []}, "/test.mkv")

        assert result["video_streams"] == [{"codec_name": "h264"}]


# ---------------------------------------------------------------------------
# _match_language: reverse mapping (line 884)
# ---------------------------------------------------------------------------


class TestMatchLanguage:
    def test_reverse_mapping_stream_iso1_preferred_iso2(self):
        """stream_lang=iso1, preferred=iso2 matches via reverse lookup."""
        assert _match_language("de", "ger") is True
        assert _match_language("de", "deu") is True
        assert _match_language("en", "eng") is True

    def test_no_match_returns_false(self):
        """Unrelated languages return False."""
        assert _match_language("de", "jpn") is False

    def test_empty_inputs_return_false(self):
        assert _match_language("", "en") is False
        assert _match_language("en", "") is False


# ---------------------------------------------------------------------------
# prefetch_next_episode (lines 345-464 in the function)
# ---------------------------------------------------------------------------


class TestPrefetchNextEpisode:
    @pytest.mark.asyncio
    async def test_prefetch_not_episode_returns_early(self, db_session: AsyncSession):
        """If current item is not SHOWS type, returns early."""
        mock_svc = MagicMock()
        mock_svc.get_by_id = AsyncMock(return_value=None)

        with patch("pyrate.services.media.MediaService", return_value=mock_svc):
            # Should not raise
            await prefetch_next_episode(db_session, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_prefetch_exception_caught(self, db_session: AsyncSession):
        """Exceptions in prefetch are caught and logged."""
        mock_svc = MagicMock()
        mock_svc.get_by_id = AsyncMock(side_effect=Exception("db error"))

        with patch("pyrate.services.media.MediaService", return_value=mock_svc):
            # Should not raise
            await prefetch_next_episode(db_session, uuid.uuid4())


# ---------------------------------------------------------------------------
# select_streams_for_user (covers select logic)
# ---------------------------------------------------------------------------


class TestSelectStreamsForUser:
    def test_select_default_audio_stream(self):
        """When no preferred language, uses default stream."""
        probe_data = {
            "audio_streams": [
                {"language": "eng", "default": False},
                {"language": "ger", "default": True},
            ],
            "subtitle_streams": [],
        }

        result = select_streams_for_user(probe_data, preferred_audio_languages=["fr"])
        # No match for French, should fall back to default (index 1)
        assert result["audio_stream"] == 1

    def test_select_matched_audio_stream(self):
        """Preferred language matches an audio stream."""
        probe_data = {
            "audio_streams": [
                {"language": "eng", "default": True},
                {"language": "ger", "default": False},
            ],
            "subtitle_streams": [],
        }

        result = select_streams_for_user(probe_data, preferred_audio_languages=["de"])
        assert result["audio_stream"] == 1

    def test_select_subtitle_stream(self):
        """Subtitle stream is selected by language preference."""
        probe_data = {
            "audio_streams": [{"language": "eng", "default": True}],
            "subtitle_streams": [
                {"language": "eng", "forced": False},
                {"language": "ger", "forced": False},
            ],
        }

        result = select_streams_for_user(
            probe_data,
            preferred_audio_languages=["en"],
            preferred_subtitle_language="de",
        )
        assert result["subtitle_stream"] == 1

    def test_empty_probe_data_returns_defaults(self):
        """Empty probe data returns default indices."""
        result = select_streams_for_user({})
        assert result["audio_stream"] == 0
        assert result["subtitle_stream"] is None

    def test_none_probe_data_returns_defaults(self):
        """None probe data returns default indices."""
        result = select_streams_for_user(None)
        assert result["audio_stream"] == 0
        assert result["subtitle_stream"] is None

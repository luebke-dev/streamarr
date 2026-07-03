"""Tests for play.py (negotiate_codecs + resolve_play_action)."""

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyrate.services.play import (
    CodecNegotiationResult,
    PlayAction,
    build_stream_info,
    extract_source_info,
    negotiate_codecs,
    select_streams_for_user,
)


# ---------------------------------------------------------------------------
# Helper to create a minimal fake MediaFile
# ---------------------------------------------------------------------------

def _fake_file(codec="h264", height=1080, width=1920):
    return SimpleNamespace(
        codec=codec,
        height=height,
        width=width,
        file_path="/data/movies/test.mkv",
        probe_data=None,
    )


def _source_info(video_codec="h264", audio_codec="aac", height=1080):
    return {"video_codec": video_codec, "audio_codec": audio_codec, "height": height}


# ---------------------------------------------------------------------------
# negotiate_codecs — video codec selection
# ---------------------------------------------------------------------------

class TestNegotiateCodecsVideo:
    def test_copy_when_source_matches_client(self):
        result = negotiate_codecs(
            source_info=_source_info("h264"),
            probe_data={},
            file=_fake_file("h264"),
            supported_video_codecs="h264,h265",
            supported_audio_codecs=None,
            client_max_resolution=None,
        )
        assert result.video_codec == "copy"

    def test_copy_hevc_to_h265(self):
        result = negotiate_codecs(
            source_info=_source_info("hevc"),
            probe_data={},
            file=_fake_file("hevc"),
            supported_video_codecs="h265,h264",
            supported_audio_codecs=None,
            client_max_resolution=None,
        )
        assert result.video_codec == "copy"

    def test_transcode_when_source_not_in_client(self):
        result = negotiate_codecs(
            source_info=_source_info("av1"),
            probe_data={},
            file=_fake_file("av1"),
            supported_video_codecs="h264",
            supported_audio_codecs=None,
            client_max_resolution=None,
        )
        assert result.video_codec == "h264"

    def test_fallback_to_h264(self):
        result = negotiate_codecs(
            source_info=_source_info("mpeg2video"),
            probe_data={},
            file=_fake_file("mpeg2"),
            supported_video_codecs="somethingweird",
            supported_audio_codecs=None,
            client_max_resolution=None,
        )
        assert result.video_codec == "h264"

    def test_no_supported_codecs_uses_default(self):
        result = negotiate_codecs(
            source_info=_source_info("h264"),
            probe_data={},
            file=_fake_file(),
            supported_video_codecs=None,
            supported_audio_codecs=None,
            client_max_resolution=None,
        )
        assert result.video_codec == "h264"  # default requested codec

    def test_resolution_limit_prevents_copy(self):
        """When source is 4K but client max is 1080p, should not copy."""
        result = negotiate_codecs(
            source_info=_source_info("h264", height=2160),
            probe_data={},
            file=_fake_file("h264", height=2160),
            supported_video_codecs="h264",
            supported_audio_codecs=None,
            client_max_resolution="1080p",
        )
        assert result.video_codec == "h264"
        assert result.resolution == "1920x1080"

    def test_resolution_limit_allows_copy_when_below(self):
        """When source is 1080p and client max is 4K, copy is fine."""
        result = negotiate_codecs(
            source_info=_source_info("h264", height=1080),
            probe_data={},
            file=_fake_file("h264", height=1080),
            supported_video_codecs="h264",
            supported_audio_codecs=None,
            client_max_resolution="4k",
        )
        assert result.video_codec == "copy"


# ---------------------------------------------------------------------------
# negotiate_codecs — audio codec selection
# ---------------------------------------------------------------------------

class TestNegotiateCodecsAudio:
    def test_copy_when_source_aac(self):
        result = negotiate_codecs(
            source_info=_source_info(audio_codec="aac"),
            probe_data={"streams": []},
            file=_fake_file(),
            supported_video_codecs=None,
            supported_audio_codecs="aac,opus",
            client_max_resolution=None,
        )
        assert result.audio_codec == "copy"

    def test_transcode_ac3_to_aac(self):
        result = negotiate_codecs(
            source_info=_source_info(audio_codec="ac3"),
            probe_data={"streams": []},
            file=_fake_file(),
            supported_video_codecs=None,
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )
        assert result.audio_codec == "aac"

    def test_transcode_dts_to_aac(self):
        result = negotiate_codecs(
            source_info=_source_info(audio_codec="dts"),
            probe_data={"streams": []},
            file=_fake_file(),
            supported_video_codecs=None,
            supported_audio_codecs="aac,opus",
            client_max_resolution=None,
        )
        assert result.audio_codec == "aac"

    def test_copy_opus(self):
        result = negotiate_codecs(
            source_info=_source_info(audio_codec="opus"),
            probe_data={"streams": []},
            file=_fake_file(),
            supported_video_codecs=None,
            supported_audio_codecs="opus,aac",
            client_max_resolution=None,
        )
        assert result.audio_codec == "copy"

    def test_no_probe_data_uses_default(self):
        result = negotiate_codecs(
            source_info=_source_info(audio_codec="truehd"),
            probe_data=None,
            file=_fake_file(),
            supported_video_codecs=None,
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )
        assert result.audio_codec == "aac"  # default


# ---------------------------------------------------------------------------
# negotiate_codecs — resolution
# ---------------------------------------------------------------------------

class TestNegotiateCodecsResolution:
    def test_explicit_resolution(self):
        result = negotiate_codecs(
            source_info=_source_info(),
            probe_data={},
            file=_fake_file(),
            supported_video_codecs=None,
            supported_audio_codecs=None,
            client_max_resolution=None,
            requested_resolution="1280x720",
        )
        assert result.resolution == "1280x720"

    def test_resolution_from_client_max_when_transcoding(self):
        result = negotiate_codecs(
            source_info=_source_info("av1"),
            probe_data={},
            file=_fake_file("av1"),
            supported_video_codecs="h264",
            supported_audio_codecs=None,
            client_max_resolution="720p",
        )
        assert result.resolution == "1280x720"

    def test_no_resolution_limit_when_copy(self):
        result = negotiate_codecs(
            source_info=_source_info("h264", height=720),
            probe_data={},
            file=_fake_file("h264", height=720),
            supported_video_codecs="h264",
            supported_audio_codecs=None,
            client_max_resolution="1080p",
        )
        assert result.video_codec == "copy"
        # resolution should be None when copying
        assert result.resolution is None


# ---------------------------------------------------------------------------
# CodecNegotiationResult dataclass
# ---------------------------------------------------------------------------

class TestCodecNegotiationResult:
    def test_defaults(self):
        r = CodecNegotiationResult(video_codec="h264", audio_codec="aac", resolution=None)
        assert r.transcode_reasons == []

    def test_with_reasons(self):
        r = CodecNegotiationResult(
            video_codec="h264",
            audio_codec="aac",
            resolution="1920x1080",
            transcode_reasons=["codec unsupported"],
        )
        assert len(r.transcode_reasons) == 1


class TestPlayAction:
    def test_ready_status(self):
        action = PlayAction(status="ready", message="Ready")
        assert action.file is None
        assert action.download_progress is None

    def test_downloading_status(self):
        action = PlayAction(
            status="downloading",
            message="Downloading...",
            download_progress=45.0,
            download_status="Downloading",
        )
        assert action.download_progress == 45.0


# ---------------------------------------------------------------------------
# Helpers for new test sections
# ---------------------------------------------------------------------------

def _structured_probe(
    video_codec="h264",
    audio_codec="aac",
    width=1920,
    height=1080,
    pix_fmt="yuv420p",
    audio_language="eng",
):
    """Build canonical structured probe_data."""
    return {
        "video_streams": [
            {
                "codec_name": video_codec,
                "width": width,
                "height": height,
                "pix_fmt": pix_fmt,
                "index": 0,
            }
        ],
        "audio_streams": [
            {
                "codec_name": audio_codec,
                "language": audio_language,
                "index": 0,
                "default": True,
            }
        ],
        "subtitle_streams": [],
    }


def _make_file(
    codec="h264",
    width=1920,
    height=1080,
    file_path="/library/movies/test.mkv",
    file_size=5_000_000_000,
    duration=7200.0,
):
    return SimpleNamespace(
        codec=codec,
        width=width,
        height=height,
        file_path=file_path,
        file_size=file_size,
        duration=duration,
    )


# ---------------------------------------------------------------------------
# extract_source_info
# ---------------------------------------------------------------------------

class TestExtractSourceInfo:
    def test_no_probe_data_no_file(self):
        info = extract_source_info(None, file=None)
        assert info["video_codec"] is None
        assert info["audio_codec"] is None
        assert info["bit_depth"] == 8

    def test_no_probe_data_with_file(self):
        f = _make_file(codec="hevc", width=3840, height=2160)
        info = extract_source_info(None, file=f)
        assert info["video_codec"] == "hevc"
        assert info["width"] == 3840
        assert info["height"] == 2160

    def test_structured_format_basic(self):
        probe = _structured_probe(video_codec="hevc", audio_codec="ac3")
        info = extract_source_info(probe)
        assert info["video_codec"] == "hevc"
        assert info["audio_codec"] == "ac3"
        assert info["bit_depth"] == 8
        assert info["width"] == 1920
        assert info["height"] == 1080

    def test_structured_format_10bit(self):
        probe = _structured_probe(pix_fmt="yuv420p10le")
        info = extract_source_info(probe)
        assert info["bit_depth"] == 10

    def test_structured_format_12bit(self):
        probe = _structured_probe(pix_fmt="yuv420p12le")
        info = extract_source_info(probe)
        assert info["bit_depth"] == 12

    def test_structured_format_p010(self):
        probe = _structured_probe(pix_fmt="p010le")
        info = extract_source_info(probe)
        assert info["bit_depth"] == 10

    def test_raw_ffprobe_streams_format(self):
        probe = {
            "streams": [
                {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p", "width": 3840, "height": 2160},
                {"codec_type": "audio", "codec_name": "truehd"},
            ]
        }
        info = extract_source_info(probe)
        assert info["video_codec"] == "hevc"
        assert info["audio_codec"] == "truehd"
        assert info["width"] == 3840

    def test_raw_ffprobe_10bit(self):
        probe = {
            "streams": [
                {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le", "width": 1920, "height": 1080},
            ]
        }
        info = extract_source_info(probe)
        assert info["bit_depth"] == 10

    def test_legacy_flat_dict_format(self):
        probe = {
            "video_codec": "h264",
            "audio_codec": "AAC",
            "width": 1920,
            "height": 1080,
        }
        info = extract_source_info(probe)
        assert info["video_codec"] == "h264"
        assert info["audio_codec"] == "aac"  # lowercased

    def test_legacy_flat_dict_hdr(self):
        probe = {
            "video_codec": "hevc",
            "hdr_format": "Dolby Vision",
            "width": 3840,
            "height": 2160,
        }
        info = extract_source_info(probe)
        assert info["bit_depth"] == 10

    def test_fallback_to_file_codec(self):
        probe = {"video_streams": [], "audio_streams": []}
        f = _make_file(codec="vp9")
        info = extract_source_info(probe, file=f)
        assert info["video_codec"] == "vp9"

    def test_structured_uses_first_video_stream(self):
        probe = {
            "video_streams": [
                {"codec_name": "h264", "width": 1920, "height": 1080, "pix_fmt": "yuv420p"},
                {"codec_name": "mjpeg", "width": 320, "height": 240, "pix_fmt": "yuvj420p"},
            ],
            "audio_streams": [],
            "subtitle_streams": [],
        }
        info = extract_source_info(probe)
        assert info["video_codec"] == "h264"
        assert info["width"] == 1920

    def test_raw_streams_picks_first_per_type(self):
        probe = {
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "width": 1920, "height": 1080},
                {"codec_type": "audio", "codec_name": "ac3"},
            ]
        }
        info = extract_source_info(probe)
        assert info["video_codec"] == "h264"
        assert info["audio_codec"] == "aac"


# ---------------------------------------------------------------------------
# select_streams_for_user
# ---------------------------------------------------------------------------

class TestSelectStreamsForUser:
    def test_empty_probe_data(self):
        result = select_streams_for_user(None)
        assert result["audio_stream"] == 0
        assert result["subtitle_stream"] is None

    def test_default_first_audio_stream(self):
        probe = _structured_probe()
        result = select_streams_for_user(probe)
        assert result["audio_stream"] == 0

    def test_preferred_audio_language_match(self):
        probe = {
            "audio_streams": [
                {"codec_name": "aac", "language": "eng", "index": 0},
                {"codec_name": "aac", "language": "deu", "index": 1},
                {"codec_name": "aac", "language": "jpn", "index": 2},
            ],
            "subtitle_streams": [],
        }
        result = select_streams_for_user(probe, preferred_audio_languages=["deu"])
        assert result["audio_stream"] == 1

    def test_preferred_audio_no_match_uses_default(self):
        probe = {
            "audio_streams": [
                {"codec_name": "aac", "language": "eng", "index": 0},
                {"codec_name": "aac", "language": "deu", "index": 1, "default": True},
            ],
            "subtitle_streams": [],
        }
        result = select_streams_for_user(probe, preferred_audio_languages=["fra"])
        assert result["audio_stream"] == 1

    def test_preferred_subtitle_language(self):
        probe = {
            "audio_streams": [{"codec_name": "aac", "language": "jpn", "index": 0}],
            "subtitle_streams": [
                {"language": "eng", "index": 0, "forced": False},
                {"language": "deu", "index": 1, "forced": False},
            ],
        }
        result = select_streams_for_user(
            probe,
            preferred_audio_languages=["jpn"],
            preferred_subtitle_language="deu",
        )
        assert result["subtitle_stream"] == 1

    def test_subtitle_prefers_non_forced(self):
        probe = {
            "audio_streams": [{"codec_name": "aac", "language": "eng", "index": 0}],
            "subtitle_streams": [
                {"language": "eng", "index": 0, "forced": True},
                {"language": "eng", "index": 1, "forced": False},
            ],
        }
        result = select_streams_for_user(probe, preferred_subtitle_language="eng")
        assert result["subtitle_stream"] == 1

    def test_subtitle_forced_only_option(self):
        probe = {
            "audio_streams": [{"codec_name": "aac", "language": "eng", "index": 0}],
            "subtitle_streams": [
                {"language": "eng", "index": 0, "forced": True},
            ],
        }
        result = select_streams_for_user(probe, preferred_subtitle_language="eng")
        assert result["subtitle_stream"] == 0

    def test_no_subtitle_preference(self):
        probe = {
            "audio_streams": [{"codec_name": "aac", "language": "eng", "index": 0}],
            "subtitle_streams": [
                {"language": "eng", "index": 0, "forced": False},
            ],
        }
        result = select_streams_for_user(probe, preferred_subtitle_language=None)
        assert result["subtitle_stream"] is None

    def test_subtitle_no_match(self):
        probe = {
            "audio_streams": [{"codec_name": "aac", "language": "eng", "index": 0}],
            "subtitle_streams": [
                {"language": "eng", "index": 0, "forced": False},
            ],
        }
        result = select_streams_for_user(probe, preferred_subtitle_language="jpn")
        assert result["subtitle_stream"] is None

    def test_partial_language_match(self):
        probe = {
            "audio_streams": [
                {"codec_name": "aac", "language": "deu", "index": 0},
            ],
            "subtitle_streams": [],
        }
        result = select_streams_for_user(probe, preferred_audio_languages=["de"])
        assert result["audio_stream"] == 0

    def test_empty_streams(self):
        probe = {"audio_streams": [], "subtitle_streams": []}
        result = select_streams_for_user(probe, preferred_audio_languages=["en"])
        assert result["audio_stream"] == 0
        assert result["subtitle_stream"] is None


# ---------------------------------------------------------------------------
# build_stream_info
# ---------------------------------------------------------------------------

class TestBuildStreamInfo:
    def test_basic_transcode(self):
        f = _make_file(codec="hevc", width=3840, height=2160)
        probe = _structured_probe(video_codec="hevc", audio_codec="truehd", width=3840, height=2160)
        result = build_stream_info(
            file=f,
            probe_data=probe,
            effective_video_codec="h264",
            effective_audio_codec="aac",
            effective_resolution="1920x1080",
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution="1080p",
        )
        assert result["source_file"]["video_codec"] == "hevc"
        assert result["source_file"]["audio_codec"] == "truehd"
        assert result["transcoding"]["video_codec"] == "h264"
        assert result["transcoding"]["audio_codec"] == "aac"
        assert result["transcoding"]["resolution"] == "1920x1080"
        assert len(result["transcoding_reasons"]) > 0
        assert result["client_capabilities"]["max_resolution"] == "1080p"

    def test_copy_no_transcode_reasons(self):
        f = _make_file()
        probe = _structured_probe()
        result = build_stream_info(
            file=f,
            probe_data=probe,
            effective_video_codec="copy",
            effective_audio_codec="copy",
            effective_resolution=None,
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )
        assert result["transcoding"]["video_codec"] == "copy"
        assert result["transcoding"]["audio_codec"] == "copy"
        assert len(result["transcoding_reasons"]) == 0

    def test_unsupported_codec_reason(self):
        f = _make_file(codec="hevc")
        probe = _structured_probe(video_codec="hevc")
        result = build_stream_info(
            file=f,
            probe_data=probe,
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
        assert any("hevc" in r.lower() or "nicht" in r.lower() for r in reasons)

    def test_10bit_reason(self):
        f = _make_file()
        probe = _structured_probe(pix_fmt="yuv420p10le")
        result = build_stream_info(
            file=f,
            probe_data=probe,
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

    def test_surround_audio_reason(self):
        f = _make_file()
        probe = _structured_probe(audio_codec="dts")
        result = build_stream_info(
            file=f,
            probe_data=probe,
            effective_video_codec="copy",
            effective_audio_codec="aac",
            effective_resolution=None,
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )
        reasons = result["transcoding_reasons"]
        assert any("dts" in r.lower() for r in reasons)

    def test_resolution_reason(self):
        f = _make_file(width=3840, height=2160)
        probe = _structured_probe(width=3840, height=2160)
        result = build_stream_info(
            file=f,
            probe_data=probe,
            effective_video_codec="h264",
            effective_audio_codec="copy",
            effective_resolution="1920x1080",
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution="1080p",
        )
        reasons = result["transcoding_reasons"]
        assert any("1920x1080" in r for r in reasons)

    def test_source_file_metadata(self):
        f = _make_file(file_size=2_000_000, duration=3600.0, file_path="/lib/movie.mkv")
        probe = _structured_probe()
        result = build_stream_info(
            file=f,
            probe_data=probe,
            effective_video_codec="copy",
            effective_audio_codec="copy",
            effective_resolution=None,
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs=None,
            supported_audio_codecs=None,
            client_max_resolution=None,
        )
        assert result["source_file"]["file_name"] == "movie.mkv"
        assert result["source_file"]["file_size"] == 2_000_000
        assert result["source_file"]["duration"] == 3600.0

    def test_eac3_audio_reason(self):
        f = _make_file()
        probe = _structured_probe(audio_codec="eac3")
        result = build_stream_info(
            file=f,
            probe_data=probe,
            effective_video_codec="copy",
            effective_audio_codec="aac",
            effective_resolution=None,
            video_codec="h264",
            audio_codec="aac",
            supported_video_codecs="h264",
            supported_audio_codecs="aac",
            client_max_resolution=None,
        )
        reasons = result["transcoding_reasons"]
        assert any("eac3" in r.lower() for r in reasons)


# ---------------------------------------------------------------------------
# resolve_play_action (integration with mocked DB / workers)
# ---------------------------------------------------------------------------

class TestResolvePlayAction:
    @pytest.mark.asyncio
    async def test_file_exists_returns_ready(self, db_session, tmp_path):
        from pyrate.models.media import MediaFile, MediaItem, MediaType
        from pyrate.services.play import resolve_play_action

        media_id = uuid.uuid4()
        item = MediaItem(guid=media_id, title="Test Movie", media_type=MediaType.MOVIES)
        db_session.add(item)
        await db_session.flush()

        video = tmp_path / "movie.mkv"
        video.write_bytes(b"\x00" * 100)

        mf = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=media_id,
            file_path=str(video),
            file_size=100,
            codec="h264",
            width=1920,
            height=1080,
            probe_data=json.dumps(
                {
                    "streams": [
                        {"codec_type": "video", "codec_name": "h264", "index": 0},
                        {"codec_type": "audio", "codec_name": "aac", "index": 1},
                    ]
                }
            ),
        )
        db_session.add(mf)
        await db_session.commit()

        action = await resolve_play_action(db_session, item, media_id)
        assert action.status == "ready"
        assert action.file_path == str(video)

    @pytest.mark.asyncio
    async def test_no_file_no_releases_triggers_search(self, db_session):
        from pyrate.models.media import MediaItem, MediaType
        from pyrate.services.play import resolve_play_action

        media_id = uuid.uuid4()
        item = MediaItem(guid=media_id, title="Unknown Movie", media_type=MediaType.MOVIES)
        db_session.add(item)
        await db_session.commit()

        with patch("pyrate.worker.search_media_item_releases") as mock_search:
            mock_search.kiq = AsyncMock()
            action = await resolve_play_action(db_session, item, media_id)
            assert action.status == "searching"
            mock_search.kiq.assert_awaited_once()

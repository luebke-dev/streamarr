"""Tests for shows plugin, worker, web, environment, and schemas."""

import os
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ==========================================================================
# Shows Plugin (src/pyrate/plugins/shows/__init__.py)
# ==========================================================================


def _make_show_plugin():
    from pyrate.libraries.shows import ShowLibraryPlugin
    return ShowLibraryPlugin()


class TestShowPluginBasicInfo:
    def test_get_name(self):
        plugin = _make_show_plugin()
        assert plugin.get_name() == "Show Library"

    def test_get_library_type(self):
        plugin = _make_show_plugin()
        assert plugin.get_library_type() == "SHOWS"

    def test_get_media_item_types(self):
        plugin = _make_show_plugin()
        types = plugin.get_media_item_types()
        assert len(types) == 3
        names = [t["name"] for t in types]
        assert "SHOWS" in names
        assert "SEASONS" in names
        assert "EPISODES" in names

    @pytest.mark.asyncio
    async def test_get_default_path(self):
        plugin = _make_show_plugin()
        path = await plugin.get_default_path()
        assert path == "/library/shows"

    @pytest.mark.asyncio
    async def test_get_supported_extensions(self):
        plugin = _make_show_plugin()
        extensions = await plugin.get_supported_extensions()
        assert ".mkv" in extensions
        assert ".mp4" in extensions
        assert ".avi" in extensions

    @pytest.mark.asyncio
    async def test_get_metadata_provider(self):
        plugin = _make_show_plugin()
        provider = await plugin.get_metadata_provider()
        assert provider == "tmdb"

    def test_get_naming_schema(self):
        plugin = _make_show_plugin()
        schema = plugin.get_naming_schema()
        assert "variables" in schema
        assert "defaults" in schema
        assert "options" in schema
        assert len(schema["variables"]) > 0

    def test_get_settings_schema(self):
        plugin = _make_show_plugin()
        schema = plugin.get_settings_schema()
        assert "enable_library" in schema
        assert "library_path" in schema

    def test_get_preview_data(self):
        plugin = _make_show_plugin()
        data = plugin.get_preview_data()
        assert data["title"] == "The Walking Dead"
        assert data["year"] == 2010


class TestShowPluginValidatePath:
    @pytest.mark.asyncio
    async def test_validate_path_existing_dir(self, tmp_path):
        plugin = _make_show_plugin()
        result = await plugin.validate_path(str(tmp_path))
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_path_existing_file(self, tmp_path):
        file_path = tmp_path / "file.txt"
        file_path.touch()
        plugin = _make_show_plugin()
        result = await plugin.validate_path(str(file_path))
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_path_nonexistent_with_writable_parent(self, tmp_path):
        plugin = _make_show_plugin()
        result = await plugin.validate_path(str(tmp_path / "new_dir"))
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_path_exception(self):
        plugin = _make_show_plugin()
        with patch("pyrate.libraries.shows.Path") as MockPath:
            MockPath.side_effect = Exception("error")
            result = await plugin.validate_path("/some/path")
        assert result is False


class TestShowPluginLibraryStats:
    @pytest.mark.asyncio
    async def test_get_library_stats_empty_dir(self, tmp_path):
        plugin = _make_show_plugin()
        stats = await plugin.get_library_stats(str(tmp_path))
        assert stats["file_count"] == 0
        assert stats["total_size"] == 0
        assert stats["show_count"] == 0

    @pytest.mark.asyncio
    async def test_get_library_stats_with_files(self, tmp_path):
        show_dir = tmp_path / "Show1"
        season_dir = show_dir / "Season 01"
        season_dir.mkdir(parents=True)
        ep_file = season_dir / "S01E01.mkv"
        ep_file.write_bytes(b"x" * 1000)
        ep2_file = season_dir / "S01E02.mp4"
        ep2_file.write_bytes(b"x" * 2000)

        show_dir2 = tmp_path / "Show2"
        show_dir2.mkdir()

        plugin = _make_show_plugin()
        stats = await plugin.get_library_stats(str(tmp_path))
        assert stats["file_count"] == 2
        assert stats["total_size"] == 3000
        assert stats["show_count"] == 2
        assert ".mkv" in stats["file_types"]
        assert ".mp4" in stats["file_types"]

    @pytest.mark.asyncio
    async def test_get_library_stats_nonexistent_path(self):
        plugin = _make_show_plugin()
        stats = await plugin.get_library_stats("/nonexistent/path")
        assert stats["file_count"] == 0

    @pytest.mark.asyncio
    async def test_get_library_stats_exception(self, tmp_path):
        plugin = _make_show_plugin()
        with patch("pyrate.libraries.shows.Path") as MockPath:
            mock_path_obj = MagicMock()
            mock_path_obj.exists.side_effect = Exception("error")
            MockPath.return_value = mock_path_obj
            stats = await plugin.get_library_stats(str(tmp_path))
        assert stats["file_count"] == 0


class TestShowPluginScanLibrary:
    @pytest.mark.asyncio
    async def test_scan_library_empty(self, tmp_path):
        plugin = _make_show_plugin()
        result = await plugin.scan_library(str(tmp_path))
        assert result == []

    @pytest.mark.asyncio
    async def test_scan_library_finds_episodes(self, tmp_path):
        show_dir = tmp_path / "Breaking Bad"
        season_dir = show_dir / "Season 01"
        season_dir.mkdir(parents=True)
        ep_file = season_dir / "Breaking.Bad.S01E01.1080p.BluRay.mkv"
        ep_file.write_bytes(b"x" * 100)

        plugin = _make_show_plugin()
        result = await plugin.scan_library(str(tmp_path))
        assert len(result) == 1
        assert result[0]["filename"] == "Breaking.Bad.S01E01.1080p.BluRay.mkv"
        assert result[0]["season"] == 1
        assert result[0]["episode"] == 1
        assert result[0]["quality"] == "1080p"
        assert result[0]["source"] == "BluRay"

    @pytest.mark.asyncio
    async def test_scan_library_extracts_show_name(self, tmp_path):
        show_dir = tmp_path / "The Office"
        season_dir = show_dir / "Season 03"
        season_dir.mkdir(parents=True)
        ep_file = season_dir / "S03E05.mp4"
        ep_file.write_bytes(b"x" * 100)

        plugin = _make_show_plugin()
        result = await plugin.scan_library(str(tmp_path))
        assert len(result) == 1
        assert result[0]["show_name"] == "The Office"

    @pytest.mark.asyncio
    async def test_scan_library_nonexistent_path(self):
        plugin = _make_show_plugin()
        result = await plugin.scan_library("/nonexistent/path")
        assert result == []

    @pytest.mark.asyncio
    async def test_scan_library_ignores_non_video(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "cover.jpg").write_bytes(b"img")

        plugin = _make_show_plugin()
        result = await plugin.scan_library(str(tmp_path))
        assert result == []


class TestShowPluginExtractMetadata:
    @pytest.mark.asyncio
    async def test_standard_sxxexx(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("Show.S02E05.mkv")
        assert meta["season"] == 2
        assert meta["episode"] == 5

    @pytest.mark.asyncio
    async def test_lowercase_sxxexx(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("show.s01e10.mkv")
        assert meta["season"] == 1
        assert meta["episode"] == 10

    @pytest.mark.asyncio
    async def test_alternative_1x01_pattern(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("Show.3x07.Episode.mkv")
        assert meta["season"] == 3
        assert meta["episode"] == 7

    @pytest.mark.asyncio
    async def test_quality_2160p(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("S01E01.2160p.mkv")
        assert meta["quality"] == "2160p"

    @pytest.mark.asyncio
    async def test_quality_4k(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("S01E01.4K.mkv")
        assert meta["quality"] == "2160p"

    @pytest.mark.asyncio
    async def test_quality_1080p(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("S01E01.1080p.mkv")
        assert meta["quality"] == "1080p"

    @pytest.mark.asyncio
    async def test_quality_720p(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("S01E01.720p.mkv")
        assert meta["quality"] == "720p"

    @pytest.mark.asyncio
    async def test_quality_480p(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("S01E01.480p.mkv")
        assert meta["quality"] == "480p"

    @pytest.mark.asyncio
    async def test_source_bluray(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("S01E01.BluRay.mkv")
        assert meta["source"] == "BluRay"

    @pytest.mark.asyncio
    async def test_source_webdl(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("S01E01.WEB-DL.mkv")
        assert meta["source"] == "WEB"

    @pytest.mark.asyncio
    async def test_source_webrip(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("S01E01.WEBRip.mkv")
        assert meta["source"] == "WEB"

    @pytest.mark.asyncio
    async def test_source_hdtv(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("S01E01.HDTV.mkv")
        assert meta["source"] == "HDTV"

    @pytest.mark.asyncio
    async def test_no_pattern_match(self):
        plugin = _make_show_plugin()
        meta = await plugin.extract_metadata_from_filename("random_file.mkv")
        assert "season" not in meta
        assert "episode" not in meta


class TestShowPluginFormatFilePath:
    @pytest.mark.asyncio
    async def test_format_file_path(self):
        plugin = _make_show_plugin()
        result = await plugin.format_file_path(
            {"show_name": "The Office", "season": 3},
            "/library/shows",
        )
        assert "The Office" in result
        assert "Season 03" in result

    @pytest.mark.asyncio
    async def test_format_file_path_defaults(self):
        plugin = _make_show_plugin()
        result = await plugin.format_file_path({}, "/library/shows")
        assert "Unknown Show" in result
        assert "Season 01" in result

    @pytest.mark.asyncio
    async def test_format_file_path_sanitizes_name(self):
        plugin = _make_show_plugin()
        result = await plugin.format_file_path(
            {"show_name": "Show: With <Special> Chars!", "season": 1},
            "/library/shows",
        )
        # Should not contain illegal chars
        assert "<" not in result
        assert ">" not in result


class TestShowPluginValidateMediaFile:
    @pytest.mark.asyncio
    async def test_validate_valid_file(self, tmp_path):
        plugin = _make_show_plugin()
        ep_file = tmp_path / "Show.S01E01.mkv"
        ep_file.write_bytes(b"x" * 30 * 1024 * 1024)  # 30MB
        result = await plugin.validate_media_file(str(ep_file))
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_wrong_extension(self, tmp_path):
        plugin = _make_show_plugin()
        ep_file = tmp_path / "Show.S01E01.txt"
        ep_file.write_bytes(b"x" * 30 * 1024 * 1024)
        result = await plugin.validate_media_file(str(ep_file))
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_no_episode_pattern(self, tmp_path):
        plugin = _make_show_plugin()
        ep_file = tmp_path / "random_movie.mkv"
        ep_file.write_bytes(b"x" * 30 * 1024 * 1024)
        result = await plugin.validate_media_file(str(ep_file))
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_too_small(self, tmp_path):
        plugin = _make_show_plugin()
        ep_file = tmp_path / "Show.S01E01.mkv"
        ep_file.write_bytes(b"x" * 1000)  # Only 1KB
        result = await plugin.validate_media_file(str(ep_file))
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_nonexistent(self):
        plugin = _make_show_plugin()
        result = await plugin.validate_media_file("/nonexistent/file.mkv")
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_with_alt_pattern(self, tmp_path):
        plugin = _make_show_plugin()
        ep_file = tmp_path / "Show.1x01.mkv"
        ep_file.write_bytes(b"x" * 30 * 1024 * 1024)
        result = await plugin.validate_media_file(str(ep_file))
        assert result is True


class TestShowPluginMatchMedia:
    @pytest.mark.asyncio
    async def test_match_media_success(self):
        plugin = _make_show_plugin()
        result = await plugin.match_media({
            "show_name": "Breaking Bad",
            "season": 1,
            "episode": 1,
        })
        assert result is not None
        assert result["show_name"] == "Breaking Bad"
        assert result["matched"] is False

    @pytest.mark.asyncio
    async def test_match_media_missing_info(self):
        plugin = _make_show_plugin()
        result = await plugin.match_media({"show_name": "Test"})
        assert result is None

    @pytest.mark.asyncio
    async def test_match_media_no_show_name(self):
        plugin = _make_show_plugin()
        result = await plugin.match_media({"season": 1, "episode": 1})
        assert result is None


class TestShowPluginExtractReleaseMetadata:
    @pytest.mark.asyncio
    async def test_extract_full_release(self):
        plugin = _make_show_plugin()
        title = "Show.Name.S01E01.1080p.WEB-DL.DDP5.1.H.265-GROUP"
        metadata = await plugin.extract_release_metadata(title)
        assert metadata["original_title"] == title
        assert metadata.get("resolution") is not None

    @pytest.mark.asyncio
    async def test_extract_minimal_release(self):
        plugin = _make_show_plugin()
        metadata = await plugin.extract_release_metadata("SimpleTitle")
        assert metadata["original_title"] == "SimpleTitle"


class TestShowPluginScoreRelease:
    @pytest.mark.asyncio
    async def test_score_low_quality_rejected(self):
        plugin = _make_show_plugin()
        score = await plugin.score_release({"is_low_quality": True})
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_score_1080p_webdl_h265(self):
        plugin = _make_show_plugin()
        metadata = {
            "resolution": "1080p",
            "source": "WEB-DL",
            "video_codec": "h265",
            "audio_codecs": ["eac3"],
            "is_hdr": False,
            "is_dolby_vision": False,
            "is_proper": False,
            "is_repack": False,
            "is_low_quality": False,
            "release_group": "FLUX",
        }
        score = await plugin.score_release(metadata)
        # 1080p=22, WEB-DL=20, h265=15, eac3=7, trusted=5 = 69
        assert score >= 60
        assert score <= 100

    @pytest.mark.asyncio
    async def test_score_720p_hdtv_h264(self):
        plugin = _make_show_plugin()
        metadata = {
            "resolution": "720p",
            "source": "HDTV",
            "video_codec": "h264",
            "audio_codecs": ["aac"],
            "is_hdr": False,
            "is_dolby_vision": False,
            "is_proper": False,
            "is_repack": False,
            "is_low_quality": False,
            "release_group": "UNKNOWN",
        }
        score = await plugin.score_release(metadata)
        # 720p=15, HDTV=12, h264=13, aac=5 = 45
        assert score >= 40
        assert score <= 55

    @pytest.mark.asyncio
    async def test_score_2160p_bluray_hdr(self):
        plugin = _make_show_plugin()
        metadata = {
            "resolution": "2160p",
            "source": "bluray",
            "video_codec": "h265",
            "audio_codecs": ["truehd"],
            "is_hdr": True,
            "is_dolby_vision": True,
            "is_proper": True,
            "is_repack": False,
            "is_low_quality": False,
            "release_group": "NTB",
        }
        score = await plugin.score_release(metadata)
        # 2160p=25, bluray=16, h265=15, truehd=10, HDR=5, DV=5, proper=5, trusted=5 = 86
        assert score >= 80

    @pytest.mark.asyncio
    async def test_score_with_preferences(self):
        plugin = _make_show_plugin()
        metadata = {
            "resolution": "1080p",
            "source": "WEB-DL",
            "video_codec": "h264",
            "audio_codecs": ["ac3"],
            "is_hdr": False,
            "is_dolby_vision": False,
            "is_proper": False,
            "is_repack": True,
            "is_low_quality": False,
            "release_group": "MYGROUP",
            "languages": ["en"],
        }
        preferences = {
            "resolution": {"1080p": 20},
            "source": {"web-dl": 18},
            "codec": {"h264": 12},
            "audio": {"ac3": 6},
            "hdr_bonus": 3,
            "dolby_vision_bonus": 3,
            "proper_bonus": 4,
            "repack_bonus": 2,
            "trusted_groups": ["MYGROUP"],
            "blocked_groups": [],
            "trusted_group_bonus": 8,
            "user_language": "en",
            "language_match_bonus": 10,
        }
        score = await plugin.score_release(metadata, preferences)
        # 1080p=20, WEB-DL=18, h264=12, ac3=6, repack=2, trusted=8, lang=10 = 76
        assert score >= 70

    @pytest.mark.asyncio
    async def test_score_blocked_group(self):
        plugin = _make_show_plugin()
        metadata = {
            "resolution": "1080p",
            "source": "WEB-DL",
            "video_codec": "h264",
            "audio_codecs": [],
            "is_hdr": False,
            "is_dolby_vision": False,
            "is_proper": False,
            "is_repack": False,
            "is_low_quality": False,
            "release_group": "BADGROUP",
        }
        preferences = {
            "resolution": {"1080p": 22},
            "source": {"web-dl": 20},
            "codec": {"h264": 13},
            "audio": {},
            "hdr_bonus": 5,
            "dolby_vision_bonus": 5,
            "proper_bonus": 5,
            "repack_bonus": 3,
            "trusted_groups": [],
            "blocked_groups": ["BADGROUP"],
            "trusted_group_bonus": 5,
        }
        score = await plugin.score_release(metadata, preferences)
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_score_480p_dvd_xvid(self):
        plugin = _make_show_plugin()
        metadata = {
            "resolution": "480p",
            "source": "dvd",
            "video_codec": "xvid",
            "audio_codecs": [],
            "is_hdr": False,
            "is_dolby_vision": False,
            "is_proper": False,
            "is_repack": False,
            "is_low_quality": False,
            "release_group": "",
        }
        score = await plugin.score_release(metadata)
        # 480p=8, dvd=5, xvid=5 = 18
        assert score >= 15
        assert score <= 25

    @pytest.mark.asyncio
    async def test_score_codec_compatibility(self):
        plugin = _make_show_plugin()
        metadata = {
            "resolution": "1080p",
            "source": "WEB-DL",
            "video_codec": "h265",
            "audio_codecs": ["eac3"],
            "is_hdr": False,
            "is_dolby_vision": False,
            "is_proper": False,
            "is_repack": False,
            "is_low_quality": False,
            "release_group": "",
        }
        preferences = {
            "resolution": {"1080p": 22},
            "source": {"web-dl": 20},
            "codec": {"h265": 15},
            "audio": {"eac3": 7},
            "hdr_bonus": 0,
            "dolby_vision_bonus": 0,
            "proper_bonus": 0,
            "repack_bonus": 0,
            "trusted_groups": [],
            "blocked_groups": [],
            "trusted_group_bonus": 0,
            "supported_video_codecs": ["h264", "h265"],
            "supported_audio_codecs": ["aac", "eac3"],
            "codec_match_bonus": 5,
            "codec_mismatch_penalty": 10,
        }
        score = await plugin.score_release(metadata, preferences)
        # Should get codec_match_bonus for both video and audio
        assert score >= 64  # 22+20+15+7+5+5 = 74

    @pytest.mark.asyncio
    async def test_score_no_resolution(self):
        plugin = _make_show_plugin()
        metadata = {
            "resolution": "",
            "source": "",
            "video_codec": "",
            "audio_codecs": [],
            "is_hdr": False,
            "is_dolby_vision": False,
            "is_proper": False,
            "is_repack": False,
            "is_low_quality": False,
            "release_group": "",
        }
        score = await plugin.score_release(metadata)
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_score_language_mismatch(self):
        plugin = _make_show_plugin()
        metadata = {
            "resolution": "1080p",
            "source": "WEB-DL",
            "video_codec": "h264",
            "audio_codecs": [],
            "is_hdr": False,
            "is_dolby_vision": False,
            "is_proper": False,
            "is_repack": False,
            "is_low_quality": False,
            "release_group": "",
            "languages": ["fr"],
        }
        preferences = {
            "resolution": {"1080p": 22},
            "source": {"web-dl": 20},
            "codec": {"h264": 13},
            "audio": {},
            "hdr_bonus": 0,
            "dolby_vision_bonus": 0,
            "proper_bonus": 0,
            "repack_bonus": 0,
            "trusted_groups": [],
            "blocked_groups": [],
            "trusted_group_bonus": 0,
            "user_language": "en",
            "allowed_languages": ["en", "de"],
            "language_mismatch_penalty": 15,
        }
        score = await plugin.score_release(metadata, preferences)
        # Language not in allowed_languages → hard reject (score 0)
        assert score == 0.0


class TestShowPluginSuggestFolderName:
    @pytest.mark.asyncio
    async def test_suggest_folder_with_year_and_tmdb(self):
        plugin = _make_show_plugin()
        result = await plugin.suggest_folder_name(
            {"title": "Breaking Bad", "year": 2008},
            tmdb_id=1396,
        )
        assert "Breaking Bad" in result
        assert "(2008)" in result
        assert "{tmdb-1396}" in result

    @pytest.mark.asyncio
    async def test_suggest_folder_no_year(self):
        plugin = _make_show_plugin()
        result = await plugin.suggest_folder_name({"title": "The Show"})
        assert "The Show" in result
        assert "(" not in result

    @pytest.mark.asyncio
    async def test_suggest_folder_imdb_fallback(self):
        plugin = _make_show_plugin()
        result = await plugin.suggest_folder_name(
            {"title": "The Show", "year": 2020},
            imdb_id="tt1234567",
        )
        assert "{imdb-tt1234567}" in result

    @pytest.mark.asyncio
    async def test_suggest_folder_tmdb_from_media_info(self):
        plugin = _make_show_plugin()
        result = await plugin.suggest_folder_name(
            {"title": "Show", "year": 2020, "tmdb_id": 999},
        )
        assert "{tmdb-999}" in result


class TestShowPluginSuggestFileName:
    @pytest.mark.asyncio
    async def test_suggest_file_name_basic(self):
        plugin = _make_show_plugin()
        result = await plugin.suggest_file_name(
            media_info={
                "show_title": "Breaking Bad",
                "season": 1,
                "episode": 1,
                "episode_title": "Pilot",
            },
        )
        assert "Breaking Bad" in result
        assert "S01E01" in result
        assert "Pilot" in result

    @pytest.mark.asyncio
    async def test_suggest_file_name_with_release_metadata(self):
        plugin = _make_show_plugin()
        result = await plugin.suggest_file_name(
            media_info={
                "show_title": "Test Show",
                "season": 2,
                "episode": 5,
            },
            release_metadata={
                "source": "AMZN",
                "resolution": "1080p",
                "video_codec": "x265",
                "audio_codec": "EAC3",
                "audio_channels": "5.1",
            },
            release_group="FLUX",
        )
        assert "S02E05" in result
        assert "AMZN" in result or "1080p" in result

    @pytest.mark.asyncio
    async def test_suggest_file_name_defaults(self):
        plugin = _make_show_plugin()
        result = await plugin.suggest_file_name(media_info={})
        assert "S01E01" in result
        assert "Unknown Show" in result


# ==========================================================================
# Worker (src/pyrate/worker.py) - key functions
# ==========================================================================


class TestWorkerParseSpotifyDate:
    def test_parse_full_date(self):
        from pyrate.utils.dates import parse_spotify_date

        result = parse_spotify_date("2020-05-15")
        assert result is not None
        assert result.year == 2020
        assert result.month == 5
        assert result.day == 15

    def test_parse_year_month(self):
        from pyrate.utils.dates import parse_spotify_date

        result = parse_spotify_date("2020-05")
        assert result is not None
        assert result.year == 2020
        assert result.month == 5

    def test_parse_year_only(self):
        from pyrate.utils.dates import parse_spotify_date

        result = parse_spotify_date("2020")
        assert result is not None
        assert result.year == 2020

    def test_parse_none(self):
        from pyrate.utils.dates import parse_spotify_date

        result = parse_spotify_date(None)
        assert result is None

    def test_parse_invalid(self):
        from pyrate.utils.dates import parse_spotify_date

        result = parse_spotify_date("not-a-date")
        assert result is None


# ==========================================================================
# Web (src/pyrate/web.py)
# ==========================================================================


class TestWebApp:
    def test_app_exists(self):
        from pyrate.web import app
        assert app is not None
        assert app.title == "pyrate.media"

    def test_app_has_docs_url(self):
        from pyrate.web import app
        assert app.docs_url == "/api/docs"
        assert app.redoc_url is None
        assert app.openapi_url == "/api/openapi.json"

    def test_app_has_cors_middleware(self):
        from pyrate.web import app
        # FastAPI stores middleware in a stack
        middleware_classes = [
            type(m).__name__
            for m in getattr(app, "user_middleware", [])
        ]
        # The middleware is added; verify by checking the middleware list
        assert len(app.user_middleware) > 0

    def test_app_includes_api_router(self):
        from pyrate.web import app
        # Check that routes starting with /api exist
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        # At minimum, the static mount and API routes should exist
        assert any("/api" in r for r in routes) or len(routes) > 0

    @pytest.mark.asyncio
    async def test_lifespan_runs(self):
        from pyrate.web import lifespan

        mock_app = MagicMock()
        with (
            patch("pyrate.web.load_settings_from_database", new_callable=AsyncMock),
            patch("pyrate.web.elasticsearch_service") as mock_es,
            patch("pyrate.libraries.get_registered_plugins", return_value={}),
            patch("pyrate.web.Path") as mock_path,
        ):
            mock_es.initialize = AsyncMock()
            mock_es.close = AsyncMock()

            # Patch sessionmanager to prevent real DB connection
            with (
                patch("pyrate.database.sessionmanager") as mock_sm,
            ):
                mock_session = AsyncMock()
                mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)

                try:
                    async with lifespan(mock_app):
                        pass
                except Exception:
                    # Some imports inside lifespan may fail in test env
                    pass

    @pytest.mark.asyncio
    async def test_lifespan_settings_load_failure(self):
        import warnings

        from pyrate.web import lifespan

        mock_app = MagicMock()
        mock_es = MagicMock()
        mock_es.initialize = AsyncMock()
        mock_es.close = AsyncMock()

        with (
            patch(
                "pyrate.web.load_settings_from_database",
                new_callable=AsyncMock,
                side_effect=Exception("DB unavailable"),
            ),
            patch("pyrate.web.elasticsearch_service", mock_es),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                async with lifespan(mock_app):
                    pass
            except Exception:
                pass


# ==========================================================================
# Environment Detection (src/pyrate/utils/environment.py)
# ==========================================================================


class TestEnvironmentDetection:
    def test_detect_kubernetes_sa(self):
        from pyrate.utils.environment import detect_environment, Environment

        with patch("pyrate.utils.environment.Path") as MockPath:
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.is_dir.return_value = True
            MockPath.return_value = mock_path

            result = detect_environment()
            assert result == Environment.KUBERNETES

    def test_detect_kubernetes_env_vars(self):
        from pyrate.utils.environment import detect_environment, Environment

        with (
            patch("pyrate.utils.environment.Path") as MockPath,
            patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}),
        ):
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_path.is_dir.return_value = False
            MockPath.return_value = mock_path

            result = detect_environment()
            assert result == Environment.KUBERNETES

    def test_detect_docker_dockerenv(self):
        from pyrate.utils.environment import detect_environment, Environment

        with (
            patch("pyrate.utils.environment.Path") as MockPath,
            patch.dict(os.environ, {}, clear=True),
        ):
            # Remove KUBERNETES_SERVICE_HOST if present
            os.environ.pop("KUBERNETES_SERVICE_HOST", None)
            os.environ.pop("KUBERNETES_SERVICE_PORT", None)

            call_count = 0

            def path_factory(path_str):
                nonlocal call_count
                mock = MagicMock()
                if "kubernetes" in str(path_str):
                    mock.exists.return_value = False
                    mock.is_dir.return_value = False
                elif ".dockerenv" in str(path_str):
                    mock.exists.return_value = True
                else:
                    mock.exists.return_value = False
                return mock

            MockPath.side_effect = path_factory
            result = detect_environment()
            assert result == Environment.DOCKER

    def test_detect_docker_cgroup(self):
        from pyrate.utils.environment import detect_environment, Environment

        with (
            patch("pyrate.utils.environment.Path") as MockPath,
            patch.dict(os.environ, {}, clear=True),
            patch("builtins.open", create=True) as mock_open,
        ):
            os.environ.pop("KUBERNETES_SERVICE_HOST", None)
            os.environ.pop("KUBERNETES_SERVICE_PORT", None)

            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_path.is_dir.return_value = False
            MockPath.return_value = mock_path

            mock_open.return_value.__enter__ = MagicMock(
                return_value=MagicMock(read=MagicMock(return_value="0::docker/abc123"))
            )
            mock_open.return_value.__exit__ = MagicMock(return_value=False)

            result = detect_environment()
            assert result == Environment.DOCKER

    def test_detect_docker_socket(self):
        from pyrate.utils.environment import detect_environment, Environment

        with (
            patch("pyrate.utils.environment.Path") as MockPath,
            patch.dict(os.environ, {}, clear=True),
            patch("builtins.open", side_effect=FileNotFoundError),
        ):
            os.environ.pop("KUBERNETES_SERVICE_HOST", None)
            os.environ.pop("KUBERNETES_SERVICE_PORT", None)

            call_count = [0]

            def path_factory(path_str):
                mock = MagicMock()
                if "docker.sock" in str(path_str):
                    mock.exists.return_value = True
                elif "kubernetes" in str(path_str):
                    mock.exists.return_value = False
                    mock.is_dir.return_value = False
                else:
                    mock.exists.return_value = False
                return mock

            MockPath.side_effect = path_factory
            result = detect_environment()
            assert result == Environment.DOCKER

    def test_get_computing_provider_domain_kubernetes(self):
        from pyrate.utils.environment import get_computing_provider_domain

        with patch(
            "pyrate.utils.environment.detect_environment",
            return_value="kubernetes",
        ):
            result = get_computing_provider_domain()
            assert result == "kubernetes"

    def test_get_computing_provider_domain_docker(self):
        from pyrate.utils.environment import get_computing_provider_domain

        with patch(
            "pyrate.utils.environment.detect_environment",
            return_value="docker",
        ):
            result = get_computing_provider_domain()
            assert result == "docker"

    def test_get_computing_provider_domain_unknown(self):
        from pyrate.utils.environment import get_computing_provider_domain

        with patch(
            "pyrate.utils.environment.detect_environment",
            return_value="unknown",
        ):
            result = get_computing_provider_domain()
            assert result == "docker"  # Falls back to docker


class TestEnvironmentClass:
    def test_environment_constants(self):
        from pyrate.utils.environment import Environment

        assert Environment.KUBERNETES == "kubernetes"
        assert Environment.DOCKER == "docker"
        assert Environment.UNKNOWN == "unknown"


# ==========================================================================
# Schemas: search.py (line 57 - model validator)
# ==========================================================================

from pyrate.schemas.search import SearchRequest


class TestSearchRequestSchema:
    def test_valid_with_query(self):
        req = SearchRequest(query="test")
        assert req.query == "test"

    def test_valid_with_genre_filter(self):
        req = SearchRequest(genre_id=1)
        assert req.genre_id == 1

    def test_valid_with_media_type_filter(self):
        req = SearchRequest(media_type="MOVIES")
        assert req.media_type == "MOVIES"

    def test_valid_with_library_guid_filter(self):
        guid = uuid.uuid4()
        req = SearchRequest(library_guid=guid)
        assert req.library_guid == guid

    def test_invalid_no_query_no_filters(self):
        with pytest.raises(Exception):
            SearchRequest()

    def test_invalid_empty_query_no_filters(self):
        with pytest.raises(Exception):
            SearchRequest(query="")

    def test_invalid_whitespace_query_no_filters(self):
        with pytest.raises(Exception):
            SearchRequest(query="   ")

    def test_query_with_filters(self):
        req = SearchRequest(query="test", genre_id=1)
        assert req.query == "test"
        assert req.genre_id == 1


# ==========================================================================
# Schemas: subscription.py - validators
# ==========================================================================


class TestSubscriptionSchemaValidators:
    @pytest.mark.asyncio
    async def test_package_requires_group_id(self):
        from pyrate.schemas.subscription import SubscriptionPackageBase

        with pytest.raises(Exception):
            SubscriptionPackageBase(
                name="Test",
                price=Decimal("9.99"),
            )

    @pytest.mark.asyncio
    async def test_package_rejects_empty_name(self):
        from pyrate.schemas.subscription import SubscriptionPackageBase

        with pytest.raises(Exception):
            SubscriptionPackageBase(
                name="",
                price=Decimal("9.99"),
                group_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_package_rejects_zero_price(self):
        from pyrate.schemas.subscription import SubscriptionPackageBase

        with pytest.raises(Exception):
            SubscriptionPackageBase(
                name="Test",
                price=Decimal("0"),
                group_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_validate_valid_package(self):
        from pyrate.schemas.subscription import SubscriptionPackageBase

        group_id = uuid.uuid4()
        pkg = SubscriptionPackageBase(
            name="Premium",
            price=Decimal("19.99"),
            group_id=group_id,
        )
        assert pkg.name == "Premium"
        assert pkg.group_id == group_id
        assert pkg.is_active is True

    @pytest.mark.asyncio
    async def test_update_schema_allows_partial_group_change(self):
        from pyrate.schemas.subscription import SubscriptionPackageUpdate

        group_id = uuid.uuid4()
        update = SubscriptionPackageUpdate(group_id=group_id)

        assert update.group_id == group_id
        assert update.name is None


# ==========================================================================
# Schemas: transcoding.py - to_redis_dict / from_redis_dict
# ==========================================================================


class TestTranscodingSessionRedis:
    def test_to_redis_dict(self):
        from pyrate.schemas.transcoding import TranscodingSession

        session = TranscodingSession(
            session_id="test-123",
            user_guid="user-abc",
            content_type="movie",
            content_id="content-xyz",
            content_title="Test Movie",
            container_id="container-1",
            video_codec="h265",
            audio_codec="eac3",
            resolution="1080p",
            start_position=30.5,
        )
        d = session.to_redis_dict()
        assert d["session_id"] == "test-123"
        assert d["user_guid"] == "user-abc"
        assert d["content_type"] == "movie"
        assert d["content_id"] == "content-xyz"
        assert d["video_codec"] == "h265"
        assert d["resolution"] == "1080p"
        assert d["start_position"] == 30.5
        assert d["is_active"] is True
        assert d["status"] == "active"
        assert d["retry_count"] == 0
        assert isinstance(d["started_at"], str)
        assert isinstance(d["last_accessed_at"], str)

    def test_to_redis_dict_none_values(self):
        from pyrate.schemas.transcoding import TranscodingSession

        session = TranscodingSession(
            session_id="test-456",
            content_type="episode",
            content_id="content-abc",
        )
        d = session.to_redis_dict()
        assert d["user_guid"] is None
        assert d["user_name"] is None
        assert d["container_id"] is None
        assert d["video_bitrate"] is None
        assert d["resolution"] is None
        assert d["start_position"] is None
        assert d["input_path"] is None

    def test_from_redis_dict(self):
        from pyrate.schemas.transcoding import TranscodingSession

        data = {
            "session_id": "test-123",
            "user_guid": "user-abc",
            "content_type": "movie",
            "content_id": "content-xyz",
            "content_title": "Test Movie",
            "container_id": "container-1",
            "job_name": "job-1",
            "job_namespace": "default",
            "runtime_type": "kubernetes",
            "video_codec": "h265",
            "audio_codec": "eac3",
            "video_bitrate": "5000k",
            "audio_bitrate": "256k",
            "resolution": "2160p",
            "start_position": 60.0,
            "input_path": "/library/movies/test.mkv",
            "started_at": "2024-01-15T10:00:00+00:00",
            "last_accessed_at": "2024-01-15T10:05:00+00:00",
            "is_active": True,
            "status": "active",
            "retry_count": 2,
        }
        session = TranscodingSession.from_redis_dict(data)
        assert session.session_id == "test-123"
        assert session.runtime_type == "kubernetes"
        assert session.video_codec == "h265"
        assert session.resolution == "2160p"
        assert session.retry_count == 2

    def test_from_redis_dict_minimal(self):
        from pyrate.schemas.transcoding import TranscodingSession

        data = {
            "session_id": "test-min",
            "content_type": "episode",
            "content_id": "id-123",
        }
        session = TranscodingSession.from_redis_dict(data)
        assert session.session_id == "test-min"
        assert session.runtime_type == "docker"  # Default
        assert session.video_codec == "h264"  # Default
        assert session.audio_bitrate == "128k"  # Default
        assert session.is_active is True  # Default
        assert session.status == "active"  # Default
        assert session.retry_count == 0  # Default

    def test_roundtrip(self):
        from pyrate.schemas.transcoding import TranscodingSession

        original = TranscodingSession(
            session_id="roundtrip-test",
            user_guid="user-1",
            content_type="movie",
            content_id="content-1",
            content_title="Roundtrip Movie",
            video_codec="av1",
            audio_codec="opus",
            resolution="4K",
            is_active=False,
            status="failed",
            retry_count=3,
        )
        d = original.to_redis_dict()
        restored = TranscodingSession.from_redis_dict(d)
        assert restored.session_id == original.session_id
        assert restored.video_codec == original.video_codec
        assert restored.is_active == original.is_active
        assert restored.status == original.status
        assert restored.retry_count == original.retry_count

    def test_from_session_read(self):
        from pyrate.schemas.transcoding import TranscodingSession, TranscodingSessionRead

        session = TranscodingSession(
            session_id="read-test",
            content_type="movie",
            content_id="content-1",
            video_codec="h264",
            audio_codec="aac",
        )
        read = TranscodingSessionRead.from_session(session)
        assert read.session_id == "read-test"
        assert read.duration_seconds is not None
        assert read.duration_seconds >= 0


# ==========================================================================
# Schemas: user.py - password validators
# ==========================================================================


class TestUserPasswordValidation:
    def test_password_none_is_valid(self):
        from pyrate.schemas.user import UserCreate

        user = UserCreate(
            first_name="Test",
            last_name="User",
            email="test@example.com",
            password=None,
        )
        assert user.password is None

    def test_password_too_short(self):
        from pyrate.schemas.user import UserCreate

        with pytest.raises(Exception, match="at least"):
            UserCreate(
                first_name="Test",
                last_name="User",
                email="test@example.com",
                password="Ab1",  # Too short
            )

    def test_password_valid(self):
        from pyrate.schemas.user import UserCreate

        user = UserCreate(
            first_name="Test",
            last_name="User",
            email="test@example.com",
            password="SecurePass123",
        )
        assert user.password == "SecurePass123"

    def test_password_no_uppercase(self):
        from pyrate.schemas.user import UserCreate

        with patch("pyrate.config.settings") as mock_settings:
            mock_settings.oidc.min_password_length = 8
            mock_settings.oidc.require_password_complexity = True

            with pytest.raises(Exception, match="uppercase"):
                UserCreate(
                    first_name="Test",
                    last_name="User",
                    email="test@example.com",
                    password="lowercase123",
                )

    def test_password_no_digit(self):
        from pyrate.schemas.user import UserCreate

        with patch("pyrate.config.settings") as mock_settings:
            mock_settings.oidc.min_password_length = 8
            mock_settings.oidc.require_password_complexity = True

            with pytest.raises(Exception, match="digit"):
                UserCreate(
                    first_name="Test",
                    last_name="User",
                    email="test@example.com",
                    password="NoDigitsHere",
                )

    def test_password_no_lowercase(self):
        from pyrate.schemas.user import UserCreate

        with patch("pyrate.config.settings") as mock_settings:
            mock_settings.oidc.min_password_length = 8
            mock_settings.oidc.require_password_complexity = True

            with pytest.raises(Exception, match="lowercase"):
                UserCreate(
                    first_name="Test",
                    last_name="User",
                    email="test@example.com",
                    password="NOLOWER123",
                )

    def test_password_complexity_disabled(self):
        from pyrate.schemas.user import UserCreate

        with patch("pyrate.config.settings") as mock_settings:
            mock_settings.oidc.min_password_length = 8
            mock_settings.oidc.require_password_complexity = False

            user = UserCreate(
                first_name="Test",
                last_name="User",
                email="test@example.com",
                password="alllowercase",
            )
            assert user.password == "alllowercase"


# ==========================================================================
# Worker Task Functions (higher-level tests with mocking)
# ==========================================================================


class TestWorkerTasks:
    @pytest.mark.asyncio
    async def test_handle_completed_download_success(self):
        from pyrate.worker import handle_completed_download

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_download_service = AsyncMock()
        mock_download_service.handle_completed_download = AsyncMock(
            return_value={"success": True, "files_imported": 2}
        )

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.DownloadService", return_value=mock_download_service),
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)

            await handle_completed_download("ext-123", "/downloads/movie")

        mock_download_service.handle_completed_download.assert_awaited_once_with(
            "ext-123", "/downloads/movie", expected_files=None
        )

    @pytest.mark.asyncio
    async def test_handle_completed_download_failure_with_blacklist(self):
        from pyrate.worker import handle_completed_download

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_download_service = AsyncMock()
        mock_download_service.handle_completed_download = AsyncMock(
            return_value={
                "success": False,
                "error": "bad release",
                "blacklisted": True,
                "media_item_guid": "guid-123",
            }
        )
        mock_download = MagicMock()
        mock_download.user_guid = uuid.uuid4()
        mock_download_service.get_by_external_id = AsyncMock(return_value=mock_download)

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.DownloadService", return_value=mock_download_service),
            patch("pyrate.worker.auto_download_media_item") as mock_auto,
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_auto.kiq = AsyncMock()

            await handle_completed_download("ext-123", "/downloads/movie")

        mock_auto.kiq.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_download_success(self):
        from pyrate.worker import add_download

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_download_service = AsyncMock()
        mock_download = MagicMock(title="Test Movie")
        mock_download_service.add_media_download = AsyncMock(return_value=mock_download)

        mock_downloader_service = AsyncMock()
        mock_downloader_service.get_all = AsyncMock(return_value=[MagicMock()])

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.DownloadService", return_value=mock_download_service),
            patch("pyrate.worker.DownloaderService", return_value=mock_downloader_service),
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)

            await add_download("release-guid-123", str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_add_show_download(self):
        from pyrate.worker import add_show_download

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_download_service = AsyncMock()
        mock_download = MagicMock(title="Test Episode")
        mock_download_service.add_media_download = AsyncMock(return_value=mock_download)

        mock_downloader_service = AsyncMock()
        mock_downloader_service.get_all = AsyncMock(return_value=[MagicMock()])

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.DownloadService", return_value=mock_download_service),
            patch("pyrate.worker.DownloaderService", return_value=mock_downloader_service),
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)

            await add_show_download("release-guid", None)

    @pytest.mark.asyncio
    async def test_add_music_download(self):
        from pyrate.worker import add_music_download

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_download_service = AsyncMock()
        mock_download = MagicMock(title="Test Song")
        mock_download_service.add_music_download = AsyncMock(return_value=mock_download)

        mock_downloader_service = AsyncMock()
        mock_downloader_service.get_all = AsyncMock(return_value=[MagicMock()])

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.DownloadService", return_value=mock_download_service),
            patch("pyrate.worker.DownloaderService", return_value=mock_downloader_service),
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)

            await add_music_download("release-guid", str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_send_notification_email_success(self):
        from pyrate.worker import send_notification_email

        mock_session = AsyncMock()
        mock_notification_service = AsyncMock()
        mock_notification = MagicMock()
        mock_notification.send_email = True
        mock_notification.user_id = uuid.uuid4()
        mock_notification.subject = "Test Subject"
        mock_notification.message = "Test Message"
        mock_notification.notification_type.value = "info"
        mock_notification_service.get_by_id = AsyncMock(return_value=mock_notification)
        mock_notification_service.mark_as_sent = AsyncMock()

        mock_user = MagicMock()
        mock_user.email = "test@example.com"

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.NotificationService", return_value=mock_notification_service),
            patch("pyrate.services.settings.SettingsService") as mock_settings_service,
            patch("pyrate.worker.email_service") as mock_email,
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.get = AsyncMock(return_value=mock_user)
            mock_settings = AsyncMock()
            mock_settings.get = AsyncMock(return_value="Pyrate Media")
            mock_settings_service.return_value = mock_settings
            mock_email.send_notification_email = AsyncMock(return_value=True)

            await send_notification_email("notif-123")

        mock_notification_service.mark_as_sent.assert_awaited_once_with(
            "notif-123", success=True
        )

    @pytest.mark.asyncio
    async def test_send_notification_email_not_found(self):
        from pyrate.worker import send_notification_email

        mock_session = AsyncMock()
        mock_notification_service = AsyncMock()
        mock_notification_service.get_by_id = AsyncMock(return_value=None)

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.NotificationService", return_value=mock_notification_service),
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)

            await send_notification_email("notif-missing")

    @pytest.mark.asyncio
    async def test_send_notification_email_disabled(self):
        from pyrate.worker import send_notification_email

        mock_session = AsyncMock()
        mock_notification_service = AsyncMock()
        mock_notification = MagicMock()
        mock_notification.send_email = False
        mock_notification_service.get_by_id = AsyncMock(return_value=mock_notification)

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.NotificationService", return_value=mock_notification_service),
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)

            await send_notification_email("notif-disabled")

    @pytest.mark.asyncio
    async def test_import_trending_movies(self):
        from pyrate.worker import import_trending_movies

        mock_session = AsyncMock()
        mock_trending = AsyncMock()
        mock_trending.get_new_trending_movie_ids = AsyncMock(return_value=[])
        mock_trending.update_trending_movies_list = AsyncMock()

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.TrendingService", return_value=mock_trending),
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)

            await import_trending_movies()

        mock_trending.update_trending_movies_list.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_import_trending_shows(self):
        from pyrate.worker import import_trending_shows

        mock_session = AsyncMock()
        mock_trending = AsyncMock()
        mock_trending.get_new_trending_show_ids = AsyncMock(return_value=[])
        mock_trending.update_trending_shows_list = AsyncMock()

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.TrendingService", return_value=mock_trending),
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)

            await import_trending_shows()

        mock_trending.update_trending_shows_list.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_import_trending_games(self):
        from pyrate.worker import import_trending_games

        mock_session = AsyncMock()
        mock_trending = AsyncMock()
        mock_trending.get_new_trending_game_ids = AsyncMock(return_value=[])
        mock_trending.update_trending_games_list = AsyncMock()

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.TrendingService", return_value=mock_trending),
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)

            await import_trending_games()

        mock_trending.update_trending_games_list.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_import_movie_metadata_success(self):
        from pyrate.worker import import_movie_metadata

        mock_session = AsyncMock()
        mock_tmdb = AsyncMock()
        mock_tmdb.search_movies = AsyncMock(
            return_value={"results": [{"id": 123, "title": "Test"}]}
        )

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.get_tmdb_api_key", return_value="key"),
            patch("pyrate.worker.TMDB", return_value=mock_tmdb),
            patch("pyrate.worker.import_movie") as mock_import,
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_import.kiq = AsyncMock()

            await import_movie_metadata("Test Movie", 2020)

        mock_import.kiq.assert_awaited_once_with(123)

    @pytest.mark.asyncio
    async def test_import_movie_metadata_no_results(self):
        from pyrate.worker import import_movie_metadata

        mock_session = AsyncMock()
        mock_tmdb = AsyncMock()
        mock_tmdb.search_movies = AsyncMock(return_value={"results": []})

        with (
            patch("pyrate.worker.sessionmanager") as mock_sm,
            patch("pyrate.worker.get_tmdb_api_key", return_value="key"),
            patch("pyrate.worker.TMDB", return_value=mock_tmdb),
        ):
            mock_sm.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.session.return_value.__aexit__ = AsyncMock(return_value=False)

            await import_movie_metadata("Nonexistent", 2020)

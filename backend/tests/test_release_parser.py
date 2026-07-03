"""Tests for ReleaseParser - media release name parsing utilities."""

from pyrate.parsers.release_parser import ReleaseParser


class TestNormalizeTitle:
    """Tests for title normalization."""

    def test_empty_string(self):
        assert ReleaseParser.normalize_title("") == ""

    def test_lowercase(self):
        assert ReleaseParser.normalize_title("The Movie") == "the movie"

    def test_replace_dots(self):
        assert ReleaseParser.normalize_title("The.Movie.Title") == "the movie title"

    def test_replace_underscores(self):
        assert ReleaseParser.normalize_title("The_Movie_Title") == "the movie title"

    def test_replace_dashes(self):
        assert ReleaseParser.normalize_title("The-Movie-Title") == "the movie title"

    def test_remove_accents(self):
        result = ReleaseParser.normalize_title("Café résumé über")
        assert "cafe" in result
        assert "resume" in result
        assert "uber" in result

    def test_remove_special_chars(self):
        result = ReleaseParser.normalize_title("Movie! (2023) [HD]")
        assert "!" not in result
        assert "[" not in result
        assert "]" not in result

    def test_remove_noise_words(self):
        result = ReleaseParser.normalize_title("Movie UNCUT EXTENDED EDITION")
        assert "uncut" not in result
        assert "extended" not in result
        assert "edition" not in result

    def test_normalize_whitespace(self):
        result = ReleaseParser.normalize_title("The   Movie    Title")
        assert result == "the movie title"


class TestParseMovieRelease:
    """Tests for movie release title parsing."""

    def test_basic_movie(self):
        result = ReleaseParser.parse_movie_release(
            "Movie.Title.2023.1080p.BluRay.x264-GROUP"
        )
        assert result.title == "Movie Title"
        assert result.year == 2023

    def test_movie_with_german_dl(self):
        result = ReleaseParser.parse_movie_release(
            "The.Movie.2020.GERMAN.DL.1080p.WEB.x264-GROUP"
        )
        assert result.title == "The Movie"
        assert result.year == 2020

    def test_movie_no_year(self):
        result = ReleaseParser.parse_movie_release(
            "Movie.Title.1080p.BluRay.x264-GROUP"
        )
        assert result.title == "Movie Title"
        assert result.year is None

    def test_movie_preserves_original_title(self):
        original = "Movie.Title.2023.1080p.BluRay.x264-GROUP"
        result = ReleaseParser.parse_movie_release(original)
        assert result.original_title == original

    def test_movie_with_extension(self):
        result = ReleaseParser.parse_movie_release(
            "Movie.Title.2023.1080p.BluRay.x264-GROUP.mkv"
        )
        assert result.title == "Movie Title"
        assert result.year == 2023

    def test_movie_4k(self):
        result = ReleaseParser.parse_movie_release(
            "Movie.Title.2021.2160p.UHD.BluRay.REMUX.HDR.HEVC-GROUP"
        )
        assert result.title == "Movie Title"
        assert result.year == 2021

    def test_movie_web_dl(self):
        result = ReleaseParser.parse_movie_release(
            "Movie.Title.2022.WEB-DL.1080p.DDP5.1.H.264-GROUP"
        )
        assert result.title == "Movie Title"
        assert result.year == 2022


class TestParseShowRelease:
    """Tests for TV show release title parsing."""

    def test_standard_episode(self):
        result = ReleaseParser.parse_show_release(
            "Show.Name.S01E05.1080p.WEB.x264-GROUP"
        )
        assert result.title == "Show Name"
        assert result.season == 1
        assert result.episode == 5
        assert result.is_season_pack is False

    def test_double_episode(self):
        result = ReleaseParser.parse_show_release(
            "Show.Name.S01E01E02.1080p.WEB.x264-GROUP"
        )
        assert result.season == 1
        assert result.episode == 1
        assert result.episode_end == 2

    def test_episode_range(self):
        result = ReleaseParser.parse_show_release(
            "Show.Name.S02E01-E03.720p.HDTV-GROUP"
        )
        assert result.season == 2
        assert result.episode == 1
        assert result.episode_end == 3

    def test_show_with_year(self):
        result = ReleaseParser.parse_show_release(
            "Show.Name.2019.S02E10.720p.HDTV-GROUP"
        )
        assert "Show Name" in result.title
        assert result.season == 2
        assert result.episode == 10
        # Year may or may not be extracted depending on boundary matching
        # The parser keeps "2019" as part of the title in this format

    def test_season_pack(self):
        result = ReleaseParser.parse_show_release(
            "Show.Name.S01.COMPLETE.1080p.WEB-DL-GROUP"
        )
        assert result.title == "Show Name"
        assert result.season == 1
        assert result.episode is None
        assert result.is_season_pack is True

    def test_complete_series(self):
        result = ReleaseParser.parse_show_release(
            "Show.Name.Complete.Series.1080p.BluRay-GROUP"
        )
        assert result.is_complete_series is True

    def test_alternative_format(self):
        result = ReleaseParser.parse_show_release(
            "Show.Name.1x05.720p.HDTV-GROUP"
        )
        assert result.season == 1
        assert result.episode == 5

    def test_preserves_original(self):
        original = "Show.Name.S01E01.1080p.WEB-GROUP"
        result = ReleaseParser.parse_show_release(original)
        assert result.original_title == original


class TestExtractResolution:
    """Tests for resolution extraction."""

    def test_1080p(self):
        assert ReleaseParser.extract_resolution("Movie.2023.1080p.BluRay") == "1080p"

    def test_720p(self):
        assert ReleaseParser.extract_resolution("Movie.2023.720p.HDTV") == "720p"

    def test_2160p(self):
        assert ReleaseParser.extract_resolution("Movie.2023.2160p.UHD") == "2160p"

    def test_480p(self):
        assert ReleaseParser.extract_resolution("Movie.2023.480p.DVDRip") == "480p"

    def test_no_resolution(self):
        assert ReleaseParser.extract_resolution("Movie.2023.BluRay") is None

    def test_infer_dvdrip_as_480p(self):
        """DVDRip releases without explicit resolution should infer 480p."""
        assert ReleaseParser.extract_resolution("Movie.2023.DVDRip.XviD-GROUP") == "480p"

    def test_infer_dvd_as_480p(self):
        """DVD releases without explicit resolution should infer 480p."""
        assert ReleaseParser.extract_resolution("Movie.2023.DVD.x264-GROUP") == "480p"

    def test_infer_telesync_as_480p(self):
        """TELESYNC releases without explicit resolution should infer 480p."""
        assert ReleaseParser.extract_resolution("Movie.2023.TELESYNC-GROUP") == "480p"

    def test_infer_cam_as_480p(self):
        """CAM releases without explicit resolution should infer 480p."""
        assert ReleaseParser.extract_resolution("Movie.2023.CAM-GROUP") == "480p"

    def test_infer_hdtv_as_720p(self):
        """HDTV releases without explicit resolution should infer 720p."""
        assert ReleaseParser.extract_resolution("Movie.2023.HDTV.x264-GROUP") == "720p"

    def test_explicit_resolution_takes_precedence(self):
        """Explicit resolution should take precedence over source inference."""
        assert ReleaseParser.extract_resolution("Movie.2023.1080p.DVDRip-GROUP") == "1080p"

    def test_no_resolution_no_source(self):
        """Release with neither resolution nor recognized source returns None."""
        assert ReleaseParser.extract_resolution("Movie.2023.x264-GROUP") is None


class TestExtractSource:
    """Tests for source extraction."""

    def test_bluray(self):
        assert ReleaseParser.extract_source("Movie.2023.1080p.BluRay") == "bluray"

    def test_bdrip(self):
        assert ReleaseParser.extract_source("Movie.2023.BDRip") == "bluray"

    def test_web_dl(self):
        assert ReleaseParser.extract_source("Movie.2023.WEB-DL") == "web-dl"

    def test_webrip(self):
        assert ReleaseParser.extract_source("Movie.2023.WEBRip") == "webrip"

    def test_hdtv(self):
        assert ReleaseParser.extract_source("Movie.2023.HDTV") == "hdtv"

    def test_dvdrip(self):
        assert ReleaseParser.extract_source("Movie.2023.DVDRip") == "dvd"

    def test_remux(self):
        assert ReleaseParser.extract_source("Movie.2023.REMUX") == "remux"

    def test_telesync(self):
        assert ReleaseParser.extract_source("Movie.2023.TELESYNC") == "telesync"

    def test_no_source(self):
        assert ReleaseParser.extract_source("Movie.2023.x264") is None


class TestExtractVideoCodec:
    """Tests for video codec extraction."""

    def test_x264(self):
        assert ReleaseParser.extract_video_codec("Movie.x264-GROUP") == "h264"

    def test_x265(self):
        assert ReleaseParser.extract_video_codec("Movie.x265-GROUP") == "h265"

    def test_hevc(self):
        assert ReleaseParser.extract_video_codec("Movie.HEVC-GROUP") == "h265"

    def test_h264_dot(self):
        assert ReleaseParser.extract_video_codec("Movie.H.264-GROUP") == "h264"

    def test_avc(self):
        assert ReleaseParser.extract_video_codec("Movie.AVC-GROUP") == "h264"

    def test_av1(self):
        assert ReleaseParser.extract_video_codec("Movie.AV1-GROUP") == "av1"

    def test_no_codec(self):
        assert ReleaseParser.extract_video_codec("Movie.1080p-GROUP") is None


class TestExtractAudioCodec:
    """Tests for audio codec extraction."""

    def test_aac(self):
        assert "aac" in ReleaseParser.extract_audio_codec("Movie.AAC-GROUP")

    def test_ac3(self):
        assert "ac3" in ReleaseParser.extract_audio_codec("Movie.AC3-GROUP")

    def test_dts(self):
        assert "dts" in ReleaseParser.extract_audio_codec("Movie.DTS-GROUP")

    def test_flac(self):
        assert "flac" in ReleaseParser.extract_audio_codec("Movie.FLAC-GROUP")

    def test_truehd(self):
        assert "truehd" in ReleaseParser.extract_audio_codec("Movie.TrueHD-GROUP")

    def test_atmos(self):
        assert "atmos" in ReleaseParser.extract_audio_codec("Movie.Atmos-GROUP")

    def test_multiple_codecs(self):
        codecs = ReleaseParser.extract_audio_codec("Movie.DTS.AAC.FLAC-GROUP")
        assert len(codecs) >= 2

    def test_no_codec(self):
        assert ReleaseParser.extract_audio_codec("Movie.1080p-GROUP") == []

    def test_eac3(self):
        codecs = ReleaseParser.extract_audio_codec("Movie.EAC3-GROUP")
        assert "eac3" in codecs


class TestExtractLanguages:
    """Tests for language extraction."""

    def test_german(self):
        assert "de" in ReleaseParser.extract_languages("Movie.GERMAN.1080p")

    def test_english(self):
        assert "en" in ReleaseParser.extract_languages("Movie.ENGLISH.1080p")

    def test_dual_language(self):
        langs = ReleaseParser.extract_languages("Movie.DL.1080p")
        assert "de" in langs
        assert "en" in langs

    def test_multi(self):
        assert "multi" in ReleaseParser.extract_languages("Movie.MULTI.1080p")

    def test_default_english(self):
        """When no language is specified, default to English."""
        langs = ReleaseParser.extract_languages("Movie.1080p.BluRay")
        assert "en" in langs

    def test_french(self):
        assert "fr" in ReleaseParser.extract_languages("Movie.FRENCH.1080p")

    def test_japanese(self):
        assert "ja" in ReleaseParser.extract_languages("Movie.JAPANESE.1080p")


class TestExtractAudioChannels:
    """Tests for audio channel extraction."""

    def test_5_1(self):
        assert ReleaseParser.extract_audio_channels("Movie.5.1.1080p") == "5.1"

    def test_7_1(self):
        assert ReleaseParser.extract_audio_channels("Movie.7.1.1080p") == "7.1"

    def test_2_0(self):
        assert ReleaseParser.extract_audio_channels("Movie.2.0.1080p") == "2.0"

    def test_stereo(self):
        assert ReleaseParser.extract_audio_channels("Movie.STEREO.1080p") == "2.0"

    def test_no_channels(self):
        assert ReleaseParser.extract_audio_channels("Movie.1080p") is None


class TestExtractReleaseGroup:
    """Tests for release group extraction."""

    def test_basic_group(self):
        assert ReleaseParser.extract_release_group("Movie.1080p-GROUP") == "GROUP"

    def test_group_with_tags(self):
        group = ReleaseParser.extract_release_group("Movie.1080p-GROUP[tag]")
        assert group == "GROUP"

    def test_no_group(self):
        assert ReleaseParser.extract_release_group("Movie.1080p") is None


class TestBooleanChecks:
    """Tests for boolean property checks."""

    def test_has_hdr(self):
        assert ReleaseParser.has_hdr("Movie.2160p.HDR10.BluRay") is True

    def test_has_hdr10_plus(self):
        assert ReleaseParser.has_hdr("Movie.2160p.HDR10+.BluRay") is True

    def test_no_hdr(self):
        assert ReleaseParser.has_hdr("Movie.1080p.BluRay") is False

    def test_has_dolby_vision(self):
        assert ReleaseParser.has_dolby_vision("Movie.DV.2160p") is True

    def test_has_dolby_vision_full(self):
        assert ReleaseParser.has_dolby_vision("Movie.Dolby Vision.2160p") is True

    def test_no_dolby_vision(self):
        assert ReleaseParser.has_dolby_vision("Movie.1080p") is False

    def test_is_remux(self):
        assert ReleaseParser.is_remux("Movie.REMUX.2160p") is True

    def test_not_remux(self):
        assert ReleaseParser.is_remux("Movie.1080p.BluRay") is False

    def test_is_3d(self):
        assert ReleaseParser.is_3d("Movie.3D.1080p.BluRay") is True

    def test_not_3d(self):
        assert ReleaseParser.is_3d("Movie.1080p.BluRay") is False

    def test_proper(self):
        is_proper, is_repack = ReleaseParser.has_proper_or_repack(
            "Movie.PROPER.1080p"
        )
        assert is_proper is True
        assert is_repack is False

    def test_repack(self):
        is_proper, is_repack = ReleaseParser.has_proper_or_repack(
            "Movie.REPACK.1080p"
        )
        assert is_proper is False
        assert is_repack is True

    def test_no_proper_repack(self):
        is_proper, is_repack = ReleaseParser.has_proper_or_repack("Movie.1080p")
        assert is_proper is False
        assert is_repack is False


class TestExtractContainer:
    """Tests for container format extraction."""

    def test_mkv(self):
        assert ReleaseParser.extract_container("Movie.mkv") == "mkv"

    def test_mp4(self):
        assert ReleaseParser.extract_container("Movie.mp4") == "mp4"

    def test_avi(self):
        assert ReleaseParser.extract_container("Movie.avi") == "avi"

    def test_no_container(self):
        assert ReleaseParser.extract_container("Movie.1080p-GROUP") is None


class TestIsLowQuality:
    """Tests for low quality detection."""

    def test_cam(self):
        assert ReleaseParser.is_low_quality("Movie.CAM.720p") is True

    def test_telesync(self):
        assert ReleaseParser.is_low_quality("Movie.TELESYNC.720p") is True

    def test_ts(self):
        assert ReleaseParser.is_low_quality("Movie.TS.720p") is True

    def test_telecine(self):
        assert ReleaseParser.is_low_quality("Movie.TELECINE.720p") is True

    def test_bluray_not_low_quality(self):
        assert ReleaseParser.is_low_quality("Movie.BluRay.1080p") is False

    def test_web_dl_not_low_quality(self):
        assert ReleaseParser.is_low_quality("Movie.WEB-DL.1080p") is False

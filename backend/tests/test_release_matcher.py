"""Tests for release parsing and matching."""

import pytest

from pyrate.parsers.release_parser import ParsedMovieRelease, ParsedShowRelease, ReleaseParser
from pyrate.services.release_matcher import MatchResult, ReleaseMatcher


class TestReleaseParser:
    """Test cases for ReleaseParser title extraction."""

    def test_parse_movie_release_basic(self):
        """Test basic movie title extraction."""
        result = ReleaseParser.parse_movie_release(
            "The.Matrix.1999.1080p.BluRay.x264-GROUP"
        )
        assert isinstance(result, ParsedMovieRelease)
        assert result.title == "The Matrix"
        assert result.year == 1999

    def test_parse_movie_release_with_german(self):
        """Test movie title with German language marker."""
        result = ReleaseParser.parse_movie_release(
            "Inception.2010.GERMAN.DL.1080p.BluRay.x264-GROUP"
        )
        assert result.title == "Inception"
        assert result.year == 2010

    def test_parse_movie_release_multi_word(self):
        """Test multi-word movie title."""
        result = ReleaseParser.parse_movie_release(
            "The.Lord.of.the.Rings.The.Fellowship.of.the.Ring.2001.EXTENDED.1080p.BluRay.x264-GROUP"
        )
        assert "Lord of the Rings" in result.title
        assert result.year == 2001

    def test_parse_show_release_basic(self):
        """Test basic TV show episode extraction."""
        result = ReleaseParser.parse_show_release(
            "Breaking.Bad.S01E01.1080p.BluRay.x264-GROUP"
        )
        assert isinstance(result, ParsedShowRelease)
        assert result.title == "Breaking Bad"
        assert result.season == 1
        assert result.episode == 1
        assert not result.is_season_pack

    def test_parse_show_release_with_year(self):
        """Test TV show with year in title."""
        result = ReleaseParser.parse_show_release(
            "Doctor.Who.2005.S13E05.720p.WEB.x264-GROUP"
        )
        # Should preserve year as it might be part of show name
        assert "Doctor Who" in result.title
        assert result.season == 13
        assert result.episode == 5

    def test_parse_show_release_multi_episode(self):
        """Test multi-episode release."""
        result = ReleaseParser.parse_show_release(
            "Game.of.Thrones.S08E01-E03.1080p.WEB.x264-GROUP"
        )
        assert result.title == "Game of Thrones"
        assert result.season == 8
        assert result.episode == 1
        assert result.episode_end == 3

    def test_parse_show_release_season_pack(self):
        """Test season pack detection."""
        result = ReleaseParser.parse_show_release(
            "Stranger.Things.S04.1080p.NF.WEB-DL.x264-GROUP"
        )
        assert result.title == "Stranger Things"
        assert result.season == 4
        assert result.episode is None
        assert result.is_season_pack

    def test_parse_show_release_alt_format(self):
        """Test alternative 1x01 format."""
        result = ReleaseParser.parse_show_release(
            "The.Simpsons.34x12.720p.HDTV.x264-GROUP"
        )
        assert "Simpsons" in result.title
        assert result.season == 34
        assert result.episode == 12

    def test_normalize_title(self):
        """Test title normalization."""
        normalized = ReleaseParser.normalize_title("The Matrix: Reloaded")
        assert normalized == "the matrix reloaded"

        normalized = ReleaseParser.normalize_title("Breaking.Bad")
        assert normalized == "breaking bad"

        # Test accent removal
        normalized = ReleaseParser.normalize_title("Amélie")
        assert normalized == "amelie"


class TestReleaseMatcher:
    """Test cases for ReleaseMatcher."""

    def test_match_movie_exact(self):
        """Test exact movie title match."""
        result = ReleaseMatcher.match_movie_release(
            release_title="The.Matrix.1999.1080p.BluRay.x264-GROUP",
            movie_title="The Matrix",
            movie_year=1999,
        )
        assert result.is_match
        assert result.match_type == "exact"
        assert result.score >= 0.95

    def test_match_movie_fuzzy(self):
        """Test fuzzy movie title match."""
        result = ReleaseMatcher.match_movie_release(
            release_title="Matrix.Reloaded.2003.1080p.BluRay.x264-GROUP",
            movie_title="The Matrix Reloaded",
            movie_year=2003,
        )
        assert result.is_match
        assert result.match_type in ["fuzzy", "partial"]
        assert result.score >= 0.8

    def test_match_movie_wrong_movie(self):
        """Test non-matching movie rejection."""
        result = ReleaseMatcher.match_movie_release(
            release_title="Inception.2010.1080p.BluRay.x264-GROUP",
            movie_title="The Matrix",
            movie_year=1999,
        )
        assert not result.is_match
        assert result.match_type == "no_match"

    def test_match_movie_by_imdb(self):
        """Test movie match by IMDB ID."""
        result = ReleaseMatcher.match_movie_release(
            release_title="Some.Random.Title.2020.1080p.WEB.x264-GROUP",
            movie_title="Completely Different Movie",
            movie_year=2020,
            imdb_id="tt0133093",
            release_imdb_id="tt0133093",
        )
        assert result.is_match
        assert result.match_type == "id"
        assert result.score == 1.0

    def test_match_episode_exact(self):
        """Test exact episode match."""
        result = ReleaseMatcher.match_episode_release(
            release_title="Breaking.Bad.S01E01.1080p.BluRay.x264-GROUP",
            show_title="Breaking Bad",
            season=1,
            episode=1,
        )
        assert result.is_match
        assert result.score >= 0.9

    def test_match_episode_wrong_episode(self):
        """Test episode number mismatch rejection."""
        result = ReleaseMatcher.match_episode_release(
            release_title="Breaking.Bad.S01E02.1080p.BluRay.x264-GROUP",
            show_title="Breaking Bad",
            season=1,
            episode=1,  # Looking for E01, release is E02
        )
        assert not result.is_match

    def test_match_episode_wrong_season(self):
        """Test season number mismatch rejection."""
        result = ReleaseMatcher.match_episode_release(
            release_title="Breaking.Bad.S02E01.1080p.BluRay.x264-GROUP",
            show_title="Breaking Bad",
            season=1,  # Looking for S01, release is S02
            episode=1,
        )
        assert not result.is_match

    def test_match_episode_multi_episode(self):
        """Test multi-episode release matching middle episode."""
        result = ReleaseMatcher.match_episode_release(
            release_title="Game.of.Thrones.S08E01-E03.1080p.WEB.x264-GROUP",
            show_title="Game of Thrones",
            season=8,
            episode=2,  # Should match E01-E03 range
        )
        assert result.is_match

    def test_match_episode_different_show(self):
        """Test wrong show rejection."""
        result = ReleaseMatcher.match_episode_release(
            release_title="Better.Call.Saul.S01E01.1080p.WEB.x264-GROUP",
            show_title="Breaking Bad",
            season=1,
            episode=1,
        )
        assert not result.is_match

    def test_filter_matching_releases_movies(self):
        """Test filtering releases for movies."""
        releases = [
            {"title": "The.Matrix.1999.1080p.BluRay.x264-GROUP"},
            {"title": "Matrix.1999.720p.WEB.x264-OTHER"},
            {"title": "Inception.2010.1080p.BluRay.x264-GROUP"},  # Wrong movie
            {"title": "The.Matrix.Reloaded.2003.1080p.BluRay.x264-GROUP"},  # Sequel
        ]

        results = ReleaseMatcher.filter_matching_releases(
            releases=releases,
            media_title="The Matrix",
            media_year=1999,
        )

        # Should match "The Matrix" releases, not Inception or Reloaded
        matched_titles = [r[0]["title"] for r in results]
        assert any("The.Matrix.1999" in t for t in matched_titles)
        assert not any("Inception" in t for t in matched_titles)

    def test_filter_matching_releases_episodes(self):
        """Test filtering releases for TV episodes."""
        releases = [
            {"title": "Breaking.Bad.S01E01.1080p.BluRay.x264-GROUP"},
            {"title": "Breaking.Bad.S01E02.1080p.BluRay.x264-GROUP"},  # Wrong episode
            {"title": "Better.Call.Saul.S01E01.1080p.WEB.x264-GROUP"},  # Wrong show
            {"title": "Breaking.Bad.S01E01.720p.HDTV.x264-OTHER"},  # Another E01
        ]

        results = ReleaseMatcher.filter_matching_releases(
            releases=releases,
            media_title="Breaking Bad",
            season=1,
            episode=1,
        )

        # Should only match S01E01 of Breaking Bad
        assert len(results) == 2
        for release, match in results:
            assert "S01E01" in release["title"]
            assert "Breaking.Bad" in release["title"]

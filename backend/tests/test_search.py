"""Coverage boost tests targeting uncovered lines in search, play, computing, download, media, library."""

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from pyrate.schemas.search import SearchRequest, SearchType
from pyrate.services.search import SearchService, IMPORT_LOCK_PREFIX, IMPORT_LOCK_TTL_SECONDS


# ============================================================================
# Helpers
# ============================================================================

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


def _search_request(query="test", search_type=SearchType.ALL, **kwargs):
    return SearchRequest(query=query, search_type=search_type, **kwargs)


# ============================================================================
# SearchService — Transform helpers (pure functions, no DB needed)
# ============================================================================


class TestTransformTmdbMovie:
    """Test _transform_tmdb_movie."""

    def test_basic_transform(self):
        db = MagicMock()
        svc = SearchService(db)
        movie = {
            "id": 12345,
            "title": "Test Movie",
            "original_title": "Test Original",
            "overview": "A great movie",
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
            "release_date": "2024-01-15",
            "popularity": 500.0,
            "vote_average": 7.5,
            "vote_count": 1000,
            "genre_ids": [28, 12],
        }
        hit = svc._transform_tmdb_movie(movie, 0)
        assert hit["tmdb_id"] == 12345
        assert hit["title"] == "Test Movie"
        assert hit["original_title"] == "Test Original"
        assert hit["description"] == "A great movie"
        assert hit["poster_path"] == "/poster.jpg"
        assert hit["backdrop_path"] == "/backdrop.jpg"
        assert hit["release_date"] == "2024-01-15"
        assert hit["type"] == SearchType.MOVIES
        assert hit["source"] == "tmdb"
        assert hit["in_library"] is False
        assert hit["igdb_id"] is None
        assert hit["spotify_id"] is None
        assert hit["genre_ids"] == [28, 12]

    def test_score_decreases_with_index(self):
        db = MagicMock()
        svc = SearchService(db)
        movie = {"popularity": 100.0}
        hit0 = svc._transform_tmdb_movie(movie, 0)
        hit5 = svc._transform_tmdb_movie(movie, 5)
        hit20 = svc._transform_tmdb_movie(movie, 20)
        assert hit0["score"] > hit5["score"]
        assert hit5["score"] > hit20["score"]

    def test_score_capped_at_10(self):
        db = MagicMock()
        svc = SearchService(db)
        movie = {"popularity": 99999.0}
        hit = svc._transform_tmdb_movie(movie, 0)
        assert hit["score"] <= 10.0

    def test_missing_fields_defaults(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_tmdb_movie({}, 0)
        assert hit["title"] == ""
        assert hit["tmdb_id"] is None
        assert hit["genre_ids"] == []
        assert hit["description"] is None


class TestTransformTmdbShow:
    """Test _transform_tmdb_show."""

    def test_basic_show_transform(self):
        db = MagicMock()
        svc = SearchService(db)
        show = {
            "id": 67890,
            "name": "Test Show",
            "original_name": "Original Show",
            "overview": "A TV show",
            "poster_path": "/show_poster.jpg",
            "backdrop_path": "/show_backdrop.jpg",
            "first_air_date": "2023-06-01",
            "popularity": 200.0,
            "vote_average": 8.0,
            "vote_count": 500,
            "genre_ids": [18, 10765],
        }
        hit = svc._transform_tmdb_show(show, 0)
        assert hit["tmdb_id"] == 67890
        assert hit["title"] == "Test Show"
        assert hit["original_title"] == "Original Show"
        assert hit["type"] == SearchType.SHOWS
        assert hit["first_air_date"] == "2023-06-01"
        assert hit["release_date"] is None
        assert hit["source"] == "tmdb"

    def test_missing_fields(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_tmdb_show({}, 3)
        assert hit["title"] == ""
        assert hit["genre_ids"] == []


class TestTransformIgdbGame:
    """Test _transform_igdb_game."""

    def test_basic_game_transform(self):
        db = MagicMock()
        svc = SearchService(db)
        game = {
            "id": 111,
            "name": "Test Game",
            "summary": "A game description",
            "rating": 85.0,
            "rating_count": 200,
            "cover": {"image_id": "abc123"},
            "first_release_date": 1609459200,  # 2021-01-01
            "genres": [{"name": "Action"}, {"name": "RPG"}],
        }
        hit = svc._transform_igdb_game(game, 0)
        assert hit["igdb_id"] == 111
        assert hit["title"] == "Test Game"
        assert hit["type"] == SearchType.GAMES
        assert hit["source"] == "igdb"
        assert "igdb.com" in hit["poster_path"]
        assert "abc123" in hit["poster_path"]
        assert hit["release_date"] is not None
        assert hit["genres"] == ["Action", "RPG"]

    def test_no_cover(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_igdb_game({"name": "NoCover"}, 0)
        assert hit["poster_path"] is None

    def test_cover_without_image_id(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_igdb_game({"cover": {"other": "data"}}, 0)
        assert hit["poster_path"] is None

    def test_invalid_release_date(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_igdb_game({"first_release_date": -999999999999}, 0)
        # Should not crash, release_date can be None
        assert hit["release_date"] is None or isinstance(hit["release_date"], str)

    def test_no_rating(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_igdb_game({"rating": None}, 0)
        assert hit["score"] >= 0

    def test_genres_empty(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_igdb_game({"genres": [{"other": "x"}]}, 0)
        assert hit["genres"] == []


class TestTransformSpotifyAlbum:
    """Test _transform_spotify_album."""

    def test_basic_album_transform(self):
        db = MagicMock()
        svc = SearchService(db)
        album = {
            "id": "album123",
            "name": "Test Album",
            "popularity": 75,
            "images": [{"url": "https://img.spotify.com/album.jpg"}],
            "artists": [{"name": "Artist 1"}, {"name": "Artist 2"}],
            "release_date": "2023-06-15",
            "album_type": "album",
            "total_tracks": 12,
        }
        hit = svc._transform_spotify_album(album, 0)
        assert hit["spotify_id"] == "album123"
        assert hit["title"] == "Test Album"
        assert hit["type"] == SearchType.MUSIC
        assert hit["source"] == "spotify"
        assert hit["poster_path"] == "https://img.spotify.com/album.jpg"
        assert hit["description"] == "Artist 1, Artist 2"
        assert hit["status"] == "album"
        assert hit["number_of_episodes"] == 12

    def test_no_images(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_spotify_album({"images": []}, 0)
        assert hit["poster_path"] is None

    def test_no_artists(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_spotify_album({"artists": []}, 0)
        assert hit["description"] is None

    def test_null_popularity(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_spotify_album({"popularity": None}, 0)
        assert hit["score"] >= 0


class TestTransformSpotifyArtist:
    """Test _transform_spotify_artist."""

    def test_basic_artist_transform(self):
        db = MagicMock()
        svc = SearchService(db)
        artist = {
            "id": "artist456",
            "name": "Famous Artist",
            "popularity": 90,
            "images": [{"url": "https://img.spotify.com/artist.jpg"}],
            "genres": ["pop", "rock"],
        }
        hit = svc._transform_spotify_artist(artist, 0)
        assert hit["spotify_id"] == "artist456"
        assert hit["title"] == "Famous Artist"
        assert hit["type"] == SearchType.MUSIC
        assert hit["music_type"] == "artist"
        assert hit["genres"] == ["pop", "rock"]
        assert hit["poster_path"] == "https://img.spotify.com/artist.jpg"

    def test_no_images(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_spotify_artist({"images": []}, 0)
        assert hit["poster_path"] is None


class TestTransformSpotifyTrack:
    """Test _transform_spotify_track."""

    def test_basic_track_transform(self):
        db = MagicMock()
        svc = SearchService(db)
        track = {
            "id": "track789",
            "name": "Test Song",
            "popularity": 60,
            "artists": [{"name": "Singer"}],
            "album": {
                "id": "album_parent",
                "release_date": "2022-03-01",
                "images": [{"url": "https://img.spotify.com/track_album.jpg"}],
            },
        }
        hit = svc._transform_spotify_track(track, 0)
        assert hit["spotify_id"] == "track789"
        assert hit["album_spotify_id"] == "album_parent"
        assert hit["title"] == "Test Song"
        assert hit["type"] == SearchType.MUSIC
        assert hit["music_type"] == "track"
        assert hit["description"] == "Singer"
        assert hit["poster_path"] == "https://img.spotify.com/track_album.jpg"

    def test_no_album_images(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_spotify_track({"album": {"images": []}}, 0)
        assert hit["poster_path"] is None

    def test_no_album(self):
        db = MagicMock()
        svc = SearchService(db)
        hit = svc._transform_spotify_track({}, 0)
        assert hit["album_spotify_id"] is None


# ============================================================================
# SearchService — _should_search_* methods
# ============================================================================


class TestShouldSearchMethods:
    """Test _should_search_movies, _should_search_shows, _should_search_games, _should_search_music."""

    @pytest.mark.asyncio
    async def test_should_search_movies_returns_false_for_shows_type(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_movies(SearchType.SHOWS) is False

    @pytest.mark.asyncio
    async def test_should_search_movies_returns_false_for_games_type(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_movies(SearchType.GAMES) is False

    @pytest.mark.asyncio
    async def test_should_search_movies_returns_false_for_music_type(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_movies(SearchType.MUSIC) is False

    @pytest.mark.asyncio
    async def test_should_search_movies_with_active_library(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = {"MOVIES", "SHOWS"}
        assert await svc._should_search_movies(SearchType.ALL) is True

    @pytest.mark.asyncio
    async def test_should_search_movies_without_active_library(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = {"SHOWS"}
        assert await svc._should_search_movies(SearchType.ALL) is False

    @pytest.mark.asyncio
    async def test_should_search_shows_returns_false_for_movies_type(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_shows(SearchType.MOVIES) is False

    @pytest.mark.asyncio
    async def test_should_search_shows_returns_false_for_games_type(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_shows(SearchType.GAMES) is False

    @pytest.mark.asyncio
    async def test_should_search_shows_returns_false_for_music_type(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_shows(SearchType.MUSIC) is False

    @pytest.mark.asyncio
    async def test_should_search_shows_with_active_library(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = {"SHOWS"}
        assert await svc._should_search_shows(SearchType.ALL) is True

    @pytest.mark.asyncio
    async def test_should_search_games_returns_false_for_movies(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_games(SearchType.MOVIES) is False

    @pytest.mark.asyncio
    async def test_should_search_games_returns_false_for_shows(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_games(SearchType.SHOWS) is False

    @pytest.mark.asyncio
    async def test_should_search_games_returns_false_for_music(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_games(SearchType.MUSIC) is False

    @pytest.mark.asyncio
    async def test_should_search_games_with_active_library(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = {"GAMES"}
        assert await svc._should_search_games(SearchType.ALL) is True

    @pytest.mark.asyncio
    async def test_should_search_music_returns_false_for_movies(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_music(SearchType.MOVIES) is False

    @pytest.mark.asyncio
    async def test_should_search_music_returns_false_for_shows(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_music(SearchType.SHOWS) is False

    @pytest.mark.asyncio
    async def test_should_search_music_returns_false_for_games(self):
        db = MagicMock()
        svc = SearchService(db)
        assert await svc._should_search_music(SearchType.GAMES) is False

    @pytest.mark.asyncio
    async def test_should_search_music_with_active_library(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = {"MUSIC"}
        assert await svc._should_search_music(SearchType.MUSIC) is True


# ============================================================================
# SearchService — Client initialization
# ============================================================================


class TestClientInit:
    """Test _get_tmdb_client, _get_igdb_client, _get_spotify_client."""

    @pytest.mark.asyncio
    async def test_get_tmdb_client_no_api_key(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_tmdb_api_key = AsyncMock(return_value=None)
        result = await svc._get_tmdb_client()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_tmdb_client_with_api_key(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_tmdb_api_key = AsyncMock(return_value="test_api_key_12345678")
        result = await svc._get_tmdb_client()
        assert result is not None
        assert svc._tmdb is not None

    @pytest.mark.asyncio
    async def test_get_tmdb_client_cached(self):
        db = MagicMock()
        svc = SearchService(db)
        mock_tmdb = MagicMock()
        svc._tmdb = mock_tmdb
        result = await svc._get_tmdb_client()
        assert result is mock_tmdb

    @pytest.mark.asyncio
    async def test_get_igdb_client_no_credentials(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_igdb_credentials = AsyncMock(return_value=(None, None))
        result = await svc._get_igdb_client()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_igdb_client_with_credentials(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_igdb_credentials = AsyncMock(return_value=("client_id", "client_secret"))
        result = await svc._get_igdb_client()
        assert result is not None
        assert svc._igdb is not None

    @pytest.mark.asyncio
    async def test_get_igdb_client_cached(self):
        db = MagicMock()
        svc = SearchService(db)
        mock_igdb = MagicMock()
        svc._igdb = mock_igdb
        result = await svc._get_igdb_client()
        assert result is mock_igdb

    @pytest.mark.asyncio
    async def test_get_spotify_client_no_credentials(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_spotify_credentials = AsyncMock(return_value=(None, None))
        result = await svc._get_spotify_client()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_spotify_client_with_credentials(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._settings_service = MagicMock()
        svc._settings_service.get_spotify_credentials = AsyncMock(return_value=("client_id", "client_secret"))
        result = await svc._get_spotify_client()
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_spotify_client_cached(self):
        db = MagicMock()
        svc = SearchService(db)
        mock_spotify = MagicMock()
        svc._spotify = mock_spotify
        result = await svc._get_spotify_client()
        assert result is mock_spotify


# ============================================================================
# SearchService — _search_tmdb_movies / _search_tmdb_shows
# ============================================================================


class TestSearchTmdbMovies:
    """Test _search_tmdb_movies."""

    @pytest.mark.asyncio
    async def test_success(self):
        db = MagicMock()
        svc = SearchService(db)
        tmdb = AsyncMock()
        tmdb.search_movies = AsyncMock(return_value={
            "results": [
                {"id": 1, "title": "Movie 1", "popularity": 100.0},
                {"id": 2, "title": "Movie 2", "popularity": 50.0},
            ],
            "total_results": 2,
        })
        req = _search_request("test movie", SearchType.MOVIES)
        result = await svc._search_tmdb_movies(tmdb, req)
        assert len(result["hits"]) == 2
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_with_year_filter(self):
        db = MagicMock()
        svc = SearchService(db)
        tmdb = AsyncMock()
        tmdb.search_movies = AsyncMock(return_value={"results": [], "total_results": 0})
        req = _search_request("test", SearchType.MOVIES, year_from=2023, year_to=2023)
        await svc._search_tmdb_movies(tmdb, req)
        tmdb.search_movies.assert_called_once_with("test", year=2023)

    @pytest.mark.asyncio
    async def test_no_results_key(self):
        db = MagicMock()
        svc = SearchService(db)
        tmdb = AsyncMock()
        tmdb.search_movies = AsyncMock(return_value={"error": "something"})
        req = _search_request("test", SearchType.MOVIES)
        result = await svc._search_tmdb_movies(tmdb, req)
        assert result["hits"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_none_result(self):
        db = MagicMock()
        svc = SearchService(db)
        tmdb = AsyncMock()
        tmdb.search_movies = AsyncMock(return_value=None)
        req = _search_request("test", SearchType.MOVIES)
        result = await svc._search_tmdb_movies(tmdb, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_exception(self):
        db = MagicMock()
        svc = SearchService(db)
        tmdb = AsyncMock()
        tmdb.search_movies = AsyncMock(side_effect=ConnectionError("API Error"))
        req = _search_request("test", SearchType.MOVIES)
        result = await svc._search_tmdb_movies(tmdb, req)
        assert result["hits"] == []
        assert result["total"] == 0


class TestSearchTmdbShows:
    """Test _search_tmdb_shows."""

    @pytest.mark.asyncio
    async def test_success(self):
        db = MagicMock()
        svc = SearchService(db)
        tmdb = AsyncMock()
        tmdb._request = AsyncMock(return_value={
            "results": [
                {"id": 10, "name": "Show 1", "popularity": 100.0},
            ],
            "total_results": 1,
        })
        req = _search_request("test show", SearchType.SHOWS)
        result = await svc._search_tmdb_shows(tmdb, req)
        assert len(result["hits"]) == 1
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_with_year_filter(self):
        db = MagicMock()
        svc = SearchService(db)
        tmdb = AsyncMock()
        tmdb._request = AsyncMock(return_value={"results": [], "total_results": 0})
        req = _search_request("test", SearchType.SHOWS, year_from=2022, year_to=2022)
        await svc._search_tmdb_shows(tmdb, req)
        call_args = tmdb._request.call_args
        params = call_args.kwargs.get("params", call_args[1].get("params", {}))
        assert params.get("first_air_date_year") == 2022

    @pytest.mark.asyncio
    async def test_no_results_key(self):
        db = MagicMock()
        svc = SearchService(db)
        tmdb = AsyncMock()
        tmdb._request = AsyncMock(return_value={})
        req = _search_request("test", SearchType.SHOWS)
        result = await svc._search_tmdb_shows(tmdb, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_exception(self):
        db = MagicMock()
        svc = SearchService(db)
        tmdb = AsyncMock()
        tmdb._request = AsyncMock(side_effect=ConnectionError("TMDB Error"))
        req = _search_request("test", SearchType.SHOWS)
        result = await svc._search_tmdb_shows(tmdb, req)
        assert result["hits"] == []


# ============================================================================
# SearchService — _search_igdb_games
# ============================================================================


class TestSearchIgdbGames:
    """Test _search_igdb_games."""

    @pytest.mark.asyncio
    async def test_success(self):
        db = MagicMock()
        svc = SearchService(db)
        igdb = AsyncMock()
        igdb.search_games = AsyncMock(return_value=[
            {"id": 1, "name": "Game1", "rating": 80},
            {"id": 2, "name": "Game2", "rating": 60},
        ])
        req = _search_request("game", SearchType.GAMES)
        result = await svc._search_igdb_games(igdb, req)
        assert len(result["hits"]) == 2
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_empty_results(self):
        db = MagicMock()
        svc = SearchService(db)
        igdb = AsyncMock()
        igdb.search_games = AsyncMock(return_value=[])
        req = _search_request("game", SearchType.GAMES)
        result = await svc._search_igdb_games(igdb, req)
        assert result["hits"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_none_results(self):
        db = MagicMock()
        svc = SearchService(db)
        igdb = AsyncMock()
        igdb.search_games = AsyncMock(return_value=None)
        req = _search_request("game", SearchType.GAMES)
        result = await svc._search_igdb_games(igdb, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_exception(self):
        db = MagicMock()
        svc = SearchService(db)
        igdb = AsyncMock()
        igdb.search_games = AsyncMock(side_effect=ConnectionError("IGDB Error"))
        req = _search_request("game", SearchType.GAMES)
        result = await svc._search_igdb_games(igdb, req)
        assert result["hits"] == []


# ============================================================================
# SearchService — _search_spotify_artists / _search_spotify_albums / _search_spotify_tracks
# ============================================================================


class TestSearchSpotifyArtists:
    """Test _search_spotify_artists."""

    @pytest.mark.asyncio
    async def test_success(self):
        db = MagicMock()
        svc = SearchService(db)
        spotify = AsyncMock()
        spotify.search_artists = AsyncMock(return_value=[
            {"id": "a1", "name": "Artist1", "popularity": 90, "images": [], "genres": ["pop"]},
        ])
        req = _search_request("artist", SearchType.MUSIC)
        result = await svc._search_spotify_artists(spotify, req)
        assert len(result["hits"]) == 1
        assert result["hits"][0]["music_type"] == "artist"

    @pytest.mark.asyncio
    async def test_empty_results(self):
        db = MagicMock()
        svc = SearchService(db)
        spotify = AsyncMock()
        spotify.search_artists = AsyncMock(return_value=[])
        req = _search_request("artist", SearchType.MUSIC)
        result = await svc._search_spotify_artists(spotify, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_none_results(self):
        db = MagicMock()
        svc = SearchService(db)
        spotify = AsyncMock()
        spotify.search_artists = AsyncMock(return_value=None)
        req = _search_request("artist", SearchType.MUSIC)
        result = await svc._search_spotify_artists(spotify, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_exception(self):
        db = MagicMock()
        svc = SearchService(db)
        spotify = AsyncMock()
        spotify.search_artists = AsyncMock(side_effect=ConnectionError("Spotify Error"))
        req = _search_request("artist", SearchType.MUSIC)
        result = await svc._search_spotify_artists(spotify, req)
        assert result["hits"] == []


class TestSearchSpotifyAlbums:
    """Test _search_spotify_albums."""

    @pytest.mark.asyncio
    async def test_success(self):
        db = MagicMock()
        svc = SearchService(db)
        spotify = AsyncMock()
        spotify.search_albums = AsyncMock(return_value=[
            {"id": "al1", "name": "Album1", "popularity": 80, "images": [], "artists": [{"name": "A"}]},
        ])
        req = _search_request("album", SearchType.MUSIC)
        result = await svc._search_spotify_albums(spotify, req)
        assert len(result["hits"]) == 1

    @pytest.mark.asyncio
    async def test_none_results(self):
        db = MagicMock()
        svc = SearchService(db)
        spotify = AsyncMock()
        spotify.search_albums = AsyncMock(return_value=None)
        req = _search_request("album", SearchType.MUSIC)
        result = await svc._search_spotify_albums(spotify, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_exception(self):
        db = MagicMock()
        svc = SearchService(db)
        spotify = AsyncMock()
        spotify.search_albums = AsyncMock(side_effect=ConnectionError("err"))
        req = _search_request("album", SearchType.MUSIC)
        result = await svc._search_spotify_albums(spotify, req)
        assert result["hits"] == []


class TestSearchSpotifyTracks:
    """Test _search_spotify_tracks."""

    @pytest.mark.asyncio
    async def test_success(self):
        db = MagicMock()
        svc = SearchService(db)
        spotify = AsyncMock()
        spotify.search_tracks = AsyncMock(return_value=[
            {"id": "t1", "name": "Track1", "popularity": 70, "artists": [{"name": "A"}], "album": {"id": "al1", "images": [], "release_date": "2023-01-01"}},
        ])
        req = _search_request("track", SearchType.MUSIC)
        result = await svc._search_spotify_tracks(spotify, req)
        assert len(result["hits"]) == 1
        assert result["hits"][0]["music_type"] == "track"

    @pytest.mark.asyncio
    async def test_none_results(self):
        db = MagicMock()
        svc = SearchService(db)
        spotify = AsyncMock()
        spotify.search_tracks = AsyncMock(return_value=None)
        req = _search_request("track", SearchType.MUSIC)
        result = await svc._search_spotify_tracks(spotify, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_exception(self):
        db = MagicMock()
        svc = SearchService(db)
        spotify = AsyncMock()
        spotify.search_tracks = AsyncMock(side_effect=ConnectionError("err"))
        req = _search_request("track", SearchType.MUSIC)
        result = await svc._search_spotify_tracks(spotify, req)
        assert result["hits"] == []


# ============================================================================
# SearchService — _search_provider
# ============================================================================


class TestSearchProvider:
    """Test _search_provider."""

    @pytest.mark.asyncio
    async def test_no_active_libraries(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = set()
        req = _search_request("test")
        result = await svc._search_provider(req)
        assert result["hits"] == []
        assert "No active libraries" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_movies_only(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = {"MOVIES"}
        svc._settings_service = MagicMock()
        svc._settings_service.get_tmdb_api_key = AsyncMock(return_value="test_key_12345678")

        with patch.object(svc, "_search_tmdb_movies", new_callable=AsyncMock) as mock_movies:
            mock_movies.return_value = {"hits": [{"title": "M1", "score": 5}], "total": 1}
            req = _search_request("test", SearchType.MOVIES)
            result = await svc._search_provider(req)
            assert len(result["hits"]) == 1
            mock_movies.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_all_sorts_by_score(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = {"MOVIES", "SHOWS"}
        svc._settings_service = MagicMock()
        svc._settings_service.get_tmdb_api_key = AsyncMock(return_value="test_key_12345678")

        with (
            patch.object(svc, "_search_tmdb_movies", new_callable=AsyncMock) as mock_movies,
            patch.object(svc, "_search_tmdb_shows", new_callable=AsyncMock) as mock_shows,
        ):
            mock_movies.return_value = {"hits": [{"title": "M1", "score": 3}], "total": 1}
            mock_shows.return_value = {"hits": [{"title": "S1", "score": 9}], "total": 1}
            req = _search_request("test", SearchType.ALL)
            result = await svc._search_provider(req)
            assert result["hits"][0]["title"] == "S1"
            assert result["hits"][1]["title"] == "M1"

    @pytest.mark.asyncio
    async def test_games_search(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = {"GAMES"}
        svc._settings_service = MagicMock()
        svc._settings_service.get_igdb_credentials = AsyncMock(return_value=("id", "secret"))

        with patch.object(svc, "_search_igdb_games", new_callable=AsyncMock) as mock_games:
            mock_games.return_value = {"hits": [{"title": "G1", "score": 7}], "total": 1}
            req = _search_request("game", SearchType.GAMES)
            result = await svc._search_provider(req)
            assert len(result["hits"]) == 1

    @pytest.mark.asyncio
    async def test_music_search(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = {"MUSIC"}
        svc._settings_service = MagicMock()
        svc._settings_service.get_spotify_credentials = AsyncMock(return_value=("id", "secret"))

        with patch.object(svc, "_search_spotify_artists", new_callable=AsyncMock) as mock_artists:
            mock_artists.return_value = {"hits": [{"title": "A1", "score": 5}], "total": 1}
            req = _search_request("artist", SearchType.MUSIC)
            result = await svc._search_provider(req)
            assert len(result["hits"]) == 1

    @pytest.mark.asyncio
    async def test_no_provider_clients_returns_none(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = {"MOVIES"}
        svc._settings_service = MagicMock()
        svc._settings_service.get_tmdb_api_key = AsyncMock(return_value=None)

        req = _search_request("test", SearchType.MOVIES)
        result = await svc._search_provider(req)
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._active_library_types = {"MOVIES"}
        svc._settings_service = MagicMock()
        svc._settings_service.get_tmdb_api_key = AsyncMock(side_effect=ConnectionError("boom"))

        req = _search_request("test", SearchType.MOVIES)
        result = await svc._search_provider(req)
        assert result is None


# ============================================================================
# SearchService — _search_local
# ============================================================================


class TestSearchLocal:
    """Test _search_local."""

    @pytest.mark.asyncio
    async def test_movies_search(self):
        db = MagicMock()
        svc = SearchService(db)
        with patch("pyrate.services.search.elasticsearch_service") as mock_es:
            mock_es.search_movies = AsyncMock(return_value={"hits": [], "total": 0})
            req = _search_request("test", SearchType.MOVIES)
            result = await svc._search_local(req)
            assert result["source"] == "local"
            mock_es.search_movies.assert_called_once()

    @pytest.mark.asyncio
    async def test_shows_search(self):
        db = MagicMock()
        svc = SearchService(db)
        with patch("pyrate.services.search.elasticsearch_service") as mock_es:
            mock_es.search_shows = AsyncMock(return_value={"hits": [], "total": 0})
            req = _search_request("test", SearchType.SHOWS)
            result = await svc._search_local(req)
            mock_es.search_shows.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_search(self):
        db = MagicMock()
        svc = SearchService(db)
        with patch("pyrate.services.search.elasticsearch_service") as mock_es:
            mock_es.search_all = AsyncMock(return_value={"hits": [], "total": 0})
            req = _search_request("test", SearchType.ALL)
            result = await svc._search_local(req)
            mock_es.search_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        db = MagicMock()
        svc = SearchService(db)
        with patch("pyrate.services.search.elasticsearch_service") as mock_es:
            mock_es.search_all = AsyncMock(side_effect=ConnectionError("ES down"))
            req = _search_request("test", SearchType.ALL)
            result = await svc._search_local(req)
            assert result["hits"] == []
            assert "error" in result


# ============================================================================
# SearchService — search (top-level)
# ============================================================================


class TestSearchTopLevel:
    """Test the main search() method."""

    @pytest.mark.asyncio
    async def test_provider_results_returned(self):
        db = MagicMock()
        svc = SearchService(db)
        provider_result = {"hits": [{"title": "M1"}], "total": 1}
        with (
            patch.object(svc, "_search_provider", new_callable=AsyncMock, return_value=provider_result),
            patch.object(svc, "_queue_imports", new_callable=AsyncMock) as mock_queue,
        ):
            req = _search_request("test")
            result = await svc.search(req)
            assert result["hits"][0]["title"] == "M1"
            mock_queue.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_queue_import(self):
        db = MagicMock()
        svc = SearchService(db)
        provider_result = {"hits": [{"title": "M1"}], "total": 1}
        with (
            patch.object(svc, "_search_provider", new_callable=AsyncMock, return_value=provider_result),
            patch.object(svc, "_queue_imports", new_callable=AsyncMock) as mock_queue,
        ):
            req = _search_request("test")
            result = await svc.search(req, queue_import=False)
            mock_queue.assert_not_called()

    @pytest.mark.asyncio
    async def test_provider_fails_falls_back_to_local(self):
        db = MagicMock()
        svc = SearchService(db)
        with (
            patch.object(svc, "_search_provider", new_callable=AsyncMock, side_effect=ConnectionError("fail")),
            patch.object(svc, "_search_local", new_callable=AsyncMock, return_value={"hits": [], "total": 0}) as mock_local,
        ):
            req = _search_request("test")
            result = await svc.search(req)
            mock_local.assert_called_once()

    @pytest.mark.asyncio
    async def test_unexpected_provider_error_does_not_fall_back(self):
        db = MagicMock()
        svc = SearchService(db)
        with (
            patch.object(svc, "_search_provider", new_callable=AsyncMock, side_effect=ValueError("bug")),
            patch.object(svc, "_search_local", new_callable=AsyncMock) as mock_local,
        ):
            req = _search_request("test")
            with pytest.raises(ValueError):
                await svc.search(req)
            mock_local.assert_not_called()

    @pytest.mark.asyncio
    async def test_provider_returns_empty_falls_back(self):
        db = MagicMock()
        svc = SearchService(db)
        with (
            patch.object(svc, "_search_provider", new_callable=AsyncMock, return_value={"hits": [], "total": 0}),
            patch.object(svc, "_search_local", new_callable=AsyncMock, return_value={"hits": [], "total": 0}) as mock_local,
        ):
            req = _search_request("test")
            await svc.search(req)
            mock_local.assert_called_once()

    @pytest.mark.asyncio
    async def test_provider_returns_none_falls_back(self):
        db = MagicMock()
        svc = SearchService(db)
        with (
            patch.object(svc, "_search_provider", new_callable=AsyncMock, return_value=None),
            patch.object(svc, "_search_local", new_callable=AsyncMock, return_value={"hits": [], "total": 0}) as mock_local,
        ):
            req = _search_request("test")
            await svc.search(req)
            mock_local.assert_called_once()


# ============================================================================
# SearchService — close
# ============================================================================


class TestSearchServiceClose:
    """Test close() method."""

    @pytest.mark.asyncio
    async def test_close_all_clients(self):
        db = MagicMock()
        svc = SearchService(db)
        svc._tmdb = AsyncMock()
        svc._igdb = AsyncMock()
        svc._spotify = AsyncMock()
        svc._redis = AsyncMock()
        await svc.close()
        svc._tmdb is None
        svc._igdb is None
        svc._spotify is None
        svc._redis is None

    @pytest.mark.asyncio
    async def test_close_no_clients(self):
        db = MagicMock()
        svc = SearchService(db)
        await svc.close()  # Should not error


# ============================================================================
# SearchService — _acquire_import_lock
# ============================================================================

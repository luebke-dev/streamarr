"""Tests for the Spotify plugin with mocked HTTP calls."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def spotify(mock_client):
    from pyrate.metadata.spotify import Spotify, _response_cache

    _response_cache.clear()

    return Spotify(
        client_id="test-client-id",
        client_secret="test-client-secret",
        client=mock_client,
    )


def _auth_response():
    return {"access_token": "test-token", "expires_in": 3600}


def _mock_response(json_data, status_code=200, headers=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        error = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
        resp.raise_for_status.side_effect = error
    return resp


# ---------------------------------------------------------------------------
# Basic attributes
# ---------------------------------------------------------------------------

class TestBasicAttributes:
    def test_get_name(self, spotify):
        assert spotify.get_name() == "Spotify"

    def test_get_config_schema(self, spotify):
        schema = spotify.get_config_schema()
        assert "client_id" in schema
        assert "client_secret" in schema
        assert schema["client_id"]["type"] == "string"
        assert schema["client_secret"]["type"] == "password"


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuthentication:
    @pytest.mark.asyncio
    async def test_authenticate_success(self, spotify, mock_client):
        mock_client.post.return_value = _mock_response(_auth_response())
        result = await spotify._authenticate()
        assert result is True
        assert spotify.access_token == "test-token"
        assert spotify.token_expires_at is not None

    @pytest.mark.asyncio
    async def test_authenticate_failure(self, spotify, mock_client):
        mock_client.post.side_effect = Exception("Network error")
        result = await spotify._authenticate()
        assert result is False
        assert spotify.access_token is None

    @pytest.mark.asyncio
    async def test_ensure_authenticated_when_valid(self, spotify):
        spotify.access_token = "existing-token"
        spotify.token_expires_at = time.time() + 3600
        result = await spotify._ensure_authenticated()
        assert result is True

    @pytest.mark.asyncio
    async def test_ensure_authenticated_when_expired(self, spotify, mock_client):
        spotify.access_token = "old-token"
        spotify.token_expires_at = time.time() - 10
        mock_client.post.return_value = _mock_response(_auth_response())
        result = await spotify._ensure_authenticated()
        assert result is True
        assert spotify.access_token == "test-token"

    @pytest.mark.asyncio
    async def test_ensure_authenticated_when_no_token(self, spotify, mock_client):
        mock_client.post.return_value = _mock_response(_auth_response())
        result = await spotify._ensure_authenticated()
        assert result is True


# ---------------------------------------------------------------------------
# _request
# ---------------------------------------------------------------------------

class TestRequest:
    @pytest.mark.asyncio
    async def test_request_success(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({"data": "value"})
        result = await spotify._request("test/endpoint", {"q": "test"})
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_request_auth_fails(self, spotify, mock_client):
        mock_client.post.side_effect = Exception("auth fail")
        result = await spotify._request("test/endpoint")
        assert result == {}

    @pytest.mark.asyncio
    async def test_request_rate_limited(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {}, status_code=429, headers={"Retry-After": "1"}
        )
        result = await spotify._request("test/endpoint")
        assert result == {}

    @pytest.mark.asyncio
    async def test_request_http_error(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({}, status_code=500)
        result = await spotify._request("test/endpoint")
        assert result == {}

    @pytest.mark.asyncio
    async def test_request_generic_exception(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.side_effect = Exception("unexpected")
        result = await spotify._request("test/endpoint")
        assert result == {}


# ---------------------------------------------------------------------------
# Search methods
# ---------------------------------------------------------------------------

class TestSearch:
    @pytest.mark.asyncio
    async def test_search_albums(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"albums": {"items": [{"id": "1", "name": "Album 1"}]}}
        )
        result = await spotify.search_albums("test")
        assert len(result) == 1
        assert result[0]["name"] == "Album 1"

    @pytest.mark.asyncio
    async def test_search_albums_empty(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({})
        result = await spotify.search_albums("test")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_tracks(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"tracks": {"items": [{"id": "t1", "name": "Track 1"}]}}
        )
        result = await spotify.search_tracks("test")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_tracks_empty(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({})
        result = await spotify.search_tracks("test")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_artists(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"artists": {"items": [{"id": "a1", "name": "Artist 1"}]}}
        )
        result = await spotify.search_artists("test")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_artists_empty(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({})
        result = await spotify.search_artists("test")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_dispatches_album(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"albums": {"items": [{"id": "1"}]}}
        )
        result = await spotify.search("test", search_type="album")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_dispatches_track(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"tracks": {"items": [{"id": "t1"}]}}
        )
        result = await spotify.search("test", search_type="track")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_dispatches_artist(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"artists": {"items": [{"id": "a1"}]}}
        )
        result = await spotify.search("test", search_type="artist")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_default_type(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"albums": {"items": [{"id": "1"}]}}
        )
        result = await spotify.search("test")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_unknown_type_defaults_to_album(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"albums": {"items": [{"id": "1"}]}}
        )
        result = await spotify.search("test", search_type="unknown")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Detail methods
# ---------------------------------------------------------------------------

class TestDetails:
    @pytest.mark.asyncio
    async def test_get_album_details(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({"id": "a1", "name": "Album"})
        result = await spotify.get_album_details("a1")
        assert result["name"] == "Album"

    @pytest.mark.asyncio
    async def test_get_album_details_empty(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({})
        result = await spotify.get_album_details("a1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_album_tracks(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"items": [{"id": "t1"}, {"id": "t2"}]}
        )
        result = await spotify.get_album_tracks("a1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_album_tracks_empty(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({})
        result = await spotify.get_album_tracks("a1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_track_details(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({"id": "t1", "name": "Track"})
        result = await spotify.get_track_details("t1")
        assert result["name"] == "Track"

    @pytest.mark.asyncio
    async def test_get_track_details_empty(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({})
        result = await spotify.get_track_details("t1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_artist_details(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({"id": "ar1", "name": "Artist"})
        result = await spotify.get_artist_details("ar1")
        assert result["name"] == "Artist"

    @pytest.mark.asyncio
    async def test_get_artist_details_empty(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({})
        result = await spotify.get_artist_details("ar1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_artist_albums(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"items": [{"id": "a1"}]}
        )
        result = await spotify.get_artist_albums("ar1")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_artist_albums_empty(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({})
        result = await spotify.get_artist_albums("ar1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_details_album(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({"id": "a1"})
        result = await spotify.get_details("a1", media_type="album")
        assert result == {"id": "a1"}

    @pytest.mark.asyncio
    async def test_get_details_track(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({"id": "t1"})
        result = await spotify.get_details("t1", media_type="track")
        assert result == {"id": "t1"}

    @pytest.mark.asyncio
    async def test_get_details_artist(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({"id": "ar1"})
        result = await spotify.get_details("ar1", media_type="artist")
        assert result == {"id": "ar1"}

    @pytest.mark.asyncio
    async def test_get_details_default(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({"id": "a1"})
        result = await spotify.get_details("a1", media_type="unknown")
        assert result == {"id": "a1"}


# ---------------------------------------------------------------------------
# Browse methods
# ---------------------------------------------------------------------------

class TestBrowse:
    @pytest.mark.asyncio
    async def test_get_new_releases(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"albums": {"items": [{"id": "1"}]}}
        )
        result = await spotify.get_new_releases()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_new_releases_empty(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({})
        result = await spotify.get_new_releases()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_featured_playlists(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"playlists": {"items": [{"id": "p1"}]}}
        )
        result = await spotify.get_featured_playlists()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_featured_playlists_empty(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({})
        result = await spotify.get_featured_playlists()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_categories(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"categories": {"items": [{"id": "c1"}]}}
        )
        result = await spotify.get_categories()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_categories_empty(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({})
        result = await spotify.get_categories()
        assert result == []


# ---------------------------------------------------------------------------
# IndexerPlugin interface
# ---------------------------------------------------------------------------

class TestIndexerInterface:
    @pytest.mark.asyncio
    async def test_search_movie_returns_empty(self, spotify):
        result = await spotify.search_movie(q="test")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_show_returns_empty(self, spotify):
        result = await spotify.search_show(q="test")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_music_by_query(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"tracks": {"items": [
                {
                    "id": "t1",
                    "name": "Song 1",
                    "artists": [{"name": "Artist 1"}],
                    "album": {"name": "Album 1", "images": [{"url": "http://img.jpg"}], "id": "a1"},
                    "duration_ms": 180000,
                }
            ]}}
        )
        result = await spotify.search_music(q="test song")
        assert len(result) == 1
        assert result[0]["artist"] == "Artist 1"
        assert result[0]["source"] == "spotify"
        assert result[0]["spotify_id"] == "t1"
        assert "link" in result[0]

    @pytest.mark.asyncio
    async def test_search_music_by_spotify_id_track(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({
            "id": "t1",
            "type": "track",
            "name": "Song",
            "artists": [{"name": "Art"}],
            "album": {"name": "Alb", "images": [], "id": "a1"},
            "duration_ms": 200000,
        })
        result = await spotify.search_music(spotify_id="t1")
        assert len(result) == 1
        assert result[0]["spotify_id"] == "t1"

    @pytest.mark.asyncio
    async def test_search_music_by_spotify_id_album(self, spotify, mock_client):
        spotify.access_token = "token"
        spotify.token_expires_at = time.time() + 3600
        # First call returns non-track, second returns album with tracks
        mock_client.get.side_effect = [
            _mock_response({"id": "a1", "type": "album"}),  # track lookup fails
            _mock_response({  # album lookup
                "id": "a1",
                "name": "Album",
                "images": [{"url": "http://img.jpg"}],
                "tracks": {"items": [
                    {
                        "id": "t1",
                        "name": "Track 1",
                        "artists": [{"name": "Art"}],
                        "duration_ms": 180000,
                    }
                ]},
            }),
        ]
        result = await spotify.search_music(spotify_id="a1")
        assert len(result) == 1
        assert result[0]["album"] == "Album"

    @pytest.mark.asyncio
    async def test_search_music_no_query_no_id(self, spotify):
        result = await spotify.search_music()
        assert result == []


# ---------------------------------------------------------------------------
# _track_to_release
# ---------------------------------------------------------------------------

class TestTrackToRelease:
    def test_track_to_release_full(self, spotify):
        track = {
            "id": "t1",
            "name": "My Song",
            "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
            "album": {"name": "My Album", "images": [{"url": "http://img.jpg"}], "id": "a1"},
            "duration_ms": 240000,
        }
        release = spotify._track_to_release(track)
        assert release["title"] == "Artist A, Artist B - My Song"
        assert release["spotify_id"] == "t1"
        assert release["artist"] == "Artist A, Artist B"
        assert release["album"] == "My Album"
        assert release["poster"] == "http://img.jpg"
        assert release["size"] > 0

    def test_track_to_release_no_artists(self, spotify):
        track = {
            "id": "t1",
            "name": "Instrumental",
            "artists": [],
            "album": {},
            "duration_ms": 0,
        }
        release = spotify._track_to_release(track)
        assert release["title"] == "Instrumental"
        assert release["size"] == 0
        assert release["poster"] is None


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------

class TestValidateConfig:
    @pytest.mark.asyncio
    async def test_validate_config_missing_fields(self, spotify):
        result = await spotify.validate_config({})
        assert result["valid"] is False
        assert len(result["errors"]) == 2

    @pytest.mark.asyncio
    async def test_validate_config_missing_client_id(self, spotify):
        result = await spotify.validate_config({"client_secret": "s"})
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("pyrate.metadata.spotify.httpx.AsyncClient")
    async def test_validate_config_success(self, mock_client_cls, spotify):
        mock_instance = AsyncMock()
        mock_instance.post.return_value = _mock_response({})
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await spotify.validate_config(
            {"client_id": "id", "client_secret": "secret"}
        )
        assert result["valid"] is True

    @pytest.mark.asyncio
    @patch("pyrate.metadata.spotify.httpx.AsyncClient")
    async def test_validate_config_unauthorized(self, mock_client_cls, spotify):
        mock_instance = AsyncMock()
        resp = MagicMock()
        resp.status_code = 401
        mock_instance.post.return_value = resp
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await spotify.validate_config(
            {"client_id": "id", "client_secret": "bad"}
        )
        assert result["valid"] is False
        assert any("Invalid" in e for e in result["errors"])

    @pytest.mark.asyncio
    @patch("pyrate.metadata.spotify.httpx.AsyncClient")
    async def test_validate_config_other_status(self, mock_client_cls, spotify):
        mock_instance = AsyncMock()
        resp = MagicMock()
        resp.status_code = 500
        mock_instance.post.return_value = resp
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await spotify.validate_config(
            {"client_id": "id", "client_secret": "secret"}
        )
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("pyrate.metadata.spotify.httpx.AsyncClient")
    async def test_validate_config_timeout(self, mock_client_cls, spotify):
        mock_instance = AsyncMock()
        mock_instance.post.side_effect = httpx.TimeoutException("timeout")
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await spotify.validate_config(
            {"client_id": "id", "client_secret": "secret"}
        )
        assert result["valid"] is False
        assert any("timed out" in e for e in result["errors"])

    @pytest.mark.asyncio
    @patch("pyrate.metadata.spotify.httpx.AsyncClient")
    async def test_validate_config_http_error(self, mock_client_cls, spotify):
        mock_instance = AsyncMock()
        mock_instance.post.side_effect = httpx.HTTPError("connection error")
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await spotify.validate_config(
            {"client_id": "id", "client_secret": "secret"}
        )
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("pyrate.metadata.spotify.httpx.AsyncClient")
    async def test_validate_config_unexpected_error(self, mock_client_cls, spotify):
        mock_instance = AsyncMock()
        mock_instance.post.side_effect = RuntimeError("unexpected")
        mock_client_cls.return_value = mock_instance
        result = await spotify.validate_config(
            {"client_id": "id", "client_secret": "secret"}
        )
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# close and async_setup
# ---------------------------------------------------------------------------

class TestCloseAndSetup:
    @pytest.mark.asyncio
    async def test_close(self, spotify, mock_client):
        mock_client.aclose = AsyncMock()
        await spotify.close()
        mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_success(self):
        from pyrate.metadata.spotify import async_setup

        result = await async_setup({"client_id": "id", "client_secret": "secret"})
        assert result is True

    @pytest.mark.asyncio
    async def test_async_setup_missing_field(self):
        from pyrate.metadata.spotify import async_setup

        result = await async_setup({"client_id": "id"})
        assert result is False

    @pytest.mark.asyncio
    async def test_async_setup_empty(self):
        from pyrate.metadata.spotify import async_setup

        result = await async_setup({})
        assert result is False

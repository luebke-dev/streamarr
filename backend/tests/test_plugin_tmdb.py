"""Tests for the TMDB plugin with mocked HTTP calls."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def tmdb(mock_client):
    from streamarr.metadata.tmdb import TMDB

    return TMDB(
        api_key="test-api-key",
        client=mock_client,
        max_retries=2,
        retry_delay=0.01,
    )


def _mock_response(json_data, status_code=200, headers=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.headers = headers or {}
    return resp


# ---------------------------------------------------------------------------
# Basic attributes
# ---------------------------------------------------------------------------

class TestBasicAttributes:
    def test_get_name(self, tmdb):
        assert tmdb.get_name() == "TMDB"

    def test_get_config_schema(self, tmdb):
        schema = tmdb.get_config_schema()
        assert "api_key" in schema
        assert schema["api_key"]["type"] == "password"


# ---------------------------------------------------------------------------
# _request with retry
# ---------------------------------------------------------------------------

class TestRequest:
    @pytest.mark.asyncio
    async def test_request_success(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"data": "value"})
        result = await tmdb._request("test/endpoint")
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_request_with_result_key(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"result": {"id": 1}})
        result = await tmdb._request("test/endpoint")
        assert result == {"id": 1}

    @pytest.mark.asyncio
    async def test_request_rate_limited_then_success(self, tmdb, mock_client):
        mock_client.get.side_effect = [
            _mock_response({}, status_code=429, headers={"Retry-After": "0.01"}),
            _mock_response({"data": "value"}),
        ]
        result = await tmdb._request("test/endpoint")
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_request_rate_limited_no_retry_after(self, tmdb, mock_client):
        mock_client.get.side_effect = [
            _mock_response({}, status_code=429),
            _mock_response({"data": "value"}),
        ]
        result = await tmdb._request("test/endpoint")
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_request_rate_limited_all_retries(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response(
            {}, status_code=429, headers={"Retry-After": "0.01"}
        )
        result = await tmdb._request("test/endpoint")
        assert result == {}

    @pytest.mark.asyncio
    async def test_request_client_error(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({}, status_code=404)
        result = await tmdb._request("test/endpoint")
        assert result == {}

    @pytest.mark.asyncio
    async def test_request_timeout_then_success(self, tmdb, mock_client):
        mock_client.get.side_effect = [
            httpx.ReadTimeout("timeout"),
            _mock_response({"data": "value"}),
        ]
        result = await tmdb._request("test/endpoint")
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_request_timeout_all_retries(self, tmdb, mock_client):
        mock_client.get.side_effect = httpx.ConnectTimeout("timeout")
        result = await tmdb._request("test/endpoint")
        assert result == {}

    @pytest.mark.asyncio
    async def test_request_generic_exception(self, tmdb, mock_client):
        mock_client.get.side_effect = Exception("unexpected")
        result = await tmdb._request("test/endpoint")
        assert result == {}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    @pytest.mark.asyncio
    async def test_search_movie(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response(
            {"results": [{"id": 1}]}
        )
        result = await tmdb.search("test", media_type="movie")
        assert result == {"results": [{"id": 1}]}

    @pytest.mark.asyncio
    async def test_search_non_movie_returns_empty(self, tmdb):
        result = await tmdb.search("test", media_type="tv")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_movies_with_year(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response(
            {"results": [{"id": 1}]}
        )
        result = await tmdb.search_movies("test", year=2024)
        assert "results" in result


# ---------------------------------------------------------------------------
# Get details
# ---------------------------------------------------------------------------

class TestDetails:
    @pytest.mark.asyncio
    async def test_get_details_movie(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"id": 1, "title": "Movie"})
        result = await tmdb.get_details(1, media_type="movie")
        assert result["title"] == "Movie"

    @pytest.mark.asyncio
    async def test_get_details_tv(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"id": 1, "name": "Show"})
        result = await tmdb.get_details(1, media_type="tv")
        assert result["name"] == "Show"

    @pytest.mark.asyncio
    async def test_get_movie_details(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"id": 1})
        result = await tmdb.get_movie_details("1")
        assert result == {"id": 1}

    @pytest.mark.asyncio
    async def test_get_movie_details_no_external_ids(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"id": 1})
        result = await tmdb.get_movie_details("1", include_external_ids=False)
        assert result == {"id": 1}

    @pytest.mark.asyncio
    async def test_get_show_details(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"id": 1})
        result = await tmdb.get_show_details("1")
        assert result == {"id": 1}

    @pytest.mark.asyncio
    async def test_get_show_details_no_external_ids(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"id": 1})
        result = await tmdb.get_show_details("1", include_external_ids=False)
        assert result == {"id": 1}

    @pytest.mark.asyncio
    async def test_get_movie_credits(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"cast": []})
        result = await tmdb.get_movie_credits("1")
        assert "cast" in result

    @pytest.mark.asyncio
    async def test_get_movie_external_ids(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"imdb_id": "tt001"})
        result = await tmdb.get_movie_external_ids("1")
        assert result["imdb_id"] == "tt001"

    @pytest.mark.asyncio
    async def test_get_show_credits(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"cast": []})
        result = await tmdb.get_show_credits("1")
        assert "cast" in result

    @pytest.mark.asyncio
    async def test_get_show_external_ids(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"tvdb_id": 123})
        result = await tmdb.get_show_external_ids("1")
        assert result["tvdb_id"] == 123

    @pytest.mark.asyncio
    async def test_get_show_season(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response(
            {"episodes": [{"id": 1}]}
        )
        result = await tmdb.get_show_season("1", "1")
        assert "episodes" in result


# ---------------------------------------------------------------------------
# Trending / Popular / etc.
# ---------------------------------------------------------------------------

class TestTrending:
    @pytest.mark.asyncio
    async def test_get_trending_shows(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"results": []})
        result = await tmdb.get_trending_shows()
        assert "results" in result

    @pytest.mark.asyncio
    async def test_get_trending_movies(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"results": []})
        result = await tmdb.get_trending_movies()
        assert "results" in result

    @pytest.mark.asyncio
    async def test_get_trending_show_types(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"results": []})
        for t in ["show", "shows", "tv", "series"]:
            result = await tmdb.get_trending(t)
            assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_trending_movie_types(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"results": []})
        for t in ["movie", "movies", "film", "films"]:
            result = await tmdb.get_trending(t)
            assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_trending_invalid_type(self, tmdb):
        with pytest.raises(ValueError, match="Unsupported media type"):
            await tmdb.get_trending("podcast")

    @pytest.mark.asyncio
    async def test_get_popular_shows(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"results": []})
        result = await tmdb.get_popular_shows()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_popular_movies(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"results": []})
        result = await tmdb.get_popular_movies()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_top_rated_movies(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"results": []})
        result = await tmdb.get_top_rated_movies()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_now_playing_movies(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"results": []})
        result = await tmdb.get_now_playing_movies()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_now_playing_shows(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"results": []})
        result = await tmdb.get_now_playing_shows()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_top_rated_shows(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"results": []})
        result = await tmdb.get_top_rated_shows()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_upcoming_movies(self, tmdb, mock_client):
        mock_client.get.return_value = _mock_response({"results": []})
        result = await tmdb.get_upcoming_movies()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------

class TestValidateConfig:
    @pytest.mark.asyncio
    async def test_validate_missing_api_key(self, tmdb):
        result = await tmdb.validate_config({})
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_validate_empty_api_key(self, tmdb):
        result = await tmdb.validate_config({"api_key": "  "})
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("streamarr.metadata.tmdb.httpx.AsyncClient")
    async def test_validate_success(self, mock_client_cls, tmdb):
        mock_instance = AsyncMock()
        resp = MagicMock()
        resp.status_code = 200
        mock_instance.get.return_value = resp
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await tmdb.validate_config({"api_key": "valid-key"})
        assert result["valid"] is True

    @pytest.mark.asyncio
    @patch("streamarr.metadata.tmdb.httpx.AsyncClient")
    async def test_validate_unauthorized(self, mock_client_cls, tmdb):
        mock_instance = AsyncMock()
        resp = MagicMock()
        resp.status_code = 401
        mock_instance.get.return_value = resp
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await tmdb.validate_config({"api_key": "bad-key"})
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("streamarr.metadata.tmdb.httpx.AsyncClient")
    async def test_validate_other_status(self, mock_client_cls, tmdb):
        mock_instance = AsyncMock()
        resp = MagicMock()
        resp.status_code = 500
        mock_instance.get.return_value = resp
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await tmdb.validate_config({"api_key": "key"})
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("streamarr.metadata.tmdb.httpx.AsyncClient")
    async def test_validate_timeout(self, mock_client_cls, tmdb):
        mock_instance = AsyncMock()
        mock_instance.get.side_effect = httpx.TimeoutException("timeout")
        mock_client_cls.return_value = mock_instance
        result = await tmdb.validate_config({"api_key": "key"})
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("streamarr.metadata.tmdb.httpx.AsyncClient")
    async def test_validate_http_error(self, mock_client_cls, tmdb):
        mock_instance = AsyncMock()
        mock_instance.get.side_effect = httpx.HTTPError("connection error")
        mock_client_cls.return_value = mock_instance
        result = await tmdb.validate_config({"api_key": "key"})
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("streamarr.metadata.tmdb.httpx.AsyncClient")
    async def test_validate_unexpected_error(self, mock_client_cls, tmdb):
        mock_instance = AsyncMock()
        mock_instance.get.side_effect = RuntimeError("unexpected")
        mock_client_cls.return_value = mock_instance
        result = await tmdb.validate_config({"api_key": "key"})
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# close and async_setup
# ---------------------------------------------------------------------------

class TestCloseAndSetup:
    @pytest.mark.asyncio
    async def test_close_owns_client(self, mock_client):
        from streamarr.metadata.tmdb import TMDB

        tmdb = TMDB(api_key="key")  # _owns_client=True
        tmdb.client = mock_client
        tmdb._owns_client = True
        mock_client.aclose = AsyncMock()
        await tmdb.close()
        mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_does_not_own_client(self, tmdb, mock_client):
        mock_client.aclose = AsyncMock()
        await tmdb.close()
        mock_client.aclose.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_setup_success(self):
        from streamarr.metadata.tmdb import async_setup

        result = await async_setup({"api_key": "key"})
        assert result is True

    @pytest.mark.asyncio
    async def test_async_setup_missing_key(self):
        from streamarr.metadata.tmdb import async_setup

        result = await async_setup({})
        assert result is False

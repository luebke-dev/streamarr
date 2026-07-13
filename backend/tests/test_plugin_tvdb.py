"""Tests for the TVDB plugin with mocked HTTP calls."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def tvdb(mock_client):
    from streamarr.metadata.tvdb import TVDB

    return TVDB(
        api_key="test-api-key",
        pin="test-pin",
        language="en",
        client=mock_client,
    )


def _mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.headers = {}
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
    def test_get_name(self, tvdb):
        assert tvdb.get_name() == "TheTVDB"

    def test_init_without_client(self):
        from streamarr.metadata.tvdb import TVDB

        t = TVDB(api_key="key")
        assert t.client is not None

    def test_init_without_pin(self):
        from streamarr.metadata.tvdb import TVDB

        t = TVDB(api_key="key", client=AsyncMock())
        assert t.pin is None


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuthentication:
    @pytest.mark.asyncio
    async def test_authenticate_success(self, tvdb, mock_client):
        mock_client.post.return_value = _mock_response(
            {"status": "success", "data": {"token": "test-token"}}
        )
        result = await tvdb._authenticate()
        assert result is True
        assert tvdb.token == "test-token"
        assert tvdb.token_expires_at is not None

    @pytest.mark.asyncio
    async def test_authenticate_with_pin(self, tvdb, mock_client):
        mock_client.post.return_value = _mock_response(
            {"status": "success", "data": {"token": "token-with-pin"}}
        )
        result = await tvdb._authenticate()
        assert result is True
        # Verify pin was sent in payload
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json", {})
        assert payload.get("pin") == "test-pin"

    @pytest.mark.asyncio
    async def test_authenticate_failure_status(self, tvdb, mock_client):
        mock_client.post.return_value = _mock_response(
            {"status": "failure", "message": "Invalid API key"}
        )
        result = await tvdb._authenticate()
        assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_exception(self, tvdb, mock_client):
        mock_client.post.side_effect = Exception("Network error")
        result = await tvdb._authenticate()
        assert result is False

    @pytest.mark.asyncio
    async def test_ensure_authenticated_valid(self, tvdb):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        result = await tvdb._ensure_authenticated()
        assert result is True

    @pytest.mark.asyncio
    async def test_ensure_authenticated_expired(self, tvdb, mock_client):
        tvdb.token = "old"
        tvdb.token_expires_at = time.time() - 10
        mock_client.post.return_value = _mock_response(
            {"status": "success", "data": {"token": "new-token"}}
        )
        result = await tvdb._ensure_authenticated()
        assert result is True
        assert tvdb.token == "new-token"

    @pytest.mark.asyncio
    async def test_ensure_authenticated_no_token(self, tvdb, mock_client):
        mock_client.post.return_value = _mock_response(
            {"status": "success", "data": {"token": "new-token"}}
        )
        result = await tvdb._ensure_authenticated()
        assert result is True


# ---------------------------------------------------------------------------
# _request
# ---------------------------------------------------------------------------

class TestRequest:
    @pytest.mark.asyncio
    async def test_request_success(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": {"id": 1, "name": "Show"}}
        )
        result = await tvdb._request("series/1")
        assert result == {"id": 1, "name": "Show"}

    @pytest.mark.asyncio
    async def test_request_auth_fails(self, tvdb, mock_client):
        mock_client.post.side_effect = Exception("auth fail")
        result = await tvdb._request("series/1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_request_api_error(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "failure", "message": "Not found"}
        )
        result = await tvdb._request("series/999")
        assert result == {}

    @pytest.mark.asyncio
    async def test_request_http_error(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response({}, status_code=500)
        result = await tvdb._request("series/1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_request_generic_exception(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.side_effect = Exception("unexpected")
        result = await tvdb._request("series/1")
        assert result == {}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    @pytest.mark.asyncio
    async def test_search_returns_list(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": [{"id": 1, "name": "Show"}]}
        )
        result = await tvdb.search("show")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_returns_dict_with_series(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": {"series": [{"id": 1}]}}
        )
        result = await tvdb.search("show")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_returns_other(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": {"something": "else"}}
        )
        result = await tvdb.search("show")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_with_year(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": []}
        )
        result = await tvdb.search("show", year=2024)
        assert result == []

    @pytest.mark.asyncio
    async def test_search_series(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": [{"id": 1}]}
        )
        result = await tvdb.search_series("test", year=2024)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Get details
# ---------------------------------------------------------------------------

class TestDetails:
    @pytest.mark.asyncio
    async def test_get_details(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": {"id": 1, "name": "Show"}}
        )
        result = await tvdb.get_details(1)
        assert result == {"id": 1, "name": "Show"}

    @pytest.mark.asyncio
    async def test_get_details_extended(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": {"id": 1}}
        )
        result = await tvdb.get_details(1, extended=True)
        assert result == {"id": 1}

    @pytest.mark.asyncio
    async def test_get_details_not_dict(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": [{"id": 1}]}
        )
        result = await tvdb.get_details(1)
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_series_details(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": {"id": 1}}
        )
        result = await tvdb.get_series_details(1)
        assert result == {"id": 1}

    @pytest.mark.asyncio
    async def test_get_series_episodes(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": {"episodes": []}}
        )
        result = await tvdb.get_series_episodes(1, season=1)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_series_episodes_not_dict(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": []}
        )
        result = await tvdb.get_series_episodes(1)
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_episode_details(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": {"id": 100}}
        )
        result = await tvdb.get_episode_details(100)
        assert result == {"id": 100}

    @pytest.mark.asyncio
    async def test_get_episode_details_not_dict(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": "invalid"}
        )
        result = await tvdb.get_episode_details(100)
        assert result == {}


# ---------------------------------------------------------------------------
# Series by IMDb ID
# ---------------------------------------------------------------------------

class TestSeriesByImdb:
    @pytest.mark.asyncio
    async def test_get_series_by_imdb_id_found(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.side_effect = [
            _mock_response(
                {"status": "success", "data": [{"id": 42}]}
            ),
            _mock_response(
                {"status": "success", "data": {"id": 42, "name": "Found Show"}}
            ),
        ]
        result = await tvdb.get_series_by_imdb_id("tt0944947")
        assert result["name"] == "Found Show"

    @pytest.mark.asyncio
    async def test_get_series_by_imdb_id_not_found(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": []}
        )
        result = await tvdb.get_series_by_imdb_id("tt0000000")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_series_by_imdb_id_no_list(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": {"error": "not found"}}
        )
        result = await tvdb.get_series_by_imdb_id("tt0000000")
        assert result == {}


# ---------------------------------------------------------------------------
# Artwork
# ---------------------------------------------------------------------------

class TestArtwork:
    @pytest.mark.asyncio
    async def test_get_series_artwork(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": [{"url": "http://img.jpg"}]}
        )
        result = await tvdb.get_series_artwork(1)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_series_artwork_not_list(self, tvdb, mock_client):
        tvdb.token = "token"
        tvdb.token_expires_at = time.time() + 3600
        mock_client.get.return_value = _mock_response(
            {"status": "success", "data": {"artworks": []}}
        )
        result = await tvdb.get_series_artwork(1)
        assert result == []


# ---------------------------------------------------------------------------
# close and async_setup
# ---------------------------------------------------------------------------

class TestCloseAndSetup:
    @pytest.mark.asyncio
    async def test_close(self, tvdb, mock_client):
        mock_client.aclose = AsyncMock()
        await tvdb.close()
        mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_success(self):
        from streamarr.metadata.tvdb import async_setup

        result = await async_setup({"api_key": "key"})
        assert result is True

    @pytest.mark.asyncio
    async def test_async_setup_missing_key(self):
        from streamarr.metadata.tvdb import async_setup

        result = await async_setup({})
        assert result is False

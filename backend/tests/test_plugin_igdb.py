"""Tests for the IGDB plugin with mocked HTTP calls."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def igdb(mock_client):
    from pyrate.metadata.igdb import IGDB

    return IGDB(
        client_id="test-client-id",
        client_secret="test-client-secret",
        client=mock_client,
    )


def _auth_response():
    return {"access_token": "test-token", "expires_in": 3600}


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
    def test_get_name(self, igdb):
        assert igdb.get_name() == "IGDB"

    def test_get_config_schema(self, igdb):
        schema = igdb.get_config_schema()
        assert "client_id" in schema
        assert "client_secret" in schema


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuthentication:
    @pytest.mark.asyncio
    async def test_authenticate_success(self, igdb, mock_client):
        mock_client.post.return_value = _mock_response(_auth_response())
        result = await igdb._authenticate()
        assert result is True
        assert igdb.access_token == "test-token"

    @pytest.mark.asyncio
    async def test_authenticate_failure(self, igdb, mock_client):
        mock_client.post.side_effect = Exception("Network error")
        result = await igdb._authenticate()
        assert result is False

    @pytest.mark.asyncio
    async def test_ensure_authenticated_valid(self, igdb):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        result = await igdb._ensure_authenticated()
        assert result is True

    @pytest.mark.asyncio
    async def test_ensure_authenticated_expired(self, igdb, mock_client):
        igdb.access_token = "old"
        igdb.token_expires_at = time.time() - 10
        mock_client.post.return_value = _mock_response(_auth_response())
        result = await igdb._ensure_authenticated()
        assert result is True


# ---------------------------------------------------------------------------
# _request
# ---------------------------------------------------------------------------

class TestRequest:
    @pytest.mark.asyncio
    async def test_request_success(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response([{"id": 1, "name": "Game"}])
        result = await igdb._request("games", "fields *;")
        assert result == [{"id": 1, "name": "Game"}]

    @pytest.mark.asyncio
    async def test_request_auth_fails(self, igdb, mock_client):
        mock_client.post.side_effect = Exception("auth fail")
        result = await igdb._request("games", "fields *;")
        assert result == {}

    @pytest.mark.asyncio
    async def test_request_http_error(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response({}, status_code=500)
        result = await igdb._request("games", "fields *;")
        assert result == []

    @pytest.mark.asyncio
    async def test_request_generic_exception(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        # First post succeeds (auth), second fails
        mock_client.post.side_effect = [
            _mock_response(_auth_response()),
            Exception("unexpected"),
        ]
        igdb.access_token = None  # force re-auth
        result = await igdb._request("games", "fields *;")
        assert result == []


# ---------------------------------------------------------------------------
# Search and game details
# ---------------------------------------------------------------------------

class TestSearch:
    @pytest.mark.asyncio
    async def test_search_games(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response(
            [{"id": 1, "name": "Game 1"}]
        )
        result = await igdb.search_games("game")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_games_not_list(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response({"error": "bad"})
        result = await igdb.search_games("game")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_dispatches(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response(
            [{"id": 1}]
        )
        result = await igdb.search("test", limit=5)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_details(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response(
            [{"id": 42, "name": "Detailed Game"}]
        )
        result = await igdb.get_details(42)
        assert result["name"] == "Detailed Game"


class TestGameDetails:
    @pytest.mark.asyncio
    async def test_get_game_details(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response(
            [{"id": 1, "name": "Game"}]
        )
        result = await igdb.get_game_details(1)
        assert result["name"] == "Game"

    @pytest.mark.asyncio
    async def test_get_game_details_empty(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response([])
        result = await igdb.get_game_details(1)
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_game_details_not_list(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response({"error": "bad"})
        result = await igdb.get_game_details(1)
        assert result == {}


# ---------------------------------------------------------------------------
# Additional game methods
# ---------------------------------------------------------------------------

class TestGameMethods:
    @pytest.mark.asyncio
    async def test_get_trending_games(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response([{"id": 1}])
        result = await igdb.get_trending_games()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_trending_games_not_list(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response({})
        result = await igdb.get_trending_games()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_popular_games(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response([{"id": 1}])
        result = await igdb.get_popular_games()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_popular_games_not_list(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response({})
        result = await igdb.get_popular_games()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_upcoming_games(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response([{"id": 1}])
        result = await igdb.get_upcoming_games()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_upcoming_games_not_list(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response({})
        result = await igdb.get_upcoming_games()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recently_released_games(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response([{"id": 1}])
        result = await igdb.get_recently_released_games()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_recently_released_games_not_list(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response({})
        result = await igdb.get_recently_released_games()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_games_by_genre(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response([{"id": 1}])
        result = await igdb.get_games_by_genre("RPG")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_games_by_genre_not_list(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response({})
        result = await igdb.get_games_by_genre("RPG")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_games_by_platform(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response([{"id": 1}])
        result = await igdb.get_games_by_platform("PC")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_games_by_platform_not_list(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response({})
        result = await igdb.get_games_by_platform("PC")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_game_localizations(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response([{"name": "Spiel"}])
        result = await igdb.get_game_localizations(1)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_game_localizations_not_list(self, igdb, mock_client):
        igdb.access_token = "token"
        igdb.token_expires_at = time.time() + 3600
        mock_client.post.return_value = _mock_response({})
        result = await igdb.get_game_localizations(1)
        assert result == []


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------

class TestValidateConfig:
    @pytest.mark.asyncio
    async def test_validate_missing_fields(self, igdb):
        result = await igdb.validate_config({})
        assert result["valid"] is False
        assert len(result["errors"]) == 2

    @pytest.mark.asyncio
    @patch("pyrate.metadata.igdb.httpx.AsyncClient")
    async def test_validate_success(self, mock_client_cls, igdb):
        mock_instance = AsyncMock()
        resp = MagicMock()
        resp.status_code = 200
        mock_instance.post.return_value = resp
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await igdb.validate_config(
            {"client_id": "id", "client_secret": "secret"}
        )
        assert result["valid"] is True

    @pytest.mark.asyncio
    @patch("pyrate.metadata.igdb.httpx.AsyncClient")
    async def test_validate_bad_credentials_400(self, mock_client_cls, igdb):
        mock_instance = AsyncMock()
        resp = MagicMock()
        resp.status_code = 400
        mock_instance.post.return_value = resp
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await igdb.validate_config(
            {"client_id": "id", "client_secret": "bad"}
        )
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("pyrate.metadata.igdb.httpx.AsyncClient")
    async def test_validate_bad_credentials_401(self, mock_client_cls, igdb):
        mock_instance = AsyncMock()
        resp = MagicMock()
        resp.status_code = 401
        mock_instance.post.return_value = resp
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await igdb.validate_config(
            {"client_id": "id", "client_secret": "bad"}
        )
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("pyrate.metadata.igdb.httpx.AsyncClient")
    async def test_validate_other_status(self, mock_client_cls, igdb):
        mock_instance = AsyncMock()
        resp = MagicMock()
        resp.status_code = 503
        mock_instance.post.return_value = resp
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance
        result = await igdb.validate_config(
            {"client_id": "id", "client_secret": "secret"}
        )
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("pyrate.metadata.igdb.httpx.AsyncClient")
    async def test_validate_timeout(self, mock_client_cls, igdb):
        mock_instance = AsyncMock()
        mock_instance.post.side_effect = httpx.TimeoutException("timeout")
        mock_client_cls.return_value = mock_instance
        result = await igdb.validate_config(
            {"client_id": "id", "client_secret": "secret"}
        )
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("pyrate.metadata.igdb.httpx.AsyncClient")
    async def test_validate_http_error(self, mock_client_cls, igdb):
        mock_instance = AsyncMock()
        mock_instance.post.side_effect = httpx.HTTPError("connection error")
        mock_client_cls.return_value = mock_instance
        result = await igdb.validate_config(
            {"client_id": "id", "client_secret": "secret"}
        )
        assert result["valid"] is False

    @pytest.mark.asyncio
    @patch("pyrate.metadata.igdb.httpx.AsyncClient")
    async def test_validate_unexpected_error(self, mock_client_cls, igdb):
        mock_instance = AsyncMock()
        mock_instance.post.side_effect = RuntimeError("unexpected")
        mock_client_cls.return_value = mock_instance
        result = await igdb.validate_config(
            {"client_id": "id", "client_secret": "secret"}
        )
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# close and async_setup
# ---------------------------------------------------------------------------

class TestCloseAndSetup:
    @pytest.mark.asyncio
    async def test_close(self, igdb, mock_client):
        mock_client.aclose = AsyncMock()
        await igdb.close()
        mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_success(self):
        from pyrate.metadata.igdb import async_setup

        result = await async_setup({"client_id": "id", "client_secret": "secret"})
        assert result is True

    @pytest.mark.asyncio
    async def test_async_setup_missing_field(self):
        from pyrate.metadata.igdb import async_setup

        result = await async_setup({"client_id": "id"})
        assert result is False

    @pytest.mark.asyncio
    async def test_async_setup_empty(self):
        from pyrate.metadata.igdb import async_setup

        result = await async_setup({})
        assert result is False

"""Tests for Lightrays service (JWT token generation + HTTP calls)."""

# ruff: noqa: I001

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Patch environment before importing the module under test
os.environ.setdefault("LIGHTRAYS_JWT_SECRET", "test-secret-key-for-testing")
os.environ.setdefault("LIGHTRAYS_URL", "http://lightrays-test:8080")

from pyrate.services.lightrays import (
    _browser_websocket_url,
    create_lightrays_token,
    get_stats,
    launch_session,
    stop_session,
)


# ---------------------------------------------------------------------------
# JWT token generation
# ---------------------------------------------------------------------------

class TestCreateLightraysToken:
    def test_creates_token_string(self):
        token = create_lightrays_token("user-123")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_different_per_call(self):
        t1 = create_lightrays_token("user-1")
        t2 = create_lightrays_token("user-2")
        assert t1 != t2

    def test_custom_expiry(self):
        token = create_lightrays_token("user-1", expires_minutes=60)
        assert len(token) > 0

    def test_scope_claim(self):
        token = create_lightrays_token("user-1", scope="lightrays:admin")
        assert len(token) > 0

    @patch("pyrate.services.lightrays.LIGHTRAYS_JWT_SECRET", "")
    def test_empty_secret_returns_empty(self):
        token = create_lightrays_token("user-1")
        assert token == ""


# ---------------------------------------------------------------------------
# HTTP calls (mocked)
# ---------------------------------------------------------------------------

class TestLaunchSession:
    @pytest.mark.asyncio
    async def test_launch_session_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"session_id": "sess_1", "ws_url": "ws://..."}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("pyrate.services.lightrays.httpx.AsyncClient", return_value=mock_client):
            result = await launch_session(title="Test Session")

        assert result["session_id"] == "sess_1"
        mock_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_launch_session_custom_params(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"session_id": "sess_2"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("pyrate.services.lightrays.httpx.AsyncClient", return_value=mock_client):
            result = await launch_session(
                title="Custom",
                width=2560,
                height=1440,
                fps=120,
                bitrate_kbps=20000,
                runtime_profile="gow-steam",
                docker_image="ghcr.io/example/game-runtime:latest",
                keyboard_layout="de",
                user_id="user-123",
            )

        assert result["session_id"] == "sess_2"
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["width"] == 2560
        assert payload["runtime_profile"] == "gow-steam"
        assert payload["docker_image"] == "ghcr.io/example/game-runtime:latest"
        assert payload["keyboard_layout"] == "de"
        assert "image" not in payload
        assert "base_create_json" not in payload
        assert "container_name" not in payload


class TestBrowserWebSocketUrl:
    @patch("pyrate.services.lightrays.LIGHTRAYS_PUBLIC_URL", "")
    def test_keeps_relative_url_without_public_url(self):
        assert _browser_websocket_url("/api/lightrays-ws/sess_1") == (
            "/api/lightrays-ws/sess_1"
        )

    @patch("pyrate.services.lightrays.LIGHTRAYS_PUBLIC_URL", "https://pyrate.example")
    def test_resolves_relative_url_with_public_url(self):
        assert _browser_websocket_url("/api/lightrays-ws/sess_1") == (
            "wss://pyrate.example/api/lightrays-ws/sess_1"
        )


class TestStopSession:
    @pytest.mark.asyncio
    async def test_stop_session_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "stopped"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("pyrate.services.lightrays.httpx.AsyncClient", return_value=mock_client):
            result = await stop_session("sess_1", user_id="user-1")

        assert result["status"] == "stopped"


class TestGetStats:
    @pytest.mark.asyncio
    async def test_get_stats_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"cpu": 45.0, "memory_mb": 512}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("pyrate.services.lightrays.httpx.AsyncClient", return_value=mock_client):
            result = await get_stats("sess_1", user_id="user-1")

        assert result["cpu"] == 45.0
        assert result["memory_mb"] == 512


class TestSessionTimeoutAlignment:
    """Pyrate's Redis TTL must align with Lightrays' idle-session timeout.

    The Lightrays-side reaper drops sessions after
    ``LIGHTRAYS_SESSION_TIMEOUT_SECS``; Pyrate's bookkeeping should age
    out on the same schedule plus a 60s grace so we don't prune a
    session that Lightrays is still finalising.
    """

    def test_defaults_to_one_hour_plus_grace(self):
        from pyrate.services import lightrays as lr_module

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LIGHTRAYS_SESSION_TIMEOUT_SECS", None)
            assert lr_module._load_session_max_seconds() == 3600 + 60

    def test_picks_up_configured_value(self):
        from pyrate.services import lightrays as lr_module

        with patch.dict(os.environ, {"LIGHTRAYS_SESSION_TIMEOUT_SECS": "1800"}):
            assert lr_module._load_session_max_seconds() == 1800 + 60

    def test_falls_back_on_invalid_value(self):
        from pyrate.services import lightrays as lr_module

        with patch.dict(os.environ, {"LIGHTRAYS_SESSION_TIMEOUT_SECS": "not-a-number"}):
            assert lr_module._load_session_max_seconds() == 3600 + 60

    def test_negative_values_clamped_to_zero(self):
        """A non-positive timeout disables the Lightrays reaper; Pyrate
        should still keep at least the grace window so reads don't prune
        actively-live entries."""
        from pyrate.services import lightrays as lr_module

        with patch.dict(os.environ, {"LIGHTRAYS_SESSION_TIMEOUT_SECS": "-1"}):
            assert lr_module._load_session_max_seconds() == 0 + 60

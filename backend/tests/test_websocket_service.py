"""Tests for WebSocketManager, WebSocketConnection, and device status helpers."""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
import pytest_asyncio

from pyrate.services.websocket import (
    WebSocketConnection,
    WebSocketManager,
    set_device_status_callback,
    get_device_status_callback,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws() -> AsyncMock:
    """Create a mock FastAPI WebSocket."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# WebSocketConnection
# ---------------------------------------------------------------------------

class TestWebSocketConnection:
    @pytest.mark.asyncio
    async def test_send_event(self):
        ws = _make_ws()
        conn = WebSocketConnection(ws, user_id="u1", device_id="d1")

        await conn.send_event("test", {"key": "value"})

        ws.send_json.assert_awaited_once()
        payload = ws.send_json.call_args[0][0]
        assert payload["event"] == "test"
        assert payload["data"] == {"key": "value"}
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_send_event_failure_raises(self):
        ws = _make_ws()
        ws.send_json.side_effect = RuntimeError("closed")
        conn = WebSocketConnection(ws, user_id="u1")

        with pytest.raises(RuntimeError):
            await conn.send_event("fail", {})

    def test_attributes(self):
        ws = _make_ws()
        conn = WebSocketConnection(ws, user_id="u1", device_id="d1")
        assert conn.user_id == "u1"
        assert conn.device_id == "d1"
        assert conn.subscriptions == set()


# ---------------------------------------------------------------------------
# Device status callback helpers
# ---------------------------------------------------------------------------

class TestDeviceStatusCallback:
    def test_set_and_get_callback(self):
        cb = MagicMock()
        set_device_status_callback(cb)
        assert get_device_status_callback() is cb
        # Clean up
        set_device_status_callback(None)

    def test_default_none(self):
        set_device_status_callback(None)
        assert get_device_status_callback() is None


# ---------------------------------------------------------------------------
# WebSocketManager – connect / disconnect
# ---------------------------------------------------------------------------

class TestWebSocketManagerConnect:
    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1", device_id="d1")

            assert mgr.get_connection_count() == 1
            assert conn.user_id == "u1"
            ws.accept.assert_awaited_once()

            # WebSocket should have received "connected" message
            ws.send_json.assert_awaited()

            await mgr.disconnect(conn)
            assert mgr.get_connection_count() == 0


# ---------------------------------------------------------------------------
# WebSocketManager – subscriptions
# ---------------------------------------------------------------------------

class TestSubscriptions:
    @pytest.mark.asyncio
    async def test_subscribe_and_unsubscribe(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.subscribe(conn, "episode", "ep-123")
            assert "episode:ep-123" in conn.subscriptions
            assert mgr.get_subscription_count("episode", "ep-123") == 1

            await mgr.unsubscribe(conn, "episode", "ep-123")
            assert "episode:ep-123" not in conn.subscriptions
            assert mgr.get_subscription_count("episode", "ep-123") == 0

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_subscribe_idempotent(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.subscribe(conn, "episode", "ep-1")
            await mgr.subscribe(conn, "episode", "ep-1")
            assert mgr.get_subscription_count("episode", "ep-1") == 1

            await mgr.disconnect(conn)


# ---------------------------------------------------------------------------
# WebSocketManager – handle_message
# ---------------------------------------------------------------------------

class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_handle_subscribe_message(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.handle_message(
                conn,
                {"action": "subscribe", "resource_type": "movie", "resource_id": "m1"},
            )
            assert "movie:m1" in conn.subscriptions

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_handle_ping(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.handle_message(conn, {"action": "ping"})

            # Should have sent a pong
            calls = ws.send_json.call_args_list
            pong_found = any(c[0][0].get("event") == "pong" for c in calls)
            assert pong_found

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_handle_unknown_action(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.handle_message(conn, {"action": "bogus"})

            calls = ws.send_json.call_args_list
            error_found = any(c[0][0].get("event") == "error" for c in calls)
            assert error_found

            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_handle_subscribe_missing_fields(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")

            await mgr.handle_message(conn, {"action": "subscribe"})

            calls = ws.send_json.call_args_list
            error_found = any(c[0][0].get("event") == "error" for c in calls)
            assert error_found

            await mgr.disconnect(conn)


# ---------------------------------------------------------------------------
# WebSocketManager – broadcast and utility
# ---------------------------------------------------------------------------

class TestBroadcastAndUtility:
    @pytest.mark.asyncio
    async def test_broadcast_to_resource(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_svc.publish = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            await mgr.broadcast_to_resource("episode", "ep-1", "progress", {"pct": 50})

            mock_svc.publish.assert_awaited_once_with(
                channel="episode:ep-1",
                event="progress",
                data={"pct": 50},
            )

    @pytest.mark.asyncio
    async def test_connected_device_ids_for_user(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws1 = _make_ws()
            ws2 = _make_ws()

            conn1 = await mgr.connect(ws1, user_id="u1", device_id="d1")
            conn2 = await mgr.connect(ws2, user_id="u1", device_id="d2")

            device_ids = mgr.get_connected_device_ids_for_user("u1")
            assert device_ids == {"d1", "d2"}

            all_ids = mgr.get_all_connected_device_ids()
            assert all_ids == {"d1", "d2"}

            await mgr.disconnect(conn1)
            await mgr.disconnect(conn2)


# ---------------------------------------------------------------------------
# Cross-replica command routing and presence (multi-process scalability)
# ---------------------------------------------------------------------------

class TestCrossReplicaRouting:
    """The socket may live on another backend replica. Presence/routing must
    consult Redis instead of the process-local ``_connections`` map."""

    def _manager_with_fakeredis(self, fake):
        mock_svc = MagicMock()
        mock_svc.subscribe = AsyncMock()
        mock_svc.unsubscribe = AsyncMock()
        mock_svc.publish = AsyncMock()
        mock_svc.publish_device_command = AsyncMock()
        mock_svc.publish_device_presence = AsyncMock()
        mock_svc._get_redis = AsyncMock(return_value=fake)
        with patch(
            "pyrate.services.websocket.get_redis_event_service",
            return_value=mock_svc,
        ):
            mgr = WebSocketManager()
        return mgr, mock_svc

    @pytest.mark.asyncio
    async def test_command_routes_to_other_replica(self):
        """Device connected on another replica (only in Redis) → publish, no 409."""
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await fake.sadd("ws:connected_devices", "remote-dev")
        await fake.sadd("ws:connected_devices:u1", "remote-dev")

        mgr, mock_svc = self._manager_with_fakeredis(fake)

        result = await mgr.send_remote_control_command(
            user_id="u1",
            target_device_id="remote-dev",
            command="pause",
        )

        assert result["status"] == "sent"
        mock_svc.publish_device_command.assert_awaited_once()
        args = mock_svc.publish_device_command.await_args
        assert args.args[0] == "remote-dev"
        assert args.args[1]["command"] == "pause"

    @pytest.mark.asyncio
    async def test_command_to_unknown_device_raises(self):
        """Device connected nowhere (not in Redis) → RemoteControlError."""
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        mgr, mock_svc = self._manager_with_fakeredis(fake)

        from pyrate.services.websocket import RemoteControlError

        with pytest.raises(RemoteControlError, match="not connected"):
            await mgr.send_remote_control_command(
                user_id="u1",
                target_device_id="ghost-dev",
                command="pause",
            )
        mock_svc.publish_device_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_local_command_takes_fast_path(self):
        """A locally-held socket is delivered directly, never via Redis."""
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        mgr, mock_svc = self._manager_with_fakeredis(fake)

        ws = _make_ws()
        conn = await mgr.connect(ws, user_id="u1", device_id="local-dev")

        result = await mgr.send_remote_control_command(
            user_id="u1",
            target_device_id="local-dev",
            command="pause",
        )

        assert result["status"] == "sent"
        mock_svc.publish_device_command.assert_not_awaited()
        assert any(
            c[0][0].get("event") == "remote_control"
            for c in ws.send_json.call_args_list
        )
        await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_presence_mirror_includes_remote_devices(self):
        """A presence event from another replica surfaces in the accessors."""
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        mgr, _ = self._manager_with_fakeredis(fake)

        await mgr._on_presence_event(
            {
                "event": "device_online",
                "data": {"device_id": "remote-dev", "user_id": "u1"},
            }
        )

        assert "remote-dev" in mgr.get_connected_device_ids_for_user("u1")
        assert "remote-dev" in mgr.get_all_connected_device_ids()
        assert "u1" in mgr.get_online_user_ids()
        sessions = mgr.get_active_device_sessions("u1")
        assert any(s["device_id"] == "remote-dev" for s in sessions)

        # Going offline clears it from the mirror.
        await mgr._on_presence_event(
            {
                "event": "device_offline",
                "data": {"device_id": "remote-dev", "user_id": "u1"},
            }
        )
        assert "remote-dev" not in mgr.get_all_connected_device_ids()


# ---------------------------------------------------------------------------
# Device status handling
# ---------------------------------------------------------------------------

class TestDeviceStatusHandling:
    @pytest.mark.asyncio
    async def test_handle_device_status(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1", device_id="d1")

            cb = AsyncMock()
            set_device_status_callback(cb)

            await mgr.handle_message(
                conn,
                {
                    "action": "device_status",
                    "device_id": "d1",
                    "is_playing": True,
                    "position": 42,
                },
            )

            cb.assert_awaited_once()
            args = cb.call_args[0]
            assert args[0] == "u1"  # user_id
            assert args[1] == "d1"  # device_id

            # Clean up
            set_device_status_callback(None)
            await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_handle_device_status_missing_id(self):
        with patch("pyrate.services.websocket.get_redis_event_service") as mock_redis:
            mock_svc = MagicMock()
            mock_svc.subscribe = AsyncMock()
            mock_svc.unsubscribe = AsyncMock()
            mock_redis.return_value = mock_svc

            mgr = WebSocketManager()
            ws = _make_ws()
            conn = await mgr.connect(ws, user_id="u1")
            # No device_id on connection or message
            conn.device_id = None

            await mgr.handle_message(conn, {"action": "device_status"})

            calls = ws.send_json.call_args_list
            error_found = any(c[0][0].get("event") == "error" for c in calls)
            assert error_found

            await mgr.disconnect(conn)

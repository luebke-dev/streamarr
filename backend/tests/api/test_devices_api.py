"""Tests for devices API endpoints (/api/devices/*)."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models import ActivityLog, Device, User
from streamarr.models.media import AvailabilityStatus, MediaFile, MediaItem, MediaType

from .conftest import auth_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _create_device(db_session: AsyncSession, user: User, device_id: str = "dev-001") -> Device:
    device = Device(
        guid=uuid.uuid4(),
        user_id=user.guid,
        device_id=device_id,
        name=f"Test Device {device_id}",
        browser="Chrome",
        platform="Linux",
        is_active=True,
        is_trusted=False,
    )
    db_session.add(device)
    await db_session.commit()
    await db_session.refresh(device)
    return device


async def _create_media_item(db_session: AsyncSession, title: str = "Offline Movie"):
    item = MediaItem(
        guid=uuid.uuid4(),
        title=title,
        media_type=MediaType.MOVIES,
        availability_status=AvailabilityStatus.AVAILABLE,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


async def _create_media_file(
    db_session: AsyncSession,
    media_item: MediaItem,
    file_name: str = "Offline.Movie.mkv",
) -> MediaFile:
    media_file = MediaFile(
        guid=uuid.uuid4(),
        media_item_guid=media_item.guid,
        file_path=f"/library/{file_name}",
        file_name=file_name,
        file_size=123456,
        format="mkv",
    )
    db_session.add(media_file)
    await db_session.commit()
    await db_session.refresh(media_file)
    return media_file


class _FakeRemoteControlManager:
    def __init__(
        self,
        *,
        fail: Exception | None = None,
        active_sessions: list[dict] | None = None,
    ):
        self.fail = fail
        self.calls = []
        self.active_sessions = active_sessions or []

    async def send_remote_control_command(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise self.fail
        return {
            "target_device_id": kwargs["target_device_id"],
            "command": kwargs["command"],
            "status": "sent",
            "timestamp": "2026-05-11T00:00:00+00:00",
        }

    def get_active_device_sessions(self, user_id: str | None = None):
        if user_id:
            return [
                session
                for session in self.active_sessions
                if session["user_id"] == user_id
            ]
        return self.active_sessions

    def get_connected_device_ids_for_user(self, user_id: str):
        return {
            session["device_id"]
            for session in self.active_sessions
            if session["user_id"] == user_id
        }


# ---------------------------------------------------------------------------
# GET /api/devices/me
# ---------------------------------------------------------------------------
class TestMyDevices:
    async def test_list_my_devices_empty(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/devices/me", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_my_devices(self, client: AsyncClient, db_session, test_user, user_headers):
        await _create_device(db_session, test_user, "dev-001")
        await _create_device(db_session, test_user, "dev-002")

        resp = await client.get("/api/devices/me", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    async def test_list_my_devices_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/devices/me")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/devices/me/{device_guid}
# ---------------------------------------------------------------------------
class TestGetMyDevice:
    async def test_get_my_device(self, client: AsyncClient, db_session, test_user, user_headers):
        device = await _create_device(db_session, test_user)

        resp = await client.get(f"/api/devices/me/{device.guid}", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["device_id"] == "dev-001"

    async def test_get_other_users_device(self, client: AsyncClient, db_session, test_superuser, user_headers):
        device = await _create_device(db_session, test_superuser)

        resp = await client.get(f"/api/devices/me/{device.guid}", headers=user_headers)
        assert resp.status_code == 404

    async def test_get_device_not_found(self, client: AsyncClient, user_headers):
        fake = uuid.uuid4()
        resp = await client.get(f"/api/devices/me/{fake}", headers=user_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/devices/me/{device_guid}
# ---------------------------------------------------------------------------
class TestUpdateMyDevice:
    async def test_update_my_device_name(self, client: AsyncClient, db_session, test_user, user_headers):
        device = await _create_device(db_session, test_user)

        resp = await client.put(
            f"/api/devices/me/{device.guid}",
            json={"name": "My Living Room"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "My Living Room"

    async def test_update_other_users_device(self, client: AsyncClient, db_session, test_superuser, user_headers):
        device = await _create_device(db_session, test_superuser)

        resp = await client.put(
            f"/api/devices/me/{device.guid}",
            json={"name": "Hacked"},
            headers=user_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/devices/me/{device_guid}
# ---------------------------------------------------------------------------
class TestDeleteMyDevice:
    async def test_delete_my_device(self, client: AsyncClient, db_session, test_user, user_headers):
        device = await _create_device(db_session, test_user)

        resp = await client.delete(f"/api/devices/me/{device.guid}", headers=user_headers)
        assert resp.status_code == 204

    async def test_delete_other_users_device(self, client: AsyncClient, db_session, test_superuser, user_headers):
        device = await _create_device(db_session, test_superuser)

        resp = await client.delete(f"/api/devices/me/{device.guid}", headers=user_headers)
        assert resp.status_code == 404


class TestDeviceCapabilities:
    async def test_get_default_capabilities(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        device = await _create_device(db_session, test_user, "cap-device")

        resp = await client.get(
            f"/api/devices/me/{device.guid}/capabilities", headers=user_headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == "cap-device"
        assert data["supported_commands"] == []
        assert data["supports_media_control"] is True

    async def test_update_capabilities(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        device = await _create_device(db_session, test_user, "cap-device")

        resp = await client.put(
            f"/api/devices/me/{device.guid}/capabilities",
            headers=user_headers,
            json={
                "supported_commands": ["play", "pause", "message"],
                "supports_display_message": True,
                "supports_play_queue": True,
                "app_name": "streamarr-web",
                "app_version": "1.0.0",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["supported_commands"] == ["play", "pause", "message"]
        assert data["supports_display_message"] is True
        assert data["supports_play_queue"] is True

        await db_session.refresh(device)
        assert device.device_info["capabilities"]["app_name"] == "streamarr-web"

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "session.capabilities")
        )
        log_entry = log_result.scalar_one()
        assert log_entry.entity_guid == device.guid
        assert "streamarr-web" in log_entry.extra_data

    async def test_update_other_users_capabilities_hidden(
        self, client: AsyncClient, db_session, test_superuser, user_headers
    ):
        device = await _create_device(db_session, test_superuser, "admin-device")

        resp = await client.put(
            f"/api/devices/me/{device.guid}/capabilities",
            headers=user_headers,
            json={"supports_play_queue": True},
        )

        assert resp.status_code == 404


class TestDeviceCommands:
    async def test_send_command_to_owned_device(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        device = await _create_device(db_session, test_user, "living-room")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            f"/api/devices/{device.guid}/commands",
            json={"command": "pause", "payload": {}},
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["target_device_id"] == "living-room"
        assert data["command"] == "pause"
        assert data["status"] == "sent"
        assert manager.calls[0]["user_id"] == str(test_user.guid)
        assert manager.calls[0]["target_device_id"] == "living-room"

    async def test_send_command_by_device_id(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_user, "living-room")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            "/api/devices/by-id/living-room/commands",
            json={"command": "pause", "payload": {}},
            headers=user_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["target_device_id"] == "living-room"
        assert manager.calls[0]["target_device_id"] == "living-room"

    async def test_send_command_by_device_id_hides_other_users_device(
        self, client: AsyncClient, db_session, test_superuser, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_superuser, "admin-device")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            "/api/devices/by-id/admin-device/commands",
            json={"command": "pause", "payload": {}},
            headers=user_headers,
        )

        assert resp.status_code == 404
        assert manager.calls == []

    async def test_send_session_message_by_device_id(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_user, "living-room")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            "/api/devices/by-id/living-room/message",
            json={
                "title": "Heads up",
                "text": "Playback will pause soon",
                "timeout_seconds": 15,
                "from_device_id": "phone",
            },
            headers=user_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["command"] == "message"
        assert manager.calls[0]["target_device_id"] == "living-room"
        assert manager.calls[0]["command"] == "message"
        assert manager.calls[0]["payload"] == {
            "title": "Heads up",
            "text": "Playback will pause soon",
            "timeout_seconds": 15,
        }
        assert manager.calls[0]["from_device_id"] == "phone"

    async def test_send_session_message_by_device_id_hides_other_users_device(
        self, client: AsyncClient, db_session, test_superuser, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_superuser, "admin-device")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            "/api/devices/by-id/admin-device/message",
            json={"text": "Hello"},
            headers=user_headers,
        )

        assert resp.status_code == 404
        assert manager.calls == []

    async def test_send_session_play_media_by_device_id(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_user, "living-room")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)
        media_guid = uuid.uuid4()
        file_guid = uuid.uuid4()

        resp = await client.post(
            "/api/devices/by-id/living-room/play-media",
            json={
                "media_guid": str(media_guid),
                "media_type": "movie",
                "media_title": "Session Movie",
                "file_guid": str(file_guid),
                "from_device_id": "phone",
            },
            headers=user_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["command"] == "play_media"
        assert manager.calls[0]["target_device_id"] == "living-room"
        assert manager.calls[0]["command"] == "play_media"
        assert manager.calls[0]["payload"] == {
            "media_guid": str(media_guid),
            "media_type": "movie",
            "media_title": "Session Movie",
            "file_guid": str(file_guid),
        }
        assert manager.calls[0]["from_device_id"] == "phone"

    async def test_send_session_play_media_by_device_id_hides_other_users_device(
        self, client: AsyncClient, db_session, test_superuser, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_superuser, "admin-device")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            "/api/devices/by-id/admin-device/play-media",
            json={"media_guid": str(uuid.uuid4())},
            headers=user_headers,
        )

        assert resp.status_code == 404
        assert manager.calls == []

    async def test_send_session_play_queue_by_device_id(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_user, "living-room")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)
        first_guid = uuid.uuid4()
        second_guid = uuid.uuid4()

        resp = await client.post(
            "/api/devices/by-id/living-room/play-queue",
            json={
                "items": [
                    {
                        "media_guid": str(first_guid),
                        "media_type": "movie",
                        "media_title": "First",
                    },
                    {
                        "media_guid": str(second_guid),
                        "media_type": "movie",
                        "media_title": "Second",
                    },
                ],
                "start_index": 1,
                "start_position_seconds": 42,
                "from_device_id": "phone",
            },
            headers=user_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["command"] == "play_queue"
        assert manager.calls[0]["target_device_id"] == "living-room"
        assert manager.calls[0]["command"] == "play_queue"
        assert manager.calls[0]["payload"]["start_index"] == 1
        assert manager.calls[0]["payload"]["start_position_seconds"] == 42
        assert manager.calls[0]["payload"]["items"][1]["media_guid"] == str(second_guid)
        assert manager.calls[0]["from_device_id"] == "phone"

    async def test_send_session_play_queue_rejects_out_of_range_start(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_user, "living-room")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            "/api/devices/by-id/living-room/play-queue",
            json={
                "items": [{"media_guid": str(uuid.uuid4())}],
                "start_index": 1,
            },
            headers=user_headers,
        )

        assert resp.status_code == 422
        assert manager.calls == []

    async def test_send_session_play_command_by_device_id(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_user, "living-room")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)
        first_guid = uuid.uuid4()
        second_guid = uuid.uuid4()

        resp = await client.post(
            "/api/devices/by-id/living-room/playing",
            json={
                "item_ids": [str(first_guid), str(second_guid)],
                "play_command": "play_next",
                "start_index": 1,
                "start_position_ticks": 420_000_000,
                "media_source_id": "source-1",
                "audio_stream_index": 2,
                "subtitle_stream_index": 3,
                "from_device_id": "phone",
            },
            headers=user_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["command"] == "play_command"
        assert manager.calls[0]["target_device_id"] == "living-room"
        assert manager.calls[0]["command"] == "play_command"
        assert manager.calls[0]["payload"] == {
            "item_ids": [str(first_guid), str(second_guid)],
            "play_command": "play_next",
            "start_position_seconds": 42,
            "start_position_ticks": 420_000_000,
            "media_source_id": "source-1",
            "audio_stream_index": 2,
            "subtitle_stream_index": 3,
            "start_index": 1,
        }
        assert manager.calls[0]["from_device_id"] == "phone"

    async def test_send_session_play_command_rejects_out_of_range_start(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_user, "living-room")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            "/api/devices/by-id/living-room/playing",
            json={
                "item_ids": [str(uuid.uuid4())],
                "play_command": "play_now",
                "start_index": 1,
            },
            headers=user_headers,
        )

        assert resp.status_code == 422
        assert manager.calls == []

    async def test_send_command_to_other_users_device_is_hidden(
        self, client: AsyncClient, db_session, test_superuser, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        device = await _create_device(db_session, test_superuser, "admin-device")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            f"/api/devices/{device.guid}/commands",
            json={"command": "pause", "payload": {}},
            headers=user_headers,
        )

        assert resp.status_code == 404
        assert manager.calls == []

    async def test_admin_can_send_command_to_any_device(
        self, client: AsyncClient, db_session, test_user, admin_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        device = await _create_device(db_session, test_user, "user-device")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            f"/api/devices/{device.guid}/commands",
            json={"command": "seek", "payload": {"position": 42}},
            headers=admin_headers,
        )

        assert resp.status_code == 200
        assert manager.calls[0]["user_id"] == str(test_user.guid)
        assert manager.calls[0]["payload"] == {"position": 42}

    async def test_send_command_to_disconnected_device_logs_failure(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api
        from streamarr.services.websocket import RemoteControlError

        device = await _create_device(db_session, test_user, "offline-device")
        manager = _FakeRemoteControlManager(
            fail=RemoteControlError("Target device not connected")
        )
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            f"/api/devices/{device.guid}/commands",
            json={"command": "pause", "payload": {}},
            headers=user_headers,
        )

        assert resp.status_code == 409
        history = await client.get(
            f"/api/devices/{device.guid}/commands", headers=user_headers
        )
        assert history.status_code == 200
        entries = history.json()["items"]
        assert entries[0]["event_type"] == "session.command"
        assert "failed" in entries[0]["extra_data"]

    async def test_command_history_is_device_scoped(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        device = await _create_device(db_session, test_user, "history-device")
        other_device = await _create_device(db_session, test_user, "other-device")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        await client.post(
            f"/api/devices/{device.guid}/commands",
            json={"command": "pause", "payload": {}},
            headers=user_headers,
        )
        await client.post(
            f"/api/devices/{other_device.guid}/commands",
            json={"command": "stop", "payload": {}},
            headers=user_headers,
        )

        resp = await client.get(
            f"/api/devices/{device.guid}/commands", headers=user_headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "history-device" in data["items"][0]["extra_data"]

    async def test_send_message_command(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        device = await _create_device(db_session, test_user, "message-device")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            f"/api/devices/{device.guid}/commands",
            json={
                "command": "message",
                "payload": {"title": "Heads up", "text": "Playback will pause soon"},
            },
            headers=user_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["command"] == "message"
        assert manager.calls[0]["payload"]["text"] == "Playback will pause soon"

    async def test_send_browse_command(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        device = await _create_device(db_session, test_user, "browse-device")
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)
        item_guid = uuid.uuid4()

        resp = await client.post(
            f"/api/devices/{device.guid}/commands",
            json={
                "command": "browse",
                "payload": {
                    "route": "item",
                    "item_guid": str(item_guid),
                    "query": "ignored unless client wants it",
                },
            },
            headers=user_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["command"] == "browse"
        assert manager.calls[0]["payload"]["route"] == "item"
        assert manager.calls[0]["payload"]["item_guid"] == str(item_guid)


class TestActiveDeviceSessions:
    async def test_list_my_active_sessions(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        device = await _create_device(db_session, test_user, "living-room")
        device.is_playing = True
        device.current_media_title = "Session Movie"
        device.current_playback_position = 90
        device.current_playback_duration = 360
        await db_session.commit()

        now = datetime.now(UTC)
        manager = _FakeRemoteControlManager(
            active_sessions=[
                {
                    "user_id": str(test_user.guid),
                    "device_id": "living-room",
                    "connection_count": 2,
                    "subscription_count": 3,
                    "connected_at": now,
                    "last_seen_at": now,
                }
            ]
        )
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.get("/api/devices/sessions/active/me", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["device_guid"] == str(device.guid)
        assert data["items"][0]["device_id"] == "living-room"
        assert data["items"][0]["connection_count"] == 2
        assert data["items"][0]["subscription_count"] == 3
        assert data["items"][0]["playback_state"] == "playing"
        assert data["items"][0]["is_playing"] is True
        assert data["items"][0]["current_media_title"] == "Session Movie"
        assert data["items"][0]["progress_percentage"] == 25

    async def test_list_my_active_sessions_filters_other_users(
        self,
        client: AsyncClient,
        db_session,
        test_user,
        test_superuser,
        user_headers,
        monkeypatch,
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_user, "user-device")
        await _create_device(db_session, test_superuser, "admin-device")
        now = datetime.now(UTC)
        manager = _FakeRemoteControlManager(
            active_sessions=[
                {
                    "user_id": str(test_user.guid),
                    "device_id": "user-device",
                    "connection_count": 1,
                    "subscription_count": 0,
                    "connected_at": now,
                    "last_seen_at": now,
                },
                {
                    "user_id": str(test_superuser.guid),
                    "device_id": "admin-device",
                    "connection_count": 1,
                    "subscription_count": 0,
                    "connected_at": now,
                    "last_seen_at": now,
                },
            ]
        )
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.get("/api/devices/sessions/active/me", headers=user_headers)

        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["device_id"] == "user-device"

    async def test_admin_can_list_all_active_sessions(
        self,
        client: AsyncClient,
        db_session,
        test_user,
        test_superuser,
        admin_headers,
        monkeypatch,
    ):
        from streamarr.api.v1 import devices as devices_api

        await _create_device(db_session, test_user, "user-device")
        await _create_device(db_session, test_superuser, "admin-device")
        now = datetime.now(UTC)
        manager = _FakeRemoteControlManager(
            active_sessions=[
                {
                    "user_id": str(test_user.guid),
                    "device_id": "user-device",
                    "connection_count": 1,
                    "subscription_count": 0,
                    "connected_at": now,
                    "last_seen_at": now,
                },
                {
                    "user_id": str(test_superuser.guid),
                    "device_id": "admin-device",
                    "connection_count": 1,
                    "subscription_count": 0,
                    "connected_at": now,
                    "last_seen_at": now,
                },
            ]
        )
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.get("/api/devices/sessions/active", headers=admin_headers)

        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_regular_user_cannot_list_all_active_sessions(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.get("/api/devices/sessions/active", headers=user_headers)

        assert resp.status_code == 403


class TestDeviceSessionContract:
    async def test_get_device_session_contract(
        self, client: AsyncClient, db_session, test_user, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import devices as devices_api

        device = await _create_device(db_session, test_user, "living-room")
        media_guid = uuid.uuid4()
        device.device_info = {
            "capabilities": {
                "profile_id": "browser",
                "supported_video_codecs": ["h264"],
                "supported_audio_codecs": ["aac"],
            },
            "queue_state": {
                "items": [
                    {"media_guid": str(media_guid), "media_title": "Queue Movie"}
                ],
                "start_index": 0,
                "current_index": 0,
                "repeat_mode": "REPEAT_OFF",
                "shuffle": False,
            },
        }
        device.is_playing = True
        device.current_media_guid = media_guid
        device.current_media_type = "movie"
        device.current_media_title = "Queue Movie"
        device.current_playback_position = 60
        device.current_playback_duration = 240
        await db_session.commit()

        now = datetime.now(UTC)
        manager = _FakeRemoteControlManager(
            active_sessions=[
                {
                    "user_id": str(test_user.guid),
                    "device_id": "living-room",
                    "connection_count": 1,
                    "subscription_count": 1,
                    "connected_at": now,
                    "last_seen_at": now,
                }
            ]
        )
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.get(
            "/api/devices/by-id/living-room/session",
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["device"]["device_id"] == "living-room"
        assert data["device"]["is_ws_connected"] is True
        assert data["active_session"]["device_id"] == "living-room"
        assert data["capabilities"]["profile_id"] == "browser"
        assert data["now_playing"]["media_guid"] == str(media_guid)
        assert data["now_playing"]["playback_state"] == "playing"
        assert data["now_playing"]["progress_percentage"] == 25
        assert data["queue_state"]["items"][0]["media_title"] == "Queue Movie"

    async def test_admin_can_get_device_session_contract_by_guid(
        self,
        client: AsyncClient,
        db_session,
        test_user,
        admin_headers,
        monkeypatch,
    ):
        from streamarr.api.v1 import devices as devices_api

        device = await _create_device(db_session, test_user, "managed-living-room")
        device.is_playing = True
        device.current_media_title = "Managed Movie"
        device.current_playback_position = 30
        device.current_playback_duration = 120
        await db_session.commit()

        now = datetime.now(UTC)
        manager = _FakeRemoteControlManager(
            active_sessions=[
                {
                    "user_id": str(test_user.guid),
                    "device_id": "managed-living-room",
                    "connection_count": 1,
                    "subscription_count": 0,
                    "connected_at": now,
                    "last_seen_at": now,
                }
            ]
        )
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.get(
            f"/api/devices/{device.guid}/session",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["device"]["device_id"] == "managed-living-room"
        assert data["device"]["is_ws_connected"] is True
        assert data["active_session"]["device_id"] == "managed-living-room"
        assert data["now_playing"]["media_title"] == "Managed Movie"
        assert data["now_playing"]["progress_percentage"] == 25

    async def test_regular_user_cannot_get_other_device_session_by_guid(
        self, client: AsyncClient, db_session, test_superuser, user_headers
    ):
        device = await _create_device(db_session, test_superuser, "admin-living-room")

        resp = await client.get(
            f"/api/devices/{device.guid}/session",
            headers=user_headers,
        )

        assert resp.status_code == 404


class TestDeviceSessionUsers:
    async def test_owner_can_add_list_and_remove_session_user(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        device = await _create_device(db_session, test_user, "shared-tv")
        guest = User(
            guid=uuid.uuid4(),
            email="guest@example.com",
            first_name="Guest",
            last_name="Viewer",
            is_active=True,
        )
        db_session.add(guest)
        await db_session.commit()
        await db_session.refresh(guest)

        added = await client.post(
            f"/api/devices/{device.guid}/session-users",
            headers=user_headers,
            json={"user_guid": str(guest.guid)},
        )

        assert added.status_code == 200
        data = added.json()
        assert data["total"] == 1
        assert data["items"][0]["guid"] == str(guest.guid)
        assert data["items"][0]["name"] == "Guest Viewer"

        await db_session.refresh(device)
        assert str(guest.guid) in device.device_info["session_user_ids"]

        listed = await client.get(
            f"/api/devices/{device.guid}/session-users",
            headers=user_headers,
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        removed = await client.delete(
            f"/api/devices/{device.guid}/session-users/{guest.guid}",
            headers=user_headers,
        )
        assert removed.status_code == 200
        assert removed.json()["items"] == []

    async def test_other_users_device_is_hidden(
        self, client: AsyncClient, db_session, test_superuser, user_headers
    ):
        device = await _create_device(db_session, test_superuser, "admin-tv")

        resp = await client.get(
            f"/api/devices/{device.guid}/session-users",
            headers=user_headers,
        )

        assert resp.status_code == 404

    async def test_admin_can_manage_session_users(
        self, client: AsyncClient, db_session, test_user, admin_headers
    ):
        device = await _create_device(db_session, test_user, "managed-tv")

        resp = await client.post(
            f"/api/devices/{device.guid}/session-users",
            headers=admin_headers,
            json={"user_guid": str(test_user.guid)},
        )

        assert resp.status_code == 200
        assert resp.json()["items"][0]["email"] == test_user.email


class TestDeviceOfflineItems:
    async def test_owner_can_add_list_update_and_remove_offline_item(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        device = await _create_device(db_session, test_user, "mobile-phone")
        media_item = await _create_media_item(db_session)

        added = await client.post(
            f"/api/devices/{device.guid}/offline-items",
            headers=user_headers,
            json={
                "media_guid": str(media_item.guid),
                "status": "downloading",
                "progress": 25,
                "downloaded_bytes": 1000,
                "total_bytes": 4000,
            },
        )

        assert added.status_code == 200
        data = added.json()
        assert data["total"] == 1
        assert data["items"][0]["media_guid"] == str(media_item.guid)
        assert data["items"][0]["media_title"] == "Offline Movie"
        assert data["items"][0]["status"] == "downloading"
        assert data["items"][0]["progress"] == 25

        updated = await client.post(
            f"/api/devices/{device.guid}/offline-items",
            headers=user_headers,
            json={
                "media_guid": str(media_item.guid),
                "status": "ready",
                "progress": 100,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["items"][0]["status"] == "ready"
        assert updated.json()["items"][0]["progress"] == 100

        listed = await client.get(
            f"/api/devices/{device.guid}/offline-items",
            headers=user_headers,
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        removed = await client.delete(
            f"/api/devices/{device.guid}/offline-items/{media_item.guid}",
            headers=user_headers,
        )
        assert removed.status_code == 200
        assert removed.json()["items"] == []

    async def test_other_users_offline_items_are_hidden(
        self, client: AsyncClient, db_session, test_superuser, user_headers
    ):
        device = await _create_device(db_session, test_superuser, "admin-phone")

        resp = await client.get(
            f"/api/devices/{device.guid}/offline-items",
            headers=user_headers,
        )

        assert resp.status_code == 404

    async def test_admin_can_manage_offline_items(
        self, client: AsyncClient, db_session, test_user, admin_headers
    ):
        device = await _create_device(db_session, test_user, "managed-phone")
        media_item = await _create_media_item(db_session, "Admin Offline")

        resp = await client.post(
            f"/api/devices/{device.guid}/offline-items",
            headers=admin_headers,
            json={"media_guid": str(media_item.guid), "status": "queued"},
        )

        assert resp.status_code == 200
        assert resp.json()["items"][0]["media_title"] == "Admin Offline"

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "offline.item_update")
        )
        assert str(media_item.guid) in log_result.scalar_one().extra_data

    async def test_unknown_offline_media_returns_404(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        device = await _create_device(db_session, test_user, "mobile-phone")

        resp = await client.post(
            f"/api/devices/{device.guid}/offline-items",
            headers=user_headers,
            json={"media_guid": str(uuid.uuid4()), "status": "queued"},
        )

        assert resp.status_code == 404

    async def test_owner_can_request_offline_sync_for_multiple_items(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        device = await _create_device(db_session, test_user, "sync-phone")
        first = await _create_media_item(db_session, "First Offline")
        second = await _create_media_item(db_session, "Second Offline")

        resp = await client.post(
            f"/api/devices/{device.guid}/offline-items/sync-request",
            headers=user_headers,
            json={"media_guids": [str(first.guid), str(second.guid)]},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert {item["media_guid"] for item in data["items"]} == {
            str(first.guid),
            str(second.guid),
        }
        assert {item["status"] for item in data["items"]} == {"queued"}

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "offline.sync_request")
        )
        assert len(log_result.scalars().all()) == 2

    async def test_offline_sync_request_enforces_library_permissions(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        test_user.allowed_libraries = []
        device = await _create_device(db_session, test_user, "blocked-sync-phone")
        media_item = await _create_media_item(db_session)
        await db_session.commit()

        resp = await client.post(
            f"/api/devices/{device.guid}/offline-items/sync-request",
            headers=user_headers,
            json={"media_guids": [str(media_item.guid)]},
        )

        assert resp.status_code == 403

    async def test_offline_sync_request_enforces_download_limit(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        test_user.offline_download_limit = 1
        device = await _create_device(db_session, test_user, "limited-sync-phone")
        first = await _create_media_item(db_session, "First Offline")
        second = await _create_media_item(db_session, "Second Offline")
        await db_session.commit()

        resp = await client.post(
            f"/api/devices/{device.guid}/offline-items/sync-request",
            headers=user_headers,
            json={"media_guids": [str(first.guid), str(second.guid)]},
        )

        assert resp.status_code == 403

    async def test_owner_can_get_offline_manifest(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        device = await _create_device(db_session, test_user, "manifest-phone")
        media_item = await _create_media_item(
            db_session,
            "Manifest Offline",
        )
        media_item.extra_data = json.dumps(
            {
                "subtitles": [
                    {
                        "id": "upload:en",
                        "language": "en",
                        "title": "Uploaded English",
                        "format": "srt",
                        "path": "uploaded:upload:en",
                        "is_default": True,
                    },
                    {
                        "id": "opensubtitles:de",
                        "language": "de",
                        "title": "Remote German",
                        "format": "srt",
                        "url": "https://subs.example/de.srt",
                    },
                ]
            }
        )
        media_file = await _create_media_file(db_session, media_item)

        await client.post(
            f"/api/devices/{device.guid}/offline-items",
            headers=user_headers,
            json={
                "media_guid": str(media_item.guid),
                "file_guid": str(media_file.guid),
                "status": "ready",
                "progress": 100,
            },
        )

        resp = await client.get(
            f"/api/devices/{device.guid}/offline-items/manifest",
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == "manifest-phone"
        assert data["total"] == 1
        item = data["items"][0]
        assert item["media_guid"] == str(media_item.guid)
        assert item["file_guid"] == str(media_file.guid)
        assert item["download_url"] == (
            f"/api/media/{media_item.guid}/files/{media_file.guid}/download"
        )
        assert item["file_size"] == 123456
        assert item["duration"] == media_item.duration
        subtitles = {subtitle["id"]: subtitle for subtitle in item["subtitles"]}
        assert subtitles["upload:en"]["content_url"] == (
            f"/api/media/{media_item.guid}/subtitles/upload:en/content"
        )
        assert subtitles["opensubtitles:de"]["url"] == "https://subs.example/de.srt"
        assert subtitles["opensubtitles:de"]["content_url"] == (
            f"/api/media/{media_item.guid}/subtitles/opensubtitles:de/content"
        )

    async def test_offline_manifest_omits_removed_items(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        device = await _create_device(db_session, test_user, "removed-manifest-phone")
        media_item = await _create_media_item(db_session, "Removed Offline")

        listed = await client.post(
            f"/api/devices/{device.guid}/offline-items",
            headers=user_headers,
            json={"media_guid": str(media_item.guid), "status": "removed"},
        )
        assert listed.status_code == 200
        assert listed.json()["items"][0]["status"] == "removed"

        resp = await client.get(
            f"/api/devices/{device.guid}/offline-items/manifest",
            headers=user_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["items"] == []


# ---------------------------------------------------------------------------
# Admin device endpoints
# ---------------------------------------------------------------------------
class TestAdminDevices:
    async def test_list_all_devices(self, client: AsyncClient, db_session, test_user, test_superuser, admin_headers):
        await _create_device(db_session, test_user, "u-dev")
        await _create_device(db_session, test_superuser, "a-dev")

        resp = await client.get("/api/devices", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2

    async def test_list_all_devices_regular_user_forbidden(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/devices", headers=user_headers)
        assert resp.status_code == 403

    async def test_admin_get_device(self, client: AsyncClient, db_session, test_user, admin_headers):
        device = await _create_device(db_session, test_user)

        resp = await client.get(f"/api/devices/{device.guid}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["device_id"] == "dev-001"

    async def test_admin_update_device_trusted(self, client: AsyncClient, db_session, test_user, admin_headers):
        device = await _create_device(db_session, test_user)

        resp = await client.put(
            f"/api/devices/{device.guid}",
            json={"is_trusted": True},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_trusted"] is True

    async def test_admin_delete_device(self, client: AsyncClient, db_session, test_user, admin_headers):
        device = await _create_device(db_session, test_user)

        resp = await client.delete(f"/api/devices/{device.guid}", headers=admin_headers)
        assert resp.status_code == 204

    async def test_admin_get_user_devices(self, client: AsyncClient, db_session, test_user, admin_headers):
        await _create_device(db_session, test_user, "x1")
        await _create_device(db_session, test_user, "x2")

        resp = await client.get(f"/api/devices/user/{test_user.guid}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] >= 2

    async def test_admin_delete_device_permanent(
        self, client: AsyncClient, db_session, test_user, admin_headers
    ):
        """Admin permanent delete removes device entirely."""
        device = await _create_device(db_session, test_user, "perm-del")

        resp = await client.delete(
            f"/api/devices/{device.guid}?permanent=true",
            headers=admin_headers,
        )
        assert resp.status_code == 204

        # Should be completely gone
        resp = await client.get(f"/api/devices/{device.guid}", headers=admin_headers)
        assert resp.status_code == 404

    async def test_admin_delete_device_not_found(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.delete(
            f"/api/devices/{uuid.uuid4()}", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_admin_get_device_not_found(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.get(
            f"/api/devices/{uuid.uuid4()}", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_admin_update_device_not_found(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.put(
            f"/api/devices/{uuid.uuid4()}",
            json={"name": "Ghost"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_admin_list_devices_search(
        self, client: AsyncClient, db_session, test_user, test_superuser, admin_headers
    ):
        """Admin can search devices by name."""
        await _create_device(db_session, test_user, "searchable-xyz")

        resp = await client.get(
            "/api/devices?search=searchable", headers=admin_headers
        )
        assert resp.status_code == 200

    async def test_admin_list_devices_include_inactive(
        self, client: AsyncClient, db_session, test_user, test_superuser, admin_headers
    ):
        """Admin can include inactive devices."""
        resp = await client.get(
            "/api/devices?include_inactive=true", headers=admin_headers
        )
        assert resp.status_code == 200

    async def test_admin_get_user_devices_with_include_inactive(
        self, client: AsyncClient, db_session, test_user, test_superuser, admin_headers
    ):
        await _create_device(db_session, test_user, "ia-dev")

        resp = await client.get(
            f"/api/devices/user/{test_user.guid}?include_inactive=true",
            headers=admin_headers,
        )
        assert resp.status_code == 200

    async def test_admin_update_device_name(
        self, client: AsyncClient, db_session, test_user, admin_headers
    ):
        """Admin can update device name and the response includes user info."""
        device = await _create_device(db_session, test_user, "rename-me")

        resp = await client.put(
            f"/api/devices/{device.guid}",
            json={"name": "Renamed Device"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Renamed Device"


class TestMyDevicesPagination:
    async def test_my_devices_pagination(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        """User device pagination works correctly."""
        for i in range(5):
            await _create_device(db_session, test_user, f"pg-dev-{i}")

        resp = await client.get(
            "/api/devices/me?page=1&page_size=2", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] >= 5

    async def test_update_my_device_not_found(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.put(
            f"/api/devices/me/{uuid.uuid4()}",
            json={"name": "Nobody"},
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_delete_my_device_not_found(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.delete(
            f"/api/devices/me/{uuid.uuid4()}", headers=user_headers
        )
        assert resp.status_code == 404

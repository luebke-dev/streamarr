"""Tests for cast target registry endpoints (/api/cast/*)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy import select

from pyrate.models import ActivityLog
from pyrate.services.casting import airplay as cast_airplay
from pyrate.services.casting import chromecast as cast_chromecast
from pyrate.services.casting import dlna as cast_dlna
from pyrate.services.websocket import RemoteControlError


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
        }

    def get_active_device_sessions(self, user_id: str | None = None):
        if user_id:
            return [
                session
                for session in self.active_sessions
                if session["user_id"] == user_id
            ]
        return self.active_sessions


async def _register_targets(client: AsyncClient, admin_headers, targets: list[dict]):
    return await client.put(
        "/api/cast/targets",
        headers=admin_headers,
        json={"targets": targets},
    )


class TestCastTargets:
    async def test_list_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/cast/targets")

        assert resp.status_code == 401

    async def test_regular_user_cannot_update_targets(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.put(
            "/api/cast/targets",
            headers=user_headers,
            json={"targets": []},
        )

        assert resp.status_code == 403

    async def test_admin_updates_and_users_list_enabled_targets(
        self, client: AsyncClient, db_session, admin_headers, user_headers
    ):
        resp = await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "living-room",
                    "name": "Living Room",
                    "protocol": "pyrate",
                    "device_id": "living-room-device",
                    "supports_remote_control": True,
                },
                {
                    "id": "old-tv",
                    "name": "Old TV",
                    "protocol": "dlna",
                    "host": "192.0.2.10",
                    "enabled": False,
                },
            ],
        )

        assert resp.status_code == 200
        assert [target["id"] for target in resp.json()] == ["living-room", "old-tv"]

        listed = await client.get("/api/cast/targets", headers=user_headers)
        assert listed.status_code == 200
        data = listed.json()
        assert [target["id"] for target in data] == ["living-room"]
        assert data[0]["supports_remote_control"] is True

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "cast.targets_update")
        )
        log_entry = log_result.scalar_one()
        assert "Updated 2 cast targets" in log_entry.message

    async def test_discover_includes_manual_and_active_pyrate_sessions(
        self, client: AsyncClient, admin_headers, user_headers, test_user, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "office-tv",
                    "name": "Office TV",
                    "protocol": "dlna",
                    "host": "192.0.2.20",
                    "port": 8200,
                }
            ],
        )
        now = datetime.now(UTC)
        manager = _FakeRemoteControlManager(
            active_sessions=[
                {
                    "user_id": str(test_user.guid),
                    "device_id": "living-room-device",
                    "connection_count": 1,
                    "subscription_count": 0,
                    "connected_at": now,
                    "last_seen_at": now,
                }
            ]
        )
        monkeypatch.setattr(cast_api, "get_websocket_manager", lambda: manager)

        resp = await client.get("/api/cast/discover", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        targets = {item["id"]: item for item in data["items"]}
        assert targets["office-tv"]["discovered"] is False
        assert targets["office-tv"]["discovery_source"] == "manual"
        assert targets["pyrate:living-room-device"]["protocol"] == "pyrate"
        assert targets["pyrate:living-room-device"]["device_id"] == "living-room-device"
        assert targets["pyrate:living-room-device"]["discovery_source"] == "active_session"
        assert targets["pyrate:living-room-device"]["supports_remote_control"] is True

    async def test_discover_filters_active_sessions_to_current_user(
        self,
        client: AsyncClient,
        user_headers,
        test_user,
        test_superuser,
        monkeypatch,
    ):
        from pyrate.api.v1 import cast as cast_api

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
        monkeypatch.setattr(cast_api, "get_websocket_manager", lambda: manager)

        resp = await client.get("/api/cast/discover", headers=user_headers)

        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()["items"]}
        assert "pyrate:user-device" in ids
        assert "pyrate:admin-device" not in ids

    async def test_protocol_capabilities(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/cast/protocols", headers=user_headers)

        assert resp.status_code == 200
        protocols = {item["protocol"]: item for item in resp.json()}
        assert protocols["pyrate"]["discovery_supported"] is True
        assert protocols["pyrate"]["remote_control_supported"] is True
        assert protocols["chromecast"]["discovery_supported"] is True
        assert protocols["chromecast"]["remote_control_supported"] is True
        assert protocols["chromecast"]["native_sender_supported"] is True
        assert protocols["chromecast"]["playback_profile_id"] == "chromecast"
        assert "queue_load" in protocols["chromecast"]["supported_commands"]
        assert "video" in protocols["chromecast"]["supported_media_types"]
        assert {
            profile["container"] for profile in protocols["chromecast"]["container_profiles"]
        } >= {"mp4", "webm"}
        assert {
            profile["mime_type"] for profile in protocols["chromecast"]["transcoding_profiles"]
        } >= {"video/mp4", "video/webm"}
        assert protocols["chromecast"]["supports_volume_control"] is True
        assert protocols["dlna"]["discovery_supported"] is True
        assert protocols["dlna"]["remote_control_supported"] is True
        assert protocols["dlna"]["native_sender_supported"] is False
        assert protocols["dlna"]["playback_profile_id"] == "dlna_generic"
        assert "video/mp2t" in {
            profile["mime_type"] for profile in protocols["dlna"]["container_profiles"]
        }
        assert protocols["airplay"]["discovery_supported"] is True
        assert protocols["airplay"]["remote_control_supported"] is True
        assert protocols["airplay"]["playback_profile_id"] == "browser"

    async def test_native_discovery_includes_ssdp_dlna_targets(
        self, client: AsyncClient, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        monkeypatch.setattr(
            cast_api,
            "_discover_dlna_targets",
            lambda timeout_seconds=1.0: [
                cast_api.CastDiscoveryTarget(
                    id="dlna:uuid:renderer-1",
                    name="Living Room Renderer",
                    protocol="dlna",
                    host="192.0.2.30",
                    port=1400,
                    discovered=True,
                    discovery_source="ssdp",
                )
            ],
        )

        resp = await client.get("/api/cast/discover?native=true", headers=user_headers)

        assert resp.status_code == 200
        targets = {item["id"]: item for item in resp.json()["items"]}
        assert targets["dlna:uuid:renderer-1"]["protocol"] == "dlna"
        assert targets["dlna:uuid:renderer-1"]["discovery_source"] == "ssdp"

    async def test_native_discovery_includes_mdns_cast_targets(
        self, client: AsyncClient, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        monkeypatch.setattr(cast_api, "_discover_dlna_targets", lambda timeout_seconds=1.0: [])
        monkeypatch.setattr(
            cast_api,
            "_discover_mdns_targets",
            lambda timeout_seconds=1.0: [
                cast_api.CastDiscoveryTarget(
                    id="chromecast:living-room",
                    name="Living Room Chromecast",
                    protocol="chromecast",
                    host="192.0.2.40",
                    port=8009,
                    discovered=True,
                    discovery_source="mdns",
                ),
                cast_api.CastDiscoveryTarget(
                    id="airplay:den",
                    name="Den AirPlay",
                    protocol="airplay",
                    host="192.0.2.41",
                    port=7000,
                    discovered=True,
                    discovery_source="mdns",
                ),
            ],
        )

        resp = await client.get("/api/cast/discover?native=true", headers=user_headers)

        assert resp.status_code == 200
        targets = {item["id"]: item for item in resp.json()["items"]}
        assert targets["chromecast:living-room"]["protocol"] == "chromecast"
        assert targets["chromecast:living-room"]["discovery_source"] == "mdns"
        assert targets["airplay:den"]["protocol"] == "airplay"
        assert targets["airplay:den"]["discovery_source"] == "mdns"


class TestCastCommands:
    async def test_command_to_unknown_target_returns_404(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.post(
            "/api/cast/targets/missing/commands",
            headers=user_headers,
            json={"command": "play", "payload": {}},
        )

        assert resp.status_code == 404

    async def test_chromecast_target_rejects_unknown_commands(
        self, client: AsyncClient, admin_headers, user_headers
    ):
        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "office-tv",
                    "name": "Office TV",
                    "protocol": "chromecast",
                    "host": "192.0.2.20",
                    "port": 8009,
                }
            ],
        )

        resp = await client.post(
            "/api/cast/targets/office-tv/commands",
            headers=user_headers,
            json={"command": "brightness", "payload": {"level": 0.5}},
        )

        assert resp.status_code == 422
        assert "Unsupported Chromecast command" in resp.json()["detail"]

    async def test_pyrate_target_sends_remote_command(
        self,
        client: AsyncClient,
        db_session,
        admin_headers,
        user_headers,
        test_user,
        monkeypatch,
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "living-room",
                    "name": "Living Room",
                    "protocol": "pyrate",
                    "device_id": "living-room-device",
                    "supports_remote_control": True,
                }
            ],
        )
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(cast_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            "/api/cast/targets/living-room/commands",
            headers=user_headers,
            json={"command": "browse", "payload": {"route": "home"}},
        )

        assert resp.status_code == 200
        assert resp.json() == {"target_id": "living-room", "status": "sent"}
        assert manager.calls[0]["user_id"] == str(test_user.guid)
        assert manager.calls[0]["target_device_id"] == "living-room-device"
        assert manager.calls[0]["command"] == "browse"
        assert manager.calls[0]["payload"] == {"route": "home"}

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "cast.command")
        )
        log_entry = log_result.scalar_one()
        assert "Living Room" in log_entry.message
        assert "browse" in log_entry.extra_data

    async def test_dlna_target_sends_renderer_command(
        self, client: AsyncClient, db_session, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "dlna-living-room",
                    "name": "DLNA Living Room",
                    "protocol": "dlna",
                    "host": "192.0.2.50",
                    "port": 1400,
                    "control_url": "http://192.0.2.50:1400/control",
                }
            ],
        )
        send_dlna = AsyncMock()
        monkeypatch.setattr(cast_api, "_send_dlna_command", send_dlna)

        resp = await client.post(
            "/api/cast/targets/dlna-living-room/commands",
            headers=user_headers,
            json={"command": "play", "payload": {"media_url": "https://media.test/movie.mkv"}},
        )

        assert resp.status_code == 200
        assert resp.json() == {"target_id": "dlna-living-room", "status": "sent"}
        send_dlna.assert_awaited_once()
        assert send_dlna.await_args.args[1] == "play"
        assert send_dlna.await_args.args[2]["media_url"] == "https://media.test/movie.mkv"

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "cast.command")
        )
        log_entry = log_result.scalar_one()
        assert "DLNA Living Room" in log_entry.message
        assert "dlna" in log_entry.extra_data

    async def test_dlna_seek_command_formats_position_seconds(
        self, client: AsyncClient, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "dlna-living-room",
                    "name": "DLNA Living Room",
                    "protocol": "dlna",
                    "host": "192.0.2.50",
                    "port": 1400,
                }
            ],
        )
        sent_actions = []

        async def fake_send(_target, command, payload):
            sent_actions.append(
                (
                    command,
                    cast_dlna._dlna_seek_target(payload),
                )
            )

        monkeypatch.setattr(cast_api, "_send_dlna_command", fake_send)

        resp = await client.post(
            "/api/cast/targets/dlna-living-room/commands",
            headers=user_headers,
            json={"command": "seek", "payload": {"position_seconds": 3671}},
        )

        assert resp.status_code == 200
        assert sent_actions == [("seek", "01:01:11")]

    async def test_dlna_resume_command_is_accepted(
        self, client: AsyncClient, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "dlna-living-room",
                    "name": "DLNA Living Room",
                    "protocol": "dlna",
                    "host": "192.0.2.50",
                    "port": 1400,
                }
            ],
        )
        send_dlna = AsyncMock()
        monkeypatch.setattr(cast_api, "_send_dlna_command", send_dlna)

        resp = await client.post(
            "/api/cast/targets/dlna-living-room/commands",
            headers=user_headers,
            json={"command": "resume", "payload": {}},
        )

        assert resp.status_code == 200
        send_dlna.assert_awaited_once()
        assert send_dlna.await_args.args[1] == "resume"

    async def test_dlna_metadata_builder_uses_media_fields(self):
        from pyrate.api.v1 import cast as cast_api

        metadata = cast_dlna._dlna_metadata(
            {
                "title": "The <Movie>",
                "creator": "Director & Co",
                "media_type": "movie",
                "mime_type": "video/x-matroska",
                "artwork_url": "https://media.test/poster.jpg?size=large",
            },
            "https://media.test/movie.mkv",
        )

        assert "<dc:title>The &lt;Movie&gt;</dc:title>" in metadata
        assert "<dc:creator>Director &amp; Co</dc:creator>" in metadata
        assert "<upnp:class>object.item.videoItem</upnp:class>" in metadata
        assert "video/x-matroska" in metadata
        assert "poster.jpg?size=large" in metadata

    async def test_dlna_metadata_infers_mime_type_from_url(self):
        from pyrate.api.v1 import cast as cast_api

        metadata = cast_dlna._dlna_metadata(
            {"title": "Movie"},
            "https://media.test/movie.mkv",
        )

        assert "video/x-matroska" in metadata

    async def test_dlna_metadata_builder_preserves_raw_metadata(self):
        from pyrate.api.v1 import cast as cast_api

        metadata = cast_dlna._dlna_metadata(
            {"metadata": "<DIDL-Lite>custom</DIDL-Lite>", "title": "Ignored"},
            "https://media.test/movie.mkv",
        )

        assert metadata == "<DIDL-Lite>custom</DIDL-Lite>"

    async def test_airplay_target_sends_receiver_command(
        self, client: AsyncClient, db_session, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "airplay-den",
                    "name": "AirPlay Den",
                    "protocol": "airplay",
                    "host": "192.0.2.60",
                    "port": 7000,
                }
            ],
        )
        send_airplay = AsyncMock()
        monkeypatch.setattr(cast_api, "_send_airplay_command", send_airplay)

        resp = await client.post(
            "/api/cast/targets/airplay-den/commands",
            headers=user_headers,
            json={"command": "play", "payload": {"media_url": "https://media.test/movie.mkv"}},
        )

        assert resp.status_code == 200
        assert resp.json() == {"target_id": "airplay-den", "status": "sent"}
        send_airplay.assert_awaited_once()
        assert send_airplay.await_args.args[1] == "play"
        assert send_airplay.await_args.args[2]["media_url"] == "https://media.test/movie.mkv"

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "cast.command")
        )
        log_entry = log_result.scalar_one()
        assert "AirPlay Den" in log_entry.message
        assert "airplay" in log_entry.extra_data

    async def test_airplay_play_payload_includes_metadata_fields(self):
        from pyrate.api.v1 import cast as cast_api

        payload = cast_airplay._airplay_play_payload(
            "https://media.test/movie.mkv",
            {
                "start_position": 12.5,
                "title": "Movie Night",
                "artist": "pyrate",
                "album": "Featured",
                "poster_url": "https://media.test/poster.jpg",
            },
        )

        assert payload["Content-Location"] == "https://media.test/movie.mkv"
        assert payload["Start-Position"] == "12.5"
        assert payload["Title"] == "Movie Night"
        assert payload["Artist"] == "pyrate"
        assert payload["Album"] == "Featured"
        assert payload["Artwork-URL"] == "https://media.test/poster.jpg"

    async def test_chromecast_target_sends_dial_command(
        self, client: AsyncClient, db_session, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "chromecast-living-room",
                    "name": "Chromecast Living Room",
                    "protocol": "chromecast",
                    "host": "192.0.2.70",
                    "port": 8008,
                }
            ],
        )
        send_chromecast = AsyncMock()
        monkeypatch.setattr(cast_api, "_send_chromecast_command", send_chromecast)

        resp = await client.post(
            "/api/cast/targets/chromecast-living-room/commands",
            headers=user_headers,
            json={"command": "launch", "payload": {"app_id": "CC1AD845"}},
        )

        assert resp.status_code == 200
        assert resp.json() == {"target_id": "chromecast-living-room", "status": "sent"}
        send_chromecast.assert_awaited_once()
        assert send_chromecast.await_args.args[1] == "launch"
        assert send_chromecast.await_args.args[2]["app_id"] == "CC1AD845"

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "cast.command")
        )
        log_entry = log_result.scalar_one()
        assert "Chromecast Living Room" in log_entry.message
        assert "chromecast" in log_entry.extra_data

    async def test_chromecast_target_sends_media_namespace_play_command(
        self, client: AsyncClient, db_session, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "chromecast-living-room",
                    "name": "Chromecast Living Room",
                    "protocol": "chromecast",
                    "host": "192.0.2.70",
                    "port": 8009,
                }
            ],
        )
        send_media = AsyncMock()
        monkeypatch.setattr(cast_chromecast, "_send_chromecast_media_command", send_media)

        resp = await client.post(
            "/api/cast/targets/chromecast-living-room/commands",
            headers=user_headers,
            json={
                "command": "play",
                "payload": {
                    "media_url": "https://media.test/movie.mp4",
                    "title": "Movie Night",
                    "mime_type": "video/mp4",
                },
            },
        )

        assert resp.status_code == 200
        assert resp.json() == {"target_id": "chromecast-living-room", "status": "sent"}
        send_media.assert_awaited_once()
        assert send_media.await_args.args[1] == "play"
        assert send_media.await_args.args[2]["media_url"] == "https://media.test/movie.mp4"

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "cast.command")
        )
        log_entry = log_result.scalar_one()
        assert "Chromecast Living Room" in log_entry.message
        assert "chromecast" in log_entry.extra_data

    async def test_chromecast_target_sends_receiver_volume_command(
        self, client: AsyncClient, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "chromecast-living-room",
                    "name": "Chromecast Living Room",
                    "protocol": "chromecast",
                    "host": "192.0.2.70",
                    "port": 8009,
                }
            ],
        )
        send_receiver = AsyncMock()
        monkeypatch.setattr(cast_chromecast, "_send_chromecast_receiver_command", send_receiver)

        resp = await client.post(
            "/api/cast/targets/chromecast-living-room/commands",
            headers=user_headers,
            json={"command": "volume", "payload": {"level": 50}},
        )

        assert resp.status_code == 200
        send_receiver.assert_awaited_once()
        assert send_receiver.await_args.args[1] == "volume"
        assert send_receiver.await_args.args[2]["level"] == 50

    async def test_chromecast_receiver_volume_payload_normalizes_fields(self):
        from pyrate.api.v1 import cast as cast_api

        volume_payload = cast_chromecast._chromecast_receiver_control_payload(
            "volume",
            {"level": 50, "muted": False},
        )
        mute_payload = cast_chromecast._chromecast_receiver_control_payload("mute", {})
        unmute_payload = cast_chromecast._chromecast_receiver_control_payload("unmute", {})

        assert volume_payload == {
            "type": "SET_VOLUME",
            "requestId": 1,
            "volume": {"level": 0.5, "muted": False},
        }
        assert mute_payload == {
            "type": "SET_VOLUME",
            "requestId": 1,
            "volume": {"muted": True},
        }
        assert unmute_payload == {
            "type": "SET_VOLUME",
            "requestId": 1,
            "volume": {"muted": False},
        }

    async def test_chromecast_load_payload_includes_media_metadata(self):
        from pyrate.api.v1 import cast as cast_api

        payload = cast_chromecast._chromecast_load_payload(
            {
                "media_url": "https://media.test/movie.mp4",
                "title": "Movie Night",
                "mime_type": "video/mp4",
                "poster_url": "https://media.test/poster.jpg",
                "start_position": 42,
            }
        )

        assert payload["type"] == "LOAD"
        assert payload["media"]["contentId"] == "https://media.test/movie.mp4"
        assert payload["media"]["contentType"] == "video/mp4"
        assert payload["media"]["metadata"]["title"] == "Movie Night"
        assert payload["media"]["metadata"]["images"] == [
            {"url": "https://media.test/poster.jpg"}
        ]
        assert payload["currentTime"] == 42.0

    async def test_chromecast_queue_load_payload_includes_ordered_items(self):
        from pyrate.api.v1 import cast as cast_api

        payload = cast_chromecast._chromecast_queue_load_payload(
            {
                "start_index": 1,
                "repeat_mode": "REPEAT_ALL",
                "mime_type": "video/mp4",
                "items": [
                    {
                        "media_url": "https://media.test/one.mp4",
                        "title": "First",
                        "poster_url": "https://media.test/one.jpg",
                    },
                    {
                        "media_url": "https://media.test/two.mp4",
                        "title": "Second",
                        "start_position": 12,
                    },
                ],
            }
        )

        assert payload["type"] == "QUEUE_LOAD"
        assert payload["startIndex"] == 1
        assert payload["repeatMode"] == "REPEAT_ALL"
        assert payload["items"][0]["itemId"] == 1
        assert payload["items"][0]["media"]["contentId"] == "https://media.test/one.mp4"
        assert payload["items"][0]["media"]["metadata"]["title"] == "First"
        assert payload["items"][0]["media"]["metadata"]["images"] == [
            {"url": "https://media.test/one.jpg"}
        ]
        assert payload["items"][1]["itemId"] == 2
        assert payload["items"][1]["startTime"] == 12.0
        assert payload["items"][1]["media"]["metadata"]["title"] == "Second"

    async def test_chromecast_target_sends_media_namespace_queue_command(
        self, client: AsyncClient, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "chromecast-living-room",
                    "name": "Chromecast Living Room",
                    "protocol": "chromecast",
                    "host": "192.0.2.70",
                    "port": 8009,
                }
            ],
        )
        send_media = AsyncMock()
        monkeypatch.setattr(cast_chromecast, "_send_chromecast_media_command", send_media)

        resp = await client.post(
            "/api/cast/targets/chromecast-living-room/commands",
            headers=user_headers,
            json={
                "command": "play_queue",
                "payload": {
                    "items": [
                        {"media_url": "https://media.test/one.mp4", "title": "First"},
                        {"media_url": "https://media.test/two.mp4", "title": "Second"},
                    ],
                    "start_index": 1,
                },
            },
        )

        assert resp.status_code == 200
        send_media.assert_awaited_once()
        assert send_media.await_args.args[1] == "play_queue"
        assert send_media.await_args.args[2]["start_index"] == 1

    async def test_chromecast_control_payload_includes_provided_media_session(self):
        from pyrate.api.v1 import cast as cast_api

        payload = cast_chromecast._chromecast_media_control_payload(
            "seek",
            {"position_seconds": 25, "media_session_id": "99"},
        )

        assert payload == {
            "type": "SEEK",
            "requestId": 1,
            "currentTime": 25.0,
            "mediaSessionId": 99,
        }

    async def test_chromecast_media_command_resolves_active_media_session(self, monkeypatch):
        from pyrate.api.v1 import cast as cast_api

        target = cast_api.CastTarget(
            id="chromecast-living-room",
            name="Chromecast Living Room",
            protocol="chromecast",
            host="192.0.2.70",
        )
        calls = []

        async def fake_status(_target):
            return {"type": "MEDIA_STATUS", "status": [{"mediaSessionId": 42}]}

        def fake_send(sent_target, media_payload, *, launch_app, app_id):
            calls.append((sent_target.id, media_payload, launch_app, app_id))

        monkeypatch.setattr(
            cast_chromecast,
            "_get_chromecast_media_status_payload_async",
            fake_status,
        )
        monkeypatch.setattr(cast_chromecast, "_send_chromecast_cast_v2_payload", fake_send)

        await cast_chromecast._send_chromecast_media_command(target, "pause", {})

        assert calls == [
            (
                "chromecast-living-room",
                {"type": "PAUSE", "requestId": 1, "mediaSessionId": 42},
                False,
                "CC1AD845",
            )
        ]

    async def test_chromecast_media_command_accepts_custom_receiver_app_id(self, monkeypatch):
        from pyrate.api.v1 import cast as cast_api

        target = cast_api.CastTarget(
            id="chromecast-living-room",
            name="Chromecast Living Room",
            protocol="chromecast",
            host="192.0.2.70",
        )
        calls = []

        def fake_send(sent_target, media_payload, *, launch_app, app_id):
            calls.append((sent_target.id, media_payload["type"], launch_app, app_id))

        monkeypatch.setattr(cast_chromecast, "_send_chromecast_cast_v2_payload", fake_send)

        await cast_chromecast._send_chromecast_media_command(
            target,
            "play",
            {
                "media_url": "https://media.test/movie.mp4",
                "chromecast_app_id": "CUSTOM123",
            },
        )

        assert calls == [("chromecast-living-room", "LOAD", True, "CUSTOM123")]

    async def test_chromecast_media_command_requires_active_session(self, monkeypatch):
        from pyrate.api.v1 import cast as cast_api

        target = cast_api.CastTarget(
            id="chromecast-living-room",
            name="Chromecast Living Room",
            protocol="chromecast",
            host="192.0.2.70",
        )

        async def fake_status(_target):
            return None

        monkeypatch.setattr(
            cast_chromecast,
            "_get_chromecast_media_status_payload_async",
            fake_status,
        )

        try:
            await cast_chromecast._send_chromecast_media_command(target, "pause", {})
        except cast_api.HTTPException as exc:
            assert exc.status_code == 409
            assert "media session" in exc.detail
        else:
            raise AssertionError("pause without an active media session should fail")

    async def test_chromecast_media_command_launches_only_for_load(self, monkeypatch):
        from pyrate.api.v1 import cast as cast_api

        target = cast_api.CastTarget(
            id="chromecast-living-room",
            name="Chromecast Living Room",
            protocol="chromecast",
            host="192.0.2.70",
        )
        calls = []

        def fake_send(sent_target, media_payload, *, launch_app, app_id):
            calls.append((sent_target.id, media_payload["type"], launch_app, app_id))

        monkeypatch.setattr(cast_chromecast, "_send_chromecast_cast_v2_payload", fake_send)

        await cast_chromecast._send_chromecast_media_command(
            target,
            "play",
            {"media_url": "https://media.test/movie.mp4"},
        )
        await cast_chromecast._send_chromecast_media_command(
            target,
            "play_queue",
            {"items": [{"media_url": "https://media.test/next.mp4"}]},
        )
        await cast_chromecast._send_chromecast_media_command(
            target,
            "pause",
            {"media_session_id": 7},
        )

        assert calls == [
            ("chromecast-living-room", "LOAD", True, "CC1AD845"),
            ("chromecast-living-room", "QUEUE_LOAD", True, "CC1AD845"),
            ("chromecast-living-room", "PAUSE", False, "CC1AD845"),
        ]

    async def test_chromecast_cast_message_round_trips_payload(self):
        from pyrate.api.v1 import cast as cast_api

        raw = cast_chromecast._cast_message(
            namespace="urn:x-cast:com.google.cast.media",
            destination_id="transport-1",
            payload={"type": "PAUSE", "requestId": 7},
        )
        length = int.from_bytes(raw[:4], "big")
        parsed = cast_chromecast._parse_cast_message(raw[4:])

        assert length == len(raw) - 4
        assert parsed["destination_id"] == "transport-1"
        assert parsed["namespace"] == "urn:x-cast:com.google.cast.media"
        assert parsed["payload_utf8"] == '{"type":"PAUSE","requestId":7}'

    async def test_remote_control_failure_returns_conflict(
        self, client: AsyncClient, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "bedroom",
                    "name": "Bedroom",
                    "protocol": "pyrate",
                    "device_id": "offline-device",
                }
            ],
        )
        manager = _FakeRemoteControlManager(
            fail=RemoteControlError("Target device not connected")
        )
        monkeypatch.setattr(cast_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            "/api/cast/targets/bedroom/commands",
            headers=user_headers,
            json={"command": "pause", "payload": {}},
        )

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Target device not connected"


class TestCastStatus:
    async def test_dlna_target_status(
        self, client: AsyncClient, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "dlna-living-room",
                    "name": "DLNA Living Room",
                    "protocol": "dlna",
                    "host": "192.0.2.50",
                    "port": 1400,
                }
            ],
        )
        get_status = AsyncMock(
            return_value=cast_api.CastTargetStatus(
                target_id="dlna-living-room",
                protocol="dlna",
                transport_state="PLAYING",
                transport_status="OK",
                media_url="https://media.test/movie.mkv",
                duration="01:30:00",
                position="00:12:34",
                raw={"CurrentTransportState": "PLAYING"},
            )
        )
        monkeypatch.setattr(cast_api, "_get_dlna_status", get_status)

        resp = await client.get(
            "/api/cast/targets/dlna-living-room/status",
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "dlna-living-room"
        assert data["transport_state"] == "PLAYING"
        assert data["position"] == "00:12:34"
        get_status.assert_awaited_once()

    async def test_airplay_target_status(
        self, client: AsyncClient, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "airplay-den",
                    "name": "AirPlay Den",
                    "protocol": "airplay",
                    "host": "192.0.2.60",
                    "port": 7000,
                }
            ],
        )
        get_status = AsyncMock(
            return_value=cast_api.CastTargetStatus(
                target_id="airplay-den",
                protocol="airplay",
                transport_state="PLAYING",
                transport_status="OK",
                duration="01:30:00",
                position="00:01:23",
                raw={"rate": "1.0"},
            )
        )
        monkeypatch.setattr(cast_api, "_get_airplay_status", get_status)

        resp = await client.get(
            "/api/cast/targets/airplay-den/status",
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "airplay-den"
        assert data["transport_state"] == "PLAYING"
        assert data["position"] == "00:01:23"
        get_status.assert_awaited_once()

    async def test_chromecast_target_status(
        self, client: AsyncClient, admin_headers, user_headers, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "chromecast-living-room",
                    "name": "Chromecast Living Room",
                    "protocol": "chromecast",
                    "host": "192.0.2.70",
                    "port": 8008,
                }
            ],
        )
        get_status = AsyncMock(
            return_value=cast_api.CastTargetStatus(
                target_id="chromecast-living-room",
                protocol="chromecast",
                transport_state="AVAILABLE",
                transport_status="OK",
                raw={"name": "Chromecast Living Room"},
            )
        )
        monkeypatch.setattr(cast_api, "_get_chromecast_status", get_status)

        resp = await client.get(
            "/api/cast/targets/chromecast-living-room/status",
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "chromecast-living-room"
        assert data["transport_state"] == "AVAILABLE"
        assert data["raw"]["name"] == "Chromecast Living Room"
        get_status.assert_awaited_once()

    async def test_chromecast_status_prefers_media_session_state(self, monkeypatch):
        from pyrate.api.v1 import cast as cast_api

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"name": "Chromecast Living Room"}

        class FakeHttpClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

            async def get(self, url, params=None):
                self.url = url
                self.params = params
                return FakeResponse()

        async def fake_media_status(_target):
            return {
                "type": "MEDIA_STATUS",
                "status": [
                    {
                        "playerState": "PLAYING",
                        "currentTime": 75.5,
                        "media": {
                            "contentId": "https://media.test/movie.mp4",
                            "duration": 3600,
                        },
                    }
                ],
            }

        async def fake_receiver_status(_target):
            return {
                "type": "RECEIVER_STATUS",
                "status": {"volume": {"level": 0.4, "muted": False}},
            }

        target = cast_api.CastTarget(
            id="chromecast-living-room",
            name="Chromecast Living Room",
            protocol="chromecast",
            host="192.0.2.70",
            port=8008,
        )
        monkeypatch.setattr(cast_chromecast.httpx, "AsyncClient", FakeHttpClient)
        monkeypatch.setattr(
            cast_chromecast,
            "_get_chromecast_media_status_payload_async",
            fake_media_status,
        )
        monkeypatch.setattr(
            cast_chromecast,
            "_get_chromecast_receiver_status_payload_async",
            fake_receiver_status,
        )

        status = await cast_api._get_chromecast_status(target)

        assert status.transport_state == "PLAYING"
        assert status.transport_status == "OK"
        assert status.media_url == "https://media.test/movie.mp4"
        assert status.duration == "01:00:00"
        assert status.position == "00:01:15"
        assert status.raw["name"] == "Chromecast Living Room"
        assert status.raw["media.status.0.playerState"] == "PLAYING"
        assert status.raw["receiver.status.volume.level"] == "0.4"
        assert status.raw["receiver.status.volume.muted"] == "False"

    async def test_chromecast_status_falls_back_to_eureka_without_media_session(
        self, monkeypatch
    ):
        from pyrate.api.v1 import cast as cast_api

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"name": "Idle Chromecast"}

        class FakeHttpClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

            async def get(self, url, params=None):
                self.url = url
                self.params = params
                return FakeResponse()

        async def fake_media_status(_target):
            return None

        async def fake_receiver_status(_target):
            return {
                "type": "RECEIVER_STATUS",
                "status": {"volume": {"level": 0.8, "muted": True}},
            }

        target = cast_api.CastTarget(
            id="chromecast-living-room",
            name="Chromecast Living Room",
            protocol="chromecast",
            host="192.0.2.70",
            port=8008,
        )
        monkeypatch.setattr(cast_chromecast.httpx, "AsyncClient", FakeHttpClient)
        monkeypatch.setattr(
            cast_chromecast,
            "_get_chromecast_media_status_payload_async",
            fake_media_status,
        )
        monkeypatch.setattr(
            cast_chromecast,
            "_get_chromecast_receiver_status_payload_async",
            fake_receiver_status,
        )

        status = await cast_api._get_chromecast_status(target)

        assert status.transport_state == "AVAILABLE"
        assert status.transport_status == "OK"
        assert status.media_url is None
        assert status.raw["name"] == "Idle Chromecast"
        assert status.raw["receiver.status.volume.level"] == "0.8"
        assert status.raw["receiver.status.volume.muted"] == "True"

    async def test_status_rejects_discovery_only_protocol(
        self, client: AsyncClient, admin_headers, user_headers
    ):
        await _register_targets(
            client,
            admin_headers,
            [
                {
                    "id": "office-tv",
                    "name": "Office TV",
                    "protocol": "pyrate",
                    "host": "192.0.2.20",
                }
            ],
        )

        resp = await client.get(
            "/api/cast/targets/office-tv/status",
            headers=user_headers,
        )

        assert resp.status_code == 422

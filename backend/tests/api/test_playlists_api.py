"""Tests for playlist wrapper endpoints (/api/playlists/*)."""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import AvailabilityStatus, MediaItem, MediaType
from streamarr.models.user import User


class _FakeRemoteControlManager:
    def __init__(self):
        self.calls = []

    async def send_remote_control_command(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "target_device_id": kwargs["target_device_id"],
            "command": kwargs["command"],
            "status": "sent",
            "timestamp": "2026-05-11T00:00:00+00:00",
        }


async def _create_media_item(db: AsyncSession, **overrides) -> MediaItem:
    now = datetime.now(UTC)
    defaults = {
        "guid": uuid.uuid4(),
        "title": "Playlist Movie",
        "media_type": MediaType.MOVIES,
        "parent_guid": None,
        "availability_status": AvailabilityStatus.UNKNOWN,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    item = MediaItem(**defaults)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


class TestPlaylists:
    async def test_create_playlist(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
    ):
        resp = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "Friday Queue", "visibility": "public", "tags": "movies"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Friday Queue"
        assert data["list_type"] == "USER"
        assert data["tags"] == "movies"

    async def test_list_playlists_excludes_plain_lists(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
    ):
        await client.post(
            "/api/lists",
            headers=user_headers,
            json={
                "name": "Plain List",
                "list_type": "user",
                "visibility": "public",
            },
        )
        await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "Movie Playlist", "visibility": "public"},
        )

        resp = await client.get("/api/playlists", headers=user_headers)

        assert resp.status_code == 200
        titles = [item["name"] for item in resp.json()["items"]]
        assert "Movie Playlist" in titles
        assert "Plain List" not in titles

    async def test_add_and_reorder_playlist_items(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        first = await _create_media_item(db_session, title="First Movie")
        second = await _create_media_item(db_session, title="Second Movie")
        create_resp = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "Ordered", "visibility": "private"},
        )
        playlist_id = create_resp.json()["guid"]

        first_resp = await client.post(
            f"/api/playlists/{playlist_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(first.guid)},
        )
        second_resp = await client.post(
            f"/api/playlists/{playlist_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(second.guid)},
        )
        first_item_id = first_resp.json()["guid"]
        second_item_id = second_resp.json()["guid"]

        reorder_resp = await client.patch(
            f"/api/playlists/{playlist_id}/items/order",
            headers=user_headers,
            json={"item_ids": [second_item_id, first_item_id]},
        )

        assert reorder_resp.status_code == 200
        data = reorder_resp.json()
        assert data["total"] == 2
        assert [item["guid"] for item in data["items"]] == [
            second_item_id,
            first_item_id,
        ]
        assert [item["order_index"] for item in data["items"]] == [0, 1]

    async def test_reorder_rejects_items_from_other_playlist(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        first_playlist = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "First", "visibility": "private"},
        )
        second_playlist = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "Second", "visibility": "private"},
        )
        add_resp = await client.post(
            f"/api/playlists/{first_playlist.json()['guid']}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(item.guid)},
        )

        resp = await client.patch(
            f"/api/playlists/{second_playlist.json()['guid']}/items/order",
            headers=user_headers,
            json={"item_ids": [add_resp.json()["guid"]]},
        )

        assert resp.status_code == 404

    async def test_playlist_queue_uses_ordered_items(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        first = await _create_media_item(db_session, title="First Movie")
        second = await _create_media_item(db_session, title="Second Movie")
        create_resp = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "Queue", "visibility": "private"},
        )
        playlist_id = create_resp.json()["guid"]

        first_resp = await client.post(
            f"/api/playlists/{playlist_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(first.guid)},
        )
        second_resp = await client.post(
            f"/api/playlists/{playlist_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(second.guid)},
        )
        await client.patch(
            f"/api/playlists/{playlist_id}/items/order",
            headers=user_headers,
            json={
                "item_ids": [
                    second_resp.json()["guid"],
                    first_resp.json()["guid"],
                ]
            },
        )

        resp = await client.get(
            f"/api/playlists/{playlist_id}/queue?start_index=1",
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["playlist_name"] == "Queue"
        assert data["total"] == 2
        assert [item["title"] for item in data["items"]] == [
            "Second Movie",
            "First Movie",
        ]
        assert data["current_item"]["title"] == "First Movie"
        assert data["previous_item"]["title"] == "Second Movie"
        assert data["next_item"] is None

    async def test_playlist_queue_can_start_by_item_guid(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        first = await _create_media_item(db_session, title="First Movie")
        second = await _create_media_item(db_session, title="Second Movie")
        create_resp = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "Queue", "visibility": "private"},
        )
        playlist_id = create_resp.json()["guid"]
        await client.post(
            f"/api/playlists/{playlist_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(first.guid)},
        )
        await client.post(
            f"/api/playlists/{playlist_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(second.guid)},
        )

        resp = await client.get(
            f"/api/playlists/{playlist_id}/queue?start_item_guid={second.guid}",
            headers=user_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["current_item"]["media_item_guid"] == str(second.guid)

    async def test_play_playlist_on_device_sends_ordered_queue(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        monkeypatch,
    ):
        from streamarr.api.v1 import devices as devices_api
        from streamarr.models import Device

        device = Device(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            device_id="living-room",
            name="Living Room",
            is_active=True,
            is_trusted=False,
        )
        db_session.add(device)
        await db_session.commit()
        first = await _create_media_item(db_session, title="First Movie")
        second = await _create_media_item(db_session, title="Second Movie")
        create_resp = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "Queue", "visibility": "private"},
        )
        playlist_id = create_resp.json()["guid"]
        await client.post(
            f"/api/playlists/{playlist_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(first.guid)},
        )
        await client.post(
            f"/api/playlists/{playlist_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(second.guid)},
        )
        manager = _FakeRemoteControlManager()
        monkeypatch.setattr(devices_api, "get_websocket_manager", lambda: manager)

        resp = await client.post(
            f"/api/playlists/{playlist_id}/play-on-device",
            headers=user_headers,
            json={
                "device_id": "living-room",
                "start_item_guid": str(second.guid),
                "start_position_seconds": 12,
                "from_device_id": "phone",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["command"] == "play_queue"
        assert manager.calls[0]["target_device_id"] == "living-room"
        assert manager.calls[0]["command"] == "play_queue"
        assert manager.calls[0]["from_device_id"] == "phone"
        payload = manager.calls[0]["payload"]
        assert payload["start_index"] == 1
        assert payload["start_position_seconds"] == 12
        assert [item["media_title"] for item in payload["items"]] == [
            "First Movie",
            "Second Movie",
        ]

    async def test_private_playlist_queue_requires_access(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
    ):
        create_resp = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "Private Queue", "visibility": "private"},
        )
        playlist_id = create_resp.json()["guid"]

        resp = await client.get(f"/api/playlists/{playlist_id}/queue")

        assert resp.status_code == 403

    async def test_owner_can_update_playlist_metadata(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
    ):
        create_resp = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "Draft", "visibility": "private", "tags": "old"},
        )
        playlist_id = create_resp.json()["guid"]

        resp = await client.put(
            f"/api/playlists/{playlist_id}",
            headers=user_headers,
            json={
                "name": "Updated",
                "description": "New description",
                "visibility": "public",
                "tags": "updated,movies",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated"
        assert data["description"] == "New description"
        assert data["visibility"] == "PUBLIC"
        assert data["tags"] == "updated,movies"

    async def test_admin_can_update_user_playlist(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        admin_headers,
    ):
        create_resp = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "User Playlist", "visibility": "private"},
        )
        playlist_id = create_resp.json()["guid"]

        resp = await client.put(
            f"/api/playlists/{playlist_id}",
            headers=admin_headers,
            json={"name": "Admin Renamed"},
        )

        assert resp.status_code == 200
        assert resp.json()["name"] == "Admin Renamed"

    async def test_non_owner_cannot_update_playlist(
        self,
        client: AsyncClient,
        user_headers,
        admin_headers,
    ):
        create_resp = await client.post(
            "/api/playlists",
            headers=admin_headers,
            json={"name": "Admin Playlist", "visibility": "public"},
        )
        playlist_id = create_resp.json()["guid"]

        resp = await client.put(
            f"/api/playlists/{playlist_id}",
            headers=user_headers,
            json={"name": "Nope"},
        )

        assert resp.status_code == 403

    async def test_owner_can_enable_and_disable_playlist_sharing(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
    ):
        create_resp = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "Share Me", "visibility": "private"},
        )
        playlist_id = create_resp.json()["guid"]

        shared = await client.put(
            f"/api/playlists/{playlist_id}/share",
            headers=user_headers,
            json={"enabled": True},
        )

        assert shared.status_code == 200
        shared_data = shared.json()
        assert shared_data["is_shared"] is True
        assert shared_data["visibility"] == "PUBLIC"
        assert shared_data["share_url"].endswith(f"/playlists/{playlist_id}")

        public_get = await client.get(f"/api/playlists/{playlist_id}")
        assert public_get.status_code == 200

        unshared = await client.put(
            f"/api/playlists/{playlist_id}/share",
            headers=user_headers,
            json={"enabled": False},
        )

        assert unshared.status_code == 200
        assert unshared.json()["is_shared"] is False
        assert unshared.json()["share_url"] is None

        private_get = await client.get(f"/api/playlists/{playlist_id}")
        assert private_get.status_code == 403

    async def test_non_owner_cannot_change_playlist_sharing(
        self,
        client: AsyncClient,
        user_headers,
        admin_headers,
    ):
        create_resp = await client.post(
            "/api/playlists",
            headers=admin_headers,
            json={"name": "Admin Share", "visibility": "public"},
        )
        playlist_id = create_resp.json()["guid"]

        resp = await client.put(
            f"/api/playlists/{playlist_id}/share",
            headers=user_headers,
            json={"enabled": False},
        )

        assert resp.status_code == 403

    async def test_playlist_queue_rejects_out_of_range_start(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        create_resp = await client.post(
            "/api/playlists",
            headers=user_headers,
            json={"name": "Queue", "visibility": "private"},
        )
        playlist_id = create_resp.json()["guid"]
        await client.post(
            f"/api/playlists/{playlist_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(item.guid)},
        )

        resp = await client.get(
            f"/api/playlists/{playlist_id}/queue?start_index=10",
            headers=user_headers,
        )

        assert resp.status_code == 400

    async def test_non_owner_cannot_modify_playlist(
        self,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        user_headers,
        admin_headers,
    ):
        create_resp = await client.post(
            "/api/playlists",
            headers=admin_headers,
            json={"name": "Admin Playlist", "visibility": "public"},
        )
        playlist_id = create_resp.json()["guid"]

        resp = await client.post(
            f"/api/playlists/{playlist_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(uuid.uuid4())},
        )

        assert resp.status_code == 403

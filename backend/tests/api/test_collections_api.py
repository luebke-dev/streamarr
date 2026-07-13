"""Tests for collection wrapper endpoints (/api/collections/*)."""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import AvailabilityStatus, MediaItem, MediaType
from streamarr.models.user import User


async def _create_media_item(db: AsyncSession, **overrides) -> MediaItem:
    now = datetime.now(UTC)
    defaults = {
        "guid": uuid.uuid4(),
        "title": "Collection Movie",
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


class TestCollections:
    async def test_create_collection(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
    ):
        resp = await client.post(
            "/api/collections",
            headers=user_headers,
            json={"name": "Sci-Fi Set", "visibility": "public", "tags": "movies"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Sci-Fi Set"
        assert data["list_type"] == "USER"
        assert data["tags"] == "movies"

    async def test_list_collections_excludes_plain_lists(
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
            "/api/collections",
            headers=user_headers,
            json={"name": "Movie Collection", "visibility": "public"},
        )

        resp = await client.get("/api/collections", headers=user_headers)

        assert resp.status_code == 200
        titles = [item["name"] for item in resp.json()["items"]]
        assert "Movie Collection" in titles
        assert "Plain List" not in titles

    async def test_private_collection_requires_owner(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
    ):
        create_resp = await client.post(
            "/api/collections",
            headers=user_headers,
            json={"name": "Private Collection", "visibility": "private"},
        )
        collection_id = create_resp.json()["guid"]

        resp = await client.get(f"/api/collections/{collection_id}")

        assert resp.status_code == 403

    async def test_add_and_list_collection_items(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session, title="The Matrix")
        create_resp = await client.post(
            "/api/collections",
            headers=user_headers,
            json={"name": "Franchise", "visibility": "private"},
        )
        collection_id = create_resp.json()["guid"]

        add_resp = await client.post(
            f"/api/collections/{collection_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(item.guid)},
        )

        assert add_resp.status_code == 200
        list_item_id = add_resp.json()["guid"]

        items_resp = await client.get(
            f"/api/collections/{collection_id}/items", headers=user_headers
        )

        assert items_resp.status_code == 200
        data = items_resp.json()
        assert data["total"] == 1
        assert data["items"][0]["guid"] == list_item_id
        assert data["items"][0]["item_data"]["title"] == "The Matrix"

    async def test_non_owner_cannot_modify_collection(
        self,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        user_headers,
        admin_headers,
    ):
        create_resp = await client.post(
            "/api/collections",
            headers=admin_headers,
            json={"name": "Admin Collection", "visibility": "public"},
        )
        collection_id = create_resp.json()["guid"]

        resp = await client.post(
            f"/api/collections/{collection_id}/items",
            headers=user_headers,
            json={"item_type": "movie", "item_guid": str(uuid.uuid4())},
        )

        assert resp.status_code == 403
